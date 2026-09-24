"""Performance check for the SQL model endpoint: latency, throughput and cost at a few concurrency levels.

Uses the real GOLD prompt (question + schema), so the numbers reflect production
traffic. It is deliberately small. For deep serving benchmarks (time to first
token, inter-token latency, saturation curves) use a dedicated tool such as
NVIDIA AIPerf against the same endpoint.
"""

import asyncio
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

from gold import config, db, sql_model
from gold.evaluate import load_questions


def _pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1)))]


async def _level(model: str, prompts: list[str], schema: str, concurrency: int, requests: int) -> dict:
    sem = asyncio.Semaphore(concurrency)
    samples: list[dict] = []

    async def one(i: int) -> None:
        async with sem:
            started = time.perf_counter()
            try:
                _, usage = await sql_model.generate(prompts[i % len(prompts)], "", schema, model=model)
                samples.append({"s": time.perf_counter() - started, "in": usage.input_tokens, "out": usage.output_tokens})
            except Exception as exc:
                samples.append({"s": time.perf_counter() - started, "error": str(exc)})

    wall = time.perf_counter()
    await asyncio.gather(*[one(i) for i in range(requests)])
    wall = time.perf_counter() - wall
    ok = [s for s in samples if "error" not in s]
    lat = [s["s"] for s in ok] or [0.0]
    return {
        "concurrency": concurrency,
        "requests": requests,
        "errors": requests - len(ok),
        "p50_s": round(_pct(lat, 50), 3),
        "p95_s": round(_pct(lat, 95), 3),
        "requests_per_s": round(len(ok) / wall, 2),
        "output_tokens_per_s": round(sum(s["out"] for s in ok) / wall, 1),
        "avg_input_tokens": round(statistics.mean(s["in"] for s in ok)) if ok else 0,
        "avg_output_tokens": round(statistics.mean(s["out"] for s in ok)) if ok else 0,
    }


async def run(questions_path: str, model: str | None = None, levels=(1, 4, 8), requests: int = 16,
              price_in: float = 0.0, price_out: float = 0.0) -> dict:
    """price_in / price_out are per million tokens; leave at 0 for self-hosted models."""
    model = model or config.SQL_MODEL
    prompts = [q["question"] for q in load_questions(questions_path)]
    schema = db.describe_schema() if config.SQL_INCLUDE_SCHEMA else ""
    rows = [await _level(model, prompts, schema, c, max(requests, c)) for c in levels]
    for r in rows:
        r["cost_per_1k_questions"] = round((r["avg_input_tokens"] * price_in + r["avg_output_tokens"] * price_out) / 1000, 4)
    return {"model": model, "when": datetime.now().isoformat(timespec="seconds"),
            "price_per_million": {"input": price_in, "output": price_out}, "levels": rows}


def to_markdown(report: dict) -> str:
    lines = [f"# GOLD benchmark: `{report['model']}`", "", report["when"], "",
             "| Concurrency | p50 | p95 | Req/s | Output tok/s | Errors | Cost / 1k questions |",
             "|---|---|---|---|---|---|---|"]
    for r in report["levels"]:
        lines.append(f"| {r['concurrency']} | {r['p50_s']} s | {r['p95_s']} s | {r['requests_per_s']} | "
                     f"{r['output_tokens_per_s']} | {r['errors']} | {r['cost_per_1k_questions']} |")
    return "\n".join(lines)


def save(report: dict, out_dir: str = "results") -> Path:
    folder = Path(out_dir) / f"bench-{datetime.now():%Y%m%d-%H%M%S}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (folder / "report.md").write_text(to_markdown(report), encoding="utf-8")
    return folder
