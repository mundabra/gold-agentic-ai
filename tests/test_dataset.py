import json

import pytest

from test_end_to_end import _db_available

pytestmark = pytest.mark.skipif(not _db_available(), reason="needs Postgres with deploy/postgres/*.sql loaded")


def test_dataset_uses_the_production_prompt_and_refuses_eval_questions(tmp_path):
    from gold import dataset, sql_model

    pairs = tmp_path / "pairs.jsonl"
    rows = [
        {"question": "How many tracks are there?", "sql": "SELECT COUNT(*) FROM track"},
        {"question": "What was total revenue last year?", "sql": "SELECT 1"},  # an evaluation question
        {"question": "Broken query", "sql": "SELECT nope FROM nowhere"},
    ]
    pairs.write_text("".join(json.dumps(r) + "\n" for r in rows))
    summary = dataset.build(str(pairs), str(tmp_path / "out"), val_fraction=0)

    reasons = {d["question"]: d["reason"] for d in summary["dropped"]}
    assert reasons["What was total revenue last year?"] == "in the evaluation set"
    assert reasons["Broken query"].startswith("SQL does not run")

    example = json.loads((tmp_path / "out" / "train.jsonl").read_text().splitlines()[0])
    prompt = example["messages"][:2]
    assert prompt[0]["content"].startswith(sql_model.DEFAULT_SQL_PROMPT)
    assert prompt[1]["content"] == "How many tracks are there?"
    assert example["messages"][2] == {"role": "assistant", "content": "SELECT COUNT(*) FROM track"}


def test_dry_run_refuses_runaway_queries(monkeypatch):
    from gold import config, db
    from gold.guards import UnsafeQuery

    cross_join = "SELECT COUNT(*) FROM invoice_line a, invoice_line b, invoice_line c"
    monkeypatch.setattr(config, "MAX_QUERY_COST", 1_000_000)
    with pytest.raises(UnsafeQuery, match="too expensive"):
        db.run_query(cross_join)
    assert db.run_query("SELECT COUNT(*) FROM invoice")["rows"] == [[412]]


def test_conversation_memory_persists_in_the_session_store(tmp_path, monkeypatch):
    import asyncio

    from gold import config, sessions

    monkeypatch.setattr(config, "SESSION_DB_URL", str(tmp_path / "sessions.sqlite"))
    sessions._open.clear()
    first = sessions.get("chat-1")
    asyncio.run(first.add_items([{"role": "user", "content": "What was revenue last year?"}]))
    sessions._open.clear()  # a restart: nothing cached in memory
    again = sessions.get("chat-1")
    assert asyncio.run(again.get_items())[0]["content"] == "What was revenue last year?"
    assert asyncio.run(sessions.get("chat-2").get_items()) == []


def test_shared_session_store_in_postgres(monkeypatch):
    import asyncio

    pytest.importorskip("asyncpg")
    from gold import config, sessions

    monkeypatch.setattr(config, "SESSION_DB_URL", "postgresql+asyncpg://gold_admin:gold_admin@localhost:55432/gold")
    sessions._engine.cache_clear()
    sessions._open.clear()

    async def roundtrip():
        s = sessions.get("pg-chat")
        await s.clear_session()
        await s.add_items([{"role": "user", "content": "hello"}])
        items = await s.get_items()
        await sessions._engine().dispose()
        return items

    assert asyncio.run(roundtrip())[0]["content"] == "hello"
    sessions._engine.cache_clear()
    sessions._open.clear()
