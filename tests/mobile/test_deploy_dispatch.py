import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from gway_remote.mobile_deploy_dispatch import dispatch
from gway_remote.mobile import commands

KEY = "a" * 32


class DeploymentDispatchTests(unittest.TestCase):
    def test_explicit_dispatch_and_idempotent_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            sender = Mock()
            args = {"target": "all", "request_id": KEY, "confirm": True}
            journal, lock = Path(tmp) / "requests.json", Path(tmp) / "lock"
            first = dispatch(args, sender=sender, journal=journal, lock=lock)
            self.assertEqual(first["state"], "unconfirmed")
            self.assertIsNone(first["run_id"])
            self.assertEqual(dispatch(args, sender=sender, journal=journal, lock=lock), first)
            sender.assert_called_once_with("all", KEY)
            with self.assertRaisesRegex(ValueError, "deployment_dispatch_unresolved"):
                dispatch({**args, "request_id": "b" * 32},
                         sender=sender, journal=journal, lock=lock)

    def test_timeout_is_persisted_not_resubmitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            sender = Mock(side_effect=TimeoutError("unknown"))
            args = {"target": "ocpp-csms", "request_id": KEY, "confirm": True}
            journal, lock = Path(tmp) / "requests.json", Path(tmp) / "lock"
            with self.assertRaises(TimeoutError):
                dispatch(args, sender=sender, journal=journal, lock=lock)
            self.assertEqual(dispatch(args, sender=sender, journal=journal, lock=lock)["state"],
                             "unconfirmed")
            sender.assert_called_once()

    def test_rejects_unconfirmed_or_arbitrary_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            sender = Mock()
            for args in (
                {"target": "all", "request_id": KEY, "confirm": False},
                {"target": "gway-remote", "request_id": KEY, "confirm": True},
                {"target": "all", "request_id": "not-an-id", "confirm": True},
                {"target": "all", "request_id": KEY, "confirm": True, "force": True},
            ):
                with self.assertRaises(ValueError):
                    dispatch(args, sender=sender, journal=Path(tmp) / "journal",
                             lock=Path(tmp) / "lock")
            sender.assert_not_called()

    def test_advertised_mutating(self):
        spec = next(x for x in commands() if x["name"] == "deployments-dispatch")
        self.assertFalse(spec["read_only"])


if __name__ == "__main__":
    unittest.main()
