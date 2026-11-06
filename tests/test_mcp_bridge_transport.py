import tempfile
import threading
import unittest
from pathlib import Path

from gway_remote.mcp_bridge_contract import InvalidBridgeRequest
from gway_remote.mcp_bridge_transport import (
    AuthenticatedBridge, BridgeUnixServer, call_unix, canonical, sign,
)


class BridgeTransportTests(unittest.TestCase):
    def setUp(self):
        self.key = b"k" * 32
        self.envelope = {
            "version": 1, "request_id": "b" * 32, "principal": "operator-1",
            "audience": "gway-001", "operation": "inventory.list",
            "scope": "gway:read", "issued_at": 100, "expires_at": 130,
            "arguments": {},
        }
        self.bridge = AuthenticatedBridge(self.key, audience="gway-001",
                                          dispatch=lambda e: {"operation": e["operation"]})

    def wire(self):
        return canonical({"envelope": self.envelope, "signature": sign(self.key, self.envelope)})

    def test_authenticated_request_and_replay(self):
        self.assertEqual(self.bridge.process(self.wire(), now=101),
                         {"operation": "inventory.list"})
        with self.assertRaises(InvalidBridgeRequest):
            self.bridge.process(self.wire(), now=101)

    def test_tampered_request_rejected(self):
        raw = self.wire().replace(b"inventory.list", b"execution.start")
        with self.assertRaises(InvalidBridgeRequest):
            self.bridge.process(raw, now=101)

    def test_wrong_audience_rejected(self):
        self.bridge.audience = "gway-002"
        with self.assertRaises(InvalidBridgeRequest):
            self.bridge.process(self.wire(), now=101)

    def test_socket_round_trip(self):
        import time
        self.envelope["issued_at"] = int(time.time())
        self.envelope["expires_at"] = self.envelope["issued_at"] + 30
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sock"
            with BridgeUnixServer(path, self.bridge) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    self.assertEqual(call_unix(path, self.key, self.envelope),
                                     {"operation": "inventory.list"})
                    with self.assertRaises(PermissionError):
                        call_unix(path, self.key, self.envelope)
                finally:
                    server.shutdown()
                    thread.join(timeout=3)


    def test_stale_socket_recovers_after_abrupt_process_exit(self):
        import multiprocessing
        import os
        import socket
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sock"
            # A dead process left a real socket inode behind.
            sock = socket.socket(socket.AF_UNIX)
            sock.bind(str(path))
            sock.close()
            with BridgeUnixServer(path, self.bridge) as server:
                self.assertTrue(path.exists())
            self.assertFalse(path.exists())

    def test_active_socket_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sock"
            with BridgeUnixServer(path, self.bridge) as server:
                before = path.lstat().st_ino
                with self.assertRaises(FileExistsError):
                    BridgeUnixServer(path, self.bridge)
                self.assertEqual(path.lstat().st_ino, before)

    def test_unsafe_existing_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sock"
            path.write_text("not a socket")
            with self.assertRaises(PermissionError):
                BridgeUnixServer(path, self.bridge)
            path.unlink()
            path.symlink_to("missing")
            with self.assertRaises(PermissionError):
                BridgeUnixServer(path, self.bridge)

    def test_server_close_does_not_unlink_replacement(self):
        import socket
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sock"
            server = BridgeUnixServer(path, self.bridge)
            path.unlink()
            replacement = socket.socket(socket.AF_UNIX)
            replacement.bind(str(path))
            try:
                inode = path.lstat().st_ino
                server.server_close()
                self.assertEqual(path.lstat().st_ino, inode)
            finally:
                replacement.close()

    def test_private_directory_required(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o755)
            try:
                with self.assertRaises(PermissionError):
                    BridgeUnixServer(Path(directory) / "bridge.sock", self.bridge)
            finally:
                os.chmod(directory, 0o700)


if __name__ == "__main__":
    unittest.main()
