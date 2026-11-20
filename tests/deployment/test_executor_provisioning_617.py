"""Hermetic identity-contract tests for #617, without nodes or root writes."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
import unittest

from gway_remote import wireguard_satellite as bootstrap


def account(name):
    mapping = {"alice": 1001, "bob": 1002, "gway-exec": 998}
    if name not in mapping:
        raise KeyError(name)
    return SimpleNamespace(pw_name=name, pw_uid=mapping[name], pw_dir="/home/" + name)


class ProvisioningIdentityTests(unittest.TestCase):
    def setUp(self):
        self.pwd = patch("pwd.getpwnam", side_effect=account)
        self.pwd.start()
        self.addCleanup(self.pwd.stop)

    def test_new_install_defaults_to_verified_nonroot_user(self):
        self.assertEqual(bootstrap.select_executor_user("alice"), "alice")
        self.assertEqual(bootstrap.select_executor_user("alice", "bob"), "bob")

    def test_existing_policy_and_legacy_ledger_never_migrate(self):
        self.assertEqual(bootstrap.select_executor_user("bob", existing="alice"), "alice")
        self.assertEqual(bootstrap.select_executor_user(None, existing="alice"), "alice")
        with self.assertRaises(PermissionError):
            bootstrap.select_executor_user("bob", "bob", existing="alice")
        self.assertEqual(bootstrap.select_executor_user("bob", legacy=True), "gway-exec")
        with self.assertRaises(PermissionError):
            bootstrap.select_executor_user("bob", "bob", legacy=True)

    def test_root_missing_malformed_unknown_and_ambiguous_users_fail(self):
        for installer in (None, "", "root", "missing", "../alice", "ALICE"):
            with self.subTest(installer=installer), self.assertRaises(ValueError):
                bootstrap.select_executor_user(installer)
        for override in ("root", "missing", "../bob", 123, False):
            with self.subTest(override=override), self.assertRaises(ValueError):
                bootstrap.select_executor_user("alice", override)
        with patch("pwd.getpwnam", return_value=SimpleNamespace(pw_name="alice", pw_uid=0)):
            with self.assertRaises(ValueError):
                bootstrap.select_executor_user("alice")

    def test_verified_sudo_origin_and_root_only_override(self):
        with patch("pwd.getpwuid", side_effect=lambda uid: account("alice") if uid == 1001 else account("bob")):
            self.assertEqual(bootstrap.sudo_install_user({"SUDO_USER": "alice", "SUDO_UID": "1001"}), "alice")
            with self.assertRaises(ValueError):
                bootstrap.sudo_install_user({"SUDO_USER": "alice", "SUDO_UID": "1002"})
        with self.assertRaises(ValueError):
            bootstrap.sudo_install_user({"SUDO_USER": "alice"})
        with self.assertRaises(ValueError):
            bootstrap.sudo_install_user({"SUDO_USER": "alice", "SUDO_UID": "root"})
        self.assertIsNone(bootstrap.sudo_install_user({}))
        self.assertEqual(bootstrap.select_executor_user(None, "bob"), "bob")

    def test_resolver_preserves_existing_and_legacy_before_installer(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as d:
            root = Path(d)
            policy = root / "executor-identity.json"
            legacy = root / "legacy"
            relay = root / "relay"
            with patch.object(bootstrap, "read_executor_policy", return_value=None):
                self.assertEqual(bootstrap.resolve_executor_user("alice", policy=policy,
                                                                 legacy_state=legacy, legacy_relay=relay), "alice")
                legacy.mkdir()
                self.assertEqual(bootstrap.resolve_executor_user("bob", policy=policy,
                                                                 legacy_state=legacy, legacy_relay=relay), "gway-exec")
            with patch.object(bootstrap, "read_executor_policy", return_value="alice"):
                self.assertEqual(bootstrap.resolve_executor_user("bob", policy=policy,
                                                                 legacy_state=legacy, legacy_relay=relay), "alice")

    def test_bootstrap_persists_identity_only_after_enrollment(self):
        events = []
        with (patch.object(bootstrap, "sudo_install_user", return_value="alice"),
              patch.object(bootstrap, "resolve_executor_user", side_effect=lambda *_: events.append("resolve") or "alice"),
              patch.object(bootstrap, "bootstrap", side_effect=lambda *_a, **_k: events.append("wire") or {"ok": True}),
              patch.object(bootstrap, "persist_executor_user", side_effect=lambda *_: events.append("persist")),
              patch.object(bootstrap, "prepare_dormant_executor", side_effect=lambda: events.append("prepare") or {"execution_enabled": False}),
              patch.object(bootstrap, "_key", return_value="x"),
              patch("sys.argv", ["client.py", "bootstrap", "--device", "gway-004", "--server-public-key", "x"]),
              patch("getpass.getpass", return_value="x" * 40),
              patch("builtins.print")):
            bootstrap.main()
        self.assertEqual(events, ["resolve", "wire", "persist", "prepare"])

    def test_ansible_uses_verified_account_primary_group_not_username(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        for path in ("node-exec-select.yml", "node-mcp-deploy.yml"):
            source = (root / "ansible/roles/gway_remote/tasks" / path).read_text()
            self.assertIn('group: "{{ getent_passwd[gway_remote_exec_run_user][2] }}"', source)
            self.assertNotIn('group: "{{ gway_remote_exec_run_user }}"', source)

    def test_root_owned_policy_idempotence_and_symlink_fail_closed(self):
        import stat
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            policy = Path(temp) / "identity.json"
            original_lstat = Path.lstat
            original_fstat = os.fstat

            def root_parent(path):
                info = original_lstat(path)
                if Path(path) == policy.parent:
                    return SimpleNamespace(st_mode=info.st_mode, st_uid=0)
                return info

            def root_file(fd):
                info = original_fstat(fd)
                return SimpleNamespace(st_mode=info.st_mode, st_uid=0)

            with (patch.object(bootstrap.os, "geteuid", return_value=0),
                  patch.object(Path, "lstat", autospec=True, side_effect=root_parent),
                  patch.object(bootstrap.os, "fstat", side_effect=root_file)):
                self.assertTrue(bootstrap.persist_executor_user("alice", policy=policy))
                self.assertEqual(json.loads(policy.read_text()), {"user": "alice"})
                self.assertFalse(bootstrap.persist_executor_user("alice", policy=policy))
                with self.assertRaises(PermissionError):
                    bootstrap.persist_executor_user("bob", policy=policy)
                self.assertEqual(bootstrap.read_executor_policy(policy), "alice")
                policy.unlink()
                policy.symlink_to(Path(temp) / "elsewhere")
                with self.assertRaises(OSError):
                    bootstrap.read_executor_policy(policy)

    def test_negative_scope_and_transport_not_modified_by_selector(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        role = (root / "ansible/roles/gway_remote/tasks/main.yml").read_text()
        stage = (root / "gway_remote/bootstrap_script.py").read_text()
        self.assertIn("scripts/resolve-executor-user.py", role)
        self.assertIn('"$@"', stage)
        self.assertNotIn("node_exec_preview", (root / "scripts/resolve-executor-user.py").read_text())
        self.assertIn("gway_remote_resolved_executor_user", role)


if __name__ == "__main__":
    unittest.main()
