"""Read-only access to the business database."""

import datetime
import decimal
import re

import psycopg

from gold import config
from gold.guards import UnsafeQuery, check_read_only, mask_rows, mask_value


def _jsonable(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or config.DATABASE_URL, autocommit=False, connect_timeout=5)


def run_query(sql: str, max_rows: int | None = None) -> dict:
    """Run one read-only query and return masked rows as plain JSON types."""
    query = check_read_only(sql)
    limit = max_rows or config.MAX_ROWS
    with connect() as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '10s'")
            # prepare=True uses the extended protocol, which refuses more than one
            # statement: a second line of defence behind the SQL parser.
            if config.MAX_QUERY_COST > 0:
                # Dry run: ask the planner what the query would cost before running it.
                cur.execute("EXPLAIN (FORMAT JSON) " + query, prepare=True)
                cost = cur.fetchone()[0][0]["Plan"]["Total Cost"]
                if cost > config.MAX_QUERY_COST:
                    raise UnsafeQuery(
                        f"The query is too expensive to run (estimated cost {cost:,.0f}, limit {config.MAX_QUERY_COST:,.0f}). "
                        "Narrow it down, for example with a date range or a filter."
                    )
            cur.execute(query, prepare=True)
            columns = [d.name for d in cur.description or []]
            fetched = cur.fetchmany(limit + 1)
        conn.rollback()
    truncated = len(fetched) > limit
    rows, masked = mask_rows(columns, [list(r) for r in fetched[:limit]], config.PII_COLUMNS)
    rows = [[_jsonable(v) for v in r] for r in rows]
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "masked_columns": masked,
    }


def describe_schema() -> str:
    """Compact schema listing: one line per table with its columns and types."""
    sql = """
        SELECT CASE WHEN c.table_schema = 'public' THEN c.table_name ELSE c.table_schema || '.' || c.table_name END,
               string_agg(c.column_name || ' ' || c.data_type, ', ' ORDER BY c.ordinal_position)
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE c.table_schema = ANY(%(schemas)s) AND t.table_type IN ('BASE TABLE', 'VIEW')
          AND c.table_name <> 'glossary'
        GROUP BY c.table_schema, c.table_name
        ORDER BY c.table_schema, c.table_name
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"schemas": config.DB_SCHEMAS})
            lines = [f"{table}({cols})" for table, cols in cur.fetchall()]
        conn.rollback()
    return "\n".join(lines)


def _phrase_matches(question: str, rows: list[tuple]) -> list[tuple]:
    """Glossary rows whose term or a synonym appears in the question as a whole phrase.

    Longer phrases win: in "sales rep", the word "sales" does not also match "revenue".
    """
    text = question.lower()
    candidates = []
    for row in rows:
        phrases = [row[0]] + [p.strip() for p in row[4].split(",") if p.strip()]
        for phrase in phrases:
            for m in re.finditer(rf"\b{re.escape(phrase.lower())}\b", text):
                candidates.append((m.end() - m.start(), m.start(), m.end(), row))
    taken: list[tuple[int, int]] = []
    hits: list[tuple] = []
    for _, start, end, row in sorted(candidates, key=lambda c: -c[0]):
        if row in hits or any(start < e and s < end for s, e in taken):
            continue
        taken.append((start, end))
        hits.append(row)
    return hits


def search_glossary(query: str, limit: int = 5) -> list[dict]:
    """Find agreed definitions for the terms in `query`.

    Exact phrase matches on a term or synonym come first: they are precise, and a
    loose match can do harm (a question about "customers" must not pick up the
    definition of "active customer"). Full-text search is the fallback for
    wording the synonyms do not cover.
    """
    with connect(config.GLOSSARY_DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT term, definition, sql_hint, owner, synonyms FROM glossary")
            rows = _phrase_matches(query, cur.fetchall())
            if not rows:
                cur.execute(
                    """
                    SELECT term, definition, sql_hint, owner, synonyms
                    FROM glossary, websearch_to_tsquery('english', %(q)s) q
                    WHERE search @@ q
                    ORDER BY ts_rank(search, q) DESC
                    """,
                    {"q": query},
                )
                rows = cur.fetchall()
        conn.rollback()
    return [{"term": t, "definition": d, "sql_hint": h, "owner": o} for t, d, h, o, _ in rows[:limit]]
