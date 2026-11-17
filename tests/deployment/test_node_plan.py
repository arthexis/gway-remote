"""Hermetic node plan comparisons: inventory-only, no remote operations."""
import json
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gway_remote.node_plan import plan
from gway_remote.deployment_policy import INVENTORY


class NodePlanTest(unittest.TestCase):
    def test_policy_comparison_and_no_implicit_grant(self):
        catalog = {'revision': 'abc', 'targets': [
            {'name': 'one', 'repository': 'arthexis/one'}]}
        hosts = {'n': {'remote_managed_repositories': ['one', 'missing', 'one'],
                       'gway_agent_allowed_repos': [
                           'arthexis/gway-remote', 'other/repo']}}
        report = plan('n', hostvars=hosts, catalog=catalog)
        self.assertEqual(report['suggested_agent_additions'], ['arthexis/one'])
        self.assertEqual(report['unknown_managed_repositories'], ['missing'])
        self.assertEqual(report['duplicate_managed_repositories'], ['one'])
        self.assertEqual(report['unknown_agent_repositories'], ['other/repo'])
        self.assertNotIn('arthexis/one', hosts['n']['gway_agent_allowed_repos'])

    def test_unknown_and_invalid_host_fail(self):
        for hosts in ({}, {'n': {'remote_managed_repositories': 'one'}}):
            with self.subTest(hosts=hosts), self.assertRaises(ValueError):
                plan('n', hostvars=hosts, catalog={'revision': 'x', 'targets': []})

    def test_real_path_reads_inventory_only_and_uses_validated_export(self):
        hostvars = {'gway-001': {
            'remote_managed_repositories': ['ocpp-csms'],
            'gway_agent_allowed_repos': ['arthexis/gway-remote']}}
        inventory_json = json.dumps({'_meta': {'hostvars': hostvars}})
        catalog = {'revision': 'verified', 'targets': [
            {'name': 'ocpp-csms', 'repository': 'arthexis/ocpp-csms'}]}
        with patch('gway_remote.node_plan.subprocess.run',
                   return_value=SimpleNamespace(stdout=inventory_json)) as run, \
             patch('gway_remote.node_plan.export_targets',
                   return_value=catalog) as export:
            report = plan('gway-001')
        run.assert_called_once_with(
            ['ansible-inventory', '-i', str(INVENTORY), '--list'],
            check=True, capture_output=True, text=True, timeout=15)
        export.assert_called_once_with()
        self.assertEqual(report['catalog_revision'], 'verified')
        self.assertEqual(report['suggested_agent_additions'],
                         ['arthexis/ocpp-csms'])
        self.assertEqual(hostvars['gway-001']['gway_agent_allowed_repos'],
                         ['arthexis/gway-remote'])
        self.assertIn('no remote host', report['evidence'])

    def test_inventory_error_does_not_infer_policy_or_call_catalog(self):
        with patch('gway_remote.node_plan.subprocess.run',
                   side_effect=subprocess.CalledProcessError(
                       2, ['ansible-inventory'])) as run, \
             patch('gway_remote.node_plan.export_targets') as export:
            with self.assertRaisesRegex(ValueError, 'inventory unavailable'):
                plan('gway-001')
        run.assert_called_once()
        export.assert_not_called()


if __name__ == '__main__':
    unittest.main()
