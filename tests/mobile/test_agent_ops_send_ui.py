"""Agent Ops Send UI regression guards."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
MOBILE = ROOT / "android/app/src/main/java/com/arthexis/gwayremote"


class AgentOpsSendUiTests(unittest.TestCase):
    def test_send_requires_explicit_user_press_and_timestamp_reuse(self):
        palette = (MOBILE / "OperationPalette.kt").read_text()
        self.assertIn('Text("Send to Agent?")', palette)
        self.assertIn('Button(enabled = validUrl && !sending, onClick = { confirmRef = issueRef })', palette)
        self.assertIn('confirmButton = { TextButton(onClick = {', palette)
        self.assertIn('attemptedAt = at', palette)
        self.assertIn('prefs.edit().putString("ref", ref).putString("at", at).apply()', palette)
        self.assertIn('onSend(ref, at)', palette)
        self.assertNotIn('OutlinedTextField(selectedRef', palette)
        self.assertIn('onSend(attempted.first, attempted.second)', palette)
        self.assertIn('onObserve(attempted.first, attempted.second)', palette)
        self.assertIn('Text("Retry same submission")', palette)
        self.assertIn('ChronoUnit.SECONDS', palette)

    def test_api_call_only_in_send_callback_not_refresh(self):
        activity = (MOBILE / "MainActivity.kt").read_text()
        self.assertIn('onAgentSend = { ref, at ->', activity)
        self.assertIn('"/api/v1/execute", "agent-issue", args', activity)
        self.assertIn('JSONObject().put("ref", ref).put("at", at)', activity)
        read = activity[activity.index('fun runPanelRead('):activity.index('fun runPanelRead(') + 2300]
        self.assertNotIn('"agent-issue"', read)


if __name__ == "__main__":
    unittest.main()
