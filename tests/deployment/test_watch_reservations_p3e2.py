"""Issue #565 P3-E2: checked catalog controls reservation journal validation only.

No real GitHub calls, node operations, deployment workflows or processes.
All journal paths are unique temporary directories.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gway_remote import appliance_watch as watch
from gway_remote.catalog_shadow import load_catalog
from gway_remote.reconcile import TARGETS


NOW = datetime(2026, 11, 17, 4, 0, tzinfo=timezone.utc)
SHA = "a" * 40
OTHER = "b" * 40


class ReservationJournalP3E2Tests(unittest.TestCase):
    def test_valid_legacy_journal_and_all_seven_ids(self):
        reviewed = tuple((item.id, item.repository)
                         for item in load_catalog().targets)
        self.assertEqual(reviewed, TARGETS)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watch-dispatches.json"
            original = {name: SHA for name, _ in TARGETS}
            path.write_text(json.dumps(original), encoding="utf-8")
            with patch.object(watch, "load_catalog", wraps=load_catalog) as loader:
                self.assertEqual(watch._dispatch_reservations(directory), original)
                loader.assert_called_once_with()
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                             original)

    def test_empty_journal_validates_catalog_first(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(watch, "load_catalog",
                              side_effect=ValueError("catalog unavailable")) as loader:
                with patch.object(watch.Path, "exists",
                                  side_effect=AssertionError("journal access")) as exists:
                    with self.assertRaisesRegex(ValueError, "catalog unavailable"):
                        watch._dispatch_reservations(directory)
                    loader.assert_called_once_with()
                    exists.assert_not_called()
            self.assertFalse((Path(directory) / "watch-dispatches.json").exists())

    def test_catalog_registry_drift_fails_closed_without_journal_write(self):
        checked = load_catalog()
        changed = replace(checked, targets=checked.targets + (checked.targets[0],))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watch-dispatches.json"
            path.write_text(json.dumps({"ocpp-csms": SHA}), encoding="utf-8")
            original = path.read_bytes()
            with patch("gway_remote.catalog_shadow.load_catalog_data",
                       return_value=changed):
                with self.assertRaisesRegex(ValueError, "catalog drifts"):
                    watch._dispatch_reservations(directory)
                with self.assertRaisesRegex(ValueError, "catalog drifts"):
                    watch._reserve_dispatch("ocpp-csms", OTHER, directory)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).glob(".watch-*")), [])

    def test_unknown_names_bad_sha_and_invalid_journal_remain_rejected(self):
        cases = (
            {"ocpp-simulator": SHA},
            {"unexpected-repo": SHA},
            {"ocpp-csms": SHA, "unexpected-repo": OTHER},
            {"ocpp-csms": "A" * 40},
            {"ocpp-csms": "g" * 40},
            {"ocpp-csms": ""},
            {"ocpp-csms": 0},
            {"ocpp-csms": None},
            [("ocpp-csms", SHA)],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watch-dispatches.json"
            for payload in cases:
                with self.subTest(payload=payload):
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "invalid appliance watch dispatch journal"):
                        watch._dispatch_reservations(directory)
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                watch._dispatch_reservations(directory)

    def test_atomic_write_before_repeat_and_exact_legacy_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watch-dispatches.json"
            with patch.object(watch.os, "fsync", wraps=os.fsync) as fsync:
                with patch.object(watch.os, "replace", wraps=os.replace) as replace:
                    self.assertTrue(watch._reserve_dispatch("ocpp-csms", SHA, directory))
                    self.assertFalse(watch._reserve_dispatch("ocpp-csms", SHA, directory))
                    fsync.assert_called_once()
                    replace.assert_called_once()
            self.assertEqual(path.read_bytes(), b'{"ocpp-csms": "' + SHA.encode() + b'"}\n')
            self.assertEqual(watch._dispatch_reservations(directory),
                             {"ocpp-csms": SHA})
            self.assertEqual(list(Path(directory).glob(".watch-*")), [])

    def test_atomic_replace_failure_keeps_prior_journal_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(watch._reserve_dispatch("ocpp-csms", SHA, directory))
            path = Path(directory) / "watch-dispatches.json"
            old_bytes = path.read_bytes()
            with patch.object(watch.os, "replace",
                              side_effect=OSError("simulated replace failure")):
                with self.assertRaisesRegex(OSError, "simulated replace failure"):
                    watch._reserve_dispatch("ocpp-csms", OTHER, directory)
            self.assertEqual(path.read_bytes(), old_bytes)
            self.assertEqual(list(Path(directory).glob(".watch-*")), [])

    def test_mocked_apply_only_dispatches_after_durable_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = watch._dispatch_reservations
            reserver = watch._reserve_dispatch
            row = {"name": "ocpp-csms", "managed": True,
                   "revision_status": "behind", "attempted_sha": OTHER,
                   "attempt_status": "failed", "latest_sha": SHA,
                   "installed_sha": OTHER}
            observation = {"name": "ocpp-csms", "diagnosis": "healthy",
                           "diagnosis_reason": "", "health": "healthy"}
            dispatches = []

            def fake_dispatch(name):
                self.assertEqual(name, "ocpp-csms")
                self.assertEqual(reader(directory), {"ocpp-csms": SHA})
                self.assertTrue((Path(directory) / "watch-dispatches.json").exists())
                dispatches.append(name)

            with ExitStack() as stack:
                def fake_reader(_unused=None):
                    return reader(directory)

                stack.enter_context(patch.object(
                    watch, "_dispatch_reservations", side_effect=fake_reader))
                stack.enter_context(patch.object(
                    watch, "_reserve_dispatch",
                    side_effect=lambda name, sha: reserver(name, sha, directory)))
                stack.enter_context(patch.object(watch, "read_attempts", return_value={}))
                stack.enter_context(patch.object(
                    watch, "inventory", return_value={"components": [row]}))
                stack.enter_context(patch.object(
                    watch, "diagnose", return_value={"components": [observation]}))
                stack.enter_context(patch.object(
                    watch, "quick_component_check", return_value="ok"))
                stack.enter_context(patch.object(
                    watch, "ci_for_head", return_value="success"))
                stack.enter_context(patch.object(
                    watch, "main_arrival", return_value=NOW - timedelta(minutes=30)))
                busy = stack.enter_context(patch.object(
                    watch, "_busy", return_value=False))
                dispatch = stack.enter_context(patch.object(
                    watch, "dispatch", side_effect=fake_dispatch))
                issue = stack.enter_context(patch.object(watch, "_issue"))
                client = object()
                first = watch.check(apply=True, client=client, now=NOW)
                self.assertEqual(first["dispatched"], "ocpp-csms")
                second = watch.check(apply=True, client=client, now=NOW)
                self.assertIsNone(second["dispatched"])
                self.assertEqual(second["decisions"][0]["state"],
                                 "previously-dispatched")
                self.assertEqual(dispatches, ["ocpp-csms"])
                dispatch.assert_called_once_with("ocpp-csms")
                busy.assert_called_once_with()
                issue.assert_not_called()

    def test_reader_never_dispatches_or_writes_issues(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watch-dispatches.json"
            path.write_text(json.dumps({"ocpp-csms": SHA}), encoding="utf-8")
            old_bytes = path.read_bytes()
            with patch.object(watch, "dispatch",
                              side_effect=AssertionError("dispatch")) as dispatch:
                with patch.object(watch, "_issue",
                                  side_effect=AssertionError("issue write")) as issue:
                    self.assertEqual(
                        watch._dispatch_reservations(directory), {"ocpp-csms": SHA})
                    dispatch.assert_not_called()
                    issue.assert_not_called()
            self.assertEqual(path.read_bytes(), old_bytes)


if __name__ == "__main__":
    unittest.main()
