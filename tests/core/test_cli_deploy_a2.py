"""Frozen pre-A2 CLI contracts; never invoke a deployment."""
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

from gway_remote.cli.deploy import dispatch

GOLDEN = json.loads(Path(__file__).with_name('cli_deploy_a2_golden.json').read_text())


class CliDeployA2Tests(unittest.TestCase):
    def test_argparse_before_after(self):
        for arguments, expected in GOLDEN.items():
            with self.subTest(arguments=arguments):
                proc = subprocess.run([sys.executable, '-m', 'gway_remote', *arguments.split()],
                                      capture_output=True, check=False)
                self.assertEqual(proc.returncode, expected['code'])
                self.assertEqual(hashlib.sha256(proc.stdout).hexdigest(), expected['stdout_sha256'])
                self.assertEqual(hashlib.sha256(proc.stderr).hexdigest(), expected['stderr_sha256'])

    def test_unrelated_command_not_dispatched(self):
        self.assertFalse(dispatch(SimpleNamespace(command='status'), None, deployers={}))

    def test_deploy_invalid_request_never_dispatches(self):
        args = SimpleNamespace(command='deploy', all=True, repository='ocpp-csms',
                               node='gway-001', follow=False)
        with patch('gway_remote.deploy_dispatch.dispatch') as send:
            with self.assertRaises(SystemExit) as raised:
                dispatch(args, argparse.ArgumentParser(prog='gway-remote'), deployers={})
            self.assertEqual(raised.exception.code, 2)
            send.assert_not_called()

    def test_retention_format_and_error(self):
        args = SimpleNamespace(command='retention', repository=None, json=False)
        with patch('gway_remote.retention_preview.preview', return_value={'ok': True}), \
             patch('gway_remote.retention_preview.format_preview', return_value='preview'):
            output = StringIO()
            with redirect_stdout(output):
                self.assertTrue(dispatch(args, None, deployers={}))
            self.assertEqual(output.getvalue(), 'preview\n')
        with patch('gway_remote.retention_preview.preview', side_effect=ValueError('invalid')):
            error = StringIO()
            with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                dispatch(args, argparse.ArgumentParser(), deployers={})
            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(error.getvalue(), 'gway-remote: retention preview unavailable: invalid\n')

    def test_reconcile_error_contract(self):
        with patch('gway_remote.github_state.GitHub', side_effect=RuntimeError('offline')):
            error = StringIO()
            with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                dispatch(SimpleNamespace(command='reconcile'), argparse.ArgumentParser(), deployers={})
            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(error.getvalue(), 'gway-remote: reconciliation unavailable: offline\n')

    def test_deploy_dispatch_is_mocked(self):
        args = SimpleNamespace(command='deploy', all=False, repository='ocpp-csms',
                               node='gway-001', follow=False)
        with patch('gway_remote.deploy_dispatch.resolve_targets', return_value=('ocpp-csms',)), \
             patch('gway_remote.deploy_dispatch.dispatch', return_value='queued') as send:
            output = StringIO()
            with redirect_stdout(output):
                self.assertTrue(dispatch(args, argparse.ArgumentParser(), deployers={}))
            send.assert_called_once_with('ocpp-csms', node='gway-001')
            self.assertEqual(output.getvalue(), 'queued\n')

    def test_deploy_batch_rejects_flags_before_execute(self):
        args = SimpleNamespace(command='deploy-batch', target='ocpp-csms', all=False,
                               now=False, retry_failed=False)
        with patch('gway_remote.deployment_policy.require_local_deployment'), \
             patch('gway_remote.best_effort.execute') as execute:
            with self.assertRaises(SystemExit) as raised:
                dispatch(args, argparse.ArgumentParser(), deployers={})
            self.assertEqual(raised.exception.code, 2)
            execute.assert_not_called()
