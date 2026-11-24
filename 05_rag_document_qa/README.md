# Demo 05: Document Q&A (RAG) with an Evaluation Suite
> **Demo project built with sample policy documents. Not client work.**

**What it does:** answers staff questions from company documents, with citations, and refuses when the documents don't contain the answer. Docs are split by section, retrieved with BM25 plus a client-editable domain glossary, and answered either by Claude (grounded prompt + JSON-schema structured output: answer, citations, answerable) or by an offline extractive baseline.

**Evaluation (20 questions, including 5 reworded and 2 unanswerable), offline baseline:**

| Metric | Keyword search only | + domain glossary |
|---|---|---|
| Retrieval hit@3 | 83% | 100% |
| Answer accuracy | 72% | 83% |
| Citation accuracy | 72% | 94% |
| Correct refusals | 100% | 100% |

Honest notes: the glossary was written alongside this small development set, so a real project measures on a held-out test set. The remaining misses need reasoning, which the Claude mode is built for (not measured here: needs the client's API key).

**Tests:** `python -m unittest -v` (7 pass). **Run:** `python rag.py eval` or `python rag.py ask "..."`, plus `--mode claude` with a key.
