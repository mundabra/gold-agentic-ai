"""Checks for the semantic knowledge GOLD relies on: approved example queries."""

from gold import db
from gold.evaluate import load_questions
from gold.guards import UnsafeQuery, check_read_only


def _key(text: str) -> str:
    return " ".join(text.lower().split())


def verify_queries(eval_path: str = "evals/questions.jsonl") -> list[dict]:
    """Every approved query must be read-only, must run, and must not be an evaluation question."""
    held_out = {_key(q["question"]) for q in load_questions(eval_path)} | {_key(q["sql"]) for q in load_questions(eval_path)}
    problems = []
    for vq in db.all_verified_queries():
        reason = None
        if _key(vq["question"]) in held_out or _key(vq["sql"]) in held_out:
            reason = "it is in the evaluation set, which would make gold eval an unfair test"
        else:
            try:
                check_read_only(vq["sql"])
                db.run_query(vq["sql"], 1)
            except UnsafeQuery as exc:
                reason = f"not read-only: {exc}"
            except Exception as exc:
                reason = f"does not run: {str(exc).splitlines()[0]}"
        if reason:
            problems.append({"question": vq["question"], "reason": reason})
    return problems
