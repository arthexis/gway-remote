import unittest
from gway_remote.node_plan import plan


class NodePlanTest(unittest.TestCase):
    def test_policy_comparison_and_no_implicit_grant(self):
        catalog = {'revision': 'abc', 'targets': [{'name': 'one', 'repository': 'arthexis/one'}]}
        hosts = {'n': {'remote_managed_repositories': ['one', 'missing', 'one'],
                       'gway_agent_allowed_repos': ['arthexis/gway-remote', 'other/repo']}}
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
