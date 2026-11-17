"""Hermetic dispatch diagnostics for #606/#608; no GitHub or node I/O."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import subprocess
import unittest
from unittest.mock import patch

from gway_remote import appliance_watch as watch


NOW = datetime(2026, 11, 17, 14, tzinfo=timezone.utc)
REVISION = "a" * 40
OLD = "b" * 40
SECRET = "ghp_PRIVATE_NEVER_PUBLISH"


class SanitizedDispatchFailureTests(unittest.TestCase):
    def test_wrapped_gh_http_and_exit_code_without_stderr_or_argv(self):
        cause = subprocess.CalledProcessError(
            1, ["gh", "api", SECRET],
            stderr=f"gh: HTTP 403: token={SECRET}\nhttps://secret.invalid/{SECRET}")
        error = RuntimeError(f"GitHub workflow dispatch failed: {cause.stderr}")
        error.__cause__ = cause
        reason = watch._dispatch_failure_reason("gway-agent-ops", REVISION, error)
        self.assertIn("target=gway-agent-ops", reason)
        self.assertIn(f"revision={REVISION}", reason)
        self.assertIn("error_class=RuntimeError", reason)
        self.assertIn("cause_class=CalledProcessError", reason)
        self.assertIn("http_status=403", reason)
        self.assertIn("exit_code=1", reason)
        self.assertNotIn(SECRET, reason)
        self.assertNotIn("secret.invalid", reason)
        self.assertNotIn("stderr", reason)
        self.assertLess(len(reason), 500)

    def test_direct_process_error_and_missing_http(self):
        exc = subprocess.CalledProcessError(
            22, ["gh", SECRET], stderr=f"gh: token={SECRET}")
        reason = watch._dispatch_failure_reason("ocpp-csms", REVISION, exc)
        self.assertIn("error_class=CalledProcessError", reason)
        self.assertIn("cause_class=unavailable", reason)
        self.assertIn("http_status=unavailable", reason)
        self.assertIn("exit_code=22", reason)
        self.assertNotIn(SECRET, reason)

    def test_http_v2_and_timeout_without_a_numeric_exit(self):
        exc = RuntimeError(f"gh: HTTP/2 503: {SECRET}")
        reason = watch._dispatch_failure_reason("ocpp-csms", REVISION, exc)
        self.assertIn("http_status=503", reason)
        self.assertIn("exit_code=unavailable", reason)
        self.assertNotIn(SECRET, reason)
        timeout = subprocess.TimeoutExpired(["gh", SECRET], 30)
        exc.__cause__ = timeout
        reason = watch._dispatch_failure_reason("ocpp-csms", REVISION, exc)
        self.assertIn("cause_class=TimeoutExpired", reason)
        self.assertIn("exit_code=unavailable", reason)

    def test_malformed_input_and_unknown_exception_class_are_not_published(self):
        class EvilTokenRuntimeError(RuntimeError):
            pass

        exc = EvilTokenRuntimeError(f"HTTP 999 {SECRET}")
        reason = watch._dispatch_failure_reason("../secret", SECRET, exc)
        self.assertIn("target=unknown", reason)
        self.assertIn("revision=unknown", reason)
        self.assertIn("error_class=OtherError", reason)
        self.assertIn("http_status=unavailable", reason)
        self.assertNotIn(SECRET, reason)
        self.assertNotIn("EvilTokenRuntimeError", reason)

    def _exercise(self, target, *, failure=None, reserve_failure=None):
        events = []
        row = {
            "name": target, "managed": True, "revision_status": "behind",
            "attempted_sha": OLD, "attempt_status": "installed",
            "latest_sha": REVISION, "installed_sha": OLD,
        }
        observation = {"name": target, "diagnosis": "healthy", "health": "healthy"}
        with ExitStack() as stack:
            def mocked(attr, return_value):
                return stack.enter_context(
                    patch.object(watch, attr, return_value=return_value))

            mocked("read_attempts", {})
            mocked("_dispatch_reservations", {})
            mocked("inventory", {"components": [row]})
            mocked("diagnose", {"components": [observation]})
            mocked("quick_component_check", "healthy")
            mocked("ci_for_head", "success")
            mocked("main_arrival", NOW - timedelta(minutes=20))
            mocked("_busy", False)

            def reserve(name, sha):
                events.append(("reserve", name, sha))
                if reserve_failure is not None:
                    raise reserve_failure
                return True

            def dispatch(name):
                events.append(("dispatch", name))
                if failure is not None:
                    raise failure

            def issue(repo, name, kind, reason):
                events.append(("issue", repo, name, kind, reason))

            stack.enter_context(patch.object(watch, "_reserve_dispatch", side_effect=reserve))
            stack.enter_context(patch.object(watch, "dispatch", side_effect=dispatch))
            stack.enter_context(patch.object(watch, "_issue", side_effect=issue))
            if failure is not None or reserve_failure is not None:
                with self.assertRaises(type(failure or reserve_failure)) as caught:
                    watch.check(apply=True, client=object(), now=NOW)
                self.assertIs(caught.exception, failure or reserve_failure)
            else:
                result = watch.check(apply=True, client=object(), now=NOW)
                self.assertEqual(result["dispatched"], target)
        return events

    def test_both_issues_preserve_reservation_dispatch_issue_and_reraise_order(self):
        for target in ("ocpp-csms", "gway-agent-ops"):
            with self.subTest(target=target):
                cause = subprocess.CalledProcessError(
                    1, ["gh", SECRET], stderr=f"gh: HTTP 403: {SECRET}")
                error = RuntimeError(f"GitHub workflow dispatch failed: {SECRET}")
                error.__cause__ = cause
                events = self._exercise(target, failure=error)
                self.assertEqual([step[0] for step in events],
                                 ["reserve", "dispatch", "issue"])
                self.assertEqual(events[0], ("reserve", target, REVISION))
                self.assertEqual(events[1], ("dispatch", target))
                self.assertEqual(events[2][1:4],
                                 ("arthexis/gway-remote", target, "dispatch-failure"))
                self.assertIn(f"target={target}", events[2][4])
                self.assertIn(f"revision={REVISION}", events[2][4])
                self.assertIn("http_status=403", events[2][4])
                self.assertNotIn(SECRET, events[2][4])

    def test_reservation_oserror_still_opens_issue_without_dispatch(self):
        events = self._exercise("ocpp-csms", reserve_failure=OSError(SECRET))
        self.assertEqual([step[0] for step in events], ["reserve", "issue"])
        self.assertIn("error_class=OSError", events[-1][-1])
        self.assertIn("exit_code=unavailable", events[-1][-1])
        self.assertNotIn(SECRET, events[-1][-1])

    def test_success_does_not_open_issue_or_change_dispatch(self):
        events = self._exercise("gway-agent-ops")
        self.assertEqual(events, [
            ("reserve", "gway-agent-ops", REVISION),
            ("dispatch", "gway-agent-ops"),
        ])


if __name__ == "__main__":
    unittest.main()
