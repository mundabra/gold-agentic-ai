# AGENTS.md

Instructions for AI coding agents (and people) working on GOLD. Read this before changing anything.

## What GOLD is

GOLD is a vendor-neutral enterprise agentic AI reference architecture: **Governed · Observable · Layered · Deployable**. The **platform** (`gold/`) is the same for every app: an orchestrator built on the OpenAI Agents SDK (API, chat UI, identity, guardrails, memory, approvals, audit, feedback), a registry of A2A agents, and helpers to serve agents (A2A) and tools (MCP). **Apps** (`apps/`) are folders with an `app.yaml` manifest, instructions, agents and tools. Two sample apps: **Talk to your Data** (`apps/data_analyst`: Definitions and SQL agents, governed read-only text-to-SQL) and the **Sales copilot** (`apps/sales_copilot`: an Account agent with typed CRM tools; writes need human approval). Every model call goes to one OpenAI-compatible endpoint. See `docs/architecture.md`.

## What to work on

[ROADMAP.md](ROADMAP.md) is the plan: v0.6 (trust boundaries) first, in the order it lists, then v0.7. Each item is a GitHub issue with scope and acceptance criteria. Work on issues labelled `ready`; leave `needs-owner` ones alone. Don't start items from the "Later" or "Not planned" lists without the maintainer. Every change must pass ROADMAP.md's "Keep it simple" check: no new mandatory component, use the existing extension points (app manifest, store interfaces, MCP tools, settings), standard parts over custom code, and the smallest slice that meets the acceptance criteria.

`main` is protected: changes land only through a pull request with green `test`, `helm` and `image` checks, squash-merged. Force-pushes and deleting `main` are blocked.

## Setup and checks

```bash
uv venv && uv pip install -e ".[dev,sessions]"
docker run -d --name gold-test-pg -p 55432:5432 -e POSTGRES_DB=gold -e POSTGRES_USER=gold_admin \
  -e POSTGRES_PASSWORD=gold_admin -v "$PWD/deploy/postgres:/docker-entrypoint-initdb.d:ro" pgvector/pgvector:pg17
pytest -q                                   # expect all passed, 0 skipped, with the database up
uvx ruff check gold apps tests --select F,E9,I
helm lint deploy/helm/gold
helm template gold deploy/helm/gold --set gateway.enabled=true --set vllm.enabled=true \
  --set scriptedModel.enabled=false --set ingress.enabled=true --set networkPolicy.enabled=true > /dev/null
diff -r deploy/postgres deploy/helm/gold/files/postgres   # must print nothing
docker compose --profile scripted up --build             # the whole stack, no API key, http://localhost:8080
```

`pytest` runs both sample apps end to end with the scripted model (`gold/testing/scripted_model.py` plus each app's `scripted.py`), so no API key is needed. Run all of the checks above before you open a pull request.

## Where things live

| Path | Owns |
|---|---|
| `gold/orchestrator/` | FastAPI app for every app: `/api/apps`, `/api/ask`, `/api/actions/*`, `/api/feedback`; chat UI (`static/index.html`); guardrails; A2A tools built from the registry |
| `gold/apps.py` | Finds apps and reads their manifests (agents, components, CLI, hooks, UI) |
| `gold/approvals.py` | Signed proposals and one-time approvals for tools that change things |
| `gold/knowledge/`, `deploy/postgres/07-knowledge.sh` | Knowledge retrieval: chunking and sync (`pipeline.py`), stores (`pgvector.py`, `vector_stores.py`, `memory.py`), the `search_knowledge` MCP server, retrieval eval |
| `gold/a2a_host.py`, `gold/mcp.py` | Serve an Agents SDK agent over A2A and keep it registered; serve an MCP tool server and read the signed-in user in a tool |
| `gold/identity.py`, `gold/pg.py` | Sign-in modes and the signed user context; running a Postgres transaction as that user (row-level security) |
| `gold/feedback.py`, `deploy/postgres/05-feedback.sh` | The feedback queue and its two logins (apps add what happens next) |
| `gold/rails.py`, `deploy/guardrails/` | Optional NVIDIA NeMo Guardrails: the client and the rails configuration |
| `gold/telemetry.py`, `gold/audit.py` | OpenTelemetry tracing and the audit trail (questions and approval decisions) |
| `gold/config.py`, `gold/cli.py` | Platform settings (`GOLD_*`); the `gold` CLI (apps add commands) |
| `gold/testing/scripted_model.py` | The scripted stand-in model; each app adds canned replies in its `scripted.py` |
| `apps/data_analyst/` | Talk to your Data: `agents/`, `tools/` (MCP), `guards.py` (SQLGlot), `db.py`, **`sql_model.py` (the SQL prompt contract)**, `evaluate.py`, `bench.py`, `dataset.py`, `aiperf.py`, `curation.py`, `cli.py`, `evals/`, `finetune/`, `examples/` |
| `apps/sales_copilot/` | Sales copilot: `agents/account_agent.py`, `tools/crm_tools.py`, `crm.py` (fixed queries, the approved write) |
| `deploy/postgres/` | Sample data, glossary, logins with column grants, row-level security, feedback, the CRM activities table and its write-only login |
| `deploy/helm/gold/`, `compose.yaml`, `deploy/litellm/` | Deployment (`deploy/helm/gold/profiles/nemotron.yaml`: NVIDIA Nemotron on vLLM) |
| `scripts/aiperf.sh` | Serving benchmark with NVIDIA AIPerf, using the production SQL requests |

## Rules you must not break

0. **The platform stays app-agnostic.** Nothing in `gold/` may import from `apps/` or know an app's name. If an app needs something, add a manifest key or a hook.

1. **Stay vendor-neutral.** Never name a cloud or inference provider in code, docs or examples. Open-source projects (vLLM, LiteLLM, SQLGlot, NVIDIA AIPerf) and model names are fine.
2. **Never weaken governance to make something work.** That covers the SQLGlot check, the function denylist, single-statement execution, the dry-run cost limit, column grants, row-level security, the signed user context, approvals, text scrubbing, the input guardrail and the registry token. If a test fails because of one of them, fix the caller.
3. **No secrets in the repo.** No API keys, tokens or passwords other than the documented local defaults (`gold_reader`, `gold_admin`, `gold_crm_writer`, `sk-gold-local` and the like).
4. **The SQL prompt contract is load-bearing.** Changing `apps/data_analyst/sql_model.py` changes what a fine-tuned model sees. Say so in the pull request and re-run `gold eval`.
5. **The evaluation set is held out.** Never add `apps/data_analyst/evals/questions.jsonl` questions to training data or to `verified_queries`, and never edit reference SQL to make a model pass. `gold verify-queries` checks the latter.
6. **Report only measured numbers.** Anything in `apps/data_analyst/evals/RESULTS.md`, `PERFORMANCE.md` or a README must come from a real `gold eval`, `gold bench` or `scripts/aiperf.sh` run, with its caveats.
7. **Keep the chart's copies identical to the originals:** `deploy/postgres/` ↔ `deploy/helm/gold/files/postgres/`, and `deploy/guardrails/gold/*.yml` ↔ `deploy/helm/gold/files/guardrails/`.
8. **Settings are environment variables.** Add new ones to `gold/config.py` (platform) or the app's `settings.py`, `compose.yaml`, the Helm chart (`values.yaml` and `templates/config.yaml`) and the settings table in `docs/extending.md`, all in the same change.

## Common changes

- **Add an app:** follow `docs/build-an-app.md`; copy `apps/sales_copilot/` as a template. Add its components to `compose.yaml`, the Helm values (and secret lists, NetworkPolicy) and `tests/stack.py`.
- **Add an agent to an app:** copy `apps/data_analyst/examples/trends_agent.py`. List it in the app's `app.yaml`, or tag a skill `app:<name>`.
- **Add a tool:** add a function to an `MCPServer` in the app's `tools/`. Reading tools get `READ_ONLY`; tools that change anything get `WRITES` and must call `approvals.gate()` and be idempotent on `action_id`.
- **Add documents:** put Markdown in an app's `knowledge:` folder (with `audience:` front matter if restricted) and add questions to its `eval.jsonl`; run `gold knowledge eval`.
- **Change the glossary:** edit `deploy/postgres/02-glossary.sql`, copy it to the Helm folder, then run `gold eval` to see the effect.
- **Change the UI:** `gold/orchestrator/static/index.html` is dependency-free on purpose (it must work offline) and app-agnostic (everything app-specific comes from `/api/apps`). Keep it that way.
- **Release:** bump the version in `pyproject.toml`, `gold/__init__.py`, `deploy/helm/gold/Chart.yaml` (`version` and `appVersion`) and the image tags in `values.yaml`. Then push a `vX.Y.Z` tag; `.github/workflows/release.yml` publishes the images.

## Style

- Match the surrounding code: short docstrings that explain why, type hints, no new dependencies without a clear reason.
- Prefer what the OpenAI Agents SDK, the MCP SDK and the A2A SDK already provide over custom code.
- Every behaviour change comes with a test in `tests/`. The end-to-end tests (`tests/test_end_to_end.py`, `tests/test_sales_copilot.py`) use the stack in `tests/stack.py`.
- Docs are written for someone new to the project: plain sentences, commands they can copy, no marketing.
