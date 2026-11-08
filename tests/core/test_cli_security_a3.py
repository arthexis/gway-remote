"""A3 frozen argparse contracts and mocked security rejection paths."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from gway_remote.cli.security import dispatch

GOLDEN = json.loads(Path(__file__).with_name('cli_security_a3_golden.json').read_text())


class CliSecurityA3Tests(unittest.TestCase):
    def test_pre_refactor_cli_contracts(self):
        for arguments, expected in GOLDEN.items():
            with self.subTest(arguments=arguments):
                proc = subprocess.run([sys.executable, '-m', 'gway_remote', *arguments.split()],
                                      capture_output=True, check=False)
                self.assertEqual(proc.returncode, expected['code'])
                self.assertEqual(hashlib.sha256(proc.stdout).hexdigest(), expected['stdout_sha256'])
                self.assertEqual(hashlib.sha256(proc.stderr).hexdigest(), expected['stderr_sha256'])

    def test_unrelated_command_not_dispatched(self):
        self.assertFalse(dispatch(SimpleNamespace(command='status'), None))

    def test_exec_denial_does_not_leak_details(self):
        args = SimpleNamespace(command='exec', exec_action='grant', node='gway-001')
        with patch('gway_remote.watchtower_exec_eligibility.run_action',
                   side_effect=PermissionError('private information')):
            error = StringIO()
            with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                dispatch(args, argparse.ArgumentParser())
            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(error.getvalue(),
                             'gway-remote: execution eligibility unavailable: PermissionError\\n')

    def test_bearer_issue_requires_tty_before_registry(self):
        args = SimpleNamespace(command='bearer', bearer_action='issue')
        with patch('sys.stdin.isatty', return_value=False), \
             patch('gway_remote.mcp_bearer_cli.assume_auth_identity') as auth:
            error = StringIO()
            with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                dispatch(args, argparse.ArgumentParser())
            self.assertEqual(raised.exception.code, 1)
            auth.assert_not_called()
            self.assertIn('requires an interactive console', error.getvalue())

    def test_watchtower_nonroot_denied_before_ledger(self):
        args = SimpleNamespace(command='watchtower', read_only_stage=False, action='status')
        with patch('os.geteuid', return_value=1000), \
             patch('gway_remote.watchtower_enrollment.Ledger') as ledger:
            error = StringIO()
            with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                dispatch(args, argparse.ArgumentParser())
            self.assertEqual(raised.exception.code, 1)
            ledger.assert_not_called()
            self.assertIn('requires root or sudo', error.getvalue())

    def test_host_pin_denied_without_inventory_approval(self):
        args = SimpleNamespace(command='inspection-host-pin', node='gway-001')
        proc = SimpleNamespace(stdout='{"remote_inspection_allowed": false}')
        with patch('subprocess.run', return_value=proc), \
             patch('gway_remote.host_trust.pin_from_watchtower') as pin:
            error = StringIO()
            with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                dispatch(args, argparse.ArgumentParser())
            self.assertEqual(raised.exception.code, 1)
            pin.assert_not_called()
            self.assertIn('host pin denied: ValueError', error.getvalue())
