"""Pure MCP provider response and dispatch spies for authorization tests."""
from tests.helpers.mcp_federation import fixture_tool


def provider_reply(node='gway-001', *, source='odoo', tools=None):
    if tools is None:
        tools = [fixture_tool('list', read=True)]
    return {'node': node, 'providers': [{
        'provider': source, 'node': node, 'revision': 'a' * 40,
        'status': 'available', 'tools': tools,
    }]}


class InvocationSpy:
    def __init__(self, *, fail_node=None, response=None):
        self.calls = []
        self.fail_node = fail_node
        self.response = response

    def invoke(self, node, request, *, trusted_scope):
        self.calls.append((node, request, trusted_scope))
        if node == self.fail_node:
            raise TimeoutError('offline')
        if self.response is not None:
            return self.response
        return provider_reply(node)
