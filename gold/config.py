"""Settings, read from environment variables so the same image runs anywhere."""

import json
import os


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# Every model call goes to one OpenAI-compatible endpoint. Point it at the
# LiteLLM Proxy (default), or straight at any OpenAI-compatible server:
# self-hosted vLLM, SGLang or Ollama, or a hosted inference API.
LLM_BASE_URL = env("GOLD_LLM_BASE_URL", "http://litellm:4000/v1")
LLM_API_KEY = env("GOLD_LLM_API_KEY", "sk-gold-local")

# Model names as the endpoint knows them. With LiteLLM these are aliases
# defined in deploy/litellm/config.yaml.
ORCHESTRATOR_MODEL = env("GOLD_ORCHESTRATOR_MODEL", "gold-general")
AGENT_MODEL = env("GOLD_AGENT_MODEL", "gold-general")
SQL_MODEL = env("GOLD_SQL_MODEL", "gold-sql")

# The SQL model can be a general model or a small fine-tuned one. A fine-tuned
# model must be called with the exact prompt it was trained on, so both the
# system prompt and whether the schema is appended are configurable.
SQL_SYSTEM_PROMPT = env("GOLD_SQL_SYSTEM_PROMPT", "")
SQL_INCLUDE_SCHEMA = env_bool("GOLD_SQL_INCLUDE_SCHEMA", True)
# Whether business definitions are added to the question sent to the SQL model.
# Turn off for a fine-tuned model that was trained on bare questions only.
SQL_PASS_DEFINITIONS = env_bool("GOLD_SQL_PASS_DEFINITIONS", True)
# Reasoning models spend tokens thinking before they answer; leave them room.
SQL_MAX_TOKENS = int(env("GOLD_SQL_MAX_TOKENS", "2048"))

# Extra fields sent with every model request, as JSON: model-specific switches such as
# turning reasoning off ({"chat_template_kwargs": {"enable_thinking": false}} for
# NVIDIA Nemotron on vLLM). One for the SQL model, one for the orchestrator and agents.
SQL_EXTRA_BODY = json.loads(env("GOLD_SQL_EXTRA_BODY", "") or "{}")
AGENT_EXTRA_BODY = json.loads(env("GOLD_AGENT_EXTRA_BODY", "") or "{}")

DATABASE_URL = env("GOLD_DATABASE_URL", "postgresql://gold_reader:gold_reader@postgres:5432/gold")
# The glossary can live in its own small database, so your business data can
# stay on a read-only replica you cannot add tables to.
GLOSSARY_DATABASE_URL = env("GOLD_GLOSSARY_DATABASE_URL", "") or DATABASE_URL
# Schemas the SQL agent may see and query.
# SQL dialect used to parse and validate queries (any SQLGlot dialect name).
SQL_DIALECT = env("GOLD_SQL_DIALECT", "postgres")
DB_SCHEMAS = [s.strip() for s in env("GOLD_DB_SCHEMAS", "public").split(",") if s.strip()]
MAX_ROWS = int(env("GOLD_MAX_ROWS", "50"))
# Dry run: queries whose planner cost estimate is above this are refused before they run. 0 turns it off.
MAX_QUERY_COST = float(env("GOLD_MAX_QUERY_COST", "1000000"))
PII_COLUMNS = {c.strip().lower() for c in env("GOLD_PII_COLUMNS", "email,phone,fax,address").split(",") if c.strip()}

# Conversation memory: a SQLite file path (default: a file in the temp folder),
# or a SQLAlchemy URL for a shared database, e.g. postgresql+asyncpg://...
SESSION_DB_URL = env("GOLD_SESSION_DB_URL", "")

REGISTRY_URL = env("GOLD_REGISTRY_URL", "http://registry:8000")
# Shared secret agents must present to register. Empty means open registration
# (fine on a private network, not beyond it).
REGISTRY_TOKEN = env("GOLD_REGISTRY_TOKEN", "")
DATA_MCP_URL = env("GOLD_DATA_MCP_URL", "http://mcp-data:8000/mcp")
GLOSSARY_MCP_URL = env("GOLD_GLOSSARY_MCP_URL", "http://mcp-glossary:8000/mcp")

# The URL other services use to reach this process; goes into its Agent Card.
PUBLIC_URL = env("GOLD_PUBLIC_URL", "http://localhost:8000")
HOST = env("GOLD_HOST", "0.0.0.0")  # nosec B104 - containers must listen on all interfaces
PORT = int(env("GOLD_PORT", "8000"))

# Optional NVIDIA NeMo Guardrails server (see gold/rails.py and docs/guardrails.md).
RAILS_URL = env("GOLD_RAILS_URL", "")
RAILS_CONFIG_ID = env("GOLD_RAILS_CONFIG_ID", "gold")
RAILS_MODEL = env("GOLD_RAILS_MODEL", "gold-general")  # the model the self-check rails use
RAILS_CHECK_ANSWERS = env_bool("GOLD_RAILS_CHECK_ANSWERS", False)
RAILS_FAIL_OPEN = env_bool("GOLD_RAILS_FAIL_OPEN", False)
RAILS_TIMEOUT = float(env("GOLD_RAILS_TIMEOUT", "20"))

# Audit trail: every question is logged as JSON to stdout, and appended to this file if set.
AUDIT_LOG = env("GOLD_AUDIT_LOG", "")

# OpenTelemetry tracing turns on when OTEL_EXPORTER_OTLP_ENDPOINT is set (see gold/telemetry.py).
# Prompts, SQL and results stay out of spans unless this is true.
TRACE_CONTENT = env_bool("GOLD_TRACE_CONTENT", False)

# The Agents SDK sends traces to OpenAI by default. GOLD keeps them in your
# environment unless you opt in.
OPENAI_TRACING = env_bool("GOLD_OPENAI_TRACING", False)
