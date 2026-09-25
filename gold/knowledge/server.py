"""MCP server: search the company's documents, as the signed-in user.

    gold serve mcp-knowledge

On start-up it loads every collection the apps declare (app.yaml `knowledge:`) into the store,
embedding only new or changed passages, and retries until the embedding model is reachable.
Every search is filtered by the user's groups inside the store, and returns passages with the
citation to quote.
"""

import asyncio
import json
import logging
import threading
import time

from mcp.server.mcpserver import Context, MCPServer

from gold import apps, config, identity
from gold.knowledge import open_store, pipeline
from gold.mcp import READ_ONLY, current_user, serve

log = logging.getLogger("gold.knowledge")

server = MCPServer(
    name="gold-knowledge-tools",
    instructions="Search the company's documents. Quote the `cite` of every passage you use.",
)
_store = None


def store():
    global _store
    if _store is None:
        _store = open_store()
    return _store


def access_groups(user: identity.User | None) -> tuple[str, ...] | None:
    """None (no filter) only when sign-in is off; a signed-out user in a signed-in GOLD sees public documents."""
    if user is None:
        return None if config.AUTH_MODE == "none" else ()
    return tuple(user.groups)


@server.tool(annotations=READ_ONLY)
async def search_knowledge(collection: str, query: str, ctx: Context, k: int = 5) -> str:
    """Search a document collection and return the most relevant passages, each with a citation.

    Args:
        collection: The collection to search (list_knowledge shows them).
        query: What you are looking for, in plain words.
        k: How many passages to return (1 to 20).
    """
    try:
        user = current_user(ctx)
    except identity.AuthError as exc:
        return json.dumps({"error": "refused", "reason": str(exc)})
    if user is None and config.REQUIRE_IDENTITY:
        return json.dumps({"error": "refused", "reason": "No signed-in user: GOLD requires identity."})
    known = {c.name for c in apps.knowledge_collections()}
    if collection not in known:
        return json.dumps({"error": "unknown_collection", "reason": f"Collections: {', '.join(sorted(known))}"})
    try:
        hits = await pipeline.search(store(), collection, query, k, access_groups(user))
    except Exception as exc:  # store or embedding model unavailable: say so rather than fail the agent
        log.exception("knowledge search failed")
        return json.dumps({"error": "unavailable", "reason": str(exc).splitlines()[0]})
    result = {"collection": collection, "query": query, "results": [h.public() for h in hits]}
    if user is not None:
        result["visible_to"] = user.id
    return json.dumps(result, ensure_ascii=False)


@server.tool(annotations=READ_ONLY)
def list_knowledge() -> str:
    """List the document collections that can be searched, with what each one covers."""
    return json.dumps({"collections": [{"name": c.name, "description": c.description}
                                       for c in apps.knowledge_collections()]})


def sync_all(retry_seconds: float = 10, attempts: int = 30) -> None:
    """Load every app's documents into the store, retrying while the store or the model is not up yet."""
    for attempt in range(attempts):
        try:
            for collection in apps.knowledge_collections():
                if not store().embeds_queries:   # search-only stores are filled by their own pipeline
                    log.info("knowledge sync: %s", asyncio.run(pipeline.sync(store(), collection)))
            return
        except Exception as exc:
            log.warning("knowledge sync failed (attempt %d): %s", attempt + 1, str(exc).splitlines()[0])
            time.sleep(retry_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if config.KNOWLEDGE_SYNC:
        threading.Thread(target=sync_all, daemon=True, name="knowledge-sync").start()
    serve(server)


if __name__ == "__main__":
    main()
