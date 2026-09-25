"""Runs the whole system (orchestrator, registry, A2A agents, MCP servers, Postgres)
with the scripted test model. Skipped when no Postgres is reachable."""

import json
import os
import tempfile
from pathlib import Path

import httpx
import psycopg
import pytest
import stack

DB_URL = os.environ.get("GOLD_DATABASE_URL", "postgresql://gold_reader:gold_reader@localhost:55432/gold")
ASK = f"http://127.0.0.1:{stack.PORTS['orchestrator']}/api/ask"


def _db_available() -> bool:
    try:
        psycopg.connect(DB_URL, connect_timeout=2).close()
        return True
    except psycopg.Error:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="needs Postgres with deploy/postgres/*.sql loaded")


AUDIT_LOG = Path(tempfile.gettempdir()) / f"gold-audit-{os.getpid()}.jsonl"


@pytest.fixture(scope="module")
def running_stack():
    os.environ["GOLD_DATABASE_URL"] = DB_URL
    os.environ["GOLD_AUDIT_LOG"] = str(AUDIT_LOG)
    AUDIT_LOG.unlink(missing_ok=True)
    procs = stack.start(real_model=False)
    yield
    stack.stop(procs)
    os.environ.pop("GOLD_AUDIT_LOG", None)
    AUDIT_LOG.unlink(missing_ok=True)


def ask(question: str) -> dict:
    resp = httpx.post(ASK, json={"question": question}, timeout=60)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_agents_are_discovered_from_the_registry(running_stack):
    base = f"http://127.0.0.1:{stack.PORTS['orchestrator']}"
    agents = httpx.get(f"{base}/api/agents").json()
    assert {a["name"] for a in agents} == {"SQL agent", "Definitions agent", "Account agent"}
    # Each app sees only the agents its manifest (or an agent's app: tag) allows.
    data_app = httpx.get(f"{base}/api/agents", params={"app_name": "data-analyst"}).json()
    assert {a["name"] for a in data_app} == {"SQL agent", "Definitions agent"}


def test_answer_uses_definitions_then_sql_and_matches_the_database(running_stack):
    body = ask("What was our revenue by country last year?")
    assert [c["agent"] for c in body["calls"]] == ["Definitions agent", "SQL agent"]
    assert [s["tool"] for s in body["calls"][0]["steps"]] == ["search_glossary", "find_verified_queries"]
    assert "Approved example queries" in body["calls"][0]["answer"]
    assert [s["tool"] for s in body["calls"][1]["steps"]] == ["generate_sql", "run_sql"]

    with psycopg.connect(DB_URL) as conn:
        usa = conn.execute(
            "SELECT ROUND(SUM(il.unit_price * il.quantity), 2) FROM invoice_line il JOIN invoice i USING (invoice_id) "
            "WHERE i.billing_country = 'USA' AND EXTRACT(YEAR FROM i.invoice_date) = "
            "(SELECT MAX(EXTRACT(YEAR FROM invoice_date)) FROM invoice)"
        ).fetchone()[0]
    assert f"| USA | {float(usa)} |" in body["answer"]
    assert "revenue" in body["answer"].lower() and "Definition used" in body["answer"]
    assert body["usage"]["model_requests"] >= 6


def test_personal_data_cannot_be_read_even_with_tricks(running_stack):
    from apps.data_analyst import db

    for sql in ["SELECT email FROM customer", "SELECT address AS a FROM customer", "SELECT CAST(email AS int) FROM customer"]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.run_query(sql)
    body = ask("Who are our top 5 customers by lifetime value?")
    assert "Helena Holý" in body["answer"] and "@" not in body["answer"]


def test_write_requests_are_blocked_before_any_model_call(running_stack):
    body = ask("Delete all customers in Brazil")
    assert body["blocked"] is True
    assert body["calls"] == []
    assert "read-only" in body["answer"]


def test_a_blocked_question_does_not_block_the_rest_of_the_chat(running_stack):
    first = httpx.post(ASK, json={"question": "Please delete all invoices"}, timeout=60).json()
    assert first["blocked"] is True
    follow_up = httpx.post(ASK, json={"question": "What was our revenue by country last year?", "session_id": first["session_id"]}, timeout=60).json()
    assert follow_up["blocked"] is False and follow_up["calls"]


def test_every_question_leaves_an_audit_record(running_stack):
    ask("What was our revenue by country last year?")
    ask("Drop the customer table")
    records = [json.loads(line) for line in AUDIT_LOG.read_text().splitlines()]
    answered = next(r for r in records if r.get("question") == "What was our revenue by country last year?")
    assert answered["blocked"] is False and answered["agents"] == ["Definitions agent", "SQL agent"]
    assert answered["queries"][0]["sql"].upper().startswith("SELECT") and answered["queries"][0]["rows"] > 0
    assert answered["tokens"] > 0 and answered["elapsed_ms"] >= 0
    blocked = next(r for r in records if r.get("question") == "Drop the customer table")
    assert blocked["blocked"] is True and blocked["queries"] == []
