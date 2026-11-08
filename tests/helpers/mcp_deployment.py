"""Offline release/manifests and Ansible assertions for MCP deployment tests."""
import importlib.util
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = ROOT / 'ansible/playbooks/gway001-mcp-runtime.yml'


def load_manifest_publisher():
    path = ROOT / 'scripts/converge-mcp-manifests.py'
    spec = importlib.util.spec_from_file_location('mcp_manifest_convergence', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_manifest(revision='a' * 40):
    return {'source_id': 'fixture', 'revision': revision,
            'executable': '/opt/example/bin/mcp', 'argv': ['/opt/example/bin/mcp']}


def manifest_snapshot(path):
    stat = path.stat()
    return stat.st_ino, stat.st_mtime_ns, path.read_bytes()


def ansible_changed_count(output):
    match = re.search(r'(?m)^localhost\s*:\s*ok=\d+\s+changed=(\d+)', output)
    if match is None:
        raise AssertionError('Ansible recap missing localhost changed count')
    return int(match.group(1))
