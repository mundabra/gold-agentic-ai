# Contributing

Issues and pull requests are welcome. If you use an AI coding agent, point it at [AGENTS.md](AGENTS.md): it has the setup, the checks and the rules in one place.

## Set up

```bash
uv venv && uv pip install -e ".[dev,sessions]"
docker run -d --name gold-test-pg -p 55432:5432 -e POSTGRES_DB=gold -e POSTGRES_USER=gold_admin \
  -e POSTGRES_PASSWORD=gold_admin -v "$PWD/deploy/postgres:/docker-entrypoint-initdb.d:ro" pgvector/pgvector:pg17
pytest
```

`pytest` runs the unit tests and both sample apps end to end (orchestrator, registry, every A2A agent and MCP server, Postgres) with the scripted model, so no API key is needed.

## What CI checks

Every pull request needs green `test`, `helm` and `image` checks before it can merge:

- `test`: pytest on Python 3.11 and 3.12 (Postgres pinned by digest), `ruff check gold apps tests --select F,E9,I`, and `pip-audit` on the installed dependencies.
- `helm`: the chart lints and renders, and its copies of the SQL and rails match the originals.
- `image`: both images build, and a Trivy scan finds no critical vulnerability that has a fix.

GitHub's secret scanning and push protection are on for the repository. Each release attaches a CycloneDX SBOM of both images.

## Ground rules

- New use cases are new apps under `apps/` ([build an app](docs/build-an-app.md)); the platform in `gold/` should not need to change for them.

- Keep GOLD vendor-neutral: anything that works with one provider must work through the OpenAI-compatible API.
- A change to the SQL prompt (`apps/data_analyst/sql_model.py`) changes what a fine-tuned model sees. Say so in the pull request.
- If you change `deploy/postgres/`, copy it to `deploy/helm/gold/files/postgres/` too (CI checks they match).
- Run `gold eval` against a real model for changes that affect answers, and include the before and after numbers.
