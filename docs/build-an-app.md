# Build an app

An app is what people use: "Talk to your Data", "Sales copilot", or yours. The platform (`gold/`) is the same for every app. It provides sign-in, guardrails, conversation memory, approvals, audit, tracing, feedback, the chat UI, the API and the deployment. An app provides what is specific to it: instructions, agents and tools.

This page builds an app step by step, using the [Sales copilot](../apps/sales_copilot/) as the worked example. It took five files.

```text
apps/sales_copilot/
  app.yaml               the manifest: what the platform needs to know
  instructions.md        what the app's orchestrator is told to do
  agents/account_agent.py   an A2A agent (Agents SDK)
  tools/crm_tools.py     an MCP tool server
  crm.py, settings.py    the app's own code and settings
  scripted.py            optional: canned replies so the app runs with no model (tests, demos)
```

## 1. The manifest

```yaml
name: sales-copilot                # the id in the API, audit records and sessions
title: Sales copilot               # shown in the app picker
description: Your accounts at a glance. ...
instructions: instructions.md
read_only: false                   # true adds the platform's guardrail that blocks change requests

# Registry agents this app's orchestrator may call, by Agent Card name.
# Apps can share agents: the Definitions and SQL agents belong to Talk to your Data.
agents: [Account agent, Definitions agent, SQL agent]

# What `gold serve <component>` runs. Each becomes one container in Compose and one Deployment in Helm.
components:
  account-agent: apps.sales_copilot.agents.account_agent
  mcp-crm: apps.sales_copilot.tools.crm_tools

scripted: apps.sales_copilot.scripted   # optional
ui:
  placeholder: Which of my accounts need attention?
  examples: [Which of my accounts need attention?, Brief me on Luís Gonçalves]
```

Optional keys: `knowledge` (document collections your agents search with `search_knowledge`, loaded into pgvector on start-up; see [knowledge](knowledge.md)), `cli` (a module with `register(subparsers, groups)` and `run(args)` that adds `gold` commands; the data app adds `gold eval` this way) and `hooks` (app functions the platform calls at set points, such as `check_correction` for feedback).

`gold apps` lists what the platform found. Apps live in the `apps` package, or in your own package: set `GOLD_APP_PACKAGES=your_company_apps` and keep your apps in your own repository. `GOLD_APPS` limits which apps are served.

## 2. The instructions

`instructions.md` is the system prompt of the app's orchestrator agent. It decides which agent handles what. Keep it short and specific:

```markdown
You are the Sales copilot. You help a sales rep look after their own accounts.
- Anything about the rep's accounts: ask the Account agent. Pass the request in full.
- Company-wide numbers: ask the Definitions agent, then the SQL agent.
When the Account agent proposes logging an activity, nothing has been saved yet: say it is waiting
for the rep's approval in the app.
```

## 3. Tools: an MCP server

Tools do the work, so the rules live there, not in prompts. Each tool is a function on an `MCPServer`:

```python
from gold.mcp import READ_ONLY, WRITES, current_user, serve

server = MCPServer(name="gold-crm-tools")

@server.tool(annotations=READ_ONLY)
def account_brief(ctx: Context, customer_id: int) -> str:
    """Everything a rep needs before a call: figures, favourite genres, recent orders and activities."""
    user = current_user(ctx)                 # the signed-in user, verified
    return json.dumps(crm.brief(user, customer_id))
```

- **Identity.** `current_user(ctx)` returns the user the agent is acting for, from a signed context the platform attaches to every call. Pass it to the database (`gold.pg.act_as(cursor, user)`) and row-level security does the rest: the Sales copilot shows each rep only their accounts without a single `WHERE rep = ...` in the code.
- **Typed tools beat free-form SQL** when the questions are known. The Sales copilot never runs model-written SQL; each tool is one parameterized query.
- **Return tables as `{"columns": [...], "rows": [...]}`** and the UI draws a chart from them.

### Tools that change things

A tool that writes calls `approvals.gate()` first. Without an approval it returns a proposal and does nothing:

```python
@server.tool(annotations=WRITES)
def log_activity(ctx: Context, customer_id: int, kind: str, note: str, follow_up_on: str | None = None) -> str:
    """Log a call, email, meeting or note. Returns a proposal the rep must approve."""
    user = current_user(ctx)
    args = {"customer_id": customer_id, "kind": kind, "note": note, "follow_up_on": follow_up_on}
    gate = approvals.gate(ctx, "log_activity", args, f"Log a {kind} with ...", user)
    if not gate.approved:
        return json.dumps(gate.proposal)     # the UI shows Approve / Reject
    crm.add_activity(user, **args, action_id=gate.action_id)   # action_id: idempotency key
    return json.dumps({"status": "done", "message": "Logged."})
```

The UI shows the proposal with Approve and Reject. On Approve the platform calls the same tool with a one-time approval for exactly those arguments. Use `gate.action_id` as an idempotency key (a unique column), so an approval replayed does nothing twice. See [approvals](approvals.md) for how it is secured.

Give write tools their own database login with only the rights they need. The Sales copilot's `gold_crm_writer` can insert CRM activities, only for accounts the user can see, and nothing else ([06-sales.sh](../deploy/postgres/06-sales.sh)).

## 4. Agents: A2A services

An agent is an Agents SDK `Agent`, an Agent Card, and one call to serve it:

```python
def build_agent(servers):
    return Agent(name="Account agent", instructions=INSTRUCTIONS,
                 model=llm.model(config.AGENT_MODEL), model_settings=llm.settings(), mcp_servers=servers)

CARD = a2a_host.agent_card(name="Account agent", description="Knows the signed-in sales rep's accounts ...",
                           skills=[AgentSkill(id="manage_accounts", name="Manage my accounts", ...)])

def main():
    a2a_host.serve(CARD, a2a_host.AgentsSdkExecutor(build_agent, {"crm-tools": settings.CRM_MCP_URL}))
```

On start-up the agent publishes its card, registers with the registry and keeps its registration fresh. The orchestrator sees it as a tool (`ask_account_agent`) on the next question of any app that lists it. The card's description is what the orchestrator reads to decide when to call it, so write it for that reader.

An agent can also join an app without a manifest change: give one of its skills the tag `app:<app-name>` ([example](../apps/data_analyst/examples/trends_agent.py)). Agents don't have to be Python: anything that speaks A2A and registers works.

## 5. Settings

Read settings from environment variables in the app's `settings.py`, with `gold.config.env`:

```python
CRM_MCP_URL = env("GOLD_CRM_MCP_URL", "http://mcp-crm:8000/mcp")
```

Platform settings (model endpoint, identity, guardrails, tracing) apply to every app with no work.

## 6. Run it

**Locally and in tests:** add the components to `tests/stack.py` (a port each), then `python tests/stack.py` runs everything with the scripted model.

**Docker Compose:** add a service per component. They share one image; only the command differs:

```yaml
  mcp-crm:
    <<: *gold
    command: ["serve", "mcp-crm"]
    environment:
      <<: *gold-env
      GOLD_PUBLIC_URL: http://mcp-crm:8000   # approvals come back here
```

**Helm:** add each component under `components:` in `values.yaml` (`account-agent: { replicas: 1 }`). If it needs a secret, add it to the lists at the top of `templates/components.yaml`; with NetworkPolicies on, add who may call it in `templates/networkpolicy.yaml`. A write tool must accept calls from the orchestrator, which runs approved actions.

## 7. Test it

- **Scripted replies** (`scripted.py`) let the whole app run with no model. The platform's scripted model asks each app's `decide(turn)` in turn; return `None` for requests that aren't yours. Match on `turn.system` (your orchestrator's instructions) and `turn.tools` (your agent's tools).
- **End to end:** [`tests/test_sales_copilot.py`](../tests/test_sales_copilot.py) asks questions through the API, approves an action, checks the row landed once, and checks a forged approval is refused. Copy it.
- **With a real model:** write the questions your users ask with the answers you expect, and grade them. For data questions, `gold eval` does this ([evaluation](evaluation.md)).

## Checklist

- [ ] `app.yaml` with a unique `name`, instructions, the agents the app may use, its components
- [ ] Tools read the user with `current_user(ctx)` and pass it to the database
- [ ] Every tool that changes something goes through `approvals.gate()` and is idempotent on `action_id`
- [ ] Database logins with the least rights each tool needs; row-level security for per-user data
- [ ] Documents in a `knowledge:` collection, with `audience` on anything restricted, and an `eval.jsonl`
- [ ] Agent Cards that say clearly what each agent is for
- [ ] Components in Compose, Helm (`values.yaml`, secrets, NetworkPolicy) and `tests/stack.py`
- [ ] An end-to-end test with scripted replies
