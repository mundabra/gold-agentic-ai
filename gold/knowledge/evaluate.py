"""Retrieval quality: for questions with a known right document, does it come back, and how high?

    gold knowledge eval sales-playbook --min-hit-rate 0.9

Each line of the questions file is {"question": ..., "expected_source": "file.md"} (optionally
"groups": [...] to search as a user). Hit rate is the share of questions whose expected document
is in the top k; MRR (mean reciprocal rank) rewards putting it first. This measures retrieval
only; whether the agent then answers well is a separate question.
"""

import json
from pathlib import Path

from gold.knowledge import Collection, Store, pipeline


def load(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


async def run(store: Store, collection: Collection, questions: str | None = None, k: int = 3,
              embedder: pipeline.Embedder = pipeline.embed) -> dict:
    path = questions or str(Path(collection.path) / "eval.jsonl")
    rows = []
    for q in load(path):
        groups = tuple(q["groups"]) if "groups" in q else None
        hits = await pipeline.search(store, collection.name, q["question"], k, groups, embedder)
        sources = [h.chunk.source for h in hits]
        rank = sources.index(q["expected_source"]) + 1 if q["expected_source"] in sources else None
        rows.append({"question": q["question"], "expected": q["expected_source"], "rank": rank, "got": sources})
    n = len(rows) or 1
    return {
        "collection": collection.name, "k": k, "questions": len(rows),
        "hit_rate": sum(r["rank"] is not None for r in rows) / n,
        "mrr": sum(1 / r["rank"] for r in rows if r["rank"]) / n,
        "rows": rows,
    }


def to_markdown(report: dict) -> str:
    lines = [f"# Retrieval: {report['collection']}", "",
             f"{report['questions']} questions · hit rate @{report['k']}: {report['hit_rate']:.0%} · MRR: {report['mrr']:.2f}"]
    misses = [r for r in report["rows"] if r["rank"] is None]
    if misses:
        lines += ["", "## Misses", ""]
        lines += [f"- {r['question']}: expected {r['expected']}, got {', '.join(r['got']) or 'nothing'}" for r in misses]
    return "\n".join(lines)
