from gold import config, sql_model
from gold.orchestrator.a2a_tools import tool_name


def test_extract_sql_handles_fences_and_chatter():
    assert sql_model.extract_sql("```sql\nSELECT 1;\n```") == "SELECT 1"
    assert sql_model.extract_sql("Sure! Here you go: select 2") == "select 2"
    assert sql_model.extract_sql("WITH a AS (SELECT 1) SELECT * FROM a;") == "WITH a AS (SELECT 1) SELECT * FROM a"
    assert sql_model.extract_sql("Here is the query with the totals:\nSELECT 1") == "SELECT 1"
    assert sql_model.extract_sql("<think>I will select the invoice table.</think>SELECT 2") == "SELECT 2"


def test_prompt_contract_is_configurable(monkeypatch):
    msgs = sql_model.messages("Revenue by country?", "revenue = price x qty", "invoice(total numeric)")
    assert msgs[0]["content"].startswith(sql_model.DEFAULT_SQL_PROMPT)
    assert "Schema:\ninvoice(total numeric)" in msgs[0]["content"]
    assert "revenue = price x qty" in msgs[1]["content"]

    # A fine-tuned model trained on bare questions gets exactly its training prompt.
    monkeypatch.setattr(config, "SQL_SYSTEM_PROMPT", "You are a SQL assistant.")
    monkeypatch.setattr(config, "SQL_PASS_DEFINITIONS", False)
    msgs = sql_model.messages("Revenue by country?", "revenue = price x qty")
    assert msgs == [
        {"role": "system", "content": "You are a SQL assistant."},
        {"role": "user", "content": "Revenue by country?"},
    ]


def test_tool_names_are_valid_function_names():
    assert tool_name("SQL agent") == "ask_sql_agent"
    assert tool_name("Definitions agent") == "ask_definitions_agent"
    assert tool_name("Forecast Agent (beta)") == "ask_forecast_agent_beta"
