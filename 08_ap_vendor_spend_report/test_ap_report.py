"""Tests: python -m unittest -v  (run inside this folder; uses the live mock HTTP server)"""
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

import ap_report as ap
import mock_ledger as ml


class APReportTests(unittest.TestCase):
    def setUp(self):
        self.ledger = ml.Ledger(page_size=7, rate_limit_every=5, token_ttl_calls=3)
        self.srv, self.url = self.ledger.serve()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def client(self, refresh=ml.REFRESH_TOKEN):
        return ap.LedgerClient(self.url, ml.CLIENT_ID, ml.CLIENT_SECRET, refresh, backoff=0.0)

    def test_full_pull_survives_pagination_rate_limits_and_token_expiry(self):
        c = self.client()
        _, _, res = ap.run(c, {}, ml.AS_OF)
        self.assertEqual(res.fetched, 36)
        self.assertGreater(c.retries, 0)
        self.assertGreater(c.refreshes, 1)  # access token expired mid-run and was refreshed

    def test_first_run_reconciles_to_ledger_control(self):
        _, _, res = ap.run(self.client(), {}, ml.AS_OF)
        self.assertTrue(res.reconciled)
        self.assertAlmostEqual(res.open_ap, self.ledger.control_total(), places=2)

    def test_incremental_run_only_fetches_changes_and_never_duplicates(self):
        c = self.client()
        state, _, first = ap.run(c, {}, ml.AS_OF)
        state, _, again = ap.run(c, state, ml.AS_OF)
        self.assertEqual(again.fetched, 0)
        bill = next(b for b in self.ledger.bills if b["Balance"] > 100 and b["VendorRef"] != "V9")
        paid = bill["Balance"]
        self.ledger.update_bill(bill["Id"], Balance=0.0)  # bill paid in the ledger
        state, _, after = ap.run(c, state, ml.AS_OF)
        self.assertEqual(after.fetched, 1)
        self.assertEqual(after.total_bills, 36)
        self.assertAlmostEqual(after.open_ap, first.open_ap - paid, places=2)
        self.assertTrue(after.reconciled)

    def test_duplicate_bill_and_unknown_vendor_are_flagged(self):
        _, frames, _ = ap.run(self.client(), {}, ml.AS_OF)
        issues = " | ".join(frames["Exceptions"]["Issue"])
        self.assertIn("Duplicate bill number", issues)
        self.assertIn("Unknown vendor V9", issues)
        self.assertNotIn("V9", list(frames["Vendor Spend"].index))

    def test_stale_bill_in_state_breaks_reconciliation(self):
        c = self.client()
        state, _, _ = ap.run(c, {}, ml.AS_OF)
        gone = next(b for b in self.ledger.bills if b["Balance"] > 0 and b["VendorRef"] != "V9")
        self.ledger.bills.remove(gone)  # voided in the ledger; voids don't show in "changed since"
        _, frames, res = ap.run(c, state, ml.AS_OF)
        self.assertFalse(res.reconciled)
        self.assertIn("Do not send report", " ".join(frames["Exceptions"]["Action"]))

    def test_aging_buckets(self):
        due = date(2026, 10, 1)
        self.assertEqual(ap.aging_bucket(date(2026, 12, 1), due), "Not yet due")
        self.assertEqual(ap.aging_bucket(due, date(2026, 10, 20)), "1-30 days overdue")
        self.assertEqual(ap.aging_bucket(due, date(2026, 11, 15)), "31-60 days overdue")
        self.assertEqual(ap.aging_bucket(due, date(2027, 3, 1)), "90+ days overdue")

    def test_bad_refresh_token_raises_auth_error(self):
        with self.assertRaises(ap.AuthError):
            ap.run(self.client(refresh="wrong"), {}, ml.AS_OF)

    def test_excel_report_has_all_sheets(self):
        c = self.client()
        _, frames, res = ap.run(c, {}, ml.AS_OF)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.xlsx"
            ap.write_report(p, frames, res, ml.AS_OF, c)
            sheets = pd.ExcelFile(p).sheet_names
            summary = pd.read_excel(p, sheet_name="Summary")
        self.assertEqual(sheets, ["Summary", "Vendor Spend", "AP Aging", "Exceptions"])
        self.assertEqual(summary.set_index("Item").loc["Reconciled", "Value"], "YES")


if __name__ == "__main__":
    unittest.main()
