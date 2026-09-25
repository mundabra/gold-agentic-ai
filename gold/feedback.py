"""The feedback loop: users rate answers, reviewers act on them.

    user:      "Useful" / "Not right" (+ comment, + a correction) in the chat UI -> POST /api/feedback
    reviewer:  gold feedback list | dismiss <id>, plus what each app adds
               (the data app: gold feedback promote <id> turns a correction into a verified query)

Two separate database logins keep this apart from everything else:
GOLD_FEEDBACK_DATABASE_URL (insert-only, used by the orchestrator) and
GOLD_CURATOR_DATABASE_URL (review, used by the people curating feedback).
"""

import psycopg

from gold import config


class FeedbackError(ValueError):
    pass


def enabled() -> bool:
    return bool(config.FEEDBACK_DATABASE_URL)


def submit(*, app: str, answer_id: str, question: str, sql_ran: str | None, rating: str, comment: str | None,
           corrected_sql: str | None, user: str | None) -> None:
    if rating not in ("up", "down"):
        raise FeedbackError("rating must be 'up' or 'down'")
    with psycopg.connect(config.FEEDBACK_DATABASE_URL, connect_timeout=5) as conn:
        conn.execute(
            "INSERT INTO feedback (app, answer_id, user_id, question, sql_ran, rating, comment, corrected_sql) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (app, answer_id, user, question[:2000], (sql_ran or "")[:20000] or None, rating,
             (comment or "")[:2000] or None, corrected_sql),
        )


def curator() -> psycopg.Connection:
    if not config.CURATOR_DATABASE_URL:
        raise FeedbackError("Set GOLD_CURATOR_DATABASE_URL to review feedback.")
    return psycopg.connect(config.CURATOR_DATABASE_URL, connect_timeout=5)


def list_items(status: str = "new", app: str | None = None) -> list[dict]:
    with curator() as conn:
        rows = conn.execute(
            "SELECT id, created_at, app, user_id, rating, question, sql_ran, corrected_sql, comment, status "
            "FROM feedback WHERE status = %s AND (%s::text IS NULL OR app = %s) ORDER BY id",
            (status, app, app)).fetchall()
    keys = ["id", "created_at", "app", "user", "rating", "question", "sql_ran", "corrected_sql", "comment", "status"]
    return [dict(zip(keys, r)) for r in rows]


def dismiss(item_id: int, reviewed_by: str) -> None:
    with curator() as conn:
        updated = conn.execute("UPDATE feedback SET status = 'dismissed', reviewed_by = %s, reviewed_at = now() "
                               "WHERE id = %s AND status = 'new'", (reviewed_by, item_id)).rowcount
    if not updated:
        raise FeedbackError(f"No new feedback item {item_id}.")
