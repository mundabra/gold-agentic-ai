"""The Sales copilot's data access: fixed, parameterized queries, run as the signed-in rep.

Unlike the data app, nothing here runs SQL a model wrote. Each tool is one query with typed
parameters, and Postgres row-level security (deploy/postgres/03-row-level-security.sql) limits
every query to the rep's own accounts. Writes go through a separate login that can only add
CRM activities, and only for accounts the rep can see (deploy/postgres/06-sales.sh).
"""

import datetime

import psycopg
from psycopg.rows import dict_row

from apps.sales_copilot import settings
from gold import pg

KINDS = ("call", "email", "meeting", "note")

# One row per account the user can see, with the figures reps ask about. The sample data is a
# snapshot, so "today" is the latest invoice date in it (crm_as_of()); see 06-sales.sh.
_ACCOUNTS = """
WITH as_of AS (SELECT crm_as_of() AS d),
acct AS (
    SELECT c.customer_id, c.first_name || ' ' || c.last_name AS customer, c.company, c.city, c.country,
           e.first_name || ' ' || e.last_name AS rep,
           ROUND(COALESCE(SUM(i.total), 0), 2) AS lifetime_value,
           COUNT(i.invoice_id) AS orders,
           MIN(i.invoice_date)::date AS first_purchase,
           MAX(i.invoice_date)::date AS last_purchase,
           ROUND(COALESCE(SUM(i.total) FILTER (WHERE i.invoice_date > (SELECT d FROM as_of) - INTERVAL '12 months'), 0), 2)
               AS revenue_last_12m,
           ROUND(COALESCE(SUM(i.total) FILTER (WHERE i.invoice_date <= (SELECT d FROM as_of) - INTERVAL '12 months'
                                                 AND i.invoice_date > (SELECT d FROM as_of) - INTERVAL '24 months'), 0), 2)
               AS revenue_prior_12m
    FROM customer c
    LEFT JOIN employee e ON e.employee_id = c.support_rep_id
    LEFT JOIN invoice i ON i.customer_id = c.customer_id
    GROUP BY c.customer_id, c.first_name, c.last_name, c.company, c.city, c.country, e.first_name, e.last_name
)
SELECT acct.*, (SELECT d FROM as_of) - acct.last_purchase AS days_since_last_purchase,
       (SELECT d FROM as_of) - acct.last_purchase > %(at_risk_days)s AS at_risk
FROM acct
"""


class NotFound(LookupError):
    pass


def _read(sql: str, params: dict, user) -> list[dict]:
    with psycopg.connect(settings.DATABASE_URL, connect_timeout=5) as conn:
        conn.read_only = True
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SET LOCAL statement_timeout = '10s'")
            pg.act_as(cur, user)
            cur.execute(sql, params)
            rows = cur.fetchall()
        conn.rollback()
    return [{k: pg.jsonable(v) for k, v in row.items()} for row in rows]


def table(rows: list[dict]) -> dict:
    """Rows as columns + rows, the shape the UI charts and the audit trail understand."""
    columns = list(rows[0]) if rows else []
    return {"columns": columns, "rows": [[r[c] for c in columns] for r in rows], "row_count": len(rows)}


def as_of(user) -> str:
    return _read("SELECT crm_as_of() AS d", {}, user)[0]["d"]


def scope(user) -> str:
    return f"accounts visible to {user.id}" if user else "all accounts (no signed-in user)"


def accounts(user, sort_by: str = "revenue", limit: int = 10) -> list[dict]:
    order = {
        "revenue": "lifetime_value DESC",
        "at_risk": "days_since_last_purchase DESC NULLS FIRST",
        "recent": "last_purchase DESC NULLS LAST",
        "declining": "(revenue_last_12m - revenue_prior_12m) ASC",
    }[sort_by]
    where = "WHERE (SELECT d FROM as_of) - acct.last_purchase > %(at_risk_days)s " if sort_by == "at_risk" else ""
    sql = _ACCOUNTS + where + f"ORDER BY {order}, customer_id LIMIT %(limit)s"
    return _read(sql, {"at_risk_days": settings.AT_RISK_DAYS, "limit": max(1, min(limit, 50))}, user)


def find(user, customer: str) -> list[dict]:
    """Accounts matching an id, a name or a company, among those the user can see."""
    text = customer.strip()
    if text.isdigit():
        return _read(_ACCOUNTS + "WHERE customer_id = %(id)s", {"id": int(text), "at_risk_days": settings.AT_RISK_DAYS}, user)
    like = f"%{text}%"
    return _read(_ACCOUNTS + "WHERE customer ILIKE %(like)s OR company ILIKE %(like)s ORDER BY customer LIMIT 10",
                 {"like": like, "at_risk_days": settings.AT_RISK_DAYS}, user)


def one(user, customer_id: int) -> dict:
    rows = find(user, str(customer_id))
    if not rows:
        raise NotFound(f"No account {customer_id} among the {scope(user)}.")
    return rows[0]


def brief(user, customer_id: int) -> dict:
    account = one(user, customer_id)
    params = {"id": customer_id}
    genres = _read("""
        SELECT g.name AS genre, ROUND(SUM(il.unit_price * il.quantity), 2) AS revenue
        FROM invoice_line il JOIN invoice i ON i.invoice_id = il.invoice_id
        JOIN track t ON t.track_id = il.track_id JOIN genre g ON g.genre_id = t.genre_id
        WHERE i.customer_id = %(id)s GROUP BY g.name ORDER BY revenue DESC, genre LIMIT 3""", params, user)
    artists = _read("""
        SELECT ar.name AS artist, ROUND(SUM(il.unit_price * il.quantity), 2) AS revenue
        FROM invoice_line il JOIN invoice i ON i.invoice_id = il.invoice_id
        JOIN track t ON t.track_id = il.track_id JOIN album al ON al.album_id = t.album_id
        JOIN artist ar ON ar.artist_id = al.artist_id
        WHERE i.customer_id = %(id)s GROUP BY ar.name ORDER BY revenue DESC, artist LIMIT 3""", params, user)
    orders = _read("""
        SELECT i.invoice_date::date AS date, i.total, COUNT(il.invoice_line_id) AS tracks
        FROM invoice i JOIN invoice_line il ON il.invoice_id = i.invoice_id
        WHERE i.customer_id = %(id)s GROUP BY i.invoice_id ORDER BY i.invoice_date DESC LIMIT 5""", params, user)
    return {"account": account, "top_genres": genres, "top_artists": artists, "recent_orders": orders,
            "activities": activities(user, customer_id, limit=5)}


def offers(user, customer_id: int, limit: int = 5) -> list[dict]:
    """Albums in the customer's two favourite genres that they don't own, most popular first."""
    one(user, customer_id)
    return _read("""
        WITH bought AS (
            SELECT t.album_id, t.genre_id, il.unit_price * il.quantity AS spend
            FROM invoice_line il JOIN invoice i ON i.invoice_id = il.invoice_id JOIN track t ON t.track_id = il.track_id
            WHERE i.customer_id = %(id)s
        ),
        favourite AS (SELECT genre_id FROM bought GROUP BY genre_id ORDER BY SUM(spend) DESC, genre_id LIMIT 2),
        popularity AS (
            SELECT t.album_id, SUM(il.quantity) AS units
            FROM invoice_line il JOIN track t ON t.track_id = il.track_id GROUP BY t.album_id
        )
        SELECT al.title AS album, ar.name AS artist, g.name AS genre, COUNT(t.track_id) AS tracks,
               ROUND(SUM(t.unit_price), 2) AS price, COALESCE(p.units, 0) AS units_sold
        FROM album al JOIN artist ar ON ar.artist_id = al.artist_id JOIN track t ON t.album_id = al.album_id
        JOIN genre g ON g.genre_id = t.genre_id LEFT JOIN popularity p ON p.album_id = al.album_id
        WHERE t.genre_id IN (SELECT genre_id FROM favourite)
          AND al.album_id NOT IN (SELECT album_id FROM bought)
        GROUP BY al.album_id, al.title, ar.name, g.name, p.units
        ORDER BY units_sold DESC, tracks DESC, album LIMIT %(limit)s""",
                 {"id": customer_id, "limit": max(1, min(limit, 20))}, user)


def activities(user, customer_id: int | None = None, open_follow_ups: bool = False, limit: int = 10) -> list[dict]:
    return _read("""
        SELECT a.activity_id, a.created_at::date AS logged_on, c.first_name || ' ' || c.last_name AS customer,
               a.customer_id, a.kind, a.note, a.follow_up_on, a.logged_by
        FROM crm_activity a JOIN customer c ON c.customer_id = a.customer_id
        WHERE (%(id)s::int IS NULL OR a.customer_id = %(id)s)
          AND (NOT %(open)s OR a.follow_up_on >= crm_as_of())
        ORDER BY CASE WHEN %(open)s THEN a.follow_up_on END ASC, a.created_at DESC LIMIT %(limit)s""",
                 {"id": customer_id, "open": open_follow_ups, "limit": max(1, min(limit, 50))}, user)


def check_activity(kind: str, note: str, follow_up_on: str | None) -> tuple[str, str, str | None]:
    """Validate a new activity before it is proposed. Returns the cleaned values."""
    kind = kind.strip().lower()
    if kind not in KINDS:
        raise ValueError(f"kind must be one of: {', '.join(KINDS)}")
    note = " ".join(note.split())
    if not note or len(note) > 1000:
        raise ValueError("note must be 1 to 1000 characters")
    if follow_up_on:
        follow_up_on = datetime.date.fromisoformat(follow_up_on.strip()).isoformat()
    return kind, note, follow_up_on or None


def add_activity(user, *, customer_id: int, kind: str, note: str, follow_up_on: str | None,
                 action_id: str, approved_by: str | None) -> dict:
    """Insert an approved activity. The action id makes it idempotent: replays add nothing."""
    with psycopg.connect(settings.CRM_DATABASE_URL, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '10s'")
            pg.act_as(cur, user)
            cur.execute(
                "INSERT INTO crm_activity (customer_id, kind, note, follow_up_on, logged_by, approved_by, action_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (action_id) DO NOTHING RETURNING activity_id",
                (customer_id, kind, note, follow_up_on, user.id if user else "anonymous", approved_by or "anonymous",
                 action_id))
            row = cur.fetchone()
            if row is None:
                cur.execute("SELECT activity_id FROM crm_activity WHERE action_id = %s", (action_id,))
                return {"activity_id": cur.fetchone()[0], "already_logged": True}
    return {"activity_id": row[0], "already_logged": False}
