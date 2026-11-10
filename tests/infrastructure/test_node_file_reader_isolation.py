"""Isolated reader regression tests discovered by unittest CI."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gway_remote import node_exec_protocol, node_file_reader

RID = "a" * 32


def payload(node="gway-001"):
    return json.dumps({"operation": "file_read", "node": node,
                       "request_id": RID, "filename": "narracion.opus",
                       "offset": 0}).encode()


class FileReaderIsolationTests(unittest.TestCase):
    def test_fixed_sudo_invocation_and_correlation(self):
        with patch.object(node_exec_protocol, "require_account"), patch.object(
            node_exec_protocol.subprocess, "run"
        ) as run:
            run.return_value = SimpleNamespace(stdout=json.dumps({
                "node": "gway-001", "request_id": RID, "result": {"size": 3}
            }).encode())
            result = node_exec_protocol.serve_one(payload(), hostname="gway-001")
            self.assertEqual(result["result"]["size"], 3)
            argv = run.call_args.args[0]
            self.assertEqual(argv, ["/usr/bin/sudo", "-n", "-u", "gway-exec",
                                    "/usr/bin/env", "PYTHONPATH=/opt/gway-remote",
                                    "/usr/bin/python3", "-m", "gway_remote.node_file_reader"])
            self.assertEqual(run.call_args.kwargs["timeout"], 5)
            self.assertTrue(run.call_args.kwargs["check"])
            self.assertNotIn("shell", run.call_args.kwargs)

    def test_wrong_node_request_id_and_extra_fields_fail_closed(self):
        variants = [
            {"node": "gway-002", "request_id": RID, "result": {}},
            {"node": "gway-001", "request_id": "b" * 32, "result": {}},
            {"node": "gway-001", "request_id": RID, "result": {}, "extra": True},
            {"error": "file read rejected"},
        ]
        for variant in variants:
            with self.subTest(variant=variant), patch.object(
                node_exec_protocol, "require_account"
            ), patch.object(node_exec_protocol.subprocess, "run",
                            return_value=SimpleNamespace(stdout=json.dumps(variant).encode())):
                with self.assertRaises(PermissionError):
                    node_exec_protocol.serve_one(payload(), hostname="gway-001")

    def test_missing_sudoers_fails_closed(self):
        from subprocess import CalledProcessError
        with patch.object(node_exec_protocol, "require_account"), patch.object(
            node_exec_protocol.subprocess, "run", side_effect=CalledProcessError(1, "sudo")
        ):
            with self.assertRaisesRegex(PermissionError, "unavailable"):
                node_exec_protocol.serve_one(payload(), hostname="gway-001")

    def test_no_other_nodes(self):
        with patch.object(node_exec_protocol, "require_account"), patch.object(
            node_exec_protocol.subprocess, "run"
        ) as run:
            with self.assertRaises(PermissionError):
                node_exec_protocol.serve_one(payload("gway-002"), hostname="gway-002")
            run.assert_not_called()

    def test_helper_requires_gway_exec(self):
        with patch.object(node_file_reader.os, "geteuid", return_value=-1):
            with self.assertRaises(PermissionError):
                node_file_reader.serve(b"{}", hostname="gway-001")

    def test_helper_rejects_extra_fields_and_wrong_node(self):
        with patch.object(node_file_reader.os, "geteuid", return_value=990), patch(
            "pwd.getpwnam", return_value=SimpleNamespace(pw_uid=990)
        ), patch.object(node_file_reader, "export_chunk") as export:
            for request in [
                {"node": "gway-001", "request_id": RID, "filename": "narracion.opus",
                 "offset": 0, "command": "id"},
                {"node": "gway-002", "request_id": RID, "filename": "narracion.opus",
                 "offset": 0},
            ]:
                with self.subTest(request=request), self.assertRaises((ValueError, PermissionError)):
                    node_file_reader.serve(json.dumps(request).encode(), hostname="gway-001")
            export.assert_not_called()

    def test_helper_fixed_root_and_receipt(self):
        with patch.object(node_file_reader.os, "geteuid", return_value=990), patch(
            "pwd.getpwnam", return_value=SimpleNamespace(pw_uid=990)
        ), patch.object(node_file_reader, "export_chunk", return_value={"size": 21023}) as export:
            result = node_file_reader.serve(json.dumps({
                "node": "gway-001", "request_id": RID,
                "filename": "narracion.opus", "offset": 8192
            }).encode(), hostname="gway-001")
            self.assertEqual(result["request_id"], RID)
            export.assert_called_once_with("narracion.opus",
                                           export_root="/var/lib/gway-mcp-exports",
                                           offset=8192)
