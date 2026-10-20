"""No implicit network enrollment: endpoint configuration is local and strict."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.wireguard_endpoint import endpoint, set_endpoint, normalize_endpoint


class WireGuardEndpointTests(unittest.TestCase):
    def test_default_and_explicit_endpoint(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config/wireguard.json"
            with patch("gway_remote.wireguard_endpoint.config_path", return_value=path):
                self.assertEqual(endpoint(), {"endpoint": "https://register.jelectric.com", "configured": False})
                self.assertEqual(set_endpoint("https://register.jelectric.com/")["configured"], True)
                self.assertEqual(endpoint()["endpoint"], "https://register.jelectric.com")
                self.assertEqual(json.loads(path.read_text()), {"endpoint": "https://register.jelectric.com"})
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_rejects_untrusted_or_secret_bearing_origins(self):
        for value in ("http://register.jelectric.com", "https://evil.example",
                      "https://register.jelectric.com.evil.example",
                      "https://user:pass@register.jelectric.com",
                      "https://register.jelectric.com/a", "https://register.jelectric.com/?token=abc",
                      "https://register.jelectric.com/#secret"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_endpoint(value)

    def test_symlink_config_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "original"
            source.write_text("untouched")
            link = Path(root) / "config"
            link.symlink_to(source)
            with patch("gway_remote.wireguard_endpoint.config_path", return_value=link):
                with self.assertRaises(ValueError):
                    set_endpoint("https://register.jelectric.com")
            self.assertEqual(source.read_text(), "untouched")
