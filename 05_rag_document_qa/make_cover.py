import json, sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1]))
from cover_kit import render_cover
m = json.loads((HERE / "output" / "eval_results.json").read_text())
rows = []
for r in m["rows"][:6] + m["rows"][-4:]:
    rows.append([r["question"], ("Correct", "green") if r["correct"] else ("Miss", "red"), r["answer"][:60] or "-"])
print(render_cover(HERE / "images" / "cover_4x3.png", "Document Q&A (RAG) + Evaluation",
    "Policy docs → section chunks → retrieval → cited answers → measured accuracy",
    [("Retrieval hit@3", f"{m['hit_at_k']:.0%}", "green"), ("Answer accuracy", f"{m['answer_accuracy']:.0%}", "navy"),
     ("Citations correct", f"{m['citation_accuracy']:.0%}", "navy"), ("Refuses unknowns", f"{m['refusal_accuracy']:.0%}", "green")],
    f"Evaluation set: {m['n']} questions (incl. reworded and unanswerable)",
    [("Question", 640), ("Result", 170), ("Answer (extractive baseline)", 600)], rows,
    "Demo project · sample documents · Python BM25 + Claude API (grounded, structured output)"))
