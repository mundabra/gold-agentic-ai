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
# defined in deploy/litellm/config.yaml. Apps can add their own (the data app's gold-sql).
ORCHESTRATOR_MODEL = env("GOLD_ORCHESTRATOR_MODEL", "gold-general")
AGENT_MODEL = env("GOLD_AGENT_MODEL", "gold-general")

# Extra fields sent with every orchestrator and agent model request, as JSON: model-specific
# switches such as turning reasoning off ({"chat_template_kwargs": {"enable_thinking": false}}
# for NVIDIA Nemotron on vLLM). Apps can have their own (the data app's SQL model does).
AGENT_EXTRA_BODY = json.loads(env("GOLD_AGENT_EXTRA_BODY", "") or "{}")

# Apps to serve (see gold/apps.py): empty means every app found. Extra Python packages
# to look for apps in, so your own apps can live outside this repository.
APPS = [a.strip() for a in env("GOLD_APPS", "").split(",") if a.strip()]
APP_PACKAGES = [p.strip() for p in env("GOLD_APP_PACKAGES", "").split(",") if p.strip()]
DEFAULT_APP = env("GOLD_DEFAULT_APP", "")

# The reference deployment's database. Apps read it through their own settings and
# may point elsewhere; the platform itself only uses it for friendly error messages.
DATABASE_URL = env("GOLD_DATABASE_URL", "postgresql://gold_reader:gold_reader@postgres:5432/gold")

# Conversation memory: a SQLite file path (default: a file in the temp folder),
# or a SQLAlchemy URL for a shared database, e.g. postgresql+asyncpg://...
SESSION_DB_URL = env("GOLD_SESSION_DB_URL", "")

REGISTRY_URL = env("GOLD_REGISTRY_URL", "http://registry:8000")
# Shared secret agents must present to register. Empty means open registration
# (fine on a private network, not beyond it).
REGISTRY_TOKEN = env("GOLD_REGISTRY_TOKEN", "")

# The URL other services use to reach this process; goes into its Agent Card.
PUBLIC_URL = env("GOLD_PUBLIC_URL", "http://localhost:8000")
HOST = env("GOLD_HOST", "0.0.0.0")  # nosec B104 - containers must listen on all interfaces
PORT = int(env("GOLD_PORT", "8000"))

# Identity (see gold/identity.py): none | proxy | oidc | demo
AUTH_MODE = env("GOLD_AUTH_MODE", "none").strip().lower()
REQUIRE_IDENTITY = env_bool("GOLD_REQUIRE_IDENTITY", False)  # refuse questions without a user
IDENTITY_SECRET = env("GOLD_IDENTITY_SECRET", "gold-dev-identity-secret")  # shared by all GOLD services; set it
AUTH_USER_HEADER = env("GOLD_AUTH_USER_HEADER", "X-Forwarded-User")
AUTH_GROUPS_HEADER = env("GOLD_AUTH_GROUPS_HEADER", "X-Forwarded-Groups")
OIDC_JWKS_URL = env("GOLD_OIDC_JWKS_URL", "")
OIDC_ISSUER = env("GOLD_OIDC_ISSUER", "")
OIDC_AUDIENCE = env("GOLD_OIDC_AUDIENCE", "")
OIDC_USER_CLAIM = env("GOLD_OIDC_USER_CLAIM", "email")
OIDC_GROUPS_CLAIM = env("GOLD_OIDC_GROUPS_CLAIM", "groups")
DEMO_USERS = [u.strip() for u in env(
    "GOLD_DEMO_USERS", "finance@example.com,jane.peacock@example.com,margaret.park@example.com,steve.johnson@example.com"
).split(",") if u.strip()]

# Optional NVIDIA NeMo Guardrails server (see gold/rails.py and docs/guardrails.md).
RAILS_URL = env("GOLD_RAILS_URL", "")
RAILS_CONFIG_ID = env("GOLD_RAILS_CONFIG_ID", "gold")
RAILS_MODEL = env("GOLD_RAILS_MODEL", "gold-general")  # the model the self-check rails use
RAILS_CHECK_ANSWERS = env_bool("GOLD_RAILS_CHECK_ANSWERS", False)
RAILS_FAIL_OPEN = env_bool("GOLD_RAILS_FAIL_OPEN", False)
RAILS_TIMEOUT = float(env("GOLD_RAILS_TIMEOUT", "20"))

# Feedback loop (see gold/feedback.py): an insert-only login for the orchestrator,
# and a curator login for the people reviewing feedback. Empty turns feedback off.
FEEDBACK_DATABASE_URL = env("GOLD_FEEDBACK_DATABASE_URL", "")
CURATOR_DATABASE_URL = env("GOLD_CURATOR_DATABASE_URL", "")

# Audit trail: every question is logged as JSON to stdout, and appended to this file if set.
AUDIT_LOG = env("GOLD_AUDIT_LOG", "")

# OpenTelemetry tracing turns on when OTEL_EXPORTER_OTLP_ENDPOINT is set (see gold/telemetry.py).
# Prompts, SQL and results stay out of spans unless this is true.
TRACE_CONTENT = env_bool("GOLD_TRACE_CONTENT", False)

# The Agents SDK sends traces to OpenAI by default. GOLD keeps them in your
# environment unless you opt in.
OPENAI_TRACING = env_bool("GOLD_OPENAI_TRACING", False)
