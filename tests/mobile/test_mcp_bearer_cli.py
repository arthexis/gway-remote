"""Local bearer privilege boundaries; never touches real accounts or tokens."""
import contextlib
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipapp

from gway_remote import mcp_bearer_cli as identity
from gway_remote.__main__ import main


class BearerIdentityTests(unittest.TestCase):
    def setUp(self):
        self.account = SimpleNamespace(pw_uid=995, pw_gid=999)
        self.state = {"uid": 0, "gid": 0}
        self.steps = []
        self.os = Mock()
        self.os.getuid.side_effect = self.os.geteuid.side_effect = lambda: self.state["uid"]
        self.os.getgid.side_effect = self.os.getegid.side_effect = lambda: self.state["gid"]
        self.os.setgroups.side_effect = lambda groups: self.steps.append(("groups", groups))

        def gid(value):
            self.steps.append(("gid", value))
            self.state["gid"] = value

        def uid(value):
            self.steps.append(("uid", value))
            self.state["uid"] = value

        self.os.setgid.side_effect, self.os.setuid.side_effect = gid, uid
        self.enterContext(patch.object(identity, "os", self.os))
        self.lookup = self.enterContext(patch.object(identity.pwd, "getpwnam", return_value=self.account))

    def test_root_drops_all_groups_and_ids_before_return(self):
        identity.assume_auth_identity()
        self.assertEqual(self.steps, [("groups", []), ("gid", 999), ("uid", 995)])
        self.assertEqual(self.state, {"uid": 995, "gid": 999})
        self.lookup.assert_called_once_with("gway-mcp-auth")

    def test_existing_auth_owner_needs_no_privilege_change(self):
        self.state.update(uid=995, gid=999)
        identity.assume_auth_identity()
        self.assertEqual(self.steps, [])

    def test_unprivileged_operator_gets_sudo_guidance_without_switching(self):
        self.state.update(uid=1000, gid=1000)
        with self.assertRaisesRegex(identity.BearerAdminError, "sudo gway-remote bearer"):
            identity.assume_auth_identity()
        self.assertEqual(self.steps, [])

    def test_missing_account_does_not_create_or_switch_identity(self):
        self.lookup.side_effect = KeyError("missing")
        with self.assertRaisesRegex(identity.BearerAdminError, "not provisioned"):
            identity.assume_auth_identity()
        self.assertEqual(self.steps, [])

    def test_root_or_invalid_service_identity_is_rejected(self):
        for uid, gid in [(0, 999), (995, 0), (-1, 999), (995, -1)]:
            with self.subTest(uid=uid, gid=gid):
                self.account.pw_uid, self.account.pw_gid = uid, gid
                with self.assertRaises(identity.BearerAdminError):
                    identity.assume_auth_identity()
                self.assertEqual(self.steps, [])

    def test_failed_drop_never_opens_registry(self):
        for operation in ("setgroups", "setgid", "setuid"):
            with self.subTest(operation=operation):
                self.state.update(uid=0, gid=0)
                original = getattr(self.os, operation).side_effect
                getattr(self.os, operation).side_effect = PermissionError("denied")
                try:
                    with self.cli("issue"), patch("gway_remote.mcp_bearer.BearerRegistry") as registry:
                        with self.assertRaises(SystemExit) as stopped:
                            main()
                        self.assertEqual(stopped.exception.code, 1)
                        registry.assert_not_called()
                finally:
                    getattr(self.os, operation).side_effect = original

    def test_silent_failed_switch_is_rejected_before_registry(self):
        self.os.setuid.side_effect = lambda uid: None
        with self.cli("issue"), patch("gway_remote.mcp_bearer.BearerRegistry") as registry:
            with self.assertRaises(SystemExit):
                main()
            registry.assert_not_called()

    @contextlib.contextmanager
    def cli(self, *args, input_tty=True, output_tty=True):
        output = io.StringIO()
        with patch.object(sys, "argv", ["gway-remote", "bearer", *args]), \
                patch.object(sys, "stdin", Mock(isatty=lambda: input_tty)), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()), \
                patch.object(output, "isatty", return_value=output_tty):
            yield output

    def test_issue_and_revoke_only_open_registry_after_dropping_root(self):
        for args in [("issue", "--days", "7"), ("revoke", "a" * 24)]:
            with self.subTest(args=args):
                self.state.update(uid=0, gid=0)

                def create(path):
                    self.assertEqual(self.state, {"uid": 995, "gid": 999})
                    self.assertEqual(path, "/var/lib/gway-mcp-auth/credentials.sqlite3")
                    return Mock(issue=Mock(return_value="unit-test-token"), revoke=Mock(return_value=True))

                with self.cli(*args) as output, \
                        patch("gway_remote.mcp_bearer.BearerRegistry", side_effect=create) as registry:
                    main()
                    registry.assert_called_once()
                    self.assertIn("unit-test-token" if args[0] == "issue" else "Bearer revoked", output.getvalue())

    def test_scoped_issuance_is_console_only_and_uses_selected_scope(self):
        for flags, scope in [
            (("issue",), "gway:read"),
            (("issue", "--scope", "gway:read", "--days", "7"), "gway:read"),
            (("issue", "--scope", "gway:execute", "--days", "30"), "gway:execute"),
        ]:
            with self.subTest(flags=flags):
                self.state.update(uid=0, gid=0)
                issued = Mock(return_value="unit-test-token")
                with self.cli(*flags) as output, \
                        patch("gway_remote.mcp_bearer.BearerRegistry") as registry:
                    registry.return_value.issue = issued
                    main()
                self.assertIn("unit-test-token", output.getvalue())
                days = 7 if "7" in flags else 30
                issued.assert_called_once_with(
                    scope=scope, lifetime=days * 86400,
                    operator_approved=(scope == "gway:execute"))
                self.assertEqual(self.state, {"uid": 995, "gid": 999})

    def test_invalid_scope_fails_before_identity_switch(self):
        with self.cli("issue", "--scope", "gway:admin"), \
                patch("gway_remote.mcp_bearer.BearerRegistry") as registry:
            with self.assertRaises(SystemExit) as stopped:
                main()
        self.assertEqual(stopped.exception.code, 2)
        registry.assert_not_called()
        self.assertEqual(self.steps, [])

    def test_issuing_to_or_from_a_pipe_never_switches_or_writes(self):
        for input_tty, output_tty in [(False, True), (True, False), (False, False)]:
            with self.subTest(input_tty=input_tty, output_tty=output_tty):
                with self.cli("issue", input_tty=input_tty, output_tty=output_tty), \
                        patch("gway_remote.mcp_bearer.BearerRegistry") as registry:
                    with self.assertRaises(SystemExit):
                        main()
                    registry.assert_not_called()
                    self.assertEqual(self.steps, [])


class BearerPackagingTests(unittest.TestCase):
    def test_global_zipapp_includes_bearer_admin_and_rejects_pipe(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = temp / "src"
            source.mkdir()
            shutil.copytree(root / "gway_remote", source / "gway_remote",
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (source / "__main__.py").write_text("from gway_remote.__main__ import main\nmain()\n")
            archive = temp / "gway-remote.pyz"
            zipapp.create_archive(source, archive, interpreter="/usr/bin/env python3")
            imported = subprocess.run(
                [sys.executable, "-I", "-c",
                 "import sys; sys.path.insert(0, sys.argv[1]); "
                 "from gway_remote import mcp_bearer_cli; "
                 "assert mcp_bearer_cli.__file__.startswith(sys.argv[1]); "
                 "print(mcp_bearer_cli.AUTH_USER)", str(archive)],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(imported.returncode, 0, imported.stderr)
            self.assertEqual(imported.stdout.strip(), "gway-mcp-auth")
            help_result = subprocess.run([sys.executable, str(archive), "bearer", "issue", "--help"],
                                         capture_output=True, text=True, timeout=10)
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertIn("--days", help_result.stdout)
            self.assertIn("--scope", help_result.stdout)
            self.assertIn("gway:execute", help_result.stdout)
            issue = subprocess.run([sys.executable, str(archive), "bearer", "issue"],
                                   capture_output=True, text=True, timeout=10)
            self.assertEqual(issue.returncode, 1)
            self.assertEqual(issue.stdout, "")
            self.assertIn("interactive console", issue.stderr)
