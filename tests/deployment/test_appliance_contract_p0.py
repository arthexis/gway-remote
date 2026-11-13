"""Offline structural parity for the existing static Appliance Deploy workflow.

Parse the fixed indentation/sections we own; do not evaluate workflow expressions,
execute scripts, access GitHub, or require extra packages. A schema/layout change
fails closed until this parser and its negative fixtures are reviewed.
"""
import ast
from pathlib import Path
import re
import unittest

from gway_remote.best_effort import INSTALLERS
from gway_remote.deploy_dispatch import TARGETS as DISPATCH_TARGETS
from gway_remote.deploy_failure_issues import REPOSITORIES
from gway_remote.deployment_policy import INVENTORY
from gway_remote.reconcile import TARGETS as KNOWN_TARGETS

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/appliance-deploy.yml"
INVENTORY_SOURCE = ROOT / "ansible/inventory/deployment.yml"
JOB_RE = re.compile(r"(?m)^  ([a-z][a-z0-9_]*):\s*$")
NEEDS_RE = re.compile(r"(?m)^    needs: (.+)$")
CHOICE_RE = re.compile(r"(?m)^          - ([a-z0-9][a-z0-9-]*)$")
EXPECTED_GATE = (
    "github.event_name == 'workflow_dispatch'",
    "github.actor == 'arthexis'",
    "needs.admission.result == 'success'",
    "inputs.node == 'gway-001'",
)


def workflow_contract(source):
    """Return the closed set of choices, jobs, edges and summary mapping."""
    head, separator, tail = source.partition("\njobs:\n")
    if not separator or tail.count("\njobs:\n"):
        raise ValueError("missing or ambiguous jobs section")
    option_area = head.partition("      repository:\n")[2].partition("\npermissions:")[0]
    if not option_area or "        options:\n" not in option_area:
        raise ValueError("missing repository choice options")
    options = CHOICE_RE.findall(option_area)
    if len(options) != len(set(options)):
        raise ValueError("duplicate workflow repository option")
    matches = list(JOB_RE.finditer(tail))
    if not matches:
        raise ValueError("no workflow jobs")
    names = [match.group(1) for match in matches]
    if len(names) != len(set(names)):
        raise ValueError("duplicate workflow job")
    blocks = {
        name: tail[match.end():matches[index + 1].start()
                   if index + 1 < len(matches) else len(tail)]
        for index, (name, match) in enumerate(zip(names, matches))
    }
    edges = {}
    for name, block in blocks.items():
        dependencies = NEEDS_RE.findall(block)
        if name == "admission":
            if dependencies:
                raise ValueError("admission must be a root job")
            edges[name] = ()
            continue
        if len(dependencies) != 1:
            raise ValueError(f"{name}: expected exactly one needs declaration")
        raw = dependencies[0].strip()
        if raw.startswith("[") and raw.endswith("]"):
            needs = tuple(x.strip() for x in raw[1:-1].split(","))
        else:
            needs = (raw,)
        if not needs or any(x not in blocks or x == name for x in needs):
            raise ValueError(f"{name}: missing, unknown or self dependency")
        if len(needs) != len(set(needs)):
            raise ValueError(f"{name}: duplicate dependency")
        edges[name] = needs

    def visit(name, stack, visited):
        if name in stack:
            raise ValueError("cyclic workflow dependency")
        if name in visited:
            return
        stack.add(name)
        for predecessor in edges.get(name, ()):
            visit(predecessor, stack, visited)
        stack.remove(name)
        visited.add(name)

    visited = set()
    for name in blocks:
        visit(name, set(), visited)

    match = re.search(r"(?ms)^          jobs = (\{\n.*?^          \})", blocks["report"])
    if not match:
        raise ValueError("report job mapping unavailable")
    mapping = ast.literal_eval(match.group(1))
    if type(mapping) is not dict or any(type(k) is not str or type(v) is not str
                                        for k, v in mapping.items()):
        raise ValueError("invalid report job map")
    return options, blocks, edges, mapping, head


class ApplianceContractP0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text(encoding="utf-8")

    def test_exact_choices_jobs_summary_and_failure_map(self):
        options, blocks, edges, mapping, head = workflow_contract(self.source)
        deployable = DISPATCH_TARGETS[1:]
        expected = {name.replace("-", "_"): name for name in deployable}
        self.assertEqual(options, ["all", *deployable])
        self.assertEqual(set(blocks), {"admission", "report", *expected})
        self.assertEqual(mapping, expected)
        self.assertEqual(REPOSITORIES, expected)
        self.assertEqual(set(edges["report"]), {"admission", *expected})
        self.assertEqual(edges["report"][0], "admission")
        self.assertEqual(set(deployable), set(INSTALLERS) &
                         set(name for name, _ in KNOWN_TARGETS) -
                         ({"ocpp-reports"} if "ocpp-reports" not in deployable else set()))
        self.assertNotIn("ocpp-simulator", mapping.values())

    def test_two_tracks_are_serialized_without_cross_track_edges(self):
        _, blocks, edges, _, _ = workflow_contract(self.source)
        csms = ["ocpp_csms"] + (["ocpp_reports"] if "ocpp_reports" in blocks else [])
        gateway = ["gway_lcd_sound", "gway_agent_ops", "gway_ap_kiosk",
                   "gway_rfid", "gway_bastion"]
        for track in (csms, gateway):
            for index, name in enumerate(track):
                expected = ("admission",) if index == 0 else ("admission", track[index - 1])
                self.assertEqual(edges[name], expected)
        self.assertEqual(edges["admission"] if "admission" in edges else (), ())
        self.assertIn("stage-only", blocks["gway_bastion"])
        self.assertIn("always()", blocks["report"])
        for name in blocks:
            if name in ("admission", "report"):
                continue
            self.assertEqual(blocks[name].count("deploy-batch --all --target "), 1)
            target = name.replace("_", "-")
            self.assertIn("deploy-batch --all --target " + target, blocks[name])
            if len(edges[name]) > 1:
                self.assertIn("always()", blocks[name])

    def test_admission_runner_workflow_permissions_unchanged(self):
        _, blocks, _, _, head = workflow_contract(self.source)
        self.assertIn("workflow_dispatch:", head)
        self.assertNotIn("schedule:", head)
        self.assertIn("permissions:\n  contents: read\n  issues: write\n", head)
        self.assertIn("concurrency:\n  group: gway-001-appliance\n  cancel-in-progress: false\n", head)
        admission = blocks["admission"]
        self.assertIn("REQUEST_ACTOR", admission)
        self.assertIn("require_local_deployment(", admission)
        self.assertIn("inventory='ansible/inventory/deployment.yml'", admission)
        self.assertIn("node != 'gway-001'", admission)
        for name, block in blocks.items():
            if name == "admission":
                self.assertIn("runs-on: ubuntu-latest", block)
                continue
            self.assertIn("runs-on: [self-hosted, Linux, ARM64, gway-001]", block)
            self.assertTrue(all(clause in block for clause in EXPECTED_GATE), name)
            self.assertIn("persist-credentials: false", block)
        self.assertIn("JOB_RESULTS: ${{ toJSON(needs) }}", blocks["report"])
        self.assertIn('outcome = results[job]["result"]', blocks["report"])
        self.assertIn("report-bundle", blocks["report"])
        self.assertIn("gway_remote.deploy_failure_issues", blocks["report"])
        publisher = blocks["report"].split(
            "      - name: Open or refresh deployment failure issues", 1
        )[1].split("      - name: Upload report", 1)[0]
        self.assertNotIn("continue-on-error: true", publisher)

    def test_inventory_is_independent_and_other_hosts_deny_all(self):
        inventory = INVENTORY_SOURCE.read_text(encoding="utf-8")
        gway = inventory.split("        gway-001:\n", 1)[1].split("\n    quality:", 1)[0]
        section = gway.split("          remote_managed_repositories:\n", 1)[1]
        approved = re.findall(r"(?m)^            - ([a-z0-9-]+)$", section)
        dispatchable = set(DISPATCH_TARGETS[1:])
        self.assertTrue(dispatchable <= set(approved))
        self.assertIn("odoo-gelectriic", approved)
        self.assertNotIn("odoo-gelectriic", dispatchable)
        self.assertNotIn("ocpp-simulator", approved)
        remainder = inventory.split("\n    quality:", 1)[1]
        self.assertEqual(remainder.count("remote_managed_repositories: []"), 4)
        self.assertEqual(str(INVENTORY), "/etc/gway-remote/deployment.yml")

    def test_mutated_or_drifting_contract_is_detected(self):
        replacements = (
            ("          - ocpp-csms\n", "          - ocpp-simulator\n"),
            ("  gway_rfid:\n", "  gway_rfid:\n  gway_rfid:\n"),
            ("    needs: [admission, gway_ap_kiosk]",
             "    needs: [admission, gway_rfid]"),
            ("    needs: [admission, gway_agent_ops]",
             "    needs: [admission, no_such_job]"),
        )
        for before, after in replacements:
            with self.subTest(change=after):
                self.assertIn(before, self.source)
                mutated = self.source.replace(before, after, 1)
                try:
                    options, blocks, edges, mapping, _ = workflow_contract(mutated)
                except ValueError:
                    continue
                expected = DISPATCH_TARGETS[1:]
                self.assertFalse(
                    options == ["all", *expected]
                    and len(blocks) == len(expected) + 2
                    and edges["report"] == ("admission", *(n.replace("-", "_") for n in expected))
                    and mapping == REPOSITORIES,
                    "Mutated workflow unexpectedly preserves all parity invariants",
                )


if __name__ == "__main__":
    unittest.main()
