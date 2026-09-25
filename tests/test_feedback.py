"""The feedback loop end to end: answer -> "Not right" with corrected SQL -> analyst promotes -> verified query."""

import os

import httpx
import psycopg
import pytest
import stack
from test_end_to_end import DB_URL, _db_available

BASE = f"http://127.0.0.1:{stack.PORTS['orchestrator']}"
FEEDBACK_URL = DB_URL.replace("gold_reader:gold_reader", "gold_feedback:gold_feedback")
CURATOR_URL = DB_URL.replace("gold_reader:gold_reader", "gold_curator:gold_curator")
ADMIN_URL = DB_URL.replace("gold_reader:gold_reader", "gold_admin:gold_admin")
NEW_QUESTION = "Which five countries had the most invoices overall?"


@pytest.fixture(scope="module")
def stack_with_feedback():
    if not _db_available():
        pytest.skip("needs Postgres with deploy/postgres/*.sql loaded")
    os.environ.update(GOLD_DATABASE_URL=DB_URL, GOLD_FEEDBACK_DATABASE_URL=FEEDBACK_URL, GOLD_CURATOR_DATABASE_URL=CURATOR_URL)
    procs = stack.start(real_model=False)
    yield
    stack.stop(procs)
    for key in ("GOLD_FEEDBACK_DATABASE_URL", "GOLD_CURATOR_DATABASE_URL"):
        os.environ.pop(key)
    with psycopg.connect(ADMIN_URL) as conn:  # leave the shared test database as it was
        conn.execute("DELETE FROM verified_queries WHERE question = %s", (NEW_QUESTION,))
        conn.execute("DELETE FROM feedback")


def test_feedback_is_announced_and_answers_carry_an_id(stack_with_feedback):
    assert httpx.get(f"{BASE}/api/features").json() == {"feedback": True}
    body = httpx.post(f"{BASE}/api/ask", json={"question": "What was our revenue by country last year?"}, timeout=60).json()
    assert len(body["answer_id"]) == 32


def test_unsafe_corrections_are_refused(stack_with_feedback):
    resp = httpx.post(f"{BASE}/api/feedback", json={"answer_id": "x", "question": "q", "rating": "down",
                                                   "corrected_sql": "DELETE FROM customer"})
    assert resp.status_code == 400 and "read-only" in resp.json()["detail"]


def test_a_correction_becomes_a_verified_query(stack_with_feedback):
    from apps.data_analyst import curation, db
    from gold import config, feedback

    corrected = "SELECT billing_country, COUNT(*) AS invoices FROM invoice GROUP BY billing_country ORDER BY invoices DESC LIMIT 5"
    resp = httpx.post(f"{BASE}/api/feedback", json={"answer_id": "a1", "question": NEW_QUESTION, "sql": "SELECT 1",
                                                   "rating": "down", "comment": "Counted customers, not invoices",
                                                   "corrected_sql": corrected})
    assert resp.status_code == 200

    config.CURATOR_DATABASE_URL = CURATOR_URL
    [item] = [i for i in feedback.list_items() if i["question"] == NEW_QUESTION]
    assert item["rating"] == "down" and item["corrected_sql"] == corrected
    result = curation.promote(item["id"], "analyst@example.com")
    assert result["problems"] == []
    assert any(v["question"] == NEW_QUESTION for v in db.all_verified_queries())
    assert feedback.list_items("promoted")[0]["id"] == item["id"]
    with pytest.raises(feedback.FeedbackError):
        curation.promote(item["id"], "analyst@example.com")  # already promoted


def test_the_feedback_login_cannot_read_and_the_query_login_cannot_see_feedback(stack_with_feedback):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with psycopg.connect(FEEDBACK_URL) as conn:
            conn.execute("SELECT * FROM feedback")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with psycopg.connect(DB_URL) as conn:
            conn.execute("SELECT * FROM feedback")
