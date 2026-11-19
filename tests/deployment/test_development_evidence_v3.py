"""Hermetic V3 receipt acceptance tests: no network or node access."""
import copy
import unittest

from gway_remote.development_evidence_v3 import operational_acceptance_v3

SHA = "a" * 40
PREVIOUS = "b" * 40
NOW = "2026-11-18T23:00:00Z"


def fixture():
    return {
        "revision": SHA,
        "workflow": {
            "event": "push", "head_sha": SHA, "status": "completed",
            "conclusion": "success",
            "jobs": [{"name": name, "status": "completed", "conclusion": "success"}
                     for name in ("Classify push impact (hosted, read-only)",
                                  "deploy", "Deploy Watchtower MCP")],
        },
        "nodes": {
            "gway-001": {
                "active_revision": SHA, "previous_revision": PREVIOUS,
                "observed_at": NOW,
                "status": {"schema": "gway-remote/status/v1",
                           "node": "gway-001", "depth": "deep",
                           "components": [{"name": "ocpp-csms", "health": "healthy"}]},
            },
            "Watchtower": {
                "active_revision": SHA, "previous_revision": PREVIOUS,
                "observed_at": NOW,
                "services": {
                    "gway-mcp-gateway.service": "active",
                    "gway-mcp-link.service": "active",
                    "gway-remote-watchtower-enroll.service": "active",
                },
            },
        },
        "observed_at": NOW, "now": NOW,
    }


class V3Tests(unittest.TestCase):
    def test_complete_receipts_are_operationally_accepted_without_auth(self):
        result = operational_acceptance_v3(**fixture())
        self.assertEqual(result["state"], "accepted")
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["deployment_authorization"], "not_applicable")
        self.assertEqual(result["source_authentication"], "existing_reader_only")

    def test_absent_or_duplicate_jobs_never_accept(self):
        for mutate in (
            lambda x: x["workflow"]["jobs"].pop(),
            lambda x: x["workflow"]["jobs"].append(copy.deepcopy(x["workflow"]["jobs"][0])),
            lambda x: x["workflow"]["jobs"][0].update(conclusion="failure"),
            lambda x: x["workflow"].update(conclusion="failure"),
            lambda x: x["workflow"].update(head_sha=PREVIOUS),
            lambda x: x["workflow"].update(event="workflow_dispatch"),
        ):
            data = fixture()
            mutate(data)
            result = operational_acceptance_v3(**data)
            self.assertEqual(result["state"], "unknown")
            self.assertTrue(result["reasons"])

    def test_release_staged_or_missing_rollback_unknown(self):
        for node in ("gway-001", "Watchtower"):
            data = fixture()
            data["nodes"][node]["active_revision"] = PREVIOUS
            self.assertEqual(operational_acceptance_v3(**data)["state"], "unknown")
            data = fixture()
            data["nodes"][node]["previous_revision"] = None
            self.assertEqual(operational_acceptance_v3(**data)["state"], "unknown")

    def test_health_and_services_do_not_infer_activation(self):
        data = fixture()
        data["nodes"]["gway-001"]["status"]["depth"] = "quick"
        self.assertIn("gway-001_health_unverified",
                      operational_acceptance_v3(**data)["reasons"])
        data = fixture()
        data["nodes"]["Watchtower"]["services"]["gway-mcp-link.service"] = "inactive"
        self.assertIn("watchtower_services_unverified",
                      operational_acceptance_v3(**data)["reasons"])

    def test_stale_future_and_invalid_ttl_fail_closed(self):
        data = fixture()
        data["nodes"]["Watchtower"]["observed_at"] = "2026-11-18T22:50:00Z"
        self.assertEqual(operational_acceptance_v3(**data)["state"], "unknown")
        data["nodes"]["Watchtower"]["observed_at"] = "2026-11-18T23:00:01Z"
        self.assertEqual(operational_acceptance_v3(**data)["state"], "unknown")
        for value in (True, 0, 604801):
            with self.assertRaises(ValueError):
                operational_acceptance_v3(**fixture(), ttl_seconds=value)

    def test_node_identity_is_closed_not_remote_enrollment(self):
        data = fixture()
        data["nodes"]["gway-002"] = data["nodes"].pop("gway-001")
        with self.assertRaises(ValueError):
            operational_acceptance_v3(**data)

    def test_private_fields_are_not_reflected(self):
        data = fixture()
        data["workflow"]["token"] = "private"
        data["nodes"]["gway-001"]["private"] = "another-secret"
        report = operational_acceptance_v3(**data)
        self.assertNotIn("private", repr(report))
        self.assertNotIn("another-secret", repr(report))


if __name__ == "__main__":
    unittest.main()
