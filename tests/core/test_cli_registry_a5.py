"""Frozen complete CLI registry contracts and dependency isolation."""
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gway_remote.cli import registry
from gway_remote.reconcile import TARGETS

GOLDEN = json.loads(Path(__file__).with_name('cli_registry_a5_golden.json').read_text())


class CliRegistryA5Tests(unittest.TestCase):
    def test_pre_refactor_stdout_stderr_exit(self):
        for arguments, expected in GOLDEN.items():
            with self.subTest(arguments=arguments):
                proc = subprocess.run([sys.executable, '-m', 'gway_remote', *arguments.split()],
                                      capture_output=True, check=False)
                self.assertEqual(proc.returncode, expected['code'])
                self.assertEqual(hashlib.sha256(proc.stdout).hexdigest(), expected['stdout_sha256'])
                self.assertEqual(hashlib.sha256(proc.stderr).hexdigest(), expected['stderr_sha256'])

    def test_all_command_names_registered_once(self):
        parser = registry.build_parser(('system-health',), TARGETS)
        actions = [action for action in parser._actions if hasattr(action, 'choices') and
                   isinstance(action.choices, dict)]
        self.assertEqual(len(actions), 1)
        commands = actions[0].choices
        self.assertEqual(len(commands), 29)
        self.assertIs(commands['codex'], commands['codex-worker'])

    def test_no_entrypoint_import_or_circular_dependency(self):
        for module in ('registry', 'deploy', 'local', 'operations', 'security'):
            source = (Path(__file__).resolve().parents[2] /
                      'gway_remote' / 'cli' / (module + '.py')).read_text()
            self.assertNotIn('from ..__main__ import', source)
            self.assertNotIn('from gway_remote.__main__ import', source)
        # Import all CLI modules without loading the entrypoint module.
        script = ('import sys; import gway_remote.cli.registry; '
                  'assert "gway_remote.__main__" not in sys.modules')
        proc = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_dispatch_short_circuits_in_original_order(self):
        args = SimpleNamespace(command='run')
        with patch.object(registry.local, 'dispatch', return_value=True) as local, \
             patch.object(registry.security, 'dispatch') as security, \
             patch.object(registry.operations, 'dispatch') as operations, \
             patch.object(registry.deploy, 'dispatch') as deploy:
            self.assertTrue(registry.dispatch(args, Mock(), run_task=Mock(), deployers={}))
            local.assert_called_once()
            security.assert_not_called()
            operations.assert_not_called()
            deploy.assert_not_called()

    def test_dispatch_unknown_returns_false(self):
        args = SimpleNamespace(command='other')
        self.assertFalse(registry.dispatch(args, Mock(), run_task=Mock(), deployers={}))
