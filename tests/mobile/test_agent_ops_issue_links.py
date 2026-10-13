"""Regression guards for direct Assigned Issues actions and preview."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/arthexis/gwayremote"


class AssignedIssuesTests(unittest.TestCase):
    def test_direct_send_confirmation_persists_retry_identity(self):
        source = (ANDROID / "OperationPalette.kt").read_text()
        for marker in ('Text("Send to Agent?")', 'onSend(ref, at)',
                       'prefs.edit().putString("ref", ref).putString("at", at).apply()',
                       'onSend(attempted.first, attempted.second)'):
            self.assertIn(marker, source)
        self.assertNotIn('Text("Select for Send")', source)
        self.assertNotIn('OutlinedTextField(selectedRef', source)

    def test_link_and_copy_are_read_only(self):
        source = (ANDROID / "OperationPalette.kt").read_text()
        for marker in ('issueUrl == expectedUrl',
                       'Intent(Intent.ACTION_VIEW, Uri.parse(issueUrl))',
                       'ClipData.newPlainText("GitHub issue", issueUrl)',
                       'onCopyPrompt(issueRef)'):
            self.assertIn(marker, source)

    def test_preview_is_explicit_and_read_only(self):
        activity = (ANDROID / "MainActivity.kt").read_text()
        adapter = (ROOT / "gway_remote/agent_ops_adapter.py").read_text()
        mobile = (ROOT / "gway_remote/mobile.py").read_text()
        self.assertIn('"agent-preview"', activity)
        self.assertIn('optString("prompt", "")', activity)
        self.assertIn('return _run(["preview", ref])', adapter)
        self.assertIn('"agent-preview", "read_only": True', mobile)


if __name__ == "__main__":
    unittest.main()
