"""Tests for the inventory reorder demo (sample data). Run: python -m unittest"""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

import reorder_report as rr


def _usage(sku, qtys, start=date(2026, 1, 1)):
    return [((start + timedelta(days=i)).isoformat(), sku, q) for i, q in enumerate(qtys)]


def _frames():
    # Constant usage of 10/day for 10 days -> avg 10, std 0, safety stock 0.
    # Lead time 5 -> reorder point 50, target stock 10 * (5 + 7) = 120.
    items = pd.DataFrame([
        ("A", "Urgent item", "Sup1", 2.0, 40, 0, 5, 25),     # position 40 <= 50, cover 4 < 5
        ("B", "Healthy item", "Sup1", 1.0, 200, 0, 5, 25),   # well stocked
        ("C", "On order item", "Sup2", 3.0, 30, 100, 5, 25),  # cover 3 < 5 but position 130
        ("D", "Unused item", "Sup2", 4.0, 5, 0, 5, 10),      # no usage at all
    ], columns=["sku", "name", "supplier", "unit_cost", "on_hand", "on_order",
                "lead_time_days", "moq"])
    rows = _usage("A", [10] * 10) + _usage("B", [10] * 10) + _usage("C", [10] * 10)
    usage = pd.DataFrame(rows, columns=["date", "sku", "qty_used"])
    return items, usage


class CalculateTests(unittest.TestCase):
    def setUp(self):
        items, usage = _frames()
        self.df = rr.calculate(items, usage).set_index("sku")

    def test_reorder_point_and_target(self):
        a = self.df.loc["A"]
        self.assertEqual(a.avg_daily, 10)
        self.assertEqual(a.safety_stock, 0)
        self.assertEqual(a.reorder_point, 50)
        self.assertEqual(a.target_stock, 120)

    def test_order_rounded_up_to_moq(self):
        # need = 120 - 40 = 80 -> 4 x MOQ 25 = 100
        self.assertEqual(self.df.loc["A", "order_qty"], 100)
        self.assertEqual(self.df.loc["A", "order_value"], 200.0)

    def test_statuses(self):
        self.assertEqual(self.df.loc["A", "status"], "URGENT")
        self.assertEqual(self.df.loc["B", "status"], "OK")
        self.assertEqual(self.df.loc["C", "status"], "WATCH")  # low cover, but already on order
        self.assertEqual(self.df.loc["D", "status"], "OK")

    def test_no_order_when_position_above_reorder_point(self):
        self.assertEqual(self.df.loc["B", "order_qty"], 0)
        self.assertEqual(self.df.loc["C", "order_qty"], 0)

    def test_unused_sku_has_no_cover_figure(self):
        self.assertEqual(self.df.loc["D", "avg_daily"], 0)
        self.assertTrue(pd.isna(self.df.loc["D", "days_of_cover"]))

    def test_missing_days_count_as_zero_usage(self):
        items = pd.DataFrame([("X", "x", "S", 1.0, 0, 0, 1, 1)],
                             columns=_frames()[0].columns)
        usage = pd.DataFrame([("2026-01-01", "X", 20), ("2026-01-03", "X", 20)],
                             columns=["date", "sku", "qty_used"])
        df = rr.calculate(items, usage)
        self.assertAlmostEqual(df.loc[0, "avg_daily"], 40 / 3)
        self.assertEqual(df.attrs["history_days"], 3)

    def test_safety_stock_grows_with_variability(self):
        items = pd.DataFrame([("V", "v", "S", 1.0, 0, 0, 4, 1)],
                             columns=_frames()[0].columns)
        usage = pd.DataFrame(_usage("V", [0, 20] * 5), columns=["date", "sku", "qty_used"])
        df = rr.calculate(items, usage)
        # std (population) = 10, Z = 1.65, sqrt(4) = 2 -> 33
        self.assertEqual(df.loc[0, "safety_stock"], 33)


class OutputTests(unittest.TestCase):
    def test_demo_data_is_deterministic(self):
        i1, u1 = rr.make_demo_data(seed=1)
        i2, u2 = rr.make_demo_data(seed=1)
        pd.testing.assert_frame_equal(i1, i2)
        pd.testing.assert_frame_equal(u1, u2)

    def test_workbook_and_email(self):
        df = rr.calculate(*_frames())
        with tempfile.TemporaryDirectory() as tmp:
            xlsx, html = Path(tmp) / "d.xlsx", Path(tmp) / "e.html"
            rr.build_workbook(df, xlsx)
            rr.build_email(df, html)
            wb = load_workbook(xlsx)
            self.assertEqual(wb.sheetnames, ["Dashboard", "Stock Status", "Draft POs", "Method"])
            self.assertIn("DEMO PROJECT", wb["Dashboard"]["A2"].value)
            self.assertEqual(wb["Draft POs"]["B2"].value, "A")  # only SKU A is ordered
            text = html.read_text(encoding="utf-8")
            self.assertIn("Demo project", text)
            self.assertIn("$200.00", text)
            wb.close()


if __name__ == "__main__":
    unittest.main()
