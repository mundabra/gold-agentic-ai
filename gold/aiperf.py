"""Serving benchmarks with NVIDIA AIPerf, using GOLD's real requests.

`gold bench` answers "how long does a SQL generation take?". AIPerf goes
deeper for stage 3: time to first token, inter-token latency, throughput at
load, and goodput (the share of requests inside a latency target).

The payloads are GOLD's exact SQL-model requests, built from the same prompt
contract as production (gold/sql_model.py): system prompt, schema, business
definitions and question, streamed so AIPerf can separate waiting from
generating. scripts/aiperf.sh runs the whole sweep.
"""

import json
from pathlib import Path

from gold import config, db, sql_model
from gold.evaluate import definitions_for, load_questions


def write_payloads(questions_path: str, out_path: str, model: str | None = None, with_definitions: bool = True) -> int:
    """Write one raw AIPerf payload (a complete chat request body) per evaluation question."""
    schema = db.describe_schema() if config.SQL_INCLUDE_SCHEMA else ""
    questions = load_questions(questions_path)
    with open(out_path, "w", encoding="utf-8") as f:
        for q in questions:
            defs = definitions_for(q["question"]) if with_definitions else ""
            f.write(json.dumps({
                "model": model or config.SQL_MODEL,
                "messages": sql_model.messages(q["question"], defs, schema),
                "temperature": 0,
                "max_tokens": config.SQL_MAX_TOKENS,
                "stream": True,
                "stream_options": {"include_usage": True},
            }) + "\n")
    return len(questions)


def _level_files(run_dir: Path) -> list[Path]:
    files = sorted(run_dir.glob("concurrency_*/profile_export_aiperf.json"), key=lambda p: int(p.parent.name.split("_")[1]))
    return files or [p for p in [run_dir / "profile_export_aiperf.json"] if p.exists()]


def summarize(run_dir: str, slo_ms: float) -> list[dict]:
    """One row per concurrency level from AIPerf's JSON exports."""
    rows = []
    for f in _level_files(Path(run_dir)):
        d = json.loads(f.read_text())
        ok = d["request_count"]["avg"]
        lat, ttft = d["request_latency"], d.get("time_to_first_token", {})
        itl = d.get("inter_token_latency", {})
        rows.append({
            "concurrency": d["input_config"]["phases"][0].get("concurrency", "-") if d.get("input_config") else "-",
            "ok": ok,
            "errors": sum(e.get("count", 0) for e in d.get("error_summary") or []),
            "requests_per_s": d["request_throughput"]["avg"],
            "goodput_pct": 100 * d.get("good_request_count", {}).get("avg", 0) / ok if ok else 0,
            "p50_s": lat["p50"] / 1000, "p90_s": lat["p90"] / 1000, "p99_s": lat["p99"] / 1000,
            "ttft_p50_s": ttft.get("p50", 0) / 1000, "ttft_p90_s": ttft.get("p90", 0) / 1000,
            # First *answer* token: for reasoning models this comes after the thinking tokens.
            "first_answer_token_p50_s": d.get("time_to_first_output_token", {}).get("p50", 0) / 1000,
            "itl_p50_ms": itl.get("p50", 0),
            "output_tokens_per_s": d.get("output_token_throughput", {}).get("avg", 0),
            "output_tokens_avg": d.get("output_sequence_length", {}).get("avg", 0),
            "reasoning_pct": 100 * d.get("reasoning_token_count", {}).get("avg", 0)
            / max(d.get("output_sequence_length", {}).get("avg", 0), 1),
        })
    return rows


def to_markdown(rows: list[dict], slo_ms: float) -> str:
    lines = [
        f"| Concurrency | OK | Errors | Req/s | Under {slo_ms / 1000:g} s | p50 | p90 | p99 | TTFT p50 "
        "| First answer token p50 | ITL p50 | Output tok/s | Reasoning share |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['concurrency']} | {r['ok']:.0f} | {r['errors']} | {r['requests_per_s']:.2f} | {r['goodput_pct']:.0f}% "
            f"| {r['p50_s']:.2f} s | {r['p90_s']:.2f} s | {r['p99_s']:.2f} s | {r['ttft_p50_s']:.2f} s "
            f"| {r['first_answer_token_p50_s']:.2f} s | {r['itl_p50_ms']:.1f} ms | {r['output_tokens_per_s']:.0f} "
            f"| {r['reasoning_pct']:.0f}% |"
        )
    return "\n".join(lines)
