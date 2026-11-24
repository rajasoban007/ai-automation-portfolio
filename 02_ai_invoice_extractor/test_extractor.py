"""Tests: python -m unittest -v   (run make_samples.py first)"""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import extractor as ex

SAMPLES = Path(__file__).parent / "samples"


class OfflineExtractionTests(unittest.TestCase):
    def setUp(self):
        self.x = ex.OfflineExtractor()

    def test_layout_a_fields(self):
        d = self.x.extract(SAMPLES / "inv_lahore_paper_1041.pdf")
        self.assertEqual(d["supplier"], "Lahore Paper House (Sample)")
        self.assertEqual(d["invoice_number"], "LPH-1041")
        self.assertEqual(d["po_number"], "PO-2207")
        self.assertEqual(d["currency"], "USD")
        self.assertAlmostEqual(d["subtotal"], 1296.00)
        self.assertAlmostEqual(d["tax"], 220.32)
        self.assertAlmostEqual(d["total"], 1516.32)
        self.assertEqual(len(d["line_items"]), 2)
        date.fromisoformat(d["invoice_date"])  # valid ISO date

    def test_layout_b_and_c_labels(self):
        b = self.x.extract(SAMPLES / "inv_colortech_88.pdf")
        c = self.x.extract(SAMPLES / "inv_bindright_517.pdf")
        self.assertEqual(b["invoice_number"], "CT-0088")
        self.assertEqual(len(b["line_items"]), 3)
        self.assertEqual(c["invoice_number"], "BR-517")
        self.assertEqual(c["po_number"], "")


class ValidationTests(unittest.TestCase):
    def setUp(self):
        x = ex.OfflineExtractor()
        self.results = {p.name: ex.Result(p.name, x.extract(p)) for p in sorted(SAMPLES.glob("*.pdf"))}
        ex.validate(list(self.results.values()))

    def test_clean_invoice_auto_approved(self):
        self.assertEqual(self.results["inv_lahore_paper_1041.pdf"].status, "AUTO-APPROVED")
        self.assertEqual(self.results["inv_packline_77.pdf"].status, "AUTO-APPROVED")

    def test_math_error_flagged(self):
        r = self.results["inv_platemakers_2290.pdf"]
        self.assertTrue(any("!= subtotal + tax" in i for i in r.issues), r.issues)

    def test_missing_po_flagged(self):
        r = self.results["inv_bindright_517.pdf"]
        self.assertTrue(any("no PO number" in i for i in r.issues), r.issues)

    def test_duplicate_flagged_once(self):
        a = self.results["inv_colortech_88.pdf"]
        b = self.results["inv_colortech_88_resent.pdf"]
        dup = [r for r in (a, b) if any(i.startswith("DUPLICATE") for i in r.issues)]
        self.assertEqual(len(dup), 1)

    def test_unknown_supplier_and_future_date(self):
        r = ex.Result("x.pdf", {"supplier": "Unknown Ltd", "invoice_number": "1", "po_number": "PO-1",
                                "invoice_date": "2999-01-01", "subtotal": 10.0, "tax": 0.0, "total": 10.0,
                                "line_items": [{"description": "a", "quantity": 1, "unit_price": 10.0,
                                                "amount": 10.0}]})
        ex.validate([r])
        self.assertIn("supplier not in vendor master", r.issues)
        self.assertIn("invoice dated in the future", r.issues)


class FakeClient:
    """Stands in for anthropic.Anthropic(); records the request, returns a canned response."""

    def __init__(self, stop_reason="end_turn", payload=None):
        self.calls = []
        payload = payload or {"supplier": "ColorTech Supplies (Sample)", "invoice_number": "CT-0088",
                              "invoice_date": "2026-11-15", "po_number": "PO-2211", "currency": "USD",
                              "subtotal": 754.0, "tax": 0.0, "total": 754.0, "line_items": []}
        resp = SimpleNamespace(stop_reason=stop_reason,
                               content=[SimpleNamespace(type="text", text=json.dumps(payload))])
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self._resp = resp

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._resp


class ClaudeExtractorTests(unittest.TestCase):
    def test_request_shape(self):
        fake = FakeClient()
        d = ex.ClaudeExtractor(client=fake).extract(SAMPLES / "inv_colortech_88.pdf")
        req = fake.calls[0]
        self.assertEqual(req["model"], ex.DEFAULT_MODEL)
        self.assertEqual(req["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(req["output_config"]["format"]["schema"], ex.INVOICE_SCHEMA)
        self.assertEqual(req["fallbacks"], "default")
        doc = req["messages"][0]["content"][0]
        self.assertEqual(doc["type"], "document")
        self.assertEqual(doc["source"]["media_type"], "application/pdf")
        self.assertEqual(d["invoice_number"], "CT-0088")
        self.assertEqual(d["_confidence"], "model")

    def test_refusal_raises(self):
        with self.assertRaises(ex.ExtractionError):
            ex.ClaudeExtractor(client=FakeClient(stop_reason="refusal")).extract(
                SAMPLES / "inv_colortech_88.pdf")

    def test_schema_is_strict(self):
        self.assertFalse(ex.INVOICE_SCHEMA["additionalProperties"])
        self.assertEqual(set(ex.INVOICE_SCHEMA["required"]), set(ex.INVOICE_SCHEMA["properties"]))


class EndToEndTests(unittest.TestCase):
    def test_run_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = ex.run(SAMPLES, ex.OfflineExtractor(), Path(tmp))
            self.assertEqual(len(results), 6)
            for name in ("invoices.csv", "line_items.csv", "review_queue.csv", "invoice_register.xlsx"):
                self.assertTrue((Path(tmp) / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
