"""Odoo mobile API bridge: strict input, fixed CLIs, no credential disclosure."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote import mobile_odoo_quotations as odoo


class OdooMobileBridgeTests(unittest.TestCase):
    def test_search_is_read_only_and_bounded(self):
        calls = []
        def runner(executable, args, timeout=30):
            calls.append((executable, args))
            return json.dumps([
                {"id":857,"name":"S30958 Subestación 1","state":"draft",
                 "partner_id":[594,"Subestación 1"],"date_order":"2026-11-04 21:30:00",
                 "amount_total":364240.0,"currency_id":[33,"MXN"]},
                {"id":856,"name":"S30957","state":"sale",
                 "partner_id":[55,"Other"],"date_order":False,
                 "amount_total":1,"currency_id":[33,"MXN"]},
            ])
        with patch.object(odoo, "_run", side_effect=runner):
            result = odoo.search({"query":"Subestación", "limit":10})
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["quotations"][0]["name"], "S30958 Subestación 1")
        self.assertEqual(calls[0][0], "odoo-domain")
        self.assertEqual(calls[0][1][0:2], ["--model", "sale.order"])
        self.assertEqual(calls[0][1][-4:], ["--limit", "11", "--offset", "0"])
        domain = json.loads(calls[0][1][3])
        self.assertEqual(domain[1], ["state", "in", ["draft", "sent"]])
        self.assertEqual(domain[3], ["name", "ilike", "Subestación"])
        self.assertEqual(result["page"], 1)
        self.assertFalse(result["has_next"])

    def test_search_rejects_unbounded_input(self):
        cases = [
            {"query": "x"*81}, {"query": "bad\nnewline"}, {"query":3},
            {"limit":0}, {"limit":100}, {"limit":True},
            {"page":0}, {"page":1001}, {"page":True}, {"page":"2"},
            {"query":"","extra":1}, ["str"],
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                odoo.search(arguments)

    def test_newest_first_pagination_requests_one_extra_row(self):
        calls = []
        def runner(executable, args, timeout=30):
            calls.append(args)
            return json.dumps([
                {"id": 100 - i, "name": f"S{100-i}", "state": "draft",
                 "partner_id": [12, "Customer"], "date_order": "2026-10-01",
                 "amount_total": 100.0, "currency_id": [33, "MXN"]}
                for i in range(11)
            ])
        with patch.object(odoo, "_run", side_effect=runner):
            result = odoo.search({"page": 2, "limit": 10})
        self.assertEqual(result["page"], 2)
        self.assertEqual(result["limit"], 10)
        self.assertEqual(result["count"], 10)
        self.assertTrue(result["has_next"])
        self.assertEqual(len(result["quotations"]), 10)
        self.assertEqual(calls[0][-4:], ["--limit", "11", "--offset", "10"])
        self.assertEqual(json.loads(calls[0][3]), [["state", "in", ["draft", "sent"]]])
        self.assertEqual(calls[0][7], "date_order desc,id desc")

    def test_last_page_disables_next(self):
        with patch.object(odoo, "_run", return_value=json.dumps([
            {"id": 2, "name": "S2", "state": "sent",
             "partner_id": [12, "Customer"], "date_order": "2026-10-01",
             "amount_total": 100, "currency_id": [33, "MXN"]},
        ])):
            result = odoo.search({"page": 3, "limit": 10})
        self.assertEqual(result["count"], 1)
        self.assertFalse(result["has_next"])

    def test_download_rejects_bad_ids(self):
        for value in (0,-1,True,"857",10**11):
            with self.subTest(value=value), self.assertRaises(ValueError):
                odoo.download(value)

    def test_pdf_download_validates_bytes_and_cleans_files(self):
        output = b"%PDF-1.4\n" + b"a"*1500 + b"%%EOF"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"odoo-quotation-pdf").touch()
            def fake_runner(executable, args, timeout=30):
                self.assertEqual(executable, "odoo-quotation-pdf")
                self.assertEqual(args[:2], ["--order-id", "857"])
                self.assertEqual(args[2:4], ["--credential-profile","quotation"])
                (Path(args[-1])/"S30958 Subestación 1.pdf").write_bytes(output)
                return "{}"
            with patch.object(odoo, "ROOT", root), patch.object(odoo, "_run", side_effect=fake_runner):
                filename,data=odoo.download(857)
        self.assertEqual(filename, "S30958 Subestación 1.pdf")
        self.assertEqual(data, output)

    def test_fails_closed_on_bad_pdf(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"odoo-quotation-pdf").touch()
            def fake_runner(executable, args, timeout=30):
                (Path(args[-1])/"invoice.pdf").write_bytes(b"<html>" * 300)
                return "{}"
            with patch.object(odoo, "ROOT", root), patch.object(odoo, "_run", side_effect=fake_runner):
                with self.assertRaisesRegex(RuntimeError, "odoo_pdf_invalid"):
                    odoo.download(857)

    def test_headers_preserve_spanish_name(self):
        value=odoo.filename_headers("S30958 Subestación 1.pdf")
        self.assertIn("filename*=UTF-8''", value)
        self.assertIn("Subestaci%C3%B3n%201.pdf", value)
        self.assertNotIn("\r", value)
        self.assertNotIn("\n", value)
        with self.assertRaises(ValueError):
            odoo.filename_headers("bad\r\nname.pdf")

    def test_no_shell_invocation(self):
        class Done:
            returncode=0
            stdout="[]"
            stderr=""
        calls=[]
        def fake(command, **kwargs):
            calls.append((command,kwargs))
            return Done()
        with patch.object(odoo,"ROOT",Path("/mock/odoo/bin")), \
                patch.object(Path,"is_file",return_value=True), \
                patch.object(odoo.subprocess,"run",side_effect=fake):
            self.assertEqual(odoo._run("odoo-domain",["--model","sale.order"]),"[]")
        self.assertEqual(calls[0][0][0],"/mock/odoo/bin/odoo-domain")
        self.assertEqual(calls[0][1]["timeout"],30)
        self.assertNotIn("shell",calls[0][1])
