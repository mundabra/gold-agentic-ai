from apps.data_analyst import settings, sql_model
from gold import config
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
    monkeypatch.setattr(settings, "SQL_SYSTEM_PROMPT", "You are a SQL assistant.")
    monkeypatch.setattr(settings, "SQL_PASS_DEFINITIONS", False)
    msgs = sql_model.messages("Revenue by country?", "revenue = price x qty")
    assert msgs == [
        {"role": "system", "content": "You are a SQL assistant."},
        {"role": "user", "content": "Revenue by country?"},
    ]


def test_tool_names_are_valid_function_names():
    assert tool_name("SQL agent") == "ask_sql_agent"
    assert tool_name("Definitions agent") == "ask_definitions_agent"
    assert tool_name("Forecast Agent (beta)") == "ask_forecast_agent_beta"


def test_extra_body_reaches_the_sql_model_request(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from gold import llm

    sent = {}

    async def fake_create(**kwargs):
        sent.update(kwargs)
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="SELECT 1"))], usage=usage)

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
    monkeypatch.setattr(llm, "client", lambda: fake_client)
    monkeypatch.setattr(settings, "SQL_EXTRA_BODY", {"chat_template_kwargs": {"enable_thinking": False}})
    sql, usage = asyncio.run(sql_model.generate("How many tracks?"))
    assert sql == "SELECT 1" and usage.total_tokens == 15
    assert sent["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


def test_agent_settings_carry_the_agent_extra_body(monkeypatch):
    from gold import llm

    monkeypatch.setattr(config, "AGENT_EXTRA_BODY", {"reasoning_effort": "low"})
    assert llm.settings().extra_body == {"reasoning_effort": "low"}
    monkeypatch.setattr(config, "AGENT_EXTRA_BODY", {})
    assert llm.settings().extra_body is None
