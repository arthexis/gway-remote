"""Frozen pre-refactor argparse output and isolated read-only dispatch contracts."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gway_remote.cli.operations import dispatch

GOLDEN = json.loads(Path(__file__).with_name('cli_operations_a1_golden.json').read_text())


@pytest.mark.parametrize('arguments,expected', GOLDEN.items())
def test_argparse_compatibility(arguments, expected):
    result = subprocess.run([sys.executable, '-m', 'gway_remote', *arguments.split()],
                            capture_output=True, check=False)
    assert result.returncode == expected['code']
    assert hashlib.sha256(result.stdout).hexdigest() == expected['stdout_sha256']
    assert hashlib.sha256(result.stderr).hexdigest() == expected['stderr_sha256']


@pytest.mark.parametrize('command,module,formatter', [
    ('status', 'gway_remote.status', 'format_status'),
    ('hardware', 'gway_remote.hardware_diagnostics', 'format_hardware'),
    ('network', 'gway_remote.network_diagnostics', 'format_network'),
])
def test_read_only_output_modes(command, module, formatter, capsys):
    with patch(module + '.inspect' if command != 'status' else module + '.status',
               return_value={'ok': True}), patch(module + '.' + formatter, return_value='human'):
        for json_mode in (False, True):
            assert dispatch(SimpleNamespace(command=command, json=json_mode), None)
            output = capsys.readouterr().out.strip()
            assert output == (json.dumps({'ok': True}, indent=2, sort_keys=True) if json_mode else 'human')


def test_non_operations_not_dispatched():
    assert dispatch(SimpleNamespace(command='deploy'), None) is False


def test_diagnose_error_contract(capsys):
    with patch('gway_remote.diagnostics.diagnose', side_effect=ValueError('bad target')):
        with pytest.raises(SystemExit) as failure:
            dispatch(SimpleNamespace(command='diagnose', component=None, lines=30, json=False),
                     __import__('argparse').ArgumentParser(prog='gway-remote'))
    assert failure.value.code == 1
    assert capsys.readouterr().err == 'gway-remote: diagnosis unavailable: bad target\\n'


def test_logs_empty_contract(capsys):
    with patch('gway_remote.logs.read_log', return_value=None):
        with pytest.raises(SystemExit) as failure:
            dispatch(SimpleNamespace(command='logs', component='ocpp-csms', lines=20),
                     __import__('argparse').ArgumentParser(prog='gway-remote'))
    assert failure.value.code == 1
    assert capsys.readouterr().err == 'gway-remote: no installation logs found\\n'
