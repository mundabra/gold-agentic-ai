"""Settings of the Talk to your Data app, read from environment variables like the platform's."""

import json
from pathlib import Path

from gold.config import env, env_bool

# The model the SQL agent's generate_sql step calls: a general model, or a small
# fine-tuned one (stage 2). A fine-tuned model must be called with the exact prompt
# it was trained on, so the system prompt and whether the schema is appended are configurable.
SQL_MODEL = env("GOLD_SQL_MODEL", "gold-sql")
SQL_SYSTEM_PROMPT = env("GOLD_SQL_SYSTEM_PROMPT", "")
SQL_INCLUDE_SCHEMA = env_bool("GOLD_SQL_INCLUDE_SCHEMA", True)
# Whether business definitions are added to the question sent to the SQL model.
# Turn off for a fine-tuned model that was trained on bare questions only.
SQL_PASS_DEFINITIONS = env_bool("GOLD_SQL_PASS_DEFINITIONS", True)
# Reasoning models spend tokens thinking before they answer; leave them room.
SQL_MAX_TOKENS = int(env("GOLD_SQL_MAX_TOKENS", "2048"))
# Extra fields sent with every SQL-model request, as JSON, e.g. to turn reasoning off.
SQL_EXTRA_BODY = json.loads(env("GOLD_SQL_EXTRA_BODY", "") or "{}")

DATABASE_URL = env("GOLD_DATABASE_URL", "postgresql://gold_reader:gold_reader@postgres:5432/gold")
# The glossary can live in its own small database, so your business data can
# stay on a read-only replica you cannot add tables to.
GLOSSARY_DATABASE_URL = env("GOLD_GLOSSARY_DATABASE_URL", "") or DATABASE_URL
# SQL dialect used to parse and validate queries (any SQLGlot dialect name).
SQL_DIALECT = env("GOLD_SQL_DIALECT", "postgres")
# Schemas the SQL agent may see and query.
DB_SCHEMAS = [s.strip() for s in env("GOLD_DB_SCHEMAS", "public").split(",") if s.strip()]
MAX_ROWS = int(env("GOLD_MAX_ROWS", "50"))
# Dry run: queries whose planner cost estimate is above this are refused before they run. 0 turns it off.
MAX_QUERY_COST = float(env("GOLD_MAX_QUERY_COST", "1000000"))
PII_COLUMNS = {c.strip().lower() for c in env("GOLD_PII_COLUMNS", "email,phone,fax,address").split(",") if c.strip()}

DATA_MCP_URL = env("GOLD_DATA_MCP_URL", "http://mcp-data:8000/mcp")
GLOSSARY_MCP_URL = env("GOLD_GLOSSARY_MCP_URL", "http://mcp-glossary:8000/mcp")

# The held-out evaluation set: never used for training or as approved example queries.
EVAL_QUESTIONS = str(Path(__file__).parent / "evals" / "questions.jsonl")
