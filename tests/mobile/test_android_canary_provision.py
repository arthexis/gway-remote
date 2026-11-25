"""Hermetic USB canary credential handoff; no live Android or tokens."""
from contextlib import nullcontext
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from gway_remote import android_canary_provision as provision


class ArtifactPinTests(unittest.TestCase):
    def test_current_same_repo_pr_and_exact_manual_artifact_required(self):
        sha = "a" * 40
        replies = {
            "pulls/670": {"state": "open", "head": {
                "sha": sha, "repo": {"full_name": "arthexis/gway-remote"}}},
            "actions/runs/123": {"event": "workflow_dispatch", "status": "completed",
                                 "conclusion": "success", "head_branch": "main",
                                 "path": ".github/workflows/android-canary.yml"},
            "actions/runs/123/artifacts?per_page=25": {"artifacts": [{
                "name": "android-canary-pr670-" + sha[:12],
                "expired": False, "workflow_run": {"id": 123}}]},
        }
        def fake_gh(path):
            return replies[path.split("repos/arthexis/gway-remote/")[1]]
        with patch.object(provision.field, "gh", side_effect=fake_gh):
            with patch.object(provision.field, "provenance") as verify:
                provision.validate_artifact(pr=670, sha=sha, run_id=123, directory=Path("/not-opened"))
                verify.assert_called_once()
                replies["pulls/670"]["state"] = "closed"
                replies["pulls/670"]["merged"] = True
                provision.validate_artifact(pr=670, sha=sha, run_id=123,
                                            directory=Path("/not-opened"))
                replies["pulls/670"]["merged"] = False
                with self.assertRaisesRegex(provision.ProvisionError, "source_pr_changed"):
                    provision.validate_artifact(pr=670, sha=sha, run_id=123,
                                                directory=Path("/not-opened"))


class InstalledPairTests(unittest.TestCase):
    def test_exact_pair_required(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in provision.field.FILES:
                (root / name).write_bytes(name.encode())
            paths = {p: "/data/app/" + p + "-1/base.apk" for p in (provision.field.APP, provision.field.TEST)}
            hashes = {paths[p]: hashlib.sha256((root / n).read_bytes()).hexdigest()
                      for n, p in zip(provision.field.FILES, paths)}
            def adb(serial, *args, **kwargs):
                if args[:3] == ("shell", "pm", "path"):
                    return "package:" + paths[args[3]] + "\n"
                if args[:2] == ("shell", "sha256sum"):
                    return hashes[args[2]] + "  " + args[2] + "\n"
                raise AssertionError(args)
            with patch.object(provision.field, "adb", side_effect=adb):
                provision.verify_installed_pair("usb", root)
                hashes[paths[provision.field.TEST]] = "0" * 64
                with self.assertRaisesRegex(provision.ProvisionError, "digest_mismatch"):
                    provision.verify_installed_pair("usb", root)

    def test_split_or_unsafe_path_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            for name in provision.field.FILES:
                (Path(d) / name).write_bytes(b"fake")
            for path in ("package:/data/app/a/base.apk\npackage:/data/app/a/split.apk",
                         "package:/data/app/a/../base.apk", "package:/system/app/base.apk"):
                with patch.object(provision.field, "adb", return_value=path):
                    with self.assertRaisesRegex(provision.ProvisionError, "path_unverified"):
                        provision.verify_installed_pair("usb", d)

    def test_verified_mode_never_installs(self):
        with (patch.object(provision, "validate_artifact"),
              patch.object(provision, "DeviceCredentials") as registry,
              patch.object(provision.field, "usb", return_value="usb"),
              patch.object(provision.field, "keep_usb_screen_on", return_value=nullcontext()),
              patch.object(provision.field, "device_ready", return_value=True),
              patch.object(provision.field, "install") as install,
              patch.object(provision, "verify_installed_pair", side_effect=provision.ProvisionError("mismatch")),
              patch.object(provision, "_private_command")):
            with self.assertRaisesRegex(provision.ProvisionError, "installed_pair_verification"):
                provision.run(pr=719, sha="a"*40, run_id=123, directory=Path("/safe"), verified_installed=True)
            install.assert_not_called()
            registry.return_value.issue.assert_not_called()


class DeviceUsbProvisionTests(unittest.TestCase):
    def test_verified_stdin_secret_never_enters_command_arguments_or_output(self):
        credential = "gwymob1_" + "a" * 24 + "_" + "X" * 43
        expected = hashlib.sha256(credential.encode("ascii")).hexdigest()

        def fake_subprocess(argv, **kwargs):
            if argv[-2:] == ["-ld", "files"]:
                stdout = b"drwx------ 2 app app 4096 files\n"
            elif argv[-2:] == ["-l", provision.PROVISION_FILE]:
                stdout = b"-rw------- 1 app app 76 seed\n"
            elif "sha256sum" in argv:
                stdout = (expected + "  " + provision.PROVISION_FILE + "\n").encode()
            else:
                stdout = b""
            return Mock(returncode=0, stdout=stdout, stderr=b"")

        with patch.object(provision.subprocess, "run", side_effect=fake_subprocess) as run:
            provision.pipe_to_canary("usb-device", credential)

        calls = [call for call in run.call_args_list]
        for call in calls:
            self.assertNotIn(credential, " ".join(map(str, call.args[0])))
            self.assertTrue(call.kwargs["capture_output"])
        writer = [call for call in calls if "shell" in call.args[0]
                  and "-T" in call.args[0]]
        self.assertEqual(len(writer), 1)
        self.assertEqual(writer[0].kwargs["input"], credential.encode("ascii"))
        self.assertIn("dd", writer[0].args[0])
        self.assertIn("sha256sum", [arg for call in calls for arg in call.args[0]])
        self.assertIn("chmod", [arg for call in calls for arg in call.args[0]])

    def test_handoff_rejects_adb_zero_exit_when_digest_wrong(self):
        credential = "gwymob1_" + "c" * 24 + "_" + "Y" * 43

        def fake_subprocess(argv, **kwargs):
            if argv[-2:] == ["-ld", "files"]:
                data = b"drwx------ 2 app app 4096 files\n"
            elif "sha256sum" in argv:
                data = (("0" * 64) + "  seed\n").encode()
            else:
                data = b""
            return Mock(returncode=0, stdout=data, stderr=b"")

        with patch.object(provision.subprocess, "run", side_effect=fake_subprocess) as run:
            with self.assertRaisesRegex(provision.ProvisionError, "private_usb_handoff_unverified"):
                provision.pipe_to_canary("usb-device", credential)
        self.assertTrue(any("rm" in call.args[0] for call in run.call_args_list))
        self.assertNotIn(credential, str([call.args for call in run.call_args_list]))

    def test_failed_provision_revokes_issued_token_and_cleans_seed(self):
        record = {"id": "a"*24,
                  "token": "gwymob1_" + "a"*24 + "_" + "X"*43,
                  "scope": "read", "expires_at": 99999999}
        registry = Mock()
        registry.issue.return_value = record
        with (
            patch.object(provision, "validate_artifact"),
            patch.object(provision, "DeviceCredentials", return_value=registry),
            patch.object(provision.field, "usb", return_value="usb-serial"),
            patch.object(provision.field, "device_ready", return_value=False),
            patch.object(provision.field, "keep_usb_screen_on", return_value=nullcontext()),
            patch.object(provision.field, "install"),
            patch.object(provision.field, "adb", return_value="FAILURES!!!") as adb,
            patch.object(provision, "pipe_to_canary") as handoff,
            patch.object(provision, "_private_command") as private,
        ):
            with self.assertRaisesRegex(provision.ProvisionError, "usb_mobile_provisioning_failed:android_https"):
                provision.run(pr=670, sha="a"*40, run_id=123, directory=Path("/safe"))
            registry.revoke.assert_called_once_with("a"*24)
            handoff.assert_called_once()
            private.assert_called_with("usb-serial", "rm", "-f", provision.PROVISION_FILE)

    def test_wake_occurs_inside_usb_guard(self):
        from contextlib import contextmanager
        events = []
        @contextmanager
        def guard(serial):
            events.append("guard_enter")
            try:
                yield
            finally:
                events.append("guard_exit")
        def ready(*args, **kwargs):
            events.append("ready")
            raise provision.field.CanaryError("screen_not_awake")
        with (patch.object(provision, "validate_artifact"),
              patch.object(provision, "DeviceCredentials"),
              patch.object(provision.field, "usb", return_value="usb"),
              patch.object(provision.field, "keep_usb_screen_on", side_effect=guard),
              patch.object(provision.field, "device_ready", side_effect=ready),
              patch.object(provision, "_private_command")):
            with self.assertRaisesRegex(provision.ProvisionError, "usb_mobile_provisioning_failed:device_ready"):
                provision.run(pr=670, sha="a"*40, run_id=123, directory=Path("/safe"))
        self.assertEqual(events, ["guard_enter", "ready", "guard_exit"])

    def test_full_success_exposes_only_safe_receipt(self):
        record = {"id": "b"*24,
                  "token": "gwymob1_" + "b"*24 + "_" + "Z"*43,
                  "scope": "read", "expires_at": 3000000000}
        registry = Mock()
        registry.issue.return_value = record
        with (
            patch.object(provision, "validate_artifact"),
            patch.object(provision, "DeviceCredentials", return_value=registry),
            patch.object(provision.field, "usb", return_value="usb-serial"),
            patch.object(provision.field, "device_ready", return_value=True),
            patch.object(provision.field, "keep_usb_screen_on", return_value=nullcontext()),
            patch.object(provision.field, "install") as install,
            patch.object(provision.field, "instrument", return_value=6),
            patch.object(provision.field, "adb", return_value="OK (1 test)\nINSTRUMENTATION_CODE: -1\n"),
            patch.object(provision, "pipe_to_canary") as handoff,
            patch.object(provision, "_private_command") as private,
        ):
            result = provision.run(pr=670, sha="a"*40, run_id=123, directory=Path("/safe"))
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["compose_tests_passed"], 6)
        self.assertEqual(result["credential_id"], record["id"])
        self.assertNotIn(record["token"], repr(result))
        registry.revoke.assert_not_called()
        install.assert_called_once()
        handoff.assert_called_once_with("usb-serial", record["token"])


if __name__ == "__main__":
    unittest.main()
