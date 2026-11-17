"""#565 P3-E1 hermetic watcher catalog source-map parity and no-extra-dispatch."""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch

from gway_remote import appliance_watch
from gway_remote.catalog_shadow import load_catalog
from gway_remote.reconcile import TARGETS


NOW = datetime(2026, 11, 17, 3, 40, tzinfo=timezone.utc)
SHA = "a" * 40
OLD = "b" * 40


class WatchCatalogSourcesP3E1(TestCase):
    def fixture(self, *, name="ocpp-csms", managed=True, revision="behind",
                attempted=OLD, diagnosis="healthy", reserved=None,
                ci="success", arrival=None, busy=True):
        row = {
            "name": name, "managed": managed, "revision_status": revision,
            "attempted_sha": attempted, "attempt_status": "failed",
            "latest_sha": SHA, "installed_sha": OLD,
        }
        observed = {"name": name, "diagnosis": diagnosis,
                    "diagnosis_reason": "diagnostic", "health": "healthy"}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        def mock(name, value=None):
            return self.stack.enter_context(
                patch.object(appliance_watch, name, return_value=value))
        self.load = self.stack.enter_context(
            patch.object(appliance_watch, "load_catalog", wraps=load_catalog))
        self.auth = mock("_github_client")
        self.attempts = mock("read_attempts", {})
        self.reservations = mock("_dispatch_reservations", reserved or {})
        self.inventory = mock("inventory", {"components": [row]})
        self.diagnose = mock("diagnose", {"components": [observed]})
        self.evidence = mock("quick_component_check", "ok")
        self.ci = mock("ci_for_head", ci)
        self.arrival = mock(
            "main_arrival", NOW - timedelta(minutes=20)
            if arrival is None else arrival)
        self.busy = mock("_busy", busy)
        self.reserve = mock("_reserve_dispatch", True)
        self.dispatch = mock("dispatch", "should-not-be-called")
        self.issue = mock("_issue")
        return object()

    def test_read_only_uses_checked_repository_and_never_dispatches(self):
        client = self.fixture()
        result = appliance_watch.check(apply=False, client=client, now=NOW)
        self.load.assert_called_once_with()
        self.assertEqual(result["schema"], "gway-remote/watch/v1")
        self.assertEqual(result["decisions"],
                         [{"name": "ocpp-csms", "state": "ready",
                           "reason": "new main revision"}])
        self.ci.assert_called_once_with(client, "arthexis/ocpp-csms", SHA)
        self.arrival.assert_called_once_with(client, "arthexis/ocpp-csms", SHA)
        self.dispatch.assert_not_called()
        self.reserve.assert_not_called()
        self.busy.assert_not_called()
        self.issue.assert_not_called()

    def test_unmanaged_does_not_inquire_or_dispatch_even_with_apply(self):
        client = self.fixture(managed=False, busy=False)
        result = appliance_watch.check(apply=True, client=client, now=NOW)
        self.assertEqual(result["decisions"],
                         [{"name": "ocpp-csms", "state": "unmanaged"}])
        self.ci.assert_not_called()
        self.arrival.assert_not_called()
        self.busy.assert_not_called()
        self.reserve.assert_not_called()
        self.dispatch.assert_not_called()
        self.issue.assert_not_called()

    def test_reserved_revision_never_dispatches(self):
        client = self.fixture(reserved={"ocpp-csms": SHA}, busy=False)
        result = appliance_watch.check(apply=True, client=client, now=NOW)
        self.assertEqual(result["decisions"],
                         [{"name": "ocpp-csms", "state": "previously-dispatched"}])
        self.reserve.assert_not_called()
        self.busy.assert_not_called()
        self.dispatch.assert_not_called()

    def test_busy_workflow_prevents_new_reservation_and_dispatch(self):
        client = self.fixture(busy=True)
        result = appliance_watch.check(apply=True, client=client, now=NOW)
        self.assertIsNone(result["dispatched"])
        self.busy.assert_called_once_with()
        self.reserve.assert_not_called()
        self.dispatch.assert_not_called()

    def test_unverified_ci_and_unknown_install_never_dispatch(self):
        for kwargs in ({"ci": "unknown"}, {"revision": "unknown"}):
            with self.subTest(kwargs=kwargs):
                client = self.fixture(**kwargs, busy=False)
                result = appliance_watch.check(apply=True, client=client, now=NOW)
                self.assertIsNone(result["dispatched"])
                self.reserve.assert_not_called()
                self.dispatch.assert_not_called()
                self.stack.close()

    def test_error_catalog_fails_closed_before_token_or_journal(self):
        with patch.object(appliance_watch, "load_catalog",
                          side_effect=ValueError("catalog drift")) as loader, \
             patch.object(appliance_watch, "_github_client",
                          side_effect=AssertionError("token")) as auth, \
             patch.object(appliance_watch, "read_attempts",
                          side_effect=AssertionError("journal")) as journal, \
             patch.object(appliance_watch, "inventory",
                          side_effect=AssertionError("inventory")) as inventory, \
             patch.object(appliance_watch, "dispatch",
                          side_effect=AssertionError("dispatch")) as dispatch:
            with self.assertRaisesRegex(ValueError, "catalog drift"):
                appliance_watch.check(apply=True, now=NOW)
            loader.assert_called_once_with()
            auth.assert_not_called()
            journal.assert_not_called()
            inventory.assert_not_called()
            dispatch.assert_not_called()

    def test_all_seven_catalog_sources_equal_reviewed_map(self):
        catalog = load_catalog()
        self.assertEqual(
            tuple((target.id, target.repository) for target in catalog.targets),
            TARGETS)
        self.assertEqual(len(TARGETS), 7)
        self.assertNotIn("ocpp-simulator", dict(TARGETS))

    def test_issue_routing_uses_checked_source_not_arbitrary_inventory_repo(self):
        client = self.fixture(diagnosis="runtime-failed")
        result = appliance_watch.check(apply=True, client=client, now=NOW)
        self.assertEqual(result["decisions"],
                         [{"name": "ocpp-csms", "state": "intrinsic-failure"}])
        self.issue.assert_called_once_with(
            "arthexis/ocpp-csms", "ocpp-csms", "runtime-failure", "diagnostic")
        self.dispatch.assert_not_called()
        self.reserve.assert_not_called()

    def test_reservation_authority_not_changed(self):
        with patch.object(appliance_watch, "load_catalog",
                          side_effect=AssertionError("catalog read")) as loader:
            with patch.object(appliance_watch.Path, "exists", return_value=False):
                self.assertEqual(
                    appliance_watch._dispatch_reservations("/tmp/not-real-path"), {})
            loader.assert_not_called()
