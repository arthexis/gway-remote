"""P2 bounded offline interleaving model, NOT proof of live runner parallelism.

The model deliberately detects missing cross-workflow mutual exclusion. It does
not run GitHub, installers, Ansible, Watchtower SSH or appliance_watch --apply.
"""
from itertools import combinations
from pathlib import Path
import re
import tempfile
import unittest

from gway_remote.best_effort import appliance_lock

ROOT = Path(__file__).resolve().parents[2]
APPLIANCE = ROOT / ".github/workflows/appliance-deploy.yml"
REPORT = ROOT / ".github/workflows/appliance-report.yml"
BACKEND = ROOT / ".github/workflows/deploy-backend.yml"
BACKEND_DEPLOY = ROOT / "gway_remote/deployment.py"
BEST_EFFORT = ROOT / "gway_remote/best_effort.py"
WATCH = ROOT / "gway_remote/appliance_watch.py"
DEPLOY_SH = ROOT / "deploy.sh"
WATCHTOWER_SH = ROOT / "scripts/watchtower-auto-deploy.sh"


def group(path):
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?m)^concurrency:\n  group: ([a-z0-9-]+)\n  cancel-in-progress: false$", text)
    if not match:
        raise ValueError("unknown workflow-level concurrency contract")
    return match.group(1)


def ordered_interleavings():
    """All six possible shuffles of start/finish for two abstract activities."""
    for positions in combinations(range(4), 2):
        left = ("A:start", "A:finish")
        right = ("B:start", "B:finish")
        a = iter(left)
        b = iter(right)
        yield tuple(next(a) if i in positions else next(b) for i in range(4))


def overlaps(schedule):
    running = set()
    for event in schedule:
        label, action = event.split(":")
        if action == "start":
            running.add(label)
        else:
            running.remove(label)
        if len(running) > 1:
            return True
    return False


def allowed_schedule(schedule, *, group_a=None, group_b=None,
                     lock_a=None, lock_b=None):
    if not overlaps(schedule):
        return True
    if group_a is not None and group_a == group_b:
        return False
    if lock_a is not None and lock_a == lock_b:
        return False
    return True


class InterleavingContractP2Tests(unittest.TestCase):
    def test_all_six_ordered_interleavings_and_overlap_model(self):
        schedules = tuple(ordered_interleavings())
        self.assertEqual(len(schedules), 6)
        self.assertEqual(len(set(schedules)), 6)
        self.assertEqual(sum(overlaps(s) for s in schedules), 4)

    def test_groups_differ_and_backend_appliance_overlap_is_not_ruled_out(self):
        appliance_group = group(APPLIANCE)
        backend_group = group(BACKEND)
        self.assertEqual(appliance_group, "gway-001-appliance")
        self.assertEqual(backend_group, "gway-001-appliance-report")
        self.assertNotEqual(appliance_group, backend_group)
        schedules = tuple(ordered_interleavings())
        potential = [s for s in schedules
                     if overlaps(s) and allowed_schedule(
                         s, group_a=backend_group, group_b=appliance_group,
                         lock_a=None, lock_b="appliance.lock")]
        self.assertEqual(len(potential), 4,
                         "do not silently claim backend/appliance serialization")
        # This is a permissive resource model, not an observation of runners.

    def test_appliance_and_report_share_workflow_group(self):
        self.assertEqual(group(APPLIANCE), group(REPORT))
        self.assertFalse(any(
            overlaps(s) and allowed_schedule(
                s, group_a=group(APPLIANCE), group_b=group(REPORT))
            for s in ordered_interleavings()))

    def test_two_appliance_installers_share_flock(self):
        self.assertIn("with appliance_lock(", BEST_EFFORT.read_text())
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "appliance.lock"
            with appliance_lock(path):
                with self.assertRaises(RuntimeError):
                    with appliance_lock(path):
                        pass
        self.assertFalse(any(
            overlaps(s) and allowed_schedule(s, lock_a="appliance.lock",
                                             lock_b="appliance.lock")
            for s in ordered_interleavings()))

    def test_backend_install_does_not_take_appliance_flock(self):
        text = BACKEND_DEPLOY.read_text(encoding="utf-8")
        workflow = BACKEND.read_text(encoding="utf-8")
        shell = DEPLOY_SH.read_text(encoding="utf-8")
        self.assertIn("deploy(token=local_api_token(), install=install)", workflow)
        self.assertIn('ansible-playbook "$ROOT/ansible/playbook.yml"', shell)
        self.assertNotIn("appliance_lock(", text)
        self.assertNotIn("appliance_lock(", shell)
        self.assertNotIn("appliance.lock", workflow)
        # deploy.lock in the optional stage/Watchtower paths is distinct.
        self.assertIn('"$state_dir/deploy.lock"', shell)

    def test_watchtower_autodeploy_lock_is_separate_from_appliance(self):
        text = WATCHTOWER_SH.read_text(encoding="utf-8")
        backend = BACKEND.read_text(encoding="utf-8")
        self.assertIn('flock -n 9', text)
        self.assertIn('state/deploy.lock', text)
        self.assertIn("needs: deploy", backend)
        self.assertNotEqual(group(BACKEND), group(APPLIANCE))
        self.assertTrue(any(
            overlaps(s) and allowed_schedule(
                s, group_a=group(BACKEND), group_b=group(APPLIANCE),
                lock_a="watchtower/deploy.lock", lock_b="appliance.lock")
            for s in ordered_interleavings()))

    def test_watch_apply_checks_appliance_only_not_backend(self):
        watcher = WATCH.read_text(encoding="utf-8")
        self.assertIn('actions/workflows/appliance-deploy.yml/runs', watcher)
        self.assertNotIn('actions/workflows/deploy-backend.yml/runs', watcher)
        self.assertIn("if apply and pending:", watcher)
        self.assertIn("if not _busy():", watcher)
        self.assertIn("_reserve_dispatch(", watcher)
        self.assertIn("dispatch(dispatched)", watcher)
        # A serialized Appliance workflow can still coexist with Backend's
        # different group; the reservation journal is not a shared lock.
        self.assertTrue(any(overlaps(s) for s in ordered_interleavings()))

    def test_manual_batch_and_backend_are_not_the_same_lock_domain(self):
        schedules = tuple(ordered_interleavings())
        self.assertFalse(any(
            overlaps(s) and allowed_schedule(s, lock_a="appliance.lock",
                                             lock_b="appliance.lock")
            for s in schedules))
        self.assertTrue(any(
            overlaps(s) and allowed_schedule(s, lock_a="appliance.lock",
                                             lock_b=None)
            for s in schedules))

    def test_no_live_exclusivity_or_new_permission_claim(self):
        backend = BACKEND.read_text()
        appliance = APPLIANCE.read_text()
        self.assertIn("runs-on: [self-hosted, Linux, ARM64, gway-001]", backend)
        self.assertIn("runs-on: [self-hosted, Linux, ARM64, gway-001]", appliance)
        self.assertEqual(group(BACKEND), "gway-001-appliance-report")
        self.assertEqual(group(APPLIANCE), "gway-001-appliance")
        # Sharing a label doesn't tell us the physical runner count. A P3/P4
        # admission change needs a separate runtime evidence gate.


if __name__ == "__main__":
    unittest.main()
