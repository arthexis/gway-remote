"""Offline P2 checks for generator, privileges, reporting and immutability."""
from dataclasses import replace
import contextlib
import io
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch

from gway_remote.appliance_workflow_generator import (
    DEFAULT_WORKFLOW, MARKERS, TEMPLATE_DIR, TEMPLATES, TRACKS,
    check_workflow, main, render_workflow,
)
from gway_remote.catalog_shadow import load_catalog, parse_catalog
from gway_remote.deploy_dispatch import TARGETS as DISPATCH_TARGETS
from gway_remote.deploy_failure_issues import REPOSITORIES
from gway_remote.target_export import export_targets

EXPECTED = ("ocpp-csms", "gway-lcd-sound", "gway-agent-ops",
            "gway-ap-kiosk", "gway-rfid", "gway-bastion")
GOLDEN_REVISION = "f602ee0234e4232246c67aa8cd02bd52fc4bff8b"


class ApplianceGeneratorP2Tests(unittest.TestCase):
    def setUp(self):
        self.actual = DEFAULT_WORKFLOW.read_bytes()

    @staticmethod
    def copy_templates(dest):
        for filename in TEMPLATES.values():
            shutil.copyfile(TEMPLATE_DIR / filename, dest / filename)

    def test_byte_exact_render_and_reviewed_dispatch_subset(self):
        self.assertEqual(render_workflow().encode(), self.actual)
        self.assertEqual(render_workflow(), render_workflow())
        self.assertTrue(check_workflow())
        self.assertEqual(tuple(x for track in TRACKS for x in track), EXPECTED)
        self.assertEqual(DISPATCH_TARGETS, ("all", *EXPECTED))
        self.assertEqual(REPOSITORIES, {name.replace("-", "_"): name for name in EXPECTED})

    def test_cli_check_and_render_never_write_or_execute(self):
        out = io.StringIO()
        with patch("pathlib.Path.write_text", side_effect=AssertionError("write")), \
             patch("pathlib.Path.write_bytes", side_effect=AssertionError("write")), \
             patch("subprocess.run", side_effect=AssertionError("run")), \
             contextlib.redirect_stdout(out):
            self.assertEqual(main(["--check"]), 0)
        self.assertIn("byte-for-byte", out.getvalue())
        out = io.StringIO()
        with patch("pathlib.Path.write_text", side_effect=AssertionError("write")), \
             patch("pathlib.Path.write_bytes", side_effect=AssertionError("write")), \
             contextlib.redirect_stdout(out):
            self.assertEqual(main(["--render"]), 0)
        self.assertEqual(out.getvalue().encode(), self.actual)

    def test_one_byte_drift_fails_without_repair(self):
        with tempfile.TemporaryDirectory() as d:
            artifact = Path(d) / "appliance-deploy.yml"
            artifact.write_bytes(self.actual.replace(b"retention-days: 14", b"retention-days: 15", 1))
            before = artifact.read_bytes()
            self.assertFalse(check_workflow(artifact))
            with patch("gway_remote.appliance_workflow_generator.DEFAULT_WORKFLOW", artifact), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--check"]), 1)
            self.assertEqual(artifact.read_bytes(), before)

    def test_template_slots_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.copy_templates(root)
            skeleton = root / TEMPLATES["skeleton"]
            before = skeleton.read_text()
            for mutated in (
                before.replace("@@REPORT_MAP@@", "", 1),
                before.replace("@@CHOICES@@", "@@CHOICES@@\n@@CHOICES@@", 1),
                before.replace("@@DEPLOY_JOBS@@", "", 1),
            ):
                skeleton.write_text(mutated)
                with self.assertRaisesRegex(ValueError, "slot"):
                    render_workflow(template_dir=root)
            skeleton.write_text(before)
            linked = root / TEMPLATES["linked"]
            linked.write_text(linked.read_text().replace("@@PREV@@", "admission"))
            with self.assertRaisesRegex(ValueError, "dependency slot"):
                render_workflow(template_dir=root)

    def test_mutated_trusted_templates_cause_drift(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.copy_templates(root)
            skeleton = root / TEMPLATES["skeleton"]
            old = skeleton.read_text()
            for before, after in (
                ("  issues: write\n", "  issues: write\n  actions: write\n"),
                ("  group: gway-001-appliance\n", "  group: elsewhere\n"),
                ("  cancel-in-progress: false\n", "  cancel-in-progress: true\n"),
                ("retention-days: 14", "retention-days: 30"),
                ("gway-001-deploy-report-", "unreviewed-public-report-"),
            ):
                self.assertIn(before, old)
                skeleton.write_text(old.replace(before, after, 1))
                self.assertFalse(check_workflow(template_dir=root))
            skeleton.write_text(old)
            linked = root / TEMPLATES["linked"]
            linked.write_text(linked.read_text().replace(
                "github.actor == 'arthexis'", "true || github.actor == 'arthexis'", 1))
            self.assertFalse(check_workflow(template_dir=root))

    def test_seven_known_six_admitted_no_reports_or_simulator(self):
        rows = load_catalog().targets
        self.assertEqual(len(rows), 7)
        self.assertIn("ocpp-reports", tuple(row.id for row in rows))
        text = render_workflow()
        area = text.split("      repository:\n", 1)[1].split("\npermissions:\n", 1)[0]
        choices = re.findall(r"(?m)^          - ([a-z0-9-]+)$", area)
        self.assertEqual(choices, ["all", *EXPECTED])
        self.assertNotIn("  ocpp_reports:\n", text)
        self.assertNotIn("  ocpp_simulator:\n", text)
        for name in EXPECTED:
            self.assertEqual(text.count("deploy-batch --all --target " + name), 1)

    def test_dag_guard_and_stage_only_are_preserved(self):
        text = render_workflow()
        guard = ("github.event_name == 'workflow_dispatch' && "
                 "github.actor == 'arthexis' && "
                 "needs.admission.result == 'success' && "
                 "inputs.node == 'gway-001'")
        self.assertEqual(text.count(guard), 7)
        self.assertEqual(text.count("github.event_name == 'workflow_dispatch'"), 7)
        for previous, current in (
            ("gway_lcd_sound", "gway_agent_ops"),
            ("gway_agent_ops", "gway_ap_kiosk"),
            ("gway_ap_kiosk", "gway_rfid"),
            ("gway_rfid", "gway_bastion"),
        ):
            self.assertIn("    needs: [admission, " + previous + "]", text.split("  " + current + ":\n", 1)[1].split("\n  ", 1)[0])
        self.assertIn("    needs: [admission, ocpp_csms, gway_lcd_sound, gway_agent_ops, gway_ap_kiosk, gway_rfid, gway_bastion]", text)
        self.assertIn("Deploy gway-bastion (stage-only)", text)
        self.assertIn("Bastion staged only; running services and keys unchanged", text)
        self.assertNotIn("continue-on-error: true", text)

    def test_runner_secret_permissions_report_and_retention(self):
        text = render_workflow()
        self.assertIn("permissions:\n  contents: read\n  issues: write\n", text)
        self.assertIn("concurrency:\n  group: gway-001-appliance\n  cancel-in-progress: false\n", text)
        self.assertIn("if os.environ['REQUEST_ACTOR'] != 'arthexis':", text)
        self.assertIn("if node != 'gway-001':", text)
        self.assertIn("require_local_deployment(", text)
        self.assertIn("inventory='ansible/inventory/deployment.yml'", text)
        self.assertEqual(text.count("runs-on: [self-hosted, Linux, ARM64, gway-001]"), 7)
        self.assertEqual(text.count("timeout-minutes: 30"), 6)
        self.assertIn("timeout-minutes: 10", text)
        self.assertEqual(text.count("GH_TOKEN: ${{ secrets.GWAY_REMOTE_DISPATCH_TOKEN }}"), 6)
        self.assertIn("JOB_RESULTS: ${{ toJSON(needs) }}", text)
        self.assertIn("retention-days: 14", text)
        self.assertIn("if-no-files-found: error", text)
        self.assertIn("Open or refresh deployment failure issues", text)
        self.assertNotIn("  schedule:\n", text)
        self.assertNotIn("  push:\n", text)

    def test_catalog_drift_and_duplicate_properties_fail(self):
        c = load_catalog()
        rows = c.targets
        for bad in (
            replace(c, targets=(rows[1], rows[0], *rows[2:])),
            replace(c, targets=(replace(rows[0], adapter_id="deploy_bastion"), *rows[1:])),
            replace(c, targets=(*rows[:-1], replace(rows[-1], release_mode="standard"))),
        ):
            with self.assertRaises(ValueError):
                render_workflow(catalog=bad)
        raw = (TEMPLATE_DIR / "appliance-targets.v1.json").read_text()
        with self.assertRaises(ValueError):
            parse_catalog(raw.replace('"id": "ocpp-csms",',
                                      '"id": "ocpp-csms", "id": "ocpp-csms",', 1))
        with self.assertRaises(ValueError):
            parse_catalog(raw.replace("gway-remote/appliance-catalog/v1",
                                      "other-schema/v1", 1))

    def test_public_target_export_schema_one_and_revision_unchanged(self):
        before = export_targets()
        self.assertEqual(before["schema"], 1)
        self.assertEqual(before["revision"], GOLDEN_REVISION)
        self.assertEqual(len(before["targets"]), 7)
        self.assertEqual(render_workflow().encode(), self.actual)
        self.assertEqual(export_targets(), before)


if __name__ == "__main__":
    unittest.main()
