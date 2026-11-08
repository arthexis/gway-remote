"""Frozen pre-refactor argparse output and isolated read-only dispatch contracts."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from gway_remote.cli.operations import dispatch

GOLDEN = json.loads(Path(__file__).with_name('cli_operations_a1_golden.json').read_text())


class CliOperationsA1Tests(unittest.TestCase):
    def test_argparse_compatibility(self):
        for arguments, expected in GOLDEN.items():
            with self.subTest(arguments=arguments):
                result = subprocess.run([sys.executable, '-m', 'gway_remote', *arguments.split()],
                                        capture_output=True, check=False)
                self.assertEqual(result.returncode, expected['code'])
                self.assertEqual(hashlib.sha256(result.stdout).hexdigest(), expected['stdout_sha256'])
                self.assertEqual(hashlib.sha256(result.stderr).hexdigest(), expected['stderr_sha256'])

    def test_read_only_output_modes(self):
        cases = [('status', 'gway_remote.status', 'status', 'format_status'),
                 ('hardware', 'gway_remote.hardware_diagnostics', 'inspect', 'format_hardware'),
                 ('network', 'gway_remote.network_diagnostics', 'inspect', 'format_network')]
        for command, module, function, formatter in cases:
            with patch(module + '.' + function, return_value={'ok': True}), \
                 patch(module + '.' + formatter, return_value='human'):
                for json_mode in (False, True):
                    with self.subTest(command=command, json=json_mode):
                        out = StringIO()
                        with redirect_stdout(out):
                            self.assertTrue(dispatch(SimpleNamespace(command=command, json=json_mode), None))
                        expected = (json.dumps({'ok': True}, indent=2, sort_keys=True)
                                    if json_mode else 'human')
                        self.assertEqual(out.getvalue().strip(), expected)

    def test_non_operations_not_dispatched(self):
        self.assertFalse(dispatch(SimpleNamespace(command='deploy'), None))

    def test_diagnose_error_contract(self):
        err = StringIO()
        with patch('gway_remote.diagnostics.diagnose', side_effect=ValueError('bad target')):
            with redirect_stderr(err), self.assertRaises(SystemExit) as raised:
                dispatch(SimpleNamespace(command='diagnose', component=None, lines=30, json=False),
                         argparse.ArgumentParser(prog='gway-remote'))
        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(err.getvalue(), 'gway-remote: diagnosis unavailable: bad target\\n')

    def test_logs_empty_contract(self):
        err = StringIO()
        with patch('gway_remote.logs.read_log', return_value=None):
            with redirect_stderr(err), self.assertRaises(SystemExit) as raised:
                dispatch(SimpleNamespace(command='logs', component='ocpp-csms', lines=20),
                         argparse.ArgumentParser(prog='gway-remote'))
        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(err.getvalue(), 'gway-remote: no installation logs found\\n')
