"""OAuth discovery must advertise the same scopes as the authorization server."""
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.request import urlopen

from gway_remote.mcp_link_http import Handler


class OAuthScopeDiscoveryTests(unittest.TestCase):
    def test_protected_resource_matches_authorization_server_scopes(self):
        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            # Metadata endpoints do not require an OAuth session or any secrets.
            server.link = SimpleNamespace()
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}"
                with urlopen(url + "/.well-known/oauth-protected-resource/mcp", timeout=3) as response:
                    resource = json.load(response)
                with urlopen(url + "/.well-known/oauth-authorization-server", timeout=3) as response:
                    authorization = json.load(response)
            finally:
                server.shutdown()
                thread.join(timeout=3)
        self.assertEqual(resource["scopes_supported"], authorization["scopes_supported"])
        self.assertEqual(resource["scopes_supported"], ["gway:read", "gway:execute"])
        self.assertEqual(resource["resource"], "https://remote.arthexis.com/mcp")


if __name__ == "__main__":
    unittest.main()
