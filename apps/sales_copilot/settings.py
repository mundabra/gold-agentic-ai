"""Settings of the Sales copilot app, read from environment variables like the platform's."""

from gold.config import env

# Reads use the same read-only login as the data app; row-level security gives each rep their accounts.
DATABASE_URL = env("GOLD_DATABASE_URL", "postgresql://gold_reader:gold_reader@postgres:5432/gold")
# Writes use a separate login that can only add CRM activities, and only on accounts the user can see.
CRM_DATABASE_URL = env("GOLD_CRM_DATABASE_URL", "postgresql://gold_crm_writer:gold_crm_writer@postgres:5432/gold")
CRM_MCP_URL = env("GOLD_CRM_MCP_URL", "http://mcp-crm:8000/mcp")
# An account needs attention when its last purchase is older than this (see the glossary: at-risk account).
AT_RISK_DAYS = int(env("GOLD_AT_RISK_DAYS", "180"))
