"""Only allowlisted diagnostics may appear in a deployment receipt."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock

path = Path(__file__).resolve().parents[2] / "scripts/mcp-deployment-receipt.py"
spec = importlib.util.spec_from_file_location("mcp_receipt_690", path)
receipt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receipt)


class ReceiptTests(unittest.TestCase):
    def test_journal_is_classified_without_returning_sensitive_text(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout=(
            'PermissionError: node is not currently attested at pinned address SECRET_TOKEN\n'), stderr=''))
        self.assertEqual(receipt.failure_class(runner=run), 'node_eligibility')
        self.assertNotIn('SECRET_TOKEN', receipt.failure_class(runner=run))
        self.assertIn('-n', run.call_args.args[0])

    def test_unit_properties_are_allowlisted_and_malformed_values_removed(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout=(
            'ActiveState=active\nSubState=running\nResult=success\nExecMainStatus=1\n'
            'NRestarts=6\nEnvironment=SECRET_TOKEN\n'), stderr=''))
        result = receipt.inspect_unit('gway-mcp-gateway.service', runner=run)
        self.assertEqual(result['NRestarts'], '6')
        self.assertNotIn('Environment', result)
        self.assertNotIn('SECRET_TOKEN', repr(result))
        run.return_value.stdout = 'ActiveState=private value\n'
        self.assertEqual(receipt.inspect_unit('x', runner=run)['ActiveState'], 'unknown')

    def test_service_unavailable_is_unknown(self):
        run = Mock(side_effect=subprocess.TimeoutExpired('systemctl', 5))
        self.assertEqual(receipt.inspect_unit('x', runner=run)['Result'], 'unknown')
        self.assertEqual(receipt.failure_class(runner=run), 'unknown')
