"""Authenticated Odoo attachment route must never leak report bytes or secrets."""
import http.client
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from gway_remote.api import handler_for


def request(server, path, token):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        conn.request("GET", path, headers={"Authorization": f"Bearer {token}"})
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def test_quotation_pdf_authenticated_binary_response():
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for("test-key"))
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        pdf = b"%PDF-1.4\n" + b"0" * 2048 + b"%%EOF"
        with patch("gway_remote.api.mobile_odoo_quotations.download",
                   return_value=("S30958 Subestación 1.pdf", pdf)) as download:
            status, headers, body = request(server, "/api/v1/odoo/quotations/857/pdf", "wrong")
            assert status == 401 and body != pdf
            download.assert_not_called()
            status, headers, body = request(server, "/api/v1/odoo/quotations/857/pdf", "test-key")
            assert status == 200 and body == pdf
            assert headers["Content-Type"] == "application/pdf"
            assert headers["Cache-Control"] == "private, no-store"
            assert "filename*=UTF-8''" in headers["Content-Disposition"]
            download.assert_called_once_with(857)
            status, headers, body = request(server, "/api/v1/odoo/quotations/857/pdf?file=/etc/passwd", "test-key")
            assert status == 404 and body != pdf
            download.assert_called_once_with(857)
    finally:
        server.shutdown()
        t.join(timeout=4)
        server.server_close()


def test_download_failure_does_not_expose_odoo_details():
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for("test-key"))
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        with patch("gway_remote.api.mobile_odoo_quotations.download",
                   side_effect=RuntimeError("password=never-return-me")):
            status, headers, body = request(server, "/api/v1/odoo/quotations/857/pdf", "test-key")
            assert status == 502
            assert b"never-return-me" not in body
            assert b"odoo_pdf_unavailable" in body
    finally:
        server.shutdown()
        t.join(timeout=4)
        server.server_close()
