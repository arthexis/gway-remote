"""Offline receipt/redaction tests for gway-remote#561 (no commands executed)."""
import importlib.util
from pathlib import Path
import subprocess
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "auto-deploy-ocpp-simulator.py"
spec = importlib.util.spec_from_file_location("simulator_autoinstall_safe_task", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
SECRET = "ghp_PRIVATE_TOKEN_abc123"
TASK = "Reject existing release lacking Go executable"


def failed_output(task=TASK, failed=1):
    return (
        f"TASK [{task}] ***************************************************\n"
        f"fatal: [localhost]: FAILED! => {{'msg': '{SECRET}'}}\n"
        "PLAY RECAP **********************************************************\n"
        f"localhost : ok=7 changed=1 unreachable=0 failed={failed} skipped=2 rescued=0 ignored=0\n"
    )


def receipt(exc, stage="ansible_install"):
    mod.stage(stage)
    return mod.safe_failure(exc)


class AnsibleTaskReceiptTests(unittest.TestCase):
    def test_allowlisted_fatal_with_failed_recap(self):
        exc = subprocess.CalledProcessError(
            2, ["sh", "./deploy.sh", SECRET], output=failed_output(), stderr=SECRET
        )
        result = receipt(exc)
        self.assertIn("stage=ansible_install", result)
        self.assertIn("kind=CalledProcessError exit_code=2", result)
        self.assertIn('ansible_task="' + TASK + '"', result)
        for forbidden in (SECRET, "fatal:", "PLAY RECAP", "stderr", "deploy.sh"):
            self.assertNotIn(forbidden, result)

    def test_every_frozen_task_has_a_safe_label(self):
        self.assertGreaterEqual(len(mod._SAFE_ANSIBLE_TASKS), 35)
        for task in mod._SAFE_ANSIBLE_TASKS:
            with self.subTest(task=task):
                value = receipt(subprocess.CalledProcessError(2, [SECRET], output=failed_output(task)))
                self.assertIn('ansible_task="' + task + '"', value)
                self.assertNotIn(SECRET, value)

    def test_arbitrary_or_sensitive_task_names_are_rejected(self):
        for task in ("Install " + SECRET, "Some unreviewed future task", "{{ token }}"):
            with self.subTest(task=task):
                value = receipt(subprocess.CalledProcessError(2, [SECRET], output=failed_output(task)))
                self.assertIn('ansible_task="unknown"', value)
                self.assertNotIn(SECRET, value)
                self.assertNotIn(task, value)

    def test_missing_nonzero_recap_or_fatal_marker_is_unknown(self):
        samples = (
            failed_output(failed=0),
            failed_output().split("PLAY RECAP")[0],
            failed_output().replace("fatal: [localhost]: FAILED!", "ok: [localhost]"),
            failed_output().replace("PLAY RECAP ", "OTHER RECAP "),
        )
        for sample in samples:
            with self.subTest(kind=sample[:20]):
                value = receipt(subprocess.CalledProcessError(2, [SECRET], output=sample))
                self.assertIn('ansible_task="unknown"', value)
                self.assertNotIn(SECRET, value)

    def test_never_use_stderr_or_other_exception_types(self):
        cases = (
            subprocess.CalledProcessError(2, [SECRET], output=None, stderr=failed_output()),
            subprocess.CalledProcessError(2, [SECRET], output=failed_output().encode(), stderr=SECRET),
            subprocess.TimeoutExpired([SECRET], 3, output=failed_output(), stderr=SECRET),
            OSError(SECRET),
        )
        for exc in cases:
            with self.subTest(kind=type(exc).__name__):
                value = receipt(exc)
                self.assertIn('ansible_task="unknown"', value)
                self.assertNotIn(SECRET, value)
                self.assertNotIn("fatal:", value)

    def test_other_stage_cannot_claim_ansible_task(self):
        value = receipt(
            subprocess.CalledProcessError(2, [SECRET], output=failed_output()),
            stage="checkout",
        )
        self.assertNotIn("ansible_task=", value)
        self.assertNotIn(SECRET, value)

    def test_ansi_malformed_and_large_untrusted_output_fail_closed(self):
        cases = (
            failed_output().replace("TASK [", "\x1b[31mTASK ["),
            "X" * 300000 + failed_output(task="Secret " + SECRET),
        )
        for output in cases:
            with self.subTest(length=len(output)):
                value = receipt(subprocess.CalledProcessError(2, [SECRET], output=output))
                self.assertIn('ansible_task="unknown"', value)
                self.assertNotIn(SECRET, value)


if __name__ == "__main__":
    unittest.main()
