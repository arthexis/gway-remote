"""#615: hermetic gway-004 executor migration preflight; never contacts nodes."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/preflight-executor-migration-004.py"
PLAYBOOK = ROOT / "ansible/migrate-executor-004.yml"
spec = importlib.util.spec_from_file_location("executor_migration_004", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class MigrationPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="migrate-004-")
        self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name)
        self.parent.chmod(0o700)
        self.db = self.parent / "jobs.sqlite3"
        self.owner_uid = self.parent.stat().st_uid

    def ledger(self, *states):
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TABLE jobs (status TEXT NOT NULL)")
            for state in states:
                db.execute("INSERT INTO jobs VALUES (?)", (state,))
        self.db.chmod(0o600)

    def call(self, *, current="gway-exec", host="gway-004", uid=0, ledger=None):
        relay = Mock()
        account = lambda name: SimpleNamespace(
            pw_uid=self.owner_uid if name == "gway-exec" else self.owner_uid + 1,
            pw_name=name,
        )
        with (patch.object(guard, "selected_user", return_value=current),
              patch.object(guard, "validated_account", side_effect=account),
              patch.object(guard, "executor_path", return_value="/usr/bin:/bin")):
            result = guard.preflight(
                hostname=host, euid=uid,
                ledger=self.db if ledger is None else ledger,
                relay_verifier=relay,
            )
        return result, relay

    def test_terminal_receipts_stay_byte_identical(self):
        self.ledger("succeeded", "failed", "cancelled", "timed_out")
        before = self.db.read_bytes()
        result, relay = self.call()
        self.assertEqual(result["status"], "preflight_only")
        self.assertEqual(result["preserved_terminal_receipts"], 4)
        self.assertEqual((result["node"], result["previous"], result["selected"]),
                         ("gway-004", "gway-exec", "arthe"))
        self.assertEqual(self.db.read_bytes(), before)
        relay.assert_called_once_with("gway-exec")

    def test_unknown_or_active_or_unrecognized_jobs_block(self):
        for state in ("queued", "running", "unknown", "uncertain", "invented"):
            with self.subTest(state=state):
                self.db.unlink(missing_ok=True)
                self.ledger("succeeded", state)
                with self.assertRaisesRegex(RuntimeError, "unresolved"):
                    self.call()

    def test_empty_but_valid_ledger_is_allowed(self):
        self.ledger()
        result, _ = self.call()
        self.assertEqual(result["preserved_terminal_receipts"], 0)

    def test_missing_or_corrupt_ledger_fails_closed(self):
        with self.assertRaisesRegex(PermissionError, "ledger unavailable"):
            self.call()
        self.db.write_text("not sqlite")
        self.db.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, "ledger unreadable"):
            self.call()

    def test_symlink_and_world_or_group_write_fail_closed(self):
        self.ledger("succeeded")
        target = self.parent / "elsewhere"
        self.db.rename(target)
        self.db.symlink_to(target)
        with self.assertRaisesRegex(PermissionError, "unsafe executor ledger file"):
            self.call()
        self.db.unlink()
        target.rename(self.db)
        self.db.chmod(0o666)
        with self.assertRaisesRegex(PermissionError, "unsafe executor ledger file"):
            self.call()
        self.db.chmod(0o600)
        self.parent.chmod(0o770)
        with self.assertRaisesRegex(PermissionError, "unsafe executor ledger directory"):
            self.call()

    def test_wrong_node_root_or_existing_policy_denied_before_relay(self):
        for options in (
            {"host": "gway-001"},
            {"host": "gway-002"},
            {"uid": 1000},
            {"current": "root"},
            {"current": "unexpected"},
        ):
            with self.subTest(options=options), self.assertRaises(PermissionError):
                self.call(**options)

    def test_post_617_runtime_required_before_any_policy_change(self):
        self.ledger("succeeded")
        with (patch.object(guard, "selected_user", return_value="gway-exec"),
              patch.object(guard, "validated_account",
                           side_effect=lambda name: SimpleNamespace(
                               pw_uid=self.owner_uid if name == "gway-exec" else self.owner_uid + 1)),
              patch.object(guard, "executor_path", side_effect=PermissionError("old runtime"))):
            with self.assertRaisesRegex(PermissionError, "old runtime"):
                guard.preflight(hostname="gway-004", euid=0, ledger=self.db,
                                relay_verifier=Mock())

    def test_same_unix_uid_is_not_an_identity_separation(self):
        with (patch.object(guard, "selected_user", return_value="gway-exec"),
              patch.object(guard, "validated_account",
                           return_value=SimpleNamespace(pw_uid=self.owner_uid)),
              patch.object(guard, "executor_path", return_value="/usr/bin")):
            with self.assertRaisesRegex(PermissionError, "ambiguous"):
                guard.preflight(hostname="gway-004", euid=0, ledger=self.db,
                                relay_verifier=Mock())

    def test_already_selected_idempotent_without_old_ledger(self):
        result, relay = self.call(current="arthe")
        self.assertEqual(result["status"], "already_selected")
        self.assertEqual(result["preserved_terminal_receipts"], 0)
        self.assertFalse(self.db.exists())
        relay.assert_called_once_with("arthe")

    def test_relay_verification_is_exact_no_shell_or_credentials(self):
        with patch.object(guard.subprocess, "run") as run:
            guard.verify_current_relay("gway-exec")
        args = run.call_args.args[0]
        self.assertEqual(args[-2:], ["--user", "gway-exec"])
        self.assertTrue(args[1].endswith("/verify-exec-relay-policy.py"))
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertEqual(run.call_args.kwargs["timeout"], 8)
        with patch.object(guard.subprocess, "run", side_effect=OSError()):
            with self.assertRaisesRegex(PermissionError, "relay policy"):
                guard.verify_current_relay("gway-exec")

    def test_playbook_is_dormant_exact_node_explicit_reviewed_sha_only(self):
        yml = PLAYBOOK.read_text()
        self.assertIn("hosts: gway-004", yml)
        self.assertIn("connection: local", yml)
        self.assertIn("become: true", yml)
        self.assertIn("ansible_hostname == 'gway-004'", yml)
        self.assertIn("I_ACCEPT_GWAY_004_EXECUTOR_ARTHE", yml)
        self.assertIn("gway_executor_migration_expected_sha", yml)
        self.assertIn("status, --porcelain, --untracked-files=all", yml)
        self.assertIn("preflight-executor-migration-004.py", yml)
        self.assertIn("ansible.builtin.import_tasks: roles/gway_remote/tasks/node-exec-select.yml", yml)
        self.assertNotIn("ansible/playbook.yml", yml)
        self.assertNotIn("node-exec-relay.yml", yml)
        self.assertNotIn("agentops.runtime.json", yml)
        self.assertNotIn("systemd:", yml)
        self.assertNotIn("sudo -u", yml)

    def test_regular_deploy_and_bootstrap_cannot_use_migration_gate(self):
        for path in ("deploy.sh", "ansible/playbook.yml",
                     "ansible/roles/gway_remote/tasks/main.yml",
                     "scripts/resolve-executor-user.py",
                     "gway_remote/wireguard_satellite.py"):
            with self.subTest(path=path):
                self.assertNotIn("gway_executor_migration_approval",
                                 (ROOT / path).read_text())


if __name__ == "__main__":
    unittest.main()
