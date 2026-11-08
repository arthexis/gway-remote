"""Frozen A4 CLI stdout, stderr, exit and local dispatch contracts."""
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

from gway_remote.cli.local import dispatch

GOLDEN = json.loads(Path(__file__).with_name('cli_local_a4_golden.json').read_text())


class CliLocalA4Tests(unittest.TestCase):
    def test_pre_refactor_cli_contracts(self):
        for arguments, expected in GOLDEN.items():
            with self.subTest(arguments=arguments):
                proc = subprocess.run([sys.executable, '-m', 'gway_remote', *arguments.split()],
                                      capture_output=True, check=False)
                self.assertEqual(proc.returncode, expected['code'])
                self.assertEqual(hashlib.sha256(proc.stdout).hexdigest(), expected['stdout_sha256'])
                self.assertEqual(hashlib.sha256(proc.stderr).hexdigest(), expected['stderr_sha256'])

    def test_unhandled_run_error_type_preserved(self):
        proc = subprocess.run([sys.executable, '-m', 'gway_remote', 'run', 'system-health',
                               '--sha', 'abc'], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('RuntimeError:', proc.stderr)

    def test_unrelated_command_not_dispatched(self):
        self.assertFalse(dispatch(SimpleNamespace(command='status'), None, run_task=None))

    def test_run_delegates_to_original_executor(self):
        args = SimpleNamespace(command='run', task='system-health', repository='', sha='')
        with patch('gway_remote.deployment_policy.require_local_deployment') as policy:
            task = unittest.mock.Mock()
            self.assertTrue(dispatch(args, argparse.ArgumentParser(), run_task=task))
            policy.assert_called_once_with('')
            task.assert_called_once_with('system-health', '', '')

    def test_api_error_preserves_exit_and_stderr(self):
        args = SimpleNamespace(command='api', host='127.0.0.1', port=8765)
        with patch('gway_remote.api.serve', side_effect=OSError('offline')):
            err = StringIO()
            with redirect_stderr(err), self.assertRaises(SystemExit) as raised:
                dispatch(args, argparse.ArgumentParser(), run_task=None)
            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(err.getvalue(), 'gway-remote: API unavailable: OSError\\n'.replace('OSError', 'offline'))

    def test_watchdog_show_rejects_mutation_flags(self):
        args = SimpleNamespace(command='watchdog', action='show', apply=True, seconds=None)
        with patch('gway_remote.watchdog.inspect') as inspect:
            with self.assertRaises(SystemExit) as raised:
                dispatch(args, argparse.ArgumentParser(), run_task=None)
            self.assertEqual(raised.exception.code, 2)
            inspect.assert_not_called()

    def test_watch_without_apply_remains_read_only(self):
        args = SimpleNamespace(command='watch', apply=False)
        with patch('gway_remote.appliance_watch.check', return_value={'ok': True}) as check:
            with redirect_stdout(StringIO()):
                self.assertTrue(dispatch(args, argparse.ArgumentParser(), run_task=None))
            check.assert_called_once_with(apply=False)

    def test_codex_submit_missing_metadata_rejected_before_queue(self):
        args = SimpleNamespace(command='codex', action='submit', task_id=None,
                               repo=None, issue=None, kind=None)
        with patch('gway_remote.codex_queue.TaskQueue') as queue:
            with self.assertRaises(SystemExit) as raised:
                dispatch(args, argparse.ArgumentParser(), run_task=None)
            self.assertEqual(raised.exception.code, 2)
            queue.assert_not_called()
