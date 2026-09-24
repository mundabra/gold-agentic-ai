"""The feedback loop: users rate answers, analysts review, approved fixes become verified queries.

    user:     "Useful" / "Not right" (+ comment, + corrected SQL) in the chat UI -> POST /api/feedback
    analyst:  gold feedback list | promote <id> | dismiss <id> | export

Two separate database logins keep this apart from query execution:
GOLD_FEEDBACK_DATABASE_URL (insert-only, used by the orchestrator) and
GOLD_CURATOR_DATABASE_URL (review and add verified queries, used by analysts).
"""

import json

import psycopg

from gold import config, db
from gold.guards import UnsafeQuery, check_read_only
from gold.semantic import verify_queries


class FeedbackError(ValueError):
    pass


def enabled() -> bool:
    return bool(config.FEEDBACK_DATABASE_URL)


def submit(*, answer_id: str, question: str, sql_ran: str | None, rating: str, comment: str | None,
           corrected_sql: str | None, user: str | None) -> None:
    if rating not in ("up", "down"):
        raise FeedbackError("rating must be 'up' or 'down'")
    if corrected_sql:
        try:
            corrected_sql = check_read_only(corrected_sql)
        except UnsafeQuery as exc:
            raise FeedbackError(f"The corrected SQL is not a single read-only query: {exc}") from exc
    with psycopg.connect(config.FEEDBACK_DATABASE_URL, connect_timeout=5) as conn:
        conn.execute(
            "INSERT INTO feedback (answer_id, user_id, question, sql_ran, rating, comment, corrected_sql) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (answer_id, user, question[:2000], (sql_ran or "")[:20000] or None, rating,
             (comment or "")[:2000] or None, corrected_sql),
        )


def _curator():
    if not config.CURATOR_DATABASE_URL:
        raise FeedbackError("Set GOLD_CURATOR_DATABASE_URL to review feedback.")
    return psycopg.connect(config.CURATOR_DATABASE_URL, connect_timeout=5)


def list_items(status: str = "new") -> list[dict]:
    with _curator() as conn:
        rows = conn.execute(
            "SELECT id, created_at, user_id, rating, question, sql_ran, corrected_sql, comment, status "
            "FROM feedback WHERE status = %s ORDER BY id", (status,)).fetchall()
    keys = ["id", "created_at", "user", "rating", "question", "sql_ran", "corrected_sql", "comment", "status"]
    return [dict(zip(keys, r)) for r in rows]


def promote(item_id: int, verified_by: str, question: str | None = None, sql: str | None = None,
            eval_path: str = "evals/questions.jsonl") -> dict:
    """Turn a feedback item into a verified query, after checking the SQL is read-only and runs."""
    with _curator() as conn:
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


def dismiss(item_id: int, reviewed_by: str) -> None:
    with _curator() as conn:
        updated = conn.execute("UPDATE feedback SET status = 'dismissed', reviewed_by = %s, reviewed_at = now() "
                               "WHERE id = %s AND status = 'new'", (reviewed_by, item_id)).rowcount
    if not updated:
        raise FeedbackError(f"No new feedback item {item_id}.")


def export_pairs() -> list[dict]:
    """Promoted question/SQL pairs, ready for `gold dataset` (fine-tuning) or as evaluation candidates."""
    with _curator() as conn:
        rows = conn.execute("SELECT question, sql FROM verified_queries ORDER BY id").fetchall()
    return [{"question": q, "sql": s} for q, s in rows]
