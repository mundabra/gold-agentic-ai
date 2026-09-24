"""A scripted, OpenAI-compatible stand-in model. It is NOT a real model.

It lets the whole system (orchestrator, A2A agents, MCP tools, Postgres) run
end to end with no API key and no GPU: for the automated tests, and for a
first look at GOLD before you connect a real model. It follows the same
tool-calling steps a real model is instructed to follow and returns canned SQL,
so only the example questions in the chat UI get meaningful answers.

    gold serve scripted-model
"""

import json
import time
import uuid

import uvicorn
from fastapi import FastAPI, Request

app = FastAPI(title="GOLD scripted test model")

CANNED_SQL = [
    (
        ("lifetime value", "top 5 customers"),
        "SELECT c.first_name || ' ' || c.last_name AS customer, c.country, "
        "ROUND(SUM(il.unit_price * il.quantity), 2) AS lifetime_value "
        "FROM customer c JOIN invoice i ON i.customer_id = c.customer_id "
        "JOIN invoice_line il ON il.invoice_id = i.invoice_id "
        "GROUP BY c.customer_id, c.first_name, c.last_name, c.country "
        "ORDER BY lifetime_value DESC LIMIT 5",
    ),
    (
        ("genre",),
        "SELECT g.name AS genre, ROUND(SUM(il.unit_price * il.quantity), 2) AS revenue "
        "FROM invoice_line il JOIN invoice i ON i.invoice_id = il.invoice_id "
        "JOIN track t ON t.track_id = il.track_id JOIN genre g ON g.genre_id = t.genre_id "
        "WHERE EXTRACT(YEAR FROM i.invoice_date) = (SELECT MAX(EXTRACT(YEAR FROM invoice_date)) FROM invoice) "
        "GROUP BY g.name ORDER BY revenue DESC LIMIT 1",
    ),
    (
        ("active customers",),
        "SELECT COUNT(DISTINCT customer_id) AS active_customers FROM invoice "
        "WHERE invoice_date > (SELECT MAX(invoice_date) FROM invoice) - INTERVAL '12 months'",
    ),
    (
        ("revenue by country",),
        "SELECT i.billing_country AS country, ROUND(SUM(il.unit_price * il.quantity), 2) AS revenue "
        "FROM invoice_line il JOIN invoice i ON i.invoice_id = il.invoice_id "
        "WHERE EXTRACT(YEAR FROM i.invoice_date) = (SELECT MAX(EXTRACT(YEAR FROM invoice_date)) FROM invoice) "
        "GROUP BY i.billing_country ORDER BY revenue DESC",
    ),
]
DEFAULT_SQL = "SELECT COUNT(*) AS invoices FROM invoice"


def _tool_call(name: str, arguments: dict) -> dict:
    return {
        "id": "call_" + uuid.uuid4().hex[:12],
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _text(content) -> str:
    """Message content can be a string or a list of content parts."""
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


def _history(messages: list[dict]) -> tuple[str, list[tuple[str, str]]]:
    """Return the first user message and (tool name, tool output) pairs so far."""
    user = next((_text(m.get("content")) for m in messages if m.get("role") == "user"), "")
    names = {}
    for m in messages:
        for call in m.get("tool_calls") or []:
            names[call["id"]] = call["function"]["name"]
    done = [(names.get(m.get("tool_call_id"), "?"), _text(m.get("content"))) for m in messages if m.get("role") == "tool"]
    return user, done


def _markdown_table(result_json: str) -> str:
    try:
        result = json.loads(result_json)
    except ValueError:
        return result_json
    if "error" in result:
        return f"The query was refused: {result.get('reason')}"
    cols = result["columns"]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in result["rows"][:20]]
    return "\n".join(lines)


def decide(body: dict) -> dict:
    messages = body.get("messages", [])
    tools = {t["function"]["name"] for t in body.get("tools") or []}
    user, done = _history(messages)
    called = [name for name, _ in done]
    output = dict(done)

    if "ask_definitions_agent" in tools:  # orchestrator
        if "ask_definitions_agent" not in called:
            return {"tool_calls": [_tool_call("ask_definitions_agent", {"request": f"Define the business terms in: {user}"})]}
        if "ask_sql_agent" not in called:
            request = f"Question: {user}\n\nDefinitions:\n{output['ask_definitions_agent']}"
            return {"tool_calls": [_tool_call("ask_sql_agent", {"request": request})]}
        return {"content": f"Here is the answer.\n\n{output['ask_sql_agent']}\n\nDefinition used:\n{output['ask_definitions_agent']}"}

    if "search_glossary" in tools:  # definitions agent
        if "search_glossary" not in called:
            return {"tool_calls": [_tool_call("search_glossary", {"terms": user})]}
        matches = json.loads(output["search_glossary"]).get("matches", [])
        bullets = [f"- **{m['term']}**: {m['definition']} (owner: {m['owner']})" for m in matches]
        return {"content": "\n".join(bullets) or "No agreed definition found."}

    if "generate_sql" in tools:  # SQL agent
        if "generate_sql" not in called:
            return {"tool_calls": [_tool_call("generate_sql", {"question": user})]}
        if "run_sql" not in called:
            return {"tool_calls": [_tool_call("run_sql", {"sql": output["generate_sql"]})]}
        return {"content": f"```sql\n{output['generate_sql']}\n```\n\n{_markdown_table(output['run_sql'])}"}

    # No tools: this is the dedicated SQL model being asked for a query.
    lowered = user.lower()
    for keywords, sql in CANNED_SQL:
        if any(k in lowered for k in keywords):
            return {"content": sql}
    return {"content": DEFAULT_SQL}


@app.post("/v1/chat/completions")
async def chat(request: Request) -> dict:
    body = await request.json()
    reply = decide(body)
    message = {"role": "assistant", "content": reply.get("content")}
    if "tool_calls" in reply:
        message["tool_calls"] = reply["tool_calls"]
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex[:12],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "scripted"),
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if "tool_calls" in reply else "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


@app.post("/v1/checks")
async def checks(request: Request) -> dict:
    """Stand-in for a NeMo Guardrails server's /v1/checks, for tests: blocks poems and emails."""
    body = await request.json()
    text = " ".join(_text(m.get("content")) for m in body.get("messages", []) if m.get("role") != "user"
                    or "input" in body.get("guardrails", {}).get("rail_types", ["input"])).lower()
    if "poem" in text:
        return {"status": "blocked", "content": "", "rail": "self check input"}
    if "@" in text:
        return {"status": "blocked", "content": "", "rail": "regex check output"}
    return {"status": "passed", "content": ""}


@app.get("/v1/models")
def models() -> dict:
    return {"object": "list", "data": [{"id": m, "object": "model"} for m in ("gold-general", "gold-sql")]}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


def main() -> None:
    from gold import config

    uvicorn.run(app, host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
