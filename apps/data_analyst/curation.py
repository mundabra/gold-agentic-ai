"""The data app's side of the feedback loop: approved corrections become verified queries.

    gold feedback promote <id> --verified-by analyst@example.com
    gold feedback export          verified question/SQL pairs, for gold dataset (fine-tuning)
"""

import json

from apps.data_analyst import db, settings
from apps.data_analyst.guards import UnsafeQuery, check_read_only
from apps.data_analyst.semantic import verify_queries
from gold.feedback import FeedbackError, curator


def check_correction(corrected: str | None) -> str | None:
    """Refuse a correction that is not one read-only query (hook: called when a user submits feedback)."""
    if not corrected:
        return None
    try:
        return check_read_only(corrected)
    except UnsafeQuery as exc:
        raise FeedbackError(f"The corrected SQL is not a single read-only query: {exc}") from exc


def promote(item_id: int, verified_by: str, question: str | None = None, sql: str | None = None,
            eval_path: str = settings.EVAL_QUESTIONS) -> dict:
    """Turn a feedback item into a verified query, after checking the SQL is read-only and runs."""
    with curator() as conn:
        row = conn.execute("SELECT question, sql_ran, corrected_sql, rating, status FROM feedback WHERE id = %s",
                           (item_id,)).fetchone()
        if not row:
            raise FeedbackError(f"No feedback item {item_id}.")
        fb_question, sql_ran, corrected, rating, status = row
        if status != "new":
            raise FeedbackError(f"Item {item_id} is already {status}.")
        final_sql = sql or corrected or (sql_ran if rating == "up" else None)
        if not final_sql:
            raise FeedbackError("A 'Not right' item needs corrected SQL: pass --sql.")
        final_question = question or fb_question
        try:
            check_read_only(final_sql)
            db.run_query(final_sql, 1)
        except Exception as exc:
            raise FeedbackError(f"The SQL does not pass: {str(exc).splitlines()[0]}") from exc
        held_out = {" ".join(q["question"].lower().split()) for q in map(json.loads, open(eval_path))}
        if " ".join(final_question.lower().split()) in held_out:
            raise FeedbackError("That question is in the evaluation set; promoting it would make gold eval unfair.")
        conn.execute("INSERT INTO verified_queries (question, sql, verified_by) VALUES (%s, %s, %s)",
                     (final_question, final_sql, verified_by))
        conn.execute("UPDATE feedback SET status = 'promoted', reviewed_by = %s, reviewed_at = now() WHERE id = %s",
                     (verified_by, item_id))
    return {"question": final_question, "sql": final_sql, "problems": verify_queries(eval_path)}


def export_pairs() -> list[dict]:
    """Promoted question/SQL pairs, ready for `gold dataset` (fine-tuning) or as evaluation candidates."""
    with curator() as conn:
        rows = conn.execute("SELECT question, sql FROM verified_queries ORDER BY id").fetchall()
    return [{"question": q, "sql": s} for q, s in rows]
