"""Exercise the production Ansible rollback probes against real local HTTP sockets."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest

try:
    import yaml
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parents[2]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(405 if self.path == '/mcp' else 200)
        self.end_headers()
    def log_message(self, *_):
        pass


@unittest.skipUnless(yaml and shutil.which('ansible-playbook'), 'Ansible and PyYAML required')
class RollbackProbeTests(unittest.TestCase):
    def run_probes(self, gateway_port, oauth_port):
        play = yaml.safe_load((ROOT / 'ansible/playbooks/watchtower-mcp.yml').read_text())
        block = next(t for t in play[0]['tasks'] if 'rescue' in t)
        selected = [deepcopy(t) for t in block['rescue'] if t['name'] in (
            'Restore previous pointer atomically if activation failed',
            'Verify gateway health independently after rollback',
            'Verify OAuth health independently after rollback',
            'Stop on failed MCP release activation')]
        for task, port in zip(selected[1:3], (gateway_port, oauth_port)):
            task['ansible.builtin.uri']['url'] = task['ansible.builtin.uri']['url'].replace(
                '19010' if port == gateway_port else '19012', str(port))
            # When the same test server serves both endpoints, choose by task name.
            if task['name'].startswith('Verify OAuth'):
                task['ansible.builtin.uri']['url'] = 'http://127.0.0.1:%d/.well-known/oauth-authorization-server' % oauth_port
            task['retries'] = 1
            task['delay'] = 0
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'releases').mkdir()
            (root / 'current').symlink_to('releases/' + 'b' * 40)
            selected[0].pop('become', None)
            selected[0]['ansible.builtin.shell'] = selected[0]['ansible.builtin.shell'].replace(
                'cd /opt/gway-mcp', 'cd ' + tmp)
            file = Path(tmp) / 'probe.yml'
            file.write_text(yaml.safe_dump([{'hosts': 'localhost', 'connection': 'local',
                'gather_facts': False, 'vars': {'mcp_correlation': {'stdout': 'a' * 32},
                    'mcp_rollback_receipt': {'rc': 0},
                    'mcp_original_target': {'stdout': 'releases/' + 'a' * 40}}, 'tasks': selected}]))
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', str(file)],
                                    text=True, capture_output=True, timeout=45)
            self.assertEqual((root / 'current').readlink().as_posix(), 'releases/' + 'a' * 40)
            return result

    def test_restored_files_but_refused_gateway_reports_unhealthy(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            unused = sock.getsockname()[1]
        try:
            result = self.run_probes(unused, server.server_port)
        finally:
            server.shutdown(); server.server_close(); thread.join()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('rollback_unhealthy', result.stdout)
        self.assertIn('OAuth HTTP health: healthy', result.stdout)

    def test_healthy_restored_gateway_and_oauth_are_reported(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = self.run_probes(server.server_port, server.server_port)
        finally:
            server.shutdown(); server.server_close(); thread.join()
        self.assertNotEqual(result.returncode, 0)  # activation failure must still fail deployment
        self.assertIn('rollback_healthy', result.stdout)
        self.assertIn('OAuth HTTP health: healthy', result.stdout)

    def test_gateway_can_be_healthy_while_oauth_is_down(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            unused = sock.getsockname()[1]
        try:
            result = self.run_probes(server.server_port, unused)
        finally:
            server.shutdown(); server.server_close(); thread.join()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('rollback_healthy', result.stdout)
        self.assertIn('OAuth HTTP health: unhealthy', result.stdout)
