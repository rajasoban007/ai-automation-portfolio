"""Tests: python -m unittest -v   (run make_dataset.py first)"""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import harness as h

DATA = json.loads((Path(__file__).parent / "dataset.json").read_text())


class FakeClaude:
    """Returns gold answers (or a wrong date) with fixed token usage, like a real model would."""

    def __init__(self, wrong_date_ids=(), stop_reason="end_turn"):
        self.wrong, self.stop_reason, self.calls = set(wrong_date_ids), stop_reason, []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        row = next(r for r in DATA if r["text"] in kw["messages"][0]["content"])
        gold = dict(row["gold"])
        if row["id"] in self.wrong:
            gold["delivery_date"] = "1999-01-01"
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="text", text=json.dumps(gold))],
                               usage=SimpleNamespace(input_tokens=200, output_tokens=50))


class HarnessTests(unittest.TestCase):
    def test_perfect_candidate_scores_100(self):
        r = h.run_candidate(h.ClaudeCandidate("claude-haiku-5-5", client=FakeClaude()), DATA)
        self.assertEqual(r["exact_match"], 1.0)
        self.assertEqual(r["failures"], [])

    def test_field_level_scoring_and_failure_list(self):
        r = h.run_candidate(h.ClaudeCandidate("claude-sonnet-5-5", client=FakeClaude(wrong_date_ids={0, 5})), DATA)
        self.assertAlmostEqual(r["field_accuracy"]["delivery_date"], 13 / 15)
        self.assertEqual(r["field_accuracy"]["supplier"], 1.0)
        self.assertEqual([f["id"] for f in r["failures"]], [0, 5])
        self.assertEqual(r["failures"][0]["wrong_fields"], ["delivery_date"])

    def test_cost_uses_token_usage_and_price_table(self):
        r = h.run_candidate(h.ClaudeCandidate("claude-opus-5-5", client=FakeClaude()), DATA)
        expected = (200 * 4.00 + 50 * 20.00) / 1e6 * 1000  # per 1k docs
        self.assertAlmostEqual(r["cost_per_1k_docs_usd"], round(expected, 4))

    def test_request_uses_structured_output(self):
        fake = FakeClaude()
        h.ClaudeCandidate("claude-haiku-5-5", client=fake).predict(DATA[0]["text"])
        self.assertEqual(fake.calls[0]["output_config"]["format"]["schema"], h.SCHEMA)

    def test_refusal_counts_as_failure(self):
        r = h.run_candidate(h.ClaudeCandidate("claude-haiku-5-5", client=FakeClaude(stop_reason="refusal")), DATA[:3])
        self.assertEqual(r["exact_match"], 0.0)

    def test_baselines_and_leaderboard_order(self):
        results = [h.run_candidate(c, DATA) for c in (h.KeywordBaseline(), h.RegexBaseline())]
        board = h.leaderboard(results)
        self.assertLess(board.index("regex-baseline"), board.index("keyword-baseline"))
        self.assertEqual(results[0]["field_accuracy"]["delivery_date"], 0.0)

    def test_date_normalisation(self):
        self.assertEqual(h.parse_date("04/01/2027"), "2027-01-04")
        self.assertEqual(h.parse_date("January 4, 2027"), "2027-01-04")
        self.assertEqual(h.parse_date("4 Jan 2027"), "2027-01-04")


if __name__ == "__main__":
    unittest.main()
