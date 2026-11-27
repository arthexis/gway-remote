import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from gway_remote import mobile_odoo_opportunities as m

class OpportunityTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(m, '_consent_bindings', return_value={})
        p.start()
        self.addCleanup(p.stop)

    def test_consent_identity(self):
        evidence = {'7': {'partner_id': 5, 'ticket': '42', 'file_id': 'example_file_12345'}}
        self.assertEqual(m._consent_url(evidence, 7, 5, '42'), 'https://drive.google.com/file/d/example_file_12345/view')
        for args in ((8, 5, '42'), (7, 6, '42'), (7, 5, '43'), (7, 5, None)):
            self.assertIsNone(m._consent_url(evidence, *args))
        evidence['7']['file_id'] = 'https://example.invalid'
        self.assertIsNone(m._consent_url(evidence, 7, 5, '42'))

    def test_request_type(self):
        self.assertEqual(m._request_type("<p>Urgente - Nueva - Model</p>"), "new")
        self.assertEqual(m._request_type("Alta - Desmontado y Montado - Model"), "remove_and_install")
        self.assertEqual(m._request_type("unverified Nueva"), "")

    def test_pagination_and_native_link(self):
        def query(model, domain, fields, limit, offset=0):
            if model == "crm.lead":
                self.assertEqual((limit, offset), (2, 1))
                return [{"id": 7, "name": "Porsche #42: Example", "stage_id": [99, "Pre-Check"], "priority": "3", "description": "Urgente - Nueva - Model", "partner_id": [5, "Example"]}, {"id": 8}]
            if model == "sale.order":
                self.assertIn(["opportunity_id", "=", 7], domain)
                return [{"id": 10, "name": "S00001", "state": "draft"}]
            if model == "res.partner":
                return [{"id": 5, "name": "Example", "phone": "555", "street": "Example street"}]
            if model == "gelectriic.customer.vehicle":
                self.assertIn(["porsche_ticket", "=", "42"], domain)
                return [{"id": 1, "model": "Example", "vin": "TEST"}]
            raise AssertionError(model)
        with patch.object(m, "_query", side_effect=query):
            result = m.search({"limit": 1, "page": 2})
        self.assertTrue(result["has_next"])
        row = result["opportunities"][0]
        self.assertEqual((row["id"], row["quotation_name"], row["request_type"]), (7, "S00001", "new"))
        self.assertIsNone(row["consent_url"])
        self.assertEqual((row["stage_id"], row["stage_name"]), (99, "Pre-Check"))

    def test_ticket_marker_and_stage_are_dynamic(self):
        lead = {"name": "Example", "description": "<p>Porsche Ticket: 123<br/>Inspection</p>",
                "stage_id": [81, "Pre-Check"]}
        self.assertEqual(m._porsche_ticket(lead), "123")
        self.assertEqual(m._stage_name(lead), "Pre-Check")
        lead["name"] = "Porsche #124: Example"
        self.assertIsNone(m._porsche_ticket(lead))
        self.assertIsNone(m._stage_name({"stage_id": False}))

    def test_invalid_pagination(self):
        for args in ({"limit": 31}, {"page": True}, {"page": 0}, {"domain": []}):
            with self.assertRaises(ValueError):
                m.search(args)

    def test_sent_and_ambiguous(self):
        for orders in ([{"state": "sent"}], [{"state": "draft"}, {"state": "sent"}]):
            with patch.object(m, "_query", side_effect=[[{"id": 1}], orders]):
                if len(orders) == 1:
                    self.assertEqual(m.search({})["opportunities"], [])
                else:
                    with self.assertRaises(RuntimeError):
                        m.search({})
