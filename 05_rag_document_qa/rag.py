"""
DEMO PROJECT (sample documents) - Document Q&A (RAG) with an evaluation suite.

  docs/*.md -> section chunks -> BM25 retrieval -> answer with citations -> evaluation

Answer back-ends:
  * ClaudeAnswerer  - Anthropic Messages API (official SDK) with a JSON-schema structured
                      output: {"answer", "citations", "answerable"}. Grounded: it must
                      answer only from the retrieved chunks and say when it can't.
                      Needs `pip install anthropic` + the client's own API key.
  * OfflineAnswerer - extractive baseline (best-matching sentence) so the demo and tests
                      run with no key and no cost.

Evaluation (eval_set.json): retrieval hit@k and MRR, answer correctness (key-phrase
match), citation accuracy, and correct refusal on questions the documents don't answer.

Usage:
    python rag.py ask "How long do suppliers get to report defects?"
    python rag.py eval                 # offline evaluation report
    python rag.py eval --mode claude   # live evaluation (client key required)
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT_MODEL = "claude-opus-5-5"
STOP = set("a an and are as at be by do does for from how if in is it its of on or the to what when which who why with within must may".split())


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9%]+", text.lower()) if t not in STOP]


# Domain glossary for query expansion. In a client build this lives in a config file the
# client's team edits (their own jargon -> the words used in their documents).
GLOSSARY = {
    "vendor": ["supplier", "suppliers"], "vendors": ["supplier", "suppliers"],
    "bill": ["invoice", "payment"], "settle": ["payment", "terms"], "pay": ["payment"],
    "signs": ["approval", "approved"], "sign": ["approval", "approved"],
    "recalculate": ["reviewed"], "wet": ["defective", "moisture"], "torn": ["defective"],
    "raises": ["increase"], "prices": ["price"], "rupees": ["pkr"],
}


def expand(query_tokens: list[str]) -> list[str]:
    out = list(query_tokens)
    for t in query_tokens:
        out += GLOSSARY.get(t, [])
    return out


@dataclass
class Chunk:
    id: str
    doc: str
    title: str
    text: str


def load_chunks(doc_dir: Path) -> list[Chunk]:
    """Split markdown docs into one chunk per '## ' section (keeps context together)."""
    chunks = []
    for path in sorted(doc_dir.glob("*.md")):
        current, buf = None, []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                if current:
                    chunks.append(Chunk(f"{path.stem}#{len(chunks)}", path.stem, current, " ".join(buf).strip()))
                current, buf = line[3:].strip(), []
            elif current and line.strip():
                buf.append(line.strip())
        if current:
            chunks.append(Chunk(f"{path.stem}#{len(chunks)}", path.stem, current, " ".join(buf).strip()))
    return chunks


class BM25:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75, use_glossary: bool = True):
        self.chunks, self.k1, self.b, self.use_glossary = chunks, k1, b, use_glossary
        self.docs = [tokens(c.title + " " + c.text) for c in chunks]
        self.avgdl = sum(map(len, self.docs)) / len(self.docs)
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 3) -> list[tuple[Chunk, float]]:
        q = expand(tokens(query)) if self.use_glossary else tokens(query)
        scores = []
        for chunk, d in zip(self.chunks, self.docs):
            tf = Counter(d)
            s = sum(self.idf.get(t, 0) * tf[t] * (self.k1 + 1) /
                    (tf[t] + self.k1 * (1 - self.b + self.b * len(d) / self.avgdl)) for t in q if t in tf)
            scores.append((chunk, s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return [x for x in scores[:k] if x[1] > 0]


ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
        "answerable": {"type": "boolean"},
    },
    "required": ["answer", "citations", "answerable"],
    "additionalProperties": False,
}
SYSTEM = ("You answer questions using ONLY the provided document excerpts. Cite the excerpt ids "
          "you used. If the excerpts do not contain the answer, set answerable=false and say so. "
          "Never use outside knowledge.")


class ClaudeAnswerer:
    def __init__(self, client=None, model: str = DEFAULT_MODEL):
        if client is None:
            import anthropic  # lazy: offline mode needs no SDK
            client = anthropic.Anthropic()
        self.client, self.model = client, model

    def build_request(self, question: str, hits: list[tuple[Chunk, float]]) -> dict:
        context = "\n\n".join(f"[{c.id}] {c.title}: {c.text}" for c, _ in hits) or "(no excerpts)"
        return dict(
            model=self.model, max_tokens=2000, system=SYSTEM,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}},
            messages=[{"role": "user", "content": f"Excerpts:\n{context}\n\nQuestion: {question}"}])

    def answer(self, question: str, hits) -> dict:
        r = self.client.beta.messages.create(**self.build_request(question, hits))
        if r.stop_reason == "refusal":
            return {"answer": "", "citations": [], "answerable": False, "error": "declined"}
        text = next(b.text for b in r.content if getattr(b, "type", "") == "text")
        return json.loads(text)


class OfflineAnswerer:
    """Extractive baseline: returns the sentence with the most query-term overlap."""
    MIN_OVERLAP = 2

    def answer(self, question: str, hits) -> dict:
        q = set(expand(tokens(question)))
        best, best_score, best_id = "", 0, None
        for chunk, _ in hits:
            for sent in re.split(r"(?<=[.!?])\s+", chunk.text):
                score = len(q & set(tokens(sent + " " + chunk.title)))
                if score > best_score:
                    best, best_score, best_id = sent, score, chunk.id
        if best_score < self.MIN_OVERLAP:
            return {"answer": "The documents don't cover this.", "citations": [], "answerable": False}
        return {"answer": best, "citations": [best_id], "answerable": True}


def ask(question: str, index: BM25, answerer, k: int = 3) -> dict:
    hits = index.search(question, k)
    out = answerer.answer(question, hits)
    out["retrieved"] = [c.id for c, _ in hits]
    return out


def evaluate(index: BM25, answerer, eval_set: list[dict], k: int = 3) -> dict:
    rows = []
    for item in eval_set:
        res = ask(item["question"], index, answerer, k)
        retrieved_docs = [r.split("#")[0] for r in res["retrieved"]]
        if item["answerable"]:
            rank = retrieved_docs.index(item["doc"]) + 1 if item["doc"] in retrieved_docs else None
            correct = res["answerable"] and all(p.lower() in res["answer"].lower() for p in item["key_phrases"])
            cited_ok = any(c.split("#")[0] == item["doc"] for c in res["citations"])
        else:
            rank, cited_ok = None, None
            correct = not res["answerable"]
        rows.append({"question": item["question"], "answerable": item["answerable"], "rank": rank,
                     "correct": correct, "citation_ok": cited_ok, "answer": res["answer"]})
    ans = [r for r in rows if r["answerable"]]
    unans = [r for r in rows if not r["answerable"]]
    return {
        "n": len(rows),
        "hit_at_k": sum(r["rank"] is not None for r in ans) / len(ans),
        "mrr": sum(1 / r["rank"] for r in ans if r["rank"]) / len(ans),
        "answer_accuracy": sum(r["correct"] for r in ans) / len(ans),
        "citation_accuracy": sum(bool(r["citation_ok"]) for r in ans) / len(ans),
        "refusal_accuracy": (sum(r["correct"] for r in unans) / len(unans)) if unans else None,
        "rows": rows,
    }


def write_report(metrics: dict, out: Path, mode: str):
    out.mkdir(exist_ok=True)
    (out / "eval_results.json").write_text(json.dumps(metrics, indent=1), encoding="utf-8")
    lines = [f"# RAG evaluation report ({mode} mode) - demo, sample documents", "",
             "| Metric | Score |", "|---|---|"]
    for key in ("hit_at_k", "mrr", "answer_accuracy", "citation_accuracy", "refusal_accuracy"):
        lines.append(f"| {key} | {metrics[key]:.0%} |" if metrics[key] is not None else f"| {key} | n/a |")
    lines += ["", "| Question | Correct | Answer |", "|---|---|---|"]
    lines += [f"| {r['question']} | {'yes' if r['correct'] else 'NO'} | {r['answer'][:90]} |" for r in metrics["rows"]]
    (out / "eval_report.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["ask", "eval"])
    ap.add_argument("question", nargs="?")
    ap.add_argument("--mode", choices=["offline", "claude"], default="offline")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    a = ap.parse_args()
    index = BM25(load_chunks(HERE / "docs"))
    answerer = OfflineAnswerer() if a.mode == "offline" else ClaudeAnswerer(model=a.model)
    if a.cmd == "ask":
        print(json.dumps(ask(a.question, index, answerer), indent=1))
    else:
        m = evaluate(index, answerer, json.loads((HERE / "eval_set.json").read_text(encoding="utf-8")))
        write_report(m, HERE / "output", a.mode)
        for key in ("hit_at_k", "mrr", "answer_accuracy", "citation_accuracy", "refusal_accuracy"):
            print(f"{key:18} {m[key]:.0%}")


if __name__ == "__main__":
    main()
