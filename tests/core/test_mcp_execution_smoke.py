import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('execution_smoke', Path(__file__).resolve().parents[2] / 'scripts/mcp-execution-smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

class ExecutionSmokeTests(unittest.TestCase):
    def test_success_and_uncertain_never_resubmits(self):
        for uncertain in (False, True):
            calls = []
            def transport(url, token, method, payload):
                name = payload['name']
                args = payload['arguments']
                calls.append(name)
                if name == 'node_exec_preview':
                    value = {'limits': {'concurrent_jobs_per_node': 3}}
                elif name == 'node_exec':
                    value = {'request_id': args['request_id'], 'status': 'uncertain' if uncertain else 'dispatched'}
                else:
                    value = {'request_id': args['request_id'], 'status': 'succeeded', 'exit_code': 0, 'stdout': 'gway-001\n'}
                return 200, json.dumps({'result': {'content': [{'text': json.dumps(value)}]}}).encode()
            if uncertain:
                with self.assertRaises(ValueError):
                    smoke.smoke('https://example.com/mcp', 'test', transport, lambda _: None)
                self.assertEqual(calls, ['node_exec_preview', 'node_exec'])
            else:
                smoke.smoke('https://example.com/mcp', 'test', transport, lambda _: None)
                self.assertEqual(calls, ['node_exec_preview', 'node_exec', 'node_result'])
