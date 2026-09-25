import json
import shutil
from pathlib import Path

import pytest
from test_end_to_end import _db_available

from apps.data_analyst import aiperf, settings

FIXTURE = Path(__file__).parent / "fixtures" / "aiperf_concurrency_4.json"


def test_summary_reads_a_real_aiperf_export(tmp_path):
    level = tmp_path / "concurrency_4"
    level.mkdir()
    shutil.copy(FIXTURE, level / "profile_export_aiperf.json")
    [row] = aiperf.summarize(str(tmp_path), slo_ms=3000)
    assert row["concurrency"] == 4 and row["ok"] == 24 and row["errors"] == 0
    assert 0 < row["ttft_p50_s"] < row["first_answer_token_p50_s"] < row["p99_s"]
    assert 0 < row["reasoning_pct"] <= 100
    table = aiperf.to_markdown([row], 3000)
    assert "| 4 | 24 | 0 |" in table and "Under 3 s" in table


@pytest.mark.skipif(not _db_available(), reason="needs Postgres with deploy/postgres/*.sql loaded")
def test_payloads_are_the_production_sql_requests(tmp_path):
    from apps.data_analyst import sql_model

    out = tmp_path / "payloads.jsonl"
    n = aiperf.write_payloads(settings.EVAL_QUESTIONS, str(out), model="gold-sql")
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert n == len(lines) == 20
    first = lines[0]
    assert first["model"] == "gold-sql" and first["stream"] is True
    assert first["messages"][0]["content"].startswith(sql_model.DEFAULT_SQL_PROMPT)
    assert "Schema:" in first["messages"][0]["content"]
    assert first["messages"][1]["content"].startswith("What was our revenue by country last year?")
