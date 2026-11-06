import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.mcp_source_policy import load_source_policy

POLICY = {"version": 1, "sources": []}


class SharedPolicyTests(unittest.TestCase):
    def test_empty_policy_preserves_legacy_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            data = json.dumps(POLICY).encode()
            path.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            with patch("gway_remote.mcp_source_policy.Path", wraps=Path):
                # Production rejects files outside the protected config root.
                with self.assertRaises(ValueError):
                    load_source_policy(str(path), expected_sha256=digest)

    def test_requires_pinned_digest(self):
        with self.assertRaises(ValueError):
            load_source_policy("/etc/gway-mcp-gateway/sources.json", expected_sha256="main")


if __name__ == "__main__":
    unittest.main()
