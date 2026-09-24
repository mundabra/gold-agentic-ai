"""MCP server: read-only access to the business database."""

import json

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from gold import db
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


@server.tool(annotations=READ_ONLY)
def run_sql(sql: str) -> str:
    """Run one read-only SELECT query and return the rows as JSON.

    Personal data (email, phone, fax, address) is masked in the result.
    Anything that would change data is refused.
    """
    try:
        result = db.run_query(sql)
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
