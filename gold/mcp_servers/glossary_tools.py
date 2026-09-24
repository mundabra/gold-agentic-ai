"""MCP server: the business glossary, so every agent uses the same definitions."""

import json

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from gold import db
from gold.mcp_servers import serve

server = MCPServer(
    name="gold-glossary-tools",
    instructions="Look up the company's agreed definitions of business terms.",
)


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True))
def search_glossary(terms: str) -> str:
    """Find the agreed business definition for one or more terms, such as "revenue" or "active customer"."""
    matches = db.search_glossary(terms)
    if not matches:
        return json.dumps({"matches": [], "note": "No agreed definition found. Say so rather than guessing."})
    return json.dumps({"matches": matches})


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True))
def find_verified_queries(question: str) -> str:
    """Find analyst-approved example queries for questions similar to this one."""
    return json.dumps({"examples": db.search_verified_queries(question)})


def main() -> None:
    serve(server)


if __name__ == "__main__":
    main()
