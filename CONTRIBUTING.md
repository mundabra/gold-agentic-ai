# Contributing

Issues and pull requests are welcome.

## Set up

```bash
uv venv && uv pip install -e ".[dev]"
docker run -d --name gold-test-pg -p 55432:5432 -e POSTGRES_DB=gold -e POSTGRES_USER=gold_admin \
  -e POSTGRES_PASSWORD=gold_admin -v "$PWD/deploy/postgres:/docker-entrypoint-initdb.d:ro" postgres:17-alpine
pytest
```

`pytest` runs the unit tests and the whole system end to end (orchestrator, registry, both A2A agents, both MCP servers, Postgres) with the scripted model, so no API key is needed.

## Ground rules

- Keep GOLD vendor-neutral: anything that works with one provider must work through the OpenAI-compatible API.
- A change to the SQL prompt (`gold/sql_model.py`) changes what a fine-tuned model sees. Say so in the pull request.
- If you change `deploy/postgres/`, copy it to `deploy/helm/gold/files/postgres/` too (CI checks they match).
- Run `gold eval` against a real model for changes that affect answers, and include the before and after numbers.
