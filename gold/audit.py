"""Audit trail: one JSON record per question, answered or blocked.

Records go to the "gold.audit" logger (stdout, so any log pipeline can collect
them) and, if GOLD_AUDIT_LOG is set, are appended to that file. Each record holds
who asked (when identity is configured), the question, whether it was blocked,
which agents ran, the exact SQL executed, rows returned, tokens, time, and the
trace ID that links to the full OpenTelemetry trace.
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


def record(*, session_id: str, question: str, blocked: bool, calls: list[dict], usage: dict,
           elapsed_ms: int, user: str | None = None, error: str | None = None,
           blocked_by: str | None = None) -> dict:
    queries = [
        {
            "sql": (step.get("input") or {}).get("sql"),
            "rows": (step.get("output") or {}).get("row_count") if isinstance(step.get("output"), dict) else None,
            "refused": (step.get("output") or {}).get("reason") if isinstance(step.get("output"), dict) else None,
        }
        for call in calls for step in call.get("steps", []) if step.get("tool") == "run_sql"
    ]
    entry = {
        "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "trace_id": _trace_id(),
        "session_id": session_id,
        "user": user,
        "question": question,
        "blocked": blocked,
        "blocked_by": blocked_by,
        "error": error,
        "agents": [c.get("agent") for c in calls],
        "queries": queries,
        "tokens": usage.get("total_tokens", 0),
        "model_requests": usage.get("model_requests", 0),
        "elapsed_ms": elapsed_ms,
    }
    line = json.dumps(entry, ensure_ascii=False, default=str)
    log.info(line)
    if config.AUDIT_LOG:
        with _lock, open(config.AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return entry
