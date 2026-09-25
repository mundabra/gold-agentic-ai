"""MCP server: read-only access to the business database."""

import json

from mcp.server.mcpserver import Context, MCPServer

from apps.data_analyst import db
from apps.data_analyst.guards import UnsafeQuery, mask_value
from gold import config, identity
from gold.mcp import READ_ONLY, current_user, serve

server = MCPServer(
    name="gold-data-tools",
    instructions="Read-only tools for the business database. Queries that change data are refused.",
)

@server.tool(annotations=READ_ONLY)
def describe_schema() -> str:
    """List every table in the business database with its columns and types."""
    return db.describe_schema()


@server.tool(annotations=READ_ONLY)
def run_sql(sql: str, ctx: Context) -> str:
    """Run one read-only SELECT query and return the rows as JSON.

    Rows are filtered for the signed-in user by the database's row-level security.
    Anything that would change data is refused.
    """
    try:
        user = current_user(ctx)
    except identity.AuthError as exc:
        return json.dumps({"error": "refused", "reason": str(exc)})
    if user is None and config.REQUIRE_IDENTITY:
        return json.dumps({"error": "refused", "reason": "No signed-in user: GOLD requires identity."})
    try:
        result = db.run_query(sql, user=user)
    except UnsafeQuery as exc:
        return json.dumps({"error": "refused", "reason": str(exc)})
    except Exception as exc:  # database errors go back to the agent so it can fix the query
        # Database errors can quote the data that caused them, so they are masked too.
        return json.dumps({"error": "query_failed", "reason": mask_value(str(exc).strip().splitlines()[0])})
    if user is not None:
        # Row-level security applied: the numbers cover only what this user may see.
        result["visible_to"] = user.id
    return json.dumps(result, default=str)


def main() -> None:
    serve(server)


if __name__ == "__main__":
    main()
