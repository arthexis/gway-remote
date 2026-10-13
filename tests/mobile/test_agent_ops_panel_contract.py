"""Regression guards for the grouped Agent Ops UI and restricted transport."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/arthexis/gwayremote"


class AgentOpsPanelContractTests(unittest.TestCase):
    def test_one_operation_panel_for_both_reads(self):
        registry = (ANDROID / "OperationRegistry.kt").read_text()
        palette = (ANDROID / "OperationPalette.kt").read_text()
        self.assertIn('OperationSpec("agent-ops"', registry)
        for obsolete_id in ('OperationSpec("agent-issues"', 'OperationSpec("agent-status"'):
            self.assertNotIn(obsolete_id, registry)
        self.assertIn('AgentOpsPanel(panel.output, agentSendLoading, agentSendResult, agentSendError, onAgentSend)', palette)
        self.assertIn('AgentBudgetWindow("5-hour", budget?.optJSONObject("five_hour"))', palette)
        self.assertIn('AgentBudgetWindow("Weekly", budget?.optJSONObject("weekly"))', palette)
        self.assertIn('issues.optJSONObject("data")?.optJSONArray("issues")', palette)
        self.assertIn('status")?.optJSONObject("data")', palette)
        self.assertIn('issue.optInt("comments", 0)', palette)
        self.assertIn('"Sent $age"', palette)

    def test_both_cli_reads_have_isolated_failures(self):
        activity = (ANDROID / "MainActivity.kt").read_text()
        for marker in ('listOf("agent-issues", "agent-status")',
                       'merged.put(key + "_error"', 'if (id == "agent-ops")'):
            with self.subTest(marker=marker):
                self.assertIn(marker, activity)
        self.assertNotIn('agent issue', activity)


if __name__ == "__main__":
    unittest.main()
