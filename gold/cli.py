"""Command line: run any GOLD component, or ask a question.

    gold serve orchestrator|registry|sql-agent|definitions-agent|mcp-data|mcp-glossary|scripted-model
    gold ask "What was revenue by country last year?" [--url http://localhost:8080]
    gold eval  [--model M] [--min-accuracy 0.8]     quality: does the SQL return the right answer?
    gold bench [--model M] [--concurrency 1,4,8]    performance: latency, throughput, cost
    gold dataset finetune/seed_pairs.jsonl          stage 2: build a fine-tuning dataset
"""

import argparse
import asyncio
import importlib
import json
import os
import sys
from pathlib import Path

import httpx

COMPONENTS = {
    "orchestrator": "gold.orchestrator.app",
    "registry": "gold.registry",
    "sql-agent": "gold.agents.sql_agent",
    "definitions-agent": "gold.agents.definitions_agent",
    "mcp-data": "gold.mcp_servers.data_tools",
    "mcp-glossary": "gold.mcp_servers.glossary_tools",
    "scripted-model": "gold.testing.scripted_model",
}


def ask(url: str, question: str, show_trace: bool) -> int:
    resp = httpx.post(f"{url.rstrip('/')}/api/ask", json={"question": question}, timeout=600)
    if resp.status_code != 200:
        print(f"Error {resp.status_code}: {resp.text}", file=sys.stderr)
        return 1
    body = resp.json()
    print(body["answer"])
    if show_trace:
        print("\n--- how this answer was made ---")
        for call in body["calls"]:
            print(f"\n{call['agent']} ({call['elapsed_ms']} ms): {call['request']}")
            for step in call["steps"]:
                print(f"  - {step['tool']}: {json.dumps(step['input'])[:200]}")
        u = body["usage"]
        print(f"\n{u.get('model_requests', 0)} model calls, {u.get('total_tokens', 0)} tokens, {body['elapsed_ms']} ms")
    return 0


def load_env_file(path: str = ".env") -> None:
    """Read KEY=VALUE lines from .env without overriding variables already set."""
    file = Path(path)
    if not file.is_file():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.split(" #", 1)[0].strip().strip('"').strip("'"))


def main() -> None:
    try:
        _main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # friendly message for the common setup mistakes
        import psycopg

        if isinstance(exc, psycopg.OperationalError):
            from gold import config

            host = config.DATABASE_URL.rsplit("@", 1)[-1]
            sys.exit(f"Cannot reach the database at {host}. Set GOLD_DATABASE_URL. ({str(exc).splitlines()[0]})")
        raise


def _main() -> None:
    parser = argparse.ArgumentParser(prog="gold", description="GOLD: Governed Open Language-to-Data")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run one component")
    serve.add_argument("component", choices=sorted(COMPONENTS))
    q = sub.add_parser("ask", help="ask the orchestrator a question")
    q.add_argument("question")
    q.add_argument("--url", default="http://localhost:8080")
    q.add_argument("--no-trace", action="store_true", help="print only the answer")
    e = sub.add_parser("eval", help="score a SQL model against the evaluation set")
    e.add_argument("--model", help="model name at GOLD_LLM_BASE_URL (default: GOLD_SQL_MODEL)")
    e.add_argument("--system", metavar="URL", help="grade the whole running GOLD at this URL instead of one model")
    e.add_argument("--questions", default="evals/questions.jsonl")
    e.add_argument("--arms", default="bare,definitions", help="comma-separated: bare, definitions")
    e.add_argument("--concurrency", type=int, default=4)
    e.add_argument("--min-accuracy", type=float, help="quality gate: exit with an error if the gated arm scores below this (0-1)")
    e.add_argument("--gate-arm", default="definitions", help="which arm the quality gate checks (default: definitions, as in production)")
    e.add_argument("--out", default="results")
    b = sub.add_parser("bench", help="measure latency, throughput and cost of a SQL model")
    b.add_argument("--model", help="model name at GOLD_LLM_BASE_URL (default: GOLD_SQL_MODEL)")
    b.add_argument("--questions", default="evals/questions.jsonl")
    b.add_argument("--concurrency", default="1,4,8", help="comma-separated concurrency levels")
    b.add_argument("--requests", type=int, default=16, help="requests per level")
    b.add_argument("--price-in", type=float, default=0.0, help="price per million input tokens")
    b.add_argument("--price-out", type=float, default=0.0, help="price per million output tokens")
    b.add_argument("--out", default="results")
    d = sub.add_parser("dataset", help="build a fine-tuning dataset from question/SQL pairs")
    d.add_argument("pairs", help="JSONL with {question, sql} per line")
    d.add_argument("--out", default="finetune/data")
    d.add_argument("--eval-questions", default="evals/questions.jsonl", help="held out: never used for training")
    d.add_argument("--no-definitions", action="store_true", help="train on bare questions only")
    args = parser.parse_args()

    if args.command in {"eval", "bench", "dataset"}:
        # Engineer commands run on your machine: read .env, and reach the
        # Compose database on localhost unless told otherwise.
        load_env_file()
        os.environ.setdefault("GOLD_DATABASE_URL", "postgresql://gold_reader:gold_reader@localhost:5432/gold")

    if args.command == "serve":
        importlib.import_module(COMPONENTS[args.component]).main()
    elif args.command == "ask":
        sys.exit(ask(args.url, args.question, not args.no_trace))
    elif args.command == "eval":
        from gold import evaluate

        if args.system:
            arms = ("system",)
            report = asyncio.run(evaluate.run_system(args.questions, args.system, args.concurrency))
        else:
            arms = tuple(a.strip() for a in args.arms.split(",") if a.strip())
            report = asyncio.run(evaluate.run(args.questions, args.model, arms, args.concurrency))
        folder = evaluate.save(report, args.out)
        print(evaluate.to_markdown(report).split("## Misses")[0].rstrip())
        print(f"\nFull report: {folder}/report.md")
        if args.min_accuracy is not None:
            arm = args.gate_arm if args.gate_arm in report["summary"] else arms[0]
            score = report["summary"][arm]["accuracy"]
            if score < args.min_accuracy:
                print(f"FAILED quality gate: {arm} scored {score:.0%}, below {args.min_accuracy:.0%}", file=sys.stderr)
                sys.exit(2)
            print(f"Passed quality gate: {arm} scored {score:.0%} (bar {args.min_accuracy:.0%})")
    elif args.command == "dataset":
        from gold import dataset

        summary = dataset.build(args.pairs, args.out, args.eval_questions, with_definitions=not args.no_definitions)
        print(f"{summary['train']} training and {summary['val']} validation examples written to {summary['out_dir']}/")
        for d in summary["dropped"]:
            print(f"  dropped: {d['question']} ({d['reason']})")
    else:
        from gold import bench

        levels = tuple(int(c) for c in args.concurrency.split(","))
        report = asyncio.run(bench.run(args.questions, args.model, levels, args.requests, args.price_in, args.price_out))
        folder = bench.save(report, args.out)
        print(bench.to_markdown(report))
        print(f"\nFull report: {folder}/report.md")


if __name__ == "__main__":
    main()
