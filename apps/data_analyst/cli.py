"""The data app's commands, added to `gold` (see gold/apps.py):

    gold eval  [--model M] [--min-accuracy 0.8]     quality: does the SQL return the right answer?
    gold bench [--model M] [--concurrency 1,4,8]    performance: latency, throughput, cost
    gold dataset apps/data_analyst/finetune/seed_pairs.jsonl   stage 2: build a fine-tuning dataset
    gold aiperf-payloads / aiperf-summary           stage 3: serving benchmarks with NVIDIA AIPerf (scripts/aiperf.sh)
    gold verify-queries                             check every approved example query (run it in CI)
    gold feedback promote ID | export               turn corrections into verified queries
"""

import asyncio
import json
import sys
from pathlib import Path

from apps.data_analyst import settings

COMMANDS = {"eval", "bench", "dataset", "aiperf-payloads", "aiperf-summary", "verify-queries", "feedback"}


def register(sub, groups: dict) -> None:
    questions = settings.EVAL_QUESTIONS
    e = sub.add_parser("eval", help="score a SQL model (or the whole running system) against the evaluation set")
    e.add_argument("--model", help="model name at GOLD_LLM_BASE_URL (default: GOLD_SQL_MODEL)")
    e.add_argument("--system", metavar="URL", help="grade the whole running GOLD at this URL instead of one model")
    e.add_argument("--questions", default=questions)
    e.add_argument("--arms", default="bare,definitions", help="comma-separated: bare, definitions")
    e.add_argument("--concurrency", type=int, default=4)
    e.add_argument("--min-accuracy", type=float, help="quality gate: exit with an error if the gated arm scores below this (0-1)")
    e.add_argument("--gate-arm", default="definitions", help="which arm the quality gate checks (default: definitions, as in production)")
    e.add_argument("--out", default="results")
    b = sub.add_parser("bench", help="measure latency, throughput and cost of a SQL model")
    b.add_argument("--model", help="model name at GOLD_LLM_BASE_URL (default: GOLD_SQL_MODEL)")
    b.add_argument("--questions", default=questions)
    b.add_argument("--concurrency", default="1,4,8", help="comma-separated concurrency levels")
    b.add_argument("--requests", type=int, default=16, help="requests per level")
    b.add_argument("--price-in", type=float, default=0.0, help="price per million input tokens")
    b.add_argument("--price-out", type=float, default=0.0, help="price per million output tokens")
    b.add_argument("--out", default="results")
    d = sub.add_parser("dataset", help="build a fine-tuning dataset from question/SQL pairs")
    d.add_argument("pairs", help="JSONL with {question, sql} per line")
    d.add_argument("--out", default="results/finetune-data")
    d.add_argument("--eval-questions", default=questions, help="held out: never used for training")
    d.add_argument("--no-definitions", action="store_true", help="train on bare questions only")
    vq = sub.add_parser("verify-queries", help="check that every approved example query parses, runs and is not an evaluation question")
    vq.add_argument("--eval-questions", default=questions)
    ap = sub.add_parser("aiperf-payloads", help="write GOLD's real SQL requests as NVIDIA AIPerf raw payloads")
    ap.add_argument("--questions", default=questions)
    ap.add_argument("--out", default="results/aiperf-payloads.jsonl")
    ap.add_argument("--model", help="model name at the endpoint (default: GOLD_SQL_MODEL)")
    ap.add_argument("--no-definitions", action="store_true", help="leave out the business definitions block")
    asum = sub.add_parser("aiperf-summary", help="summarize an AIPerf run, one row per concurrency level")
    asum.add_argument("run_dir")
    asum.add_argument("--slo-ms", type=float, default=3000, help="latency target the goodput column refers to")

    fbs = groups["feedback"]
    fp = fbs.add_parser("promote", help="turn a feedback item into a verified query")
    fp.add_argument("id", type=int)
    fp.add_argument("--verified-by", required=True, help="who vouches for the SQL")
    fp.add_argument("--question", help="reword the question (default: the user's)")
    fp.add_argument("--sql", help="the SQL to approve (default: the corrected SQL, or the SQL that ran for a 'Useful' rating)")
    fbs.add_parser("export", help="print verified question/SQL pairs as JSONL (for gold dataset)")


def run(args) -> bool:
    """Run the command if it is one of this app's; return False if it is not."""
    command = args.command
    if command == "feedback" and args.action not in ("promote", "export"):
        return False
    if command not in COMMANDS:
        return False

    if command == "eval":
        from apps.data_analyst import evaluate

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
    elif command == "feedback":
        from apps.data_analyst import curation
        from gold.feedback import FeedbackError

        try:
            if args.action == "promote":
                result = curation.promote(args.id, args.verified_by, args.question, args.sql)
                print(f"Promoted to a verified query: {result['question']}")
                for p in result["problems"]:
                    print(f"  check: {p['question']}: {p['reason']}")
            else:
                for pair in curation.export_pairs():
                    print(json.dumps(pair, ensure_ascii=False))
        except FeedbackError as exc:
            sys.exit(str(exc))
    elif command == "verify-queries":
        from apps.data_analyst import semantic

        problems = semantic.verify_queries(args.eval_questions)
        for p in problems:
            print(f"FAIL  {p['question']}: {p['reason']}")
        if problems:
            sys.exit(1)
        print("All approved example queries are valid.")
    elif command == "aiperf-payloads":
        from apps.data_analyst import aiperf

        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        n = aiperf.write_payloads(args.questions, args.out, args.model, with_definitions=not args.no_definitions)
        print(f"{n} payloads written to {args.out}")
    elif command == "aiperf-summary":
        from apps.data_analyst import aiperf

        rows = aiperf.summarize(args.run_dir, args.slo_ms)
        if not rows:
            sys.exit(f"No AIPerf exports found in {args.run_dir}")
        print(aiperf.to_markdown(rows, args.slo_ms))
    elif command == "dataset":
        from apps.data_analyst import dataset

        summary = dataset.build(args.pairs, args.out, args.eval_questions, with_definitions=not args.no_definitions)
        print(f"{summary['train']} training and {summary['val']} validation examples written to {summary['out_dir']}/")
        for d in summary["dropped"]:
            print(f"  dropped: {d['question']} ({d['reason']})")
    else:
        from apps.data_analyst import bench

        levels = tuple(int(c) for c in args.concurrency.split(","))
        report = asyncio.run(bench.run(args.questions, args.model, levels, args.requests, args.price_in, args.price_out))
        folder = bench.save(report, args.out)
        print(bench.to_markdown(report))
        print(f"\nFull report: {folder}/report.md")
    return True
