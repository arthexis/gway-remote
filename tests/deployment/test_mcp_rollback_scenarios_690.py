"""Exercise the production Ansible rollback probes against real local HTTP sockets."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
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
    issuer = 'https://remote.arthexis.com'
    challenges = ['S256']
    def do_GET(self):
        gateway = self.path == '/mcp'
        body = b'' if gateway else json.dumps({
            'issuer': self.issuer,
            'authorization_response_iss_parameter_supported': True,
            'code_challenge_methods_supported': self.challenges,
        }).encode()
        self.send_response(405 if gateway else 200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *_):
        pass


class WrongIssuerHandler(Handler):
    issuer = 'https://wrong.example'


class InvalidChallengesHandler(Handler):
    challenges = 'S256'


@unittest.skipUnless(yaml and shutil.which('ansible-playbook'), 'Ansible and PyYAML required')
class RollbackProbeTests(unittest.TestCase):
    def run_probes(self, gateway_port, oauth_port, *, pointer_failure=False, unit_failure=False, restart_failure=False, wrong_issuer=False):
        play = yaml.safe_load((ROOT / 'ansible/playbooks/watchtower-mcp.yml').read_text())
        block = next(t for t in play[0]['tasks'] if 'rescue' in t)
        selected = [deepcopy(t) for t in block['rescue'] if t['name'] in (
            'Restore previous pointer atomically if activation failed',
            'Restore original OAuth service unit exactly',
            'Restart previous private gateway after release rollback',
            'Restart existing OAuth link after rollback',
            'Verify gateway health independently after rollback',
            'Verify OAuth health independently after rollback',
            'Classify the complete rollback outcome',
            'Record private post-rollback diagnostics',
            'Stop on failed MCP release activation')]
        named = {task['name']: task for task in selected}
        for name, port in (('Verify gateway health independently after rollback', gateway_port),
                           ('Verify OAuth health independently after rollback', oauth_port)):
            task = named[name]
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
            pointer = named['Restore previous pointer atomically if activation failed']
            pointer.pop('become', None)
            pointer['ansible.builtin.shell'] = pointer['ansible.builtin.shell'].replace(
                'cd /opt/gway-mcp', 'cd ' + (tmp + '/missing' if pointer_failure else tmp))
            unit = named['Restore original OAuth service unit exactly']
            unit.pop('become', None)
            copy = unit['ansible.builtin.copy']
            copy['dest'] = str(root / ('missing/unit' if unit_failure else 'unit'))
            copy.pop('owner', None)
            copy.pop('group', None)
            for name, marker, fail in (
                    ('Restart previous private gateway after release rollback', 'gateway-restarted', restart_failure),
                    ('Restart existing OAuth link after rollback', 'oauth-restarted', False)):
                task = named[name]
                task.pop('become', None)
                task.pop('ansible.builtin.systemd')
                task['ansible.builtin.command'] = {'argv': ['/usr/bin/python3', '-c',
                    'import pathlib,sys; pathlib.Path(sys.argv[1]).touch(); sys.exit(int(sys.argv[2]))',
                    str(root / marker), str(int(fail))]}
            stub = root / 'receipt.py'
            stub.write_text('import pathlib,sys\npathlib.Path(sys.argv[1]).write_text(sys.argv[2])\n')
            receipt = root / 'result.txt'
            receipt_task = named['Record private post-rollback diagnostics']
            receipt_task.pop('become', None)
            receipt_task['ansible.builtin.command']['argv'] = [
                '/usr/bin/python3', str(stub), str(receipt), '{{ mcp_rollback_result }}']
            file = Path(tmp) / 'probe.yml'
            file.write_text(yaml.safe_dump([{'hosts': 'localhost', 'connection': 'local',
                'gather_facts': False, 'vars': {'mcp_correlation': {'stdout': 'a' * 32},
                    'mcp_original_unit': {'content': 'ZmFrZQ=='},
                    'mcp_rollback_gateway_unit': {'failed': False},
                    'mcp_rollback_reload': {'failed': False},
                    'mcp_gateway_activation_needed': True,
                    'mcp_activation_needed': True,
                    'mcp_exec_gateway_unit': {'changed': False},
                    'mcp_original_target': {'stdout': 'releases/' + 'a' * 40}}, 'tasks': selected}]))
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', str(file)],
                                    text=True, capture_output=True, timeout=45)
            self.assertEqual((root / 'current').readlink().as_posix(),
                             'releases/' + ('b' if pointer_failure else 'a') * 40)
            self.assertEqual((root / 'gateway-restarted').exists(), not pointer_failure)
            self.assertEqual((root / 'oauth-restarted').exists(), not pointer_failure and not unit_failure)
            self.assertEqual(receipt.read_text(),
                             'rollback_healthy' if not pointer_failure and not unit_failure and not restart_failure and not wrong_issuer and gateway_port == oauth_port
                             else 'rollback_unhealthy')
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
        self.assertIn('rollback_unhealthy', result.stdout)
        self.assertIn('OAuth HTTP health: unhealthy', result.stdout)

    def test_failed_pointer_restore_still_writes_unhealthy_receipt(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = self.run_probes(server.server_port, server.server_port, pointer_failure=True)
        finally:
            server.shutdown(); server.server_close(); thread.join()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('rollback_unhealthy', result.stdout)
        self.assertIn('receipt: written', result.stdout)

    def test_failed_unit_restore_still_writes_unhealthy_receipt(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = self.run_probes(server.server_port, server.server_port, unit_failure=True)
        finally:
            server.shutdown(); server.server_close(); thread.join()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('rollback_unhealthy', result.stdout)
        self.assertIn('receipt: written', result.stdout)

    def test_wrong_oauth_issuer_cannot_claim_healthy_rollback(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), WrongIssuerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = self.run_probes(server.server_port, server.server_port, wrong_issuer=True)
        finally:
            server.shutdown(); server.server_close(); thread.join()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('rollback_unhealthy', result.stdout)
        self.assertIn('OAuth HTTP health: unhealthy', result.stdout)

    def test_failed_gateway_restart_cannot_claim_healthy_rollback(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = self.run_probes(server.server_port, server.server_port, restart_failure=True)
        finally:
            server.shutdown(); server.server_close(); thread.join()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('rollback_unhealthy', result.stdout)
        self.assertIn('gateway HTTP health: healthy', result.stdout)

    def test_oauth_challenges_must_be_a_list(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), InvalidChallengesHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = self.run_probes(server.server_port, server.server_port, wrong_issuer=True)
        finally:
            server.shutdown(); server.server_close(); thread.join()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('rollback_unhealthy', result.stdout)
        self.assertIn('OAuth HTTP health: unhealthy', result.stdout)
