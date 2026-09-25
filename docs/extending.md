# Extending GOLD

GOLD is a set of small services connected by open protocols. Adding a piece means adding a service or an app. You do not edit the platform.

- **A new use case:** [build an app](build-an-app.md). An app is a folder with a manifest, its agents and its tools.
- **More for an existing app:** add an agent or a tool (below).
- **Talk to your Data on your own data:** your database, glossary and verified queries (below).

## Add an agent

A specialist is one file: an Agents SDK agent, an A2A Agent Card, and one line to serve it. See [`apps/data_analyst/examples/trends_agent.py`](../apps/data_analyst/examples/trends_agent.py):

```python
def build_agent(servers):
    return Agent(name="Trends agent", instructions=INSTRUCTIONS,
                 model=llm.model(config.AGENT_MODEL), mcp_servers=servers)

CARD = a2a_host.agent_card(
    name="Trends agent",
    description="Explains how a business metric changed between periods.",
    skills=[AgentSkill(id="explain_trend", name="Explain a trend", description="...",
                       tags=["trends", "app:data-analyst"])],   # joins the Talk to your Data app
)

a2a_host.serve(CARD, a2a_host.AgentsSdkExecutor(build_agent, {"data-tools": settings.DATA_MCP_URL}))
```

Try it: `docker compose --profile scripted --profile example up` starts the Trends agent next to the others. Run your own with `GOLD_PUBLIC_URL` set to the address other services use to reach it (and `GOLD_REGISTRY_TOKEN` if the registry requires one). On start-up it:

1. publishes its Agent Card at `/.well-known/agent-card.json`;
2. registers with the registry, and re-registers every 30 seconds;
3. appears to the orchestrator as a tool named `ask_trends_agent`, described by its card, on the very next question of every app it belongs to: the apps that list it in their `app.yaml`, and the app named in an `app:<name>` skill tag.

The orchestrator chooses agents from their descriptions, so write the card for a reader: what the agent is for, and what to send it. If an agent must always run in a set order (as Definitions runs before SQL), add that rule to the app's `instructions.md`.

Agents do not have to use the Agents SDK or Python. Any service that speaks A2A and registers with `POST /agents {"url": ...}` works.

## Add a tool

Tools are MCP servers. Add a function to an existing server, or start a new one:

```python
from mcp.server.mcpserver import Context, MCPServer
from gold.mcp import READ_ONLY, current_user, serve

server = MCPServer(name="finance-tools")

@server.tool(annotations=READ_ONLY)
def budget_owner(cost_center: str, ctx: Context) -> str:
    """Return the owner of a cost center."""
    user = current_user(ctx)   # the signed-in user the agent acts for
    ...

serve(server)
```

Give an agent the server's URL in its `AgentsSdkExecutor(build_agent, {"finance-tools": url})` mapping. A tool that changes something must go through [approvals](approvals.md). Tool servers check the signed user context but have no network authentication of their own; in production, keep them on the internal network (the Helm chart's NetworkPolicies do this).

## Use your own database

1. **A read-only login with column grants.** Grant SELECT only on the tables and columns GOLD may read, the way `deploy/postgres/04-reader-role.sh` does for the sample. The database then enforces your data policy, whatever SQL a model writes, and the schema the model sees contains only those columns. Set `GOLD_DATABASE_URL`, and `GOLD_DB_SCHEMAS` if your tables are outside `public`.
2. **A glossary.** Create the `glossary` table from `deploy/postgres/02-glossary.sql` and replace the rows with your business terms. Each row has a term, synonyms (comma-separated phrases users actually say), the definition, a SQL hint and an owner. Terms are matched as exact phrases first, so synonyms matter. If your data lives on a read-only replica, put the glossary in a small database of its own and set `GOLD_GLOSSARY_DATABASE_URL`.
3. **Masking of free text.** Set `GOLD_PII_COLUMNS` to column-name fragments to mask as a second layer.
4. **Evaluation.** Write questions for your data (`apps/data_analyst/evals/questions.jsonl`) and run `gold eval`.

GOLD's tools use PostgreSQL today. The data tools are a thin layer (`apps/data_analyst/db.py`: `run_query`, `describe_schema`, `search_glossary`). To support another engine, implement those three functions for it, set `GOLD_SQL_DIALECT` to its SQLGlot dialect name, and describe the dialect in `GOLD_SQL_SYSTEM_PROMPT`.

## Add verified queries

Verified queries are questions an analyst has answered with SQL they vouch for. For each question, the Definitions agent finds the approved examples whose wording overlaps most (at least 60% of the question's meaningful words), and the SQL agent gets them as worked examples next to the definitions.

Add them to the `verified_queries` table (see `deploy/postgres/02-glossary.sql`):

```sql
INSERT INTO verified_queries (question, sql, verified_by) VALUES
  ('What was net revenue by region last quarter?', 'SELECT ...', 'finance.analytics@your-company.com');
```

Then run `gold verify-queries`. It checks that every example is read-only, runs, and is **not** one of your evaluation questions, because an example that repeats an evaluation question makes `gold eval` an unfair test. CI runs it on every change.

Good examples cover your trickiest conventions, such as fiscal periods, net versus gross, and what counts as "active". Twenty good ones beat two hundred similar ones.

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
| `GOLD_REGISTRY_URL`, `GOLD_DATA_MCP_URL`, `GOLD_GLOSSARY_MCP_URL`, `GOLD_CRM_MCP_URL` | service names | Where the services find each other |
| `GOLD_APPS` | empty (all) | Serve only these apps, comma-separated |
| `GOLD_DEFAULT_APP` | the first app | The app the UI opens on and `/api/ask` uses when none is named |
| `GOLD_APP_PACKAGES` | empty | Extra Python packages to find apps in (apps in your own repository) |
| `GOLD_APPROVAL_TTL_SECONDS` | `3600` | How long a proposed action can be approved |
| `GOLD_CRM_DATABASE_URL` | `postgresql://gold_crm_writer:…@postgres:5432/gold` | Sales copilot: the login that can only add CRM activities (the CRM tool server only) |
| `GOLD_KNOWLEDGE_URL`, `GOLD_EMBEDDING_MODEL` and other knowledge settings | pgvector in the bundled Postgres, `gold-embed` | Knowledge retrieval ([knowledge](knowledge.md#settings)) |
| `GOLD_DEMO_USERS` | four sample users | Demo sign-in: `user=group|group` entries, comma-separated |
| `GOLD_AT_RISK_DAYS` | `180` | Sales copilot: days without a purchase before an account needs attention |
| `GOLD_PUBLIC_URL` | `http://localhost:8000` | This agent's own address, published in its Agent Card |
| `GOLD_REGISTRY_TOKEN` | empty | Shared secret agents present to register (empty: open registration) |
| `GOLD_SESSION_DB_URL` | a SQLite file | Conversation memory; a SQLAlchemy URL such as `postgresql+asyncpg://…` for a shared store |
| `GOLD_AUTH_MODE`, `GOLD_IDENTITY_SECRET`, `GOLD_REQUIRE_IDENTITY` and other identity settings | `none` | Who is asking, enforced by row-level security ([identity](identity.md#settings)) |
| `GOLD_RAILS_URL` and other `GOLD_RAILS_*` | empty (off) | Optional NVIDIA NeMo Guardrails ([guardrails](guardrails.md#run-it)) |
| `GOLD_FEEDBACK_DATABASE_URL` | empty (off) | Insert-only login for the feedback queue (orchestrator only) |
| `GOLD_CURATOR_DATABASE_URL` | empty | Reviewers' login for `gold feedback ...` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | empty | OpenTelemetry OTLP/HTTP endpoint; setting it turns tracing on ([observability](observability.md)) |
| `GOLD_TRACE_CONTENT` | `false` | Put prompts, SQL and results into spans |
| `GOLD_AUDIT_LOG` | empty | Also append the JSON audit trail to this file (it always goes to stdout) |
| `GOLD_OPENAI_TRACING` | `false` | Opt in to the Agents SDK's trace export to OpenAI (ignored when OpenTelemetry tracing is on) |
