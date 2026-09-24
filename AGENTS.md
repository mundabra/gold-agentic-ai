# AGENTS.md

Instructions for AI coding agents (and people) working on GOLD. Read this before changing anything.

## What GOLD is

GOLD (Governed Open Language-to-Data) is a vendor-neutral reference architecture for "talk to your data" assistants. An orchestrator built on the OpenAI Agents SDK finds specialist agents in a registry and calls them over A2A. The Definitions agent resolves business terms from a governed glossary. The SQL agent writes one read-only query with a dedicated SQL model. Both use MCP tool servers backed by Postgres through a read-only, column-granted login. Every model call goes to one OpenAI-compatible endpoint: a hosted API directly, or a LiteLLM gateway that routes several models. See `docs/architecture.md`.

## Setup and checks

```bash
uv venv && uv pip install -e ".[dev,sessions]"
docker run -d --name gold-test-pg -p 55432:5432 -e POSTGRES_DB=gold -e POSTGRES_USER=gold_admin \
  -e POSTGRES_PASSWORD=gold_admin -v "$PWD/deploy/postgres:/docker-entrypoint-initdb.d:ro" postgres:17-alpine
pytest -q                                   # expect all passed, 0 skipped, with the database up
helm lint deploy/helm/gold
helm template gold deploy/helm/gold --set gateway.enabled=true --set vllm.enabled=true \
  --set scriptedModel.enabled=false --set ingress.enabled=true --set networkPolicy.enabled=true > /dev/null
diff -r deploy/postgres deploy/helm/gold/files/postgres   # must print nothing
docker compose --profile scripted up --build             # the whole stack, no API key, http://localhost:8080
```

`pytest` runs the whole multi-agent system end to end with the scripted model (`gold/testing/scripted_model.py`), so no API key is needed. Run all of the checks above before you open a pull request.

## Where things live

| Path | Owns |
|---|---|
| `gold/orchestrator/` | FastAPI app, chat UI (`static/index.html`), input guardrail, A2A tools built from the registry |
| `gold/agents/` | SQL agent and Definitions agent (one file each: `build_agent`, `CARD`, `main`) |
| `gold/a2a_host.py` | Serves any Agents SDK agent over A2A and keeps it registered |
| `gold/mcp_servers/` | MCP tool servers: `data_tools.py` (`describe_schema`, `run_sql`), `glossary_tools.py` |
| `gold/guards.py` | SQLGlot read-only check, risky-function denylist, text scrubbing |
| `gold/db.py` | Query execution (dry-run cost, single statement, timeout, row cap), schema listing, glossary search |
| `gold/sql_model.py` | **The SQL prompt contract**, shared by the SQL agent, `gold eval` and `gold dataset` |
| `gold/evaluate.py`, `bench.py`, `dataset.py`, `aiperf.py`, `cli.py` | `gold eval`, `gold bench`, `gold dataset`, AIPerf payloads and summaries, the CLI |
| `scripts/aiperf.sh` | Serving benchmark with NVIDIA AIPerf, using the production SQL requests |
| `gold/config.py` | Every setting, read from `GOLD_*` environment variables |
| `gold/rails.py`, `deploy/guardrails/` | Optional NVIDIA NeMo Guardrails: the client and the rails configuration |
| `gold/telemetry.py`, `gold/audit.py` | OpenTelemetry tracing and the audit trail |
| `deploy/postgres/` | Sample data, glossary, and the read-only role with column grants |
| `deploy/helm/gold/`, `compose.yaml`, `deploy/litellm/` | Deployment |
| `evals/` | Evaluation questions with verified reference SQL, and `RESULTS.md` |

## Rules you must not break

1. **Stay vendor-neutral.** Never name a cloud or inference provider in code, docs or examples. Open-source projects (vLLM, LiteLLM, SQLGlot, NVIDIA AIPerf) and model names are fine.
2. **Never weaken governance to make something work.** That covers the SQLGlot check, the function denylist, single-statement execution, the dry-run cost limit, column grants, text scrubbing, the input guardrail and the registry token. If a test fails because of one of them, fix the caller.
3. **No secrets in the repo.** No API keys, tokens or passwords other than the documented local defaults (`gold_reader`, `gold_admin`, `sk-gold-local`).
4. **The SQL prompt contract is load-bearing.** Changing `gold/sql_model.py` changes what a fine-tuned model sees. Say so in the pull request and re-run `gold eval`.
5. **The evaluation set is held out.** Never add `evals/questions.jsonl` questions to training data, and never edit reference SQL to make a model pass.
6. **Report only measured numbers.** Anything in `evals/RESULTS.md`, `evals/PERFORMANCE.md` or the README must come from a real `gold eval`, `gold bench` or `scripts/aiperf.sh` run, with its caveats.
7. **Keep the chart's copies identical to the originals:** `deploy/postgres/` ↔ `deploy/helm/gold/files/postgres/`, and `deploy/guardrails/gold/*.yml` ↔ `deploy/helm/gold/files/guardrails/`.
8. **Settings are environment variables.** Add new ones to `gold/config.py`, `compose.yaml`, the Helm chart (`values.yaml` and `templates/config.yaml`) and the settings table in `docs/extending.md`, all in the same change.

## Common changes

- **Add an agent:** copy `examples/trends_agent.py`. It registers itself; do not edit the orchestrator unless the agent must run in a fixed order.
- **Add a tool:** add a function to an `MCPServer` in `gold/mcp_servers/`. Read-only tools get `ToolAnnotations(readOnlyHint=True)`.
- **Change the glossary:** edit `deploy/postgres/02-glossary.sql`, copy it to the Helm folder, then run `gold eval` to see the effect.
- **Change the UI:** `gold/orchestrator/static/index.html` is dependency-free on purpose (it must work offline). Keep it that way.
- **Release:** bump the version in `pyproject.toml`, `gold/__init__.py`, `deploy/helm/gold/Chart.yaml` (`version` and `appVersion`) and the image tag in `values.yaml`. Then push a `vX.Y.Z` tag; `.github/workflows/release.yml` publishes the image.

## Style

- Match the surrounding code: short docstrings that explain why, type hints, no new dependencies without a clear reason.
- Prefer what the OpenAI Agents SDK, the MCP SDK and the A2A SDK already provide over custom code.
- Every behaviour change comes with a test in `tests/`. The end-to-end tests in `tests/test_end_to_end.py` use the stack in `tests/stack.py`.
- Docs are written for someone new to the project: plain sentences, commands they can copy, no marketing.
