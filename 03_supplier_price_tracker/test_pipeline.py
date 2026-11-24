"""Tests: python -m unittest -v   (run make_samples.py first)"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pipeline as pl

SAMPLES = Path(__file__).parent / "samples"
FOLDERS = sorted(p for p in SAMPLES.iterdir() if p.is_dir())


class TransformTests(unittest.TestCase):
    def test_all_formats_normalised(self):
        df, warns = pl.transform(FOLDERS[0])
        self.assertEqual(warns, [])
        self.assertEqual(set(df.supplier), {"Lahore Paper House (Sample)", "Market Traders (Sample)",
                                            "Global Print Supply (Sample)"})
        self.assertTrue(df.sku.notna().all())
        self.assertTrue((df.price_usd > 0).all())

    def test_pkr_converted_to_usd(self):
        df, _ = pl.transform(FOLDERS[0])
        mkt = df[df.supplier == "Market Traders (Sample)"]
        self.assertTrue(mkt.price_usd.between(1, 100).all(), mkt.price_usd.tolist())

    def test_unmapped_and_missing_files_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "2026-01-01"
            folder.mkdir()
            (folder / "global_print_supply.json").write_text(json.dumps({
                "supplier": "X", "currency": "USD",
                "items": [{"sku": "NEW-123", "title": "?", "unit_price": 1.0},
                          {"sku": "GL-CTP-A1", "title": "plate", "unit_price": 7.0}]}))
            df, warns = pl.transform(folder)
            self.assertEqual(len(df), 1)
            self.assertTrue(any("unmapped supplier code NEW-123" in w for w in warns))
            self.assertTrue(any("missing lahore_paper_house.csv" in w for w in warns))

    def test_wrong_currency_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "g.json"
            p.write_text(json.dumps({"supplier": "X", "currency": "EUR", "items": []}))
            with self.assertRaises(ValueError):
                pl.load_global_json(p)


class AnalyseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(":memory:")
        cls.con.execute("""CREATE TABLE prices (snapshot TEXT, supplier TEXT, supplier_code TEXT, sku TEXT,
                           description TEXT, price_usd REAL, PRIMARY KEY (snapshot, supplier, supplier_code))""")
        for f in FOLDERS:
            pl.load(cls.con, pl.transform(f)[0])
        cls.res = pl.analyse(cls.con, threshold_pct=5)

    def test_jump_detected(self):
        a = self.res["alerts"]
        hit = a[(a.sku == "PAPER-80G-A4") & (a.supplier == "Lahore Paper House (Sample)")]
        self.assertEqual(len(hit), 1)
        self.assertGreater(hit.change_pct.iloc[0], 5)

    def test_drop_makes_new_cheapest(self):
        best = self.res["best"].set_index("sku")
        self.assertEqual(best.loc["INK-CYAN-1KG", "cheapest_supplier"], "Global Print Supply (Sample)")

    def test_reload_is_idempotent(self):
        before = self.con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
        pl.load(self.con, pl.transform(FOLDERS[-1])[0])
        after = self.con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
        self.assertEqual(before, after)

    def test_report_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = pl.write_report(self.res, Path(tmp))
            self.assertTrue(paths["xlsx"].exists() and paths["html"].exists())


if __name__ == "__main__":
    unittest.main()
