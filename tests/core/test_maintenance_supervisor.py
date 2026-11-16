"""Hermetic supervisor tests: disposable HOME, fake cgroup, no node services."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from gway_remote import maintenance_lock as lock_module
from gway_remote import maintenance_supervisor as sup
from gway_remote.maintenance_lock import Invalid, MaintenanceLock, Uncertain


class Clock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def pause(self, delay):
        self.now += max(1.0, delay)


class FakeProcess:
    pid = 76543

    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


class FakeScope:
    def __init__(self, process, *, occupied=False, attach_error=False,
                 contains=True, refuse_term=False, refuse_kill=False,
                 descendants_stick=False):
        self.process = process
        self.occupied = occupied
        self.attach_error = attach_error
        self.attested = contains
        self.refuse_term = refuse_term
        self.refuse_kill = refuse_kill
        self.descendants_stick = descendants_stick
        self.attached = False
        self.terms = self.kills = 0

    def empty(self):
        if not self.attached:
            return not self.occupied
        return self.process.code is not None and not self.descendants_stick

    def attach(self, pid):
        if self.attach_error:
            raise Invalid()
        self.attached = True
        assert pid == self.process.pid

    def contains(self, pid):
        return self.attested

    def term(self, pid):
        self.terms += 1
        if not self.refuse_term:
            self.process.code = -15

    def kill(self):
        self.kills += 1
        if not self.refuse_kill:
            self.process.code = -9


class MaintenanceSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.pwd = patch.object(
            lock_module.pwd, "getpwuid",
            return_value=SimpleNamespace(pw_dir=str(self.home)),
        )
        self.pwd.start()
        self.addCleanup(self.pwd.stop)
        self.uid = patch.object(lock_module, "_operator_uid", return_value=os.geteuid())
        self.uid.start()
        self.addCleanup(self.uid.stop)

    def lock(self):
        return MaintenanceLock(wait_seconds=0)

    def scenario(self, held, *, initial_code=None, **scope_options):
        proc = FakeProcess(initial_code)
        scope = FakeScope(proc, **scope_options)
        clock = Clock(held.started)
        calls = []
        def spawn(argv, **options):
            calls.append((argv, options))
            return proc
        return proc, scope, clock, calls, spawn

    def test_normal_success_preserves_cgroup_and_lock(self):
        with self.lock() as held:
            proc, scope, clock, calls, spawn = self.scenario(held, initial_code=0)
            result = sup.run_supervised(
                ["/bin/true"], lock=held, scope=scope,
                clock=clock, pause=clock.pause, spawn=spawn,
            )
            self.assertEqual((result.state, result.suggested_exit_code), ("EXITED", 0))
            self.assertEqual(result.exit_code, 0)
            self.assertTrue(scope.attached)
            self.assertEqual(calls[0][0][1:3], ["-m", "gway_remote.maintenance_supervisor"])
            self.assertIn(held.fileno(), calls[0][1]["pass_fds"])
            self.assertFalse(calls[0][1].get("shell", False))
            self.assertEqual(scope.terms, 0)
            self.assertEqual(scope.kills, 0)

    def test_known_failure_is_not_success(self):
        with self.lock() as held:
            proc, scope, clock, calls, spawn = self.scenario(held, initial_code=2)
            result = sup.run_supervised(
                ["/bin/false"], lock=held, scope=scope,
                clock=clock, pause=clock.pause, spawn=spawn)
            self.assertEqual((result.state, result.exit_code, result.suggested_exit_code),
                             ("EXITED", 2, 1))

    def test_term_after_275_seconds_is_timeout(self):
        with self.lock() as held:
            proc, scope, clock, calls, spawn = self.scenario(held)
            result = sup.run_supervised(
                ["/bin/sleep", "3"], lock=held, scope=scope,
                clock=clock, pause=clock.pause, spawn=spawn)
            self.assertEqual((result.state, result.suggested_exit_code), ("TIMEOUT", 124))
            self.assertEqual(scope.terms, 1)
            self.assertEqual(scope.kills, 0)

    def test_kill_at_290_after_unresponsive_term(self):
        with self.lock() as held:
            proc, scope, clock, calls, spawn = self.scenario(held, refuse_term=True)
            result = sup.run_supervised(
                ["/bin/sleep", "3"], lock=held, scope=scope,
                clock=clock, pause=clock.pause, spawn=spawn)
            self.assertEqual(result.state, "TIMEOUT")
            self.assertEqual(scope.terms, 1)
            self.assertEqual(scope.kills, 1)

    def test_unknown_descendants_leave_uncertain_marker(self):
        with self.lock() as held:
            proc, scope, clock, calls, spawn = self.scenario(
                held, refuse_term=True, descendants_stick=True)
            with self.assertRaises(Uncertain):
                sup.run_supervised(
                    ["/bin/true"], lock=held, scope=scope,
                    clock=clock, pause=clock.pause, spawn=spawn)
            marker = self.home / ".local/state/maintenance.uncertain"
            self.assertIn("process_unverified", marker.read_text())
        with self.assertRaises(Uncertain):
            with self.lock():
                pass

    def test_attach_rejection_does_not_release_gate(self):
        with self.lock() as held:
            proc, scope, clock, calls, spawn = self.scenario(held, attach_error=True)
            with self.assertRaises(Invalid):
                sup.run_supervised(
                    ["/bin/true"], lock=held, scope=scope,
                    clock=clock, pause=clock.pause, spawn=spawn)
            self.assertEqual(scope.kills, 1)
            self.assertFalse((self.home / ".local/state/maintenance.uncertain").exists())

    def test_wrong_cgroup_membership_does_not_release_gate(self):
        with self.lock() as held:
            proc, scope, clock, calls, spawn = self.scenario(held, contains=False)
            with self.assertRaises(Invalid):
                sup.run_supervised(
                    ["/bin/true"], lock=held, scope=scope,
                    clock=clock, pause=clock.pause, spawn=spawn)
            self.assertEqual(scope.kills, 1)

    def test_busy_cgroup_refuses_before_spawn(self):
        with self.lock() as held:
            proc, scope, clock, calls, spawn = self.scenario(held, occupied=True)
            with self.assertRaises(Uncertain):
                sup.run_supervised(
                    ["/bin/true"], lock=held, scope=scope,
                    clock=clock, pause=clock.pause, spawn=spawn)
            self.assertEqual(calls, [])

    def test_invalid_argv_refused_before_spawn(self):
        with self.lock() as held:
            proc, scope, clock, calls, spawn = self.scenario(held)
            for argv in ([], ["x\x00y"], [""]):
                with self.subTest(argv=repr(argv)), self.assertRaises(Invalid):
                    sup.run_supervised(argv, lock=held, scope=scope,
                                       clock=clock, pause=clock.pause, spawn=spawn)
            self.assertEqual(calls, [])

    def test_total_budget_includes_time_elapsed_before_spawn(self):
        with self.lock() as held:
            proc, scope, clock, calls, spawn = self.scenario(held)
            clock.now = held.started + 300
            with self.assertRaises(Uncertain):
                sup.run_supervised(["/bin/true"], lock=held, scope=scope,
                                   clock=clock, pause=clock.pause, spawn=spawn)
            self.assertEqual(calls, [])

    def test_cgroup_v2_populated_parser_and_kill(self):
        root = self.home / "fake-cgroup"
        scope_path = root / "isolated.scope"
        scope_path.mkdir(parents=True)
        (scope_path / "cgroup.events").write_text("populated 0\nfrozen 0\n")
        (scope_path / "cgroup.kill").write_text("")
        cgroup = sup.CgroupV2(scope_path, root=root)
        self.assertTrue(cgroup.empty())
        (scope_path / "cgroup.events").write_text("populated 1\n")
        self.assertFalse(cgroup.empty())
        cgroup.kill()
        self.assertEqual((scope_path / "cgroup.kill").read_text(), "1")

    def test_cgroup_symlink_and_root_rejected(self):
        root = self.home / "fake-cgroup"
        root.mkdir()
        (root / "scope").mkdir()
        (root / "link").symlink_to(root / "scope", target_is_directory=True)
        with self.assertRaises(Invalid):
            sup.CgroupV2(root, root=root)
        with self.assertRaises(Invalid):
            sup.CgroupV2(root / "link", root=root)


if __name__ == "__main__":
    unittest.main()
