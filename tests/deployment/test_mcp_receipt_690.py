"""Only allowlisted diagnostics may appear in a deployment receipt."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

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

    def test_private_correlated_receipts_have_distinct_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            info = directory.lstat()
            root_owned = SimpleNamespace(st_mode=info.st_mode, st_uid=0)
            with patch.object(Path, 'lstat', return_value=root_owned), \
                 patch.object(receipt, 'inspect_unit', return_value={'ActiveState': 'active'}), \
                 patch.object(receipt, 'failure_class', return_value='permission'):
                receipt.write_receipt(directory, 'a' * 32, 'before')
                receipt.write_receipt(directory, 'a' * 32, 'rollback', rollback='rollback_unhealthy')
            before = directory / ('a' * 32 + '-before.json')
            after = directory / ('a' * 32 + '-rollback.json')
            self.assertEqual(before.stat().st_mode & 0o777, 0o600)
            self.assertEqual(after.stat().st_mode & 0o777, 0o600)
            self.assertIn('rollback_unhealthy', after.read_text())
            self.assertIn('permission', after.read_text())
