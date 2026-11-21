"""Hermetic USB canary credential handoff; no live Android or tokens."""
from contextlib import nullcontext
from pathlib import Path
import subprocess
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


class DeviceUsbProvisionTests(unittest.TestCase):
    def test_secret_is_only_stdin_not_process_arguments(self):
        credential = "gwymob1_" + "a" * 24 + "_" + "X" * 43
        with patch.object(provision.subprocess, "run",
                          return_value=Mock(returncode=0)) as shell:
            provision.pipe_to_canary("usb-serial", credential)
        argv = shell.call_args.args[0]
        self.assertNotIn(credential, " ".join(argv))
        self.assertIn("run-as", argv)
        self.assertIn(provision.field.APP, argv)
        self.assertEqual(shell.call_args.kwargs["input"], credential.encode("ascii"))
        self.assertTrue(shell.call_args.kwargs["capture_output"])

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
        ):
            with self.assertRaisesRegex(provision.ProvisionError, "usb_mobile_provisioning_failed"):
                provision.run(pr=670, sha="a"*40, run_id=123, directory=Path("/safe"))
            registry.revoke.assert_called_once_with("a"*24)
            handoff.assert_called_once()
            self.assertTrue(any(
                call.args[1:4] == ("shell", "run-as", provision.field.APP)
                for call in adb.call_args_list
            ))

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
