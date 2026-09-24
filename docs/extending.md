# Extending GOLD

GOLD is a set of small services connected by open protocols. Adding a piece means adding a service. You do not edit the orchestrator.

## Add an agent

A specialist is one file: an Agents SDK agent, an A2A Agent Card, and one line to serve it. See [`examples/trends_agent.py`](../examples/trends_agent.py):

```python
def build_agent(servers):
    return Agent(name="Trends agent", instructions=INSTRUCTIONS,
                 model=llm.model(config.AGENT_MODEL), mcp_servers=servers)

CARD = a2a_host.agent_card(
    name="Trends agent",
    description="Explains how a business metric changed between periods.",
    skills=[AgentSkill(id="explain_trend", name="Explain a trend", description="...", tags=["trends"])],
)

a2a_host.serve(CARD, a2a_host.AgentsSdkExecutor(build_agent, {"data-tools": config.DATA_MCP_URL}))
```

Try it: `docker compose --profile scripted --profile example up` starts the Trends agent next to the others. Run your own with `GOLD_PUBLIC_URL` set to the address other services use to reach it (and `GOLD_REGISTRY_TOKEN` if the registry requires one). On start-up it:

1. publishes its Agent Card at `/.well-known/agent-card.json`;
2. registers with the registry, and re-registers every 30 seconds;
3. appears to the orchestrator as a tool named `ask_trends_agent`, described by its card, on the very next question.

The orchestrator chooses agents from their descriptions, so write the card for a reader: what the agent is for, and what to send it. If an agent must always run in a set order (as Definitions runs before SQL), add that rule to the orchestrator's instructions in `gold/orchestrator/app.py`.

Agents do not have to use the Agents SDK or Python. Any service that speaks A2A and registers with `POST /agents {"url": ...}` works.

## Add a tool

Tools are MCP servers. Add a function to an existing server, or start a new one:

```python
from gold.mcp_servers import serve
from mcp.server.mcpserver import MCPServer

server = MCPServer(name="crm-tools")

@server.tool()
def account_owner(account_name: str) -> str:
    """Return the owner of a customer account."""
    ...

serve(server)
```

Give an agent the server's URL in its `AgentsSdkExecutor(build_agent, {"crm-tools": url})` mapping. Tool servers have no authentication of their own; in production, keep them on the internal network or put auth in front of them.

## Use your own database

1. **A read-only login with column grants.** Grant SELECT only on the tables and columns GOLD may read, the way `deploy/postgres/03-reader-role.sh` does for the sample. The database then enforces your data policy, whatever SQL a model writes, and the schema the model sees contains only those columns. Set `GOLD_DATABASE_URL`, and `GOLD_DB_SCHEMAS` if your tables are outside `public`.
2. **A glossary.** Create the `glossary` table from `deploy/postgres/02-glossary.sql` and replace the rows with your business terms. Each row has a term, synonyms (comma-separated phrases users actually say), the definition, a SQL hint and an owner. Terms are matched as exact phrases first, so synonyms matter. If your data lives on a read-only replica, put the glossary in a small database of its own and set `GOLD_GLOSSARY_DATABASE_URL`.
3. **Masking of free text.** Set `GOLD_PII_COLUMNS` to column-name fragments to mask as a second layer.
4. **Evaluation.** Write questions for your data (`evals/questions.jsonl`) and run `gold eval`.

GOLD's tools use PostgreSQL today. The data tools are a thin layer (`gold/db.py`: `run_query`, `describe_schema`, `search_glossary`). To support another engine, implement those three functions for it, set `GOLD_SQL_DIALECT` to its SQLGlot dialect name, and describe the dialect in `GOLD_SQL_SYSTEM_PROMPT`.

## Use a different model

Change configuration, not code:

- directly: `GOLD_LLM_BASE_URL` and the three `GOLD_*_MODEL` settings;
- through the gateway: edit `deploy/litellm/config.yaml` (or `gateway.models` in the Helm values), and GOLD keeps asking for `gold-general` and `gold-sql`.

Then run `gold eval` and `gold bench` to confirm the change did not make answers worse or slower.

## Settings

| Variable | Default | Purpose |
|---|---|---|
| `GOLD_LLM_BASE_URL` | `http://litellm:4000/v1` | The OpenAI-compatible endpoint for every model call |
| `GOLD_LLM_API_KEY` | `sk-gold-local` | Its API key |
| `GOLD_ORCHESTRATOR_MODEL` / `GOLD_AGENT_MODEL` | `gold-general` | Tool-calling models for the orchestrator and the agents |
| `GOLD_SQL_MODEL` | `gold-sql` | The SQL model (`gold-sql`) |
| `GOLD_SQL_SYSTEM_PROMPT` | built-in | The SQL model's system prompt (match your fine-tune) |
| `GOLD_SQL_INCLUDE_SCHEMA` | `true` | Append the schema to the SQL prompt |
| `GOLD_SQL_PASS_DEFINITIONS` | `true` | Append business definitions to the question |
| `GOLD_SQL_MAX_TOKENS` | `2048` | Output budget (reasoning models need room) |
| `GOLD_SQL_EXTRA_BODY` | empty | JSON added to every SQL-model request, e.g. `{"chat_template_kwargs": {"enable_thinking": false}}` to turn reasoning off |
| `GOLD_AGENT_EXTRA_BODY` | empty | JSON added to every orchestrator and agent model request |
| `GOLD_DATABASE_URL` | `postgresql://gold_reader:…@postgres:5432/gold` | Read-only database login (the CLI defaults to `localhost:5432`) |
| `GOLD_GLOSSARY_DATABASE_URL` | same as above | Separate database for the glossary |
| `GOLD_DB_SCHEMAS` | `public` | Schemas the SQL agent may see |
| `GOLD_SQL_DIALECT` | `postgres` | SQLGlot dialect used to parse and check queries |
| `GOLD_MAX_ROWS` | `50` | Rows returned to the agent per query |
| `GOLD_MAX_QUERY_COST` | `1000000` | Dry-run limit on the planner's cost estimate (0 turns it off) |
| `GOLD_PII_COLUMNS` | `email,phone,fax,address` | Column-name fragments that are masked |
| `GOLD_REGISTRY_URL`, `GOLD_DATA_MCP_URL`, `GOLD_GLOSSARY_MCP_URL` | service names | Where the services find each other |
| `GOLD_PUBLIC_URL` | `http://localhost:8000` | This agent's own address, published in its Agent Card |
| `GOLD_REGISTRY_TOKEN` | empty | Shared secret agents present to register (empty: open registration) |
| `GOLD_SESSION_DB_URL` | a SQLite file | Conversation memory; a SQLAlchemy URL such as `postgresql+asyncpg://…` for a shared store |
| `GOLD_RAILS_URL` and other `GOLD_RAILS_*` | empty (off) | Optional NVIDIA NeMo Guardrails ([guardrails](guardrails.md#run-it)) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | empty | OpenTelemetry OTLP/HTTP endpoint; setting it turns tracing on ([observability](observability.md)) |
| `GOLD_TRACE_CONTENT` | `false` | Put prompts, SQL and results into spans |
| `GOLD_AUDIT_LOG` | empty | Also append the JSON audit trail to this file (it always goes to stdout) |
| `GOLD_OPENAI_TRACING` | `false` | Opt in to the Agents SDK's trace export to OpenAI (ignored when OpenTelemetry tracing is on) |
