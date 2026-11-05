"""Authenticated Odoo attachment route security and binary HTTP behavior."""
import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from gway_remote.api import handler_for


class OdooHttpApiTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(("127.0.0.1",0),handler_for("test-key"))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join,4)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self,path,token):
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=5)
        try:
            conn.request("GET",path,headers={"Authorization":f"Bearer {token}"})
            response=conn.getresponse()
            return response.status,dict(response.getheaders()),response.read()
        finally:
            conn.close()

    def test_quotation_pdf_authenticated_binary_response(self):
        pdf=b"%PDF-1.4\n"+b"0"*2048+b"%%EOF"
        with patch("gway_remote.api.mobile_odoo_quotations.download",
                   return_value=("S30958 Subestación 1.pdf",pdf)) as downloader:
            status,headers,body=self.request("/api/v1/odoo/quotations/857/pdf","wrong")
            self.assertEqual(status,401)
            self.assertNotEqual(body,pdf)
            downloader.assert_not_called()

            status,headers,body=self.request("/api/v1/odoo/quotations/857/pdf","test-key")
            self.assertEqual(status,200)
            self.assertEqual(body,pdf)
            self.assertEqual(headers["Content-Type"],"application/pdf")
            self.assertEqual(headers["Cache-Control"],"private, no-store")
            self.assertIn("filename*=UTF-8''",headers["Content-Disposition"])
            downloader.assert_called_once_with(857)

            status,headers,body=self.request(
                "/api/v1/odoo/quotations/857/pdf?file=/etc/passwd","test-key")
            self.assertEqual(status,404)
            self.assertNotEqual(body,pdf)
            downloader.assert_called_once_with(857)

    def test_download_failure_does_not_expose_odoo_details(self):
        with patch("gway_remote.api.mobile_odoo_quotations.download",
                   side_effect=RuntimeError("password=never-return-me")):
            status,headers,body=self.request("/api/v1/odoo/quotations/857/pdf","test-key")
        self.assertEqual(status,502)
        self.assertNotIn(b"never-return-me",body)
        self.assertIn(b"odoo_pdf_unavailable",body)


class OdooProxyRouteTests(unittest.TestCase):
    def test_only_bounded_pdf_path_is_exposed_by_nginx(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        config = (root / "deploy/nginx/gway-remote-locations.conf").read_text()
        self.assertIn('location ~ "^/api/v1/odoo/quotations/[1-9][0-9]{0,9}/pdf$"', config)
        route = config.split('location ~ "^/api/v1/odoo/quotations/', 1)[1].split("}", 2)[1]
        self.assertIn("limit_except GET { deny all; }", route)
        self.assertIn("proxy_set_header Authorization $http_authorization;", route)
        self.assertIn("proxy_pass http://10.90.0.2:8765;", route)
        self.assertIn("proxy_read_timeout 120s;", route)
