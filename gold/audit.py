"""Audit trail: one JSON record per question, answered or blocked.

Records go to the "gold.audit" logger (stdout, so any log pipeline can collect
them) and, if GOLD_AUDIT_LOG is set, are appended to that file. Each record holds
the app, who asked (when identity is configured), the question, whether it was
blocked, which agents ran, every tool they called, the exact SQL executed and rows
returned, actions proposed for approval, tokens, time, and the trace ID that links
to the full OpenTelemetry trace. Approving or rejecting an action is its own record
(event "action").
"""

import json
import logging
import threading
from datetime import datetime, timezone

from gold import config

log = logging.getLogger("gold.audit")
_lock = threading.Lock()


def _trace_id() -> str | None:
    try:
        from opentelemetry import trace

        ctx = trace.get_current_span().get_span_context()
        return format(ctx.trace_id, "032x") if ctx.is_valid else None
    except ImportError:
        return None


def _write(entry: dict) -> dict:
    line = json.dumps(entry, ensure_ascii=False, default=str)
    log.info(line)
    if config.AUDIT_LOG:
        with _lock, open(config.AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return entry


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def record(*, session_id: str, question: str, blocked: bool, calls: list[dict], usage: dict,
           elapsed_ms: int, app: str | None = None, user: str | None = None, error: str | None = None,
           blocked_by: str | None = None, answer_id: str | None = None, actions: list[dict] | None = None) -> dict:
    queries = [
        {
            "sql": (step.get("input") or {}).get("sql"),
            "rows": (step.get("output") or {}).get("row_count") if isinstance(step.get("output"), dict) else None,
            "refused": (step.get("output") or {}).get("reason") if isinstance(step.get("output"), dict) else None,
        }
        for call in calls for step in call.get("steps", []) if step.get("tool") == "run_sql"
    ]
    return _write({
        "event": "question",
        "time": _now(),
        "trace_id": _trace_id(),
        "app": app,
        "session_id": session_id,
        "answer_id": answer_id,
        "user": user,
        "question": question,
        "blocked": blocked,
        "blocked_by": blocked_by,
        "error": error,
        "agents": [c.get("agent") for c in calls],
        "tools": [f"{c.get('agent')}: {s.get('tool')}" for c in calls for s in c.get("steps", [])],
        "queries": queries,
        "actions_proposed": [{"id": a.get("id"), "tool": a.get("tool"), "summary": a.get("summary")} for a in actions or []],
        "tokens": usage.get("total_tokens", 0),
        "model_requests": usage.get("model_requests", 0),
        "elapsed_ms": elapsed_ms,
    })


def action(ticket: dict, decision: str, *, user: str | None, result=None, error: str | None = None) -> dict:
    """An approval decision on a proposed action: approved (and its result), rejected, or failed."""
    return _write({
        "event": "action",
        "time": _now(),
        "trace_id": _trace_id(),
        "decision": decision,
        "user": user,
        "action_id": ticket.get("id"),
        "tool": ticket.get("tool"),
        "summary": ticket.get("summary"),
        "args": ticket.get("args"),
        "result": result,
        "error": error,
    })
