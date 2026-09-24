"""MCP server: read-only access to the business database."""

import json

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from gold import config, db, identity
from gold.guards import UnsafeQuery, mask_value
from gold.mcp_servers import serve

server = MCPServer(
    name="gold-data-tools",
    instructions="Read-only tools for the business database. Queries that change data are refused.",
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)


@server.tool(annotations=READ_ONLY)
def describe_schema() -> str:
    """List every table in the business database with its columns and types."""
    return db.describe_schema()


def _user(ctx: Context):
    request = getattr(ctx.request_context, "request", None)
    token = request.headers.get(identity.HEADER) if request is not None else None
    return identity.verify(token)


@server.tool(annotations=READ_ONLY)
def run_sql(sql: str, ctx: Context) -> str:
    """Run one read-only SELECT query and return the rows as JSON.

    Rows are filtered for the signed-in user by the database's row-level security.
    Anything that would change data is refused.
    """
    try:
        user = _user(ctx)
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
    return json.dumps(result, default=str)


def main() -> None:
    serve(server)


if __name__ == "__main__":
    main()
