"""Tests: python -m unittest -v"""
import unittest
from pathlib import Path

import pandas as pd

import mock_store
import sync as sy

STOCK = pd.read_csv(Path(__file__).parent / "data" / "stock.csv")


def expected_deduction(orders):
    d = {}
    for o in orders:
        if o["status"] == "paid":
            for ln in o["lines"]:
                d[ln["sku"]] = d.get(ln["sku"], 0) + ln["quantity"]
    return d


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.store = mock_store.Store(page_size=5, rate_limit_every=3)
        self.srv, self.url = self.store.serve()

    def tearDown(self):
        self.srv.shutdown()

    def client(self, token=mock_store.TOKEN):
        return sy.StoreClient(self.url, token, backoff=0.0)

    def test_pagination_and_retry_fetch_everything(self):
        c = self.client()
        stock, state, res = sy.sync(c, STOCK, {"updated_since": "", "applied": {}})
        self.assertEqual(res.fetched, len(self.store.orders))
        self.assertGreater(res.retries, 0)  # 429s were hit and retried

    def test_stock_deducted_correctly(self):
        stock, _, _ = sy.sync(self.client(), STOCK, {"updated_since": "", "applied": {}})
        exp = expected_deduction(self.store.orders)
        for r in stock.itertuples():
            start = STOCK.set_index("sku").loc[r.sku, "on_hand"]
            self.assertEqual(r.on_hand, start - exp.get(r.sku, 0), r.sku)

    def test_idempotent_replay(self):
        stock1, state, _ = sy.sync(self.client(), STOCK, {"updated_since": "", "applied": {}})
        state["updated_since"] = ""  # force a full re-fetch
        stock2, _, res = sy.sync(self.client(), stock1, state)
        self.assertEqual(res.applied, 0)
        self.assertEqual(res.skipped_duplicates, len(self.store.orders))  # every order already recorded
        pd.testing.assert_frame_equal(stock1, stock2)

    def test_cancellation_restocks(self):
        stock1, state, _ = sy.sync(self.client(), STOCK, {"updated_since": "", "applied": {}})
        o = next(o for o in self.store.orders if o["id"] == 1003)
        o["status"], o["updated_at"] = "cancelled", "2026-11-30T00:00:00+00:00"
        stock2, _, res = sy.sync(self.client(), stock1, state)
        self.assertEqual((res.fetched, res.restocked), (1, 1))
        for ln in o["lines"]:
            before = stock1.set_index("sku").loc[ln["sku"], "on_hand"]
            after = stock2.set_index("sku").loc[ln["sku"], "on_hand"]
            self.assertGreaterEqual(after - before, ln["quantity"])

    def test_unknown_sku_reported_not_crashing(self):
        _, _, res = sy.sync(self.client(), STOCK, {"updated_since": "", "applied": {}})
        self.assertEqual(res.unknown_skus, ["order 1010: UNKNOWN-SKU"])

    def test_bad_token(self):
        with self.assertRaises(sy.ApiError):
            sy.sync(self.client(token="wrong"), STOCK, {"updated_since": "", "applied": {}})

    def test_low_stock_flagged(self):
        stock, _, res = sy.sync(self.client(), STOCK, {"updated_since": "", "applied": {}})
        self.assertTrue((res.low_stock.on_hand <= res.low_stock.reorder_level).all())
        self.assertEqual(len(res.low_stock), int((stock.on_hand <= stock.reorder_level).sum()))


if __name__ == "__main__":
    unittest.main()
