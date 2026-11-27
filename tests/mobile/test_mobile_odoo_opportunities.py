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
                self.assertIn(["opportunity_id", "in", [7]], domain)
                return [{"id": 10, "name": "S00001", "state": "draft", "opportunity_id": [7, "Lead"]}]
            if model == "res.partner":
                return [{"id": 5, "name": "Example", "phone": "555", "street": "Example street"}]
            if model == "gelectriic.customer.vehicle":
                self.assertIn(["porsche_ticket", "=", "42"], domain)
                return [{"id": 1, "partner_id": [5, "Example"], "porsche_ticket": "42", "model": "Example", "vin": "TEST"}]
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
        for orders in ([{"state": "sent", "opportunity_id": [1, "Lead"]}], [{"state": "draft", "opportunity_id": [1, "Lead"]}, {"state": "sent", "opportunity_id": [1, "Lead"]}]):
            with patch.object(m, "_query", side_effect=[[{"id": 1}], orders]):
                if len(orders) == 1:
                    self.assertEqual(m.search({})["opportunities"], [])
                else:
                    with self.assertRaises(RuntimeError):
                        m.search({})

    def test_full_page_four_queries_and_exact_bindings(self):
        leads = [{"id": i, "name": f"Porsche #{100+i}: Example",
                  "partner_id": [5, "Example"]} for i in range(1, 31)]
        # One sent quote hides only its own opportunity, despite shared partner.
        orders = [{"id": 1, "opportunity_id": [1, "Lead"], "state": "sent"},
                  {"id": 2, "opportunity_id": [2, "Lead"], "state": "draft", "name": "S00002"}]
        vehicles = [{"id": i, "partner_id": [5, "Example"], "porsche_ticket": str(100+i),
                     "model": f"Model {i}", "vin": f"TEST{i}"} for i in range(2, 31)]
        vehicles.append({"id": 99, "partner_id": [5, "Example"], "porsche_ticket": "103",
                         "model": "Ambiguous", "vin": "OTHER"})
        evidence = {"2": {"partner_id": 5, "ticket": "102", "file_id": "example_file_12345"},
                    "3": {"partner_id": 5, "ticket": "102", "file_id": "example_file_12345"}}
        with patch.object(m, "_consent_bindings", return_value=evidence), patch.object(
                m, "_query", side_effect=[leads, orders, [{"id": 5, "name": "Example"}], vehicles]) as query:
            result = m.search({"limit": 30})
        self.assertEqual(query.call_count, 4)
        calls = [c.args for c in query.call_args_list]
        self.assertEqual([c[0] for c in calls],
                         ["crm.lead", "sale.order", "res.partner", "gelectriic.customer.vehicle"])
        self.assertEqual(calls[1][3], 31)
        self.assertEqual(calls[2][1], [["id", "in", [5]]])
        self.assertEqual(calls[3][3], 59)
        domain = calls[3][1]
        self.assertEqual(domain[:28], ["|"] * 28)
        self.assertEqual(domain[28:31], ["&", ["partner_id", "=", 5], ["porsche_ticket", "=", "102"]])
        self.assertNotIn(["porsche_ticket", "=", "101"], domain)
        self.assertEqual([r["id"] for r in result["opportunities"]], list(range(2, 31)))
        rows = result["opportunities"]
        self.assertEqual(rows[0]["quotation_name"], "S00002")
        self.assertEqual(rows[0]["vin"], "TEST2")
        self.assertIsNotNone(rows[0]["consent_url"])
        self.assertEqual(rows[1]["vin"], "")
        self.assertIsNone(rows[1]["consent_url"])
        self.assertFalse(result["has_next"])

    def test_cross_pair_response_and_truncation_fail_closed(self):
        leads = [{"id": 1, "name": "Porsche #42: Example", "partner_id": [5, "Example"]}]
        partner = [{"id": 5, "name": "Example"}]
        wrong = {"id": 1, "partner_id": [6, "Other"], "porsche_ticket": "42"}
        matching = {"id": 1, "partner_id": [5, "Example"], "porsche_ticket": "42"}
        for vehicles, code in (([wrong], "odoo_response_invalid"),
                               ([matching]*3, "odoo_vehicle_batch_incomplete")):
            with self.subTest(code=code), patch.object(m, "_query",
                    side_effect=[leads, [], partner, vehicles]):
                with self.assertRaisesRegex(RuntimeError, code):
                    m.search({})

    def test_wrong_quote_relation_fails_closed(self):
        with patch.object(m, "_query", side_effect=[[{"id": 7}],
                [{"state": "draft", "opportunity_id": [8, "Other"]}]]):
            with self.assertRaisesRegex(RuntimeError, "odoo_response_invalid"):
                m.search({})

    def test_empty_or_won_page_skips_related_queries(self):
        for leads in ([], [{"id": 1, "probability": 100}]):
            with patch.object(m, "_query", return_value=leads) as query:
                self.assertEqual(m.search({})["opportunities"], [])
                self.assertEqual(query.call_count, 1)
