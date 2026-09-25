"""Governance checks shared by the tools: read-only SQL and personal-data masking.

These are the first line of defence. The database role GOLD connects with is
also read-only (deploy/postgres/04-reader-role.sh), so a query that slipped
past these checks still could not change data.
"""

import logging
import re

import sqlglot
from sqlglot import exp

from apps.data_analyst import settings

logging.getLogger("sqlglot").setLevel(logging.ERROR)

# Anything in the parsed query that could change data, schema, session state or locks.
_FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Drop, exp.Create, exp.Alter,
    exp.TruncateTable, exp.Copy, exp.Grant, exp.Revoke, exp.Set, exp.Lock, exp.Into,
    exp.Transaction, exp.Commit, exp.Rollback, exp.Command, exp.Pragma,
)
# Server-administration and side-effect functions. Analytics never needs them.
_RISKY_PREFIXES = ("pg_", "lo_", "dblink", "set_config", "current_setting", "query_to_xml", "table_to_xml",
                   "cursor_to_xml", "schema_to_xml", "database_to_xml", "txid_", "xmlexists")

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# International (+44 ...) or area-code ((780) ...) formats, so dates and IDs are left alone.
PHONE = re.compile(r"\+\d[\d\s().-]{6,}\d|\(\d{2,4}\)\s?\d[\d\s.-]{5,}\d")


class UnsafeQuery(ValueError):
    """Raised when a query could change data or is not a single read."""


def check_read_only(sql: str) -> str:
    """Parse the query with SQLGlot and return it (without a trailing semicolon) if it is one read-only query."""
    text = sql.strip().rstrip(";").strip()
    if not text:
        raise UnsafeQuery("The query is empty. The model returned no SQL; a reasoning model may need a higher GOLD_SQL_MAX_TOKENS.")
    try:
        statements = [s for s in sqlglot.parse(text, read=settings.SQL_DIALECT) if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise UnsafeQuery(f"The query could not be parsed: {str(exc).splitlines()[0]}") from exc
    if len(statements) != 1:
        raise UnsafeQuery("Only one statement is allowed.")
    query = statements[0]
    if not isinstance(query, exp.Query):
        raise UnsafeQuery("Only SELECT queries are allowed. GOLD is read-only.")
    for node in query.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise UnsafeQuery(f"{type(node).__name__.upper()} is not allowed. GOLD is read-only.")
        if isinstance(node, exp.Func):
            name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if name.startswith(_RISKY_PREFIXES):
                raise UnsafeQuery(f"The function {name}() is not allowed.")
    return text


def is_pii_column(name: str, pii_columns: set[str]) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in pii_columns)


def mask_value(value):
    if not isinstance(value, str):
        return value
    return PHONE.sub("[masked phone]", EMAIL.sub("[masked email]", value))


def mask_rows(columns: list[str], rows: list[list], pii_columns: set[str]) -> tuple[list[list], list[str]]:
    """Mask personal-data columns entirely and scrub emails and phone numbers everywhere else."""
    masked_idx = {i for i, c in enumerate(columns) if is_pii_column(c, pii_columns)}
    out = [
        ["[masked]" if i in masked_idx and v is not None else mask_value(v) for i, v in enumerate(row)]
        for row in rows
    ]
    return out, [columns[i] for i in sorted(masked_idx)]
