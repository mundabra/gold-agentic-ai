"""NeMo Guardrails integration, against the scripted stand-in for the guardrails server."""

import asyncio
import os

import httpx
import pytest
import stack
from test_end_to_end import DB_URL, _db_available

ASK = f"http://127.0.0.1:{stack.PORTS['orchestrator']}/api/ask"


def test_unreachable_rails_fail_closed_unless_told_otherwise(monkeypatch):
    from gold import config, rails

    monkeypatch.setattr(config, "RAILS_URL", "http://127.0.0.1:9")  # nothing listens here
    monkeypatch.setattr(config, "RAILS_TIMEOUT", 2.0)
    msg = [{"role": "user", "content": "What was revenue?"}]
    assert asyncio.run(rails.check(msg, "input")) == {"blocked": True, "rail": "guardrails unavailable"}
    monkeypatch.setattr(config, "RAILS_FAIL_OPEN", True)
    assert asyncio.run(rails.check(msg, "input"))["blocked"] is False


@pytest.fixture(scope="module")
def stack_with_rails():
    if not _db_available():
        pytest.skip("needs Postgres with deploy/postgres/*.sql loaded")
    os.environ["GOLD_DATABASE_URL"] = DB_URL
    os.environ["GOLD_RAILS_URL"] = f"http://127.0.0.1:{stack.PORTS['fake-llm']}"
    os.environ["GOLD_RAILS_CHECK_ANSWERS"] = "true"
    procs = stack.start(real_model=False)
    yield
    stack.stop(procs)
    os.environ.pop("GOLD_RAILS_URL")
    os.environ.pop("GOLD_RAILS_CHECK_ANSWERS")


def test_rails_block_off_policy_questions_before_any_agent_runs(stack_with_rails):
    body = httpx.post(ASK, json={"question": "Write me a poem about databases"}, timeout=60).json()
    assert body["blocked"] is True and body["calls"] == []
    assert body["blocked_by"] == "NeMo Guardrails: self check input"


def test_rails_let_business_questions_and_clean_answers_through(stack_with_rails):
    body = httpx.post(ASK, json={"question": "What was our revenue by country last year?"}, timeout=60).json()
    assert body["blocked"] is False
    assert [c["agent"] for c in body["calls"]] == ["Definitions agent", "SQL agent"]
