import json

import pytest

from test_end_to_end import _db_available

pytestmark = pytest.mark.skipif(not _db_available(), reason="needs Postgres with deploy/postgres/*.sql loaded")


def test_the_closest_approved_queries_come_first():
    from gold import db

    found = db.search_verified_queries("What was our revenue by country last year?")
    assert found and "country" in found[0]["question"].lower()
    assert found[0]["verified_by"] and found[0]["sql"].upper().startswith("SELECT")


def test_every_shipped_example_is_valid_and_held_out():
    from gold import semantic

    assert semantic.verify_queries() == []


def test_an_example_that_leaks_an_evaluation_question_is_flagged(tmp_path):
    from gold import db, semantic

    leaked = db.all_verified_queries()[0]["question"]
    evals = tmp_path / "questions.jsonl"
    evals.write_text(json.dumps({"id": "x", "question": leaked, "sql": "SELECT 1"}) + "\n")
    problems = semantic.verify_queries(str(evals))
    assert problems and "evaluation set" in problems[0]["reason"]
