"""Quality gate: how often does a model's SQL return the same answer as a known-correct query?

Every stage (hosted API, fine-tuned model, self-hosted inference) is judged by
the same questions, so a model swap is a measured decision, not a hunch.

Two ways to run it:

  gold eval --model M       the SQL step alone, in two arms:
                              bare         the question and the schema, nothing else
                              definitions  the same, plus the matching glossary definitions
  gold eval --system URL    the whole running system: ask GOLD each question and grade
                            the query its agents actually ran (arm: system)
"""

import asyncio
import json

import httpx
import statistics
import time
from datetime import datetime
from pathlib import Path

from gold import config, db, sql_model

ARMS = ("bare", "definitions")


def _norm(value):
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, (int, float)):
        return f"{round(float(value), 2):.2f}"
    try:
        return f"{round(float(value), 2):.2f}"
    except (TypeError, ValueError):
        return str(value).strip()


def _tokens(row: list) -> list[str]:
    """A row as comparable tokens: numbers to two decimals, text as lower-case words.
    So "Jane Peacock" in one column matches "Jane" and "Peacock" in two."""
    out = []
    for value in row:
        norm = _norm(value)
        if isinstance(value, str) and norm == value.strip():
            out.extend(norm.lower().split())
        else:
            out.append(norm)
    return out


def _covers(have: list[str], want: list[str]) -> bool:
    return all(have.count(v) >= want.count(v) for v in set(want))


def same_result(expected: list[list], actual: list[list]) -> bool:
    """Execution match: same number of rows, and each expected row's values appear in its own actual row.
    Column order and extra columns in the actual result are tolerated."""
    if len(expected) != len(actual):
        return False
    have = [_tokens(row) for row in actual]
    want = [_tokens(row) for row in expected]
    options = [[j for j, h in enumerate(have) if _covers(h, w)] for w in want]
    match: dict[int, int] = {}  # actual row -> expected row

    def assign(i: int, seen: set[int]) -> bool:  # augmenting path (bipartite matching)
        for j in options[i]:
            if j not in seen:
                seen.add(j)
                if j not in match or assign(match[j], seen):
                    match[j] = i
                    return True
        return False

    return all(assign(i, set()) for i in range(len(want)))


def definitions_for(question: str) -> str:
    return "\n".join(
        f"- {m['term']}: {m['definition']}" + (f" Hint: {m['sql_hint']}" if m["sql_hint"] else "")
        for m in db.search_glossary(question)
    )


def load_questions(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


async def _score(q: dict, arm: str, model: str, schema: str, expected: list[list], sem: asyncio.Semaphore) -> dict:
    async with sem:
        defs = definitions_for(q["question"]) if arm == "definitions" else ""
        started = time.perf_counter()
        try:
            sql, usage = await sql_model.generate(q["question"], defs, schema, model=model)
        except Exception as exc:
            return {"id": q["id"], "arm": arm, "question": q["question"], "correct": False, "error": f"model error: {exc}", "sql": "",
                    "latency_s": time.perf_counter() - started, "tokens": 0}
        latency = time.perf_counter() - started
    try:
        actual = (await asyncio.to_thread(db.run_query, sql, 1000))["rows"]
        correct, error = same_result(expected, actual), None
    except Exception as exc:
        correct, error = False, str(exc).strip().splitlines()[0]
    return {"id": q["id"], "arm": arm, "question": q["question"], "correct": correct, "error": error,
            "sql": sql, "latency_s": round(latency, 3), "tokens": usage.total_tokens}


async def run(questions_path: str, model: str | None = None, arms=ARMS, concurrency: int = 4) -> dict:
    model = model or config.SQL_MODEL
    questions = load_questions(questions_path)
    schema = db.describe_schema() if config.SQL_INCLUDE_SCHEMA else ""
    expected = {q["id"]: db.run_query(q["sql"], 1000)["rows"] for q in questions}
    sem = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(*[_score(q, a, model, schema, expected[q["id"]], sem) for a in arms for q in questions])
    summary = {}
    for arm in arms:
        rows = [r for r in results if r["arm"] == arm]
        summary[arm] = {
            "accuracy": round(sum(r["correct"] for r in rows) / len(rows), 3),
            "correct": sum(r["correct"] for r in rows),
            "total": len(rows),
            "p50_latency_s": round(statistics.median(r["latency_s"] for r in rows), 2),
            "avg_tokens": round(statistics.mean(r["tokens"] for r in rows)),
        }
    return {"model": model, "questions": questions_path, "when": datetime.now().isoformat(timespec="seconds"),
            "summary": summary, "results": results}


async def _ask_system(q: dict, url: str, expected: list[list], sem: asyncio.Semaphore, client: httpx.AsyncClient) -> dict:
    async with sem:
        started = time.perf_counter()
        try:
            resp = await client.post(f"{url.rstrip('/')}/api/ask", json={"question": q["question"]})
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:
            return {"id": q["id"], "arm": "system", "question": q["question"], "correct": False,
                    "error": f"request failed: {exc}", "sql": "", "latency_s": time.perf_counter() - started, "tokens": 0}
    runs = [step for call in body.get("calls", []) for step in call.get("steps", []) if step.get("tool") == "run_sql"]
    last = runs[-1] if runs else None
    output = last.get("output") if last else None
    sql = (last.get("input") or {}).get("sql", "") if last else ""
    failures = [f"{c['agent']}: {c['failure']}" for c in body.get("calls", []) if c.get("failure")]
    if isinstance(output, dict) and "rows" in output:
        correct, error = same_result(expected, output["rows"]), None
    else:
        correct = False
        error = (output or {}).get("reason") if isinstance(output, dict) else "; ".join(failures) or "no query was run"
    return {"id": q["id"], "arm": "system", "question": q["question"], "correct": correct, "error": error,
            "sql": sql, "latency_s": round(time.perf_counter() - started, 3), "tokens": body.get("usage", {}).get("total_tokens", 0)}


async def run_system(questions_path: str, url: str, concurrency: int = 2) -> dict:
    """Grade the whole running system: orchestrator, agents, glossary, SQL model and tools."""
    questions = load_questions(questions_path)
    expected = {q["id"]: db.run_query(q["sql"], 1000)["rows"] for q in questions}
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=600) as client:
        results = await asyncio.gather(*[_ask_system(q, url, expected[q["id"]], sem, client) for q in questions])
    rows = list(results)
    summary = {"system": {
        "accuracy": round(sum(r["correct"] for r in rows) / len(rows), 3),
        "correct": sum(r["correct"] for r in rows),
        "total": len(rows),
        "p50_latency_s": round(statistics.median(r["latency_s"] for r in rows), 2),
        "avg_tokens": round(statistics.mean(r["tokens"] for r in rows)),
    }}
    return {"model": f"GOLD at {url}", "questions": questions_path, "when": datetime.now().isoformat(timespec="seconds"),
            "summary": summary, "results": rows}


def to_markdown(report: dict) -> str:
    lines = [f"# GOLD evaluation: `{report['model']}`", "", f"{report['when']} · {report['questions']}", "",
             "| Arm | Accuracy | Correct | p50 latency | Avg tokens |", "|---|---|---|---|---|"]
    for arm, s in report["summary"].items():
        lines.append(f"| {arm} | {s['accuracy']:.0%} | {s['correct']}/{s['total']} | {s['p50_latency_s']} s | {s['avg_tokens']} |")
    lines += ["", "## Misses", ""]
    misses = [r for r in report["results"] if not r["correct"]]
    if not misses:
        lines.append("None.")
    for r in misses:
        lines += [f"**{r['id']} ({r['arm']})**: {r['question']}", "", f"```sql\n{r['sql']}\n```"]
        if r["error"]:
            lines.append(f"Error: {r['error']}")
        lines.append("")
    return "\n".join(lines)


def save(report: dict, out_dir: str = "results") -> Path:
    folder = Path(out_dir) / f"eval-{datetime.now():%Y%m%d-%H%M%S}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (folder / "report.md").write_text(to_markdown(report), encoding="utf-8")
    return folder
