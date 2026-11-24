"""Tests: python -m unittest -v"""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import rag

HERE = Path(__file__).parent


class RetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunks = rag.load_chunks(HERE / "docs")
        cls.index = rag.BM25(cls.chunks)

    def test_chunking_by_section(self):
        self.assertEqual(len(self.chunks), 12)  # 4 docs x 3 sections
        self.assertTrue(all(c.text and c.title for c in self.chunks))

    def test_exact_question_retrieves_right_doc_first(self):
        top = self.index.search("standard payment terms for suppliers", 3)[0][0]
        self.assertEqual(top.doc, "supplier_policy")

    def test_glossary_fixes_paraphrase(self):
        q = "How long do we have to settle a vendor's bill?"
        plain = rag.BM25(self.chunks, use_glossary=False).search(q, 3)
        expanded = self.index.search(q, 3)
        self.assertNotIn("supplier_policy", [c.doc for c, _ in plain])
        self.assertEqual(expanded[0][0].doc, "supplier_policy")

    def test_offline_refuses_unanswerable(self):
        out = rag.ask("What is the annual marketing budget?", self.index, rag.OfflineAnswerer())
        self.assertFalse(out["answerable"])
        self.assertEqual(out["citations"], [])


class EvaluationTests(unittest.TestCase):
    def test_metrics_shape_and_ranges(self):
        index = rag.BM25(rag.load_chunks(HERE / "docs"))
        m = rag.evaluate(index, rag.OfflineAnswerer(), json.loads((HERE / "eval_set.json").read_text()))
        self.assertEqual(m["n"], 20)
        for k in ("hit_at_k", "mrr", "answer_accuracy", "citation_accuracy", "refusal_accuracy"):
            self.assertGreaterEqual(m[k], 0)
            self.assertLessEqual(m[k], 1)
        self.assertEqual(m["refusal_accuracy"], 1.0)


class FakeClient:
    def __init__(self, payload, stop_reason="end_turn"):
        self.calls = []
        resp = SimpleNamespace(stop_reason=stop_reason,
                               content=[SimpleNamespace(type="text", text=json.dumps(payload))])
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: (self.calls.append(kw), resp)[1]))


class ClaudeAnswererTests(unittest.TestCase):
    def setUp(self):
        self.index = rag.BM25(rag.load_chunks(HERE / "docs"))

    def test_request_is_grounded_and_structured(self):
        fake = FakeClient({"answer": "45 days from the invoice date.", "citations": ["supplier_policy#1"],
                           "answerable": True})
        out = rag.ask("What are the payment terms?", self.index, rag.ClaudeAnswerer(client=fake))
        req = fake.calls[0]
        self.assertEqual(req["model"], rag.DEFAULT_MODEL)
        self.assertIn("ONLY", req["system"])
        self.assertEqual(req["output_config"]["format"]["schema"], rag.ANSWER_SCHEMA)
        self.assertIn("[supplier_policy#", req["messages"][0]["content"])  # excerpts with ids are sent
        self.assertEqual(out["answer"], "45 days from the invoice date.")

    def test_refusal_is_handled(self):
        fake = FakeClient({}, stop_reason="refusal")
        out = rag.ask("anything", self.index, rag.ClaudeAnswerer(client=fake))
        self.assertFalse(out["answerable"])


if __name__ == "__main__":
    unittest.main()
