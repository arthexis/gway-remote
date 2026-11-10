"""Guard the aggregate CI check against accidentally omitting validation jobs.

GitHub marks the aggregate `CI` job successful when its own `needs` jobs
succeed. A separately green or red job that is absent from `needs` is NOT
part of this gate. Keep the actual workflow and the embedded check under test.
Only standard-library parsing and a disposable Python subprocess are used.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/ci.yml"
JOBS = re.compile(r"(?m)^  ([a-z][a-z0-9-]*):[ \t]*$")


def _check_job_dependencies(workflow):
    if not workflow.startswith("name: Python checks\n"):
        raise ValueError("unexpected CI workflow")
    if workflow.count("\n  ci:\n") != 1:
        raise ValueError("one aggregate CI job required")
    if workflow.count("\njobs:\n") != 1:
        raise ValueError("one jobs block required")
    text = workflow.split("\njobs:\n", 1)[1]
    names = JOBS.findall(text)
    if len(names) != len(set(names)) or "ci" not in names:
        raise ValueError("duplicate/missing CI jobs")
    ci = text.split("\n  ci:\n", 1)[1]
    match = re.search(r"(?m)^    needs: \[([^\]\n]+)\][ \t]*$", ci)
    if match is None:
        raise ValueError("missing inline CI needs")
    needs = [name.strip() for name in match.group(1).split(",")]
    required = set(names) - {"ci"}
    if (len(needs) != len(set(needs)) or not all(needs)
            or set(needs) != required):
        raise ValueError("aggregate CI gate does not depend on every validation job")
    if "    if: always()" not in ci:
        raise ValueError("aggregate CI must evaluate failed/skipped needs")
    return needs, ci


def _gate_script(ci):
    match = re.search(r"(?ms)^          python3 - <<'PY'\n(.*?)^          PY[ \t]*$", ci)
    if match is None:
        raise ValueError("missing aggregate CI guard script")
    return textwrap.dedent(match.group(1))


class RequiredCIGateTests(unittest.TestCase):
    def test_all_defined_validation_jobs_are_required(self):
        needs, _ = _check_job_dependencies(WORKFLOW.read_text())
        self.assertIn("mcp-provider-lifecycle-ansible", needs)
        self.assertGreaterEqual(len(needs), 6)

    def test_omitted_new_job_or_duplicate_needs_fails_closed(self):
        workflow = WORKFLOW.read_text()
        needs, _ = _check_job_dependencies(workflow)
        self.assertIn("mcp-provider-lifecycle-ansible", needs)
        missing = workflow.replace(
            "unit, mcp-provider-lifecycle-ansible, ",
            "unit, ",
            1,
        )
        self.assertNotEqual(missing, workflow)
        with self.assertRaisesRegex(ValueError, "every validation job"):
            _check_job_dependencies(missing)
        extended = workflow.replace(
            "\n  ci:\n", "\n  new-security-check:\n    runs-on: ubuntu-latest\n\n  ci:\n", 1,
        )
        with self.assertRaisesRegex(ValueError, "every validation job"):
            _check_job_dependencies(extended)

    def test_actual_gate_rejects_failed_cancelled_skipped_and_missing_results(self):
        needs, ci = _check_job_dependencies(WORKFLOW.read_text())
        script = _gate_script(ci)
        def run(states):
            env = dict(os.environ)
            env["NEEDS_JSON"] = json.dumps({name: {"result": state}
                                            for name, state in states.items()})
            return subprocess.run(
                [sys.executable, "-c", script], env=env,
                capture_output=True, text=True, timeout=8, check=False,
            )
        all_success = {name: "success" for name in needs}
        self.assertEqual(run(all_success).returncode, 0)
        for status in ("failure", "cancelled", "skipped", None):
            with self.subTest(status=status):
                changed = dict(all_success)
                changed["mcp-provider-lifecycle-ansible"] = status
                result = run(changed)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("mcp-provider-lifecycle-ansible", result.stdout)


if __name__ == "__main__":
    unittest.main()
