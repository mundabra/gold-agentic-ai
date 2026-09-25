"""A knowledge base behind the OpenAI Vector Stores API (vectorstores+https://host/v1), search only.

For knowledge bases that already exist and are filled by their own pipeline, for example a
managed vector store exposed through LiteLLM's /v1/vector_stores. GOLD sends the query text;
the service embeds it and searches. Collections are vector stores looked up by name.

Access: documents carry an `audience` attribute (a group name, or "public"), and GOLD adds the
filter {"type": "in", "key": "audience", "value": ["public", *user_groups]} to every search.
Services that ignore attribute filters can't enforce access, so only point GOLD at ones that
honour them, or at knowledge bases every user may read.
"""

from openai import OpenAI

from gold import config
from gold.knowledge import Chunk, Hit

PUBLIC = "public"


class VectorStoresApi:
    embeds_queries = True

    def __init__(self, url: str):
        base = url.split("+", 1)[1] if "+" in url.split("://", 1)[0] else url
        key = config.env("GOLD_KNOWLEDGE_API_KEY", "") or config.LLM_API_KEY
        self.client = OpenAI(base_url=base, api_key=key)
        self._ids: dict[str, str] = {}

    def _store_id(self, collection: str) -> str | None:
        if collection not in self._ids:
            for store in self.client.vector_stores.list(limit=100):
                self._ids[store.name or store.id] = store.id
        return self._ids.get(collection)

    def upsert(self, chunks: list[Chunk]) -> None:
        raise NotImplementedError("This knowledge base is filled by its own pipeline; GOLD only searches it.")

    def delete(self, collection: str, ids: list[str]) -> None:
        raise NotImplementedError("This knowledge base is filled by its own pipeline; GOLD only searches it.")

    def fingerprints(self, collection: str) -> dict[str, str]:
        return {}

    def search(self, collection: str, query: str, vector: list[float] | None, k: int,
               groups: tuple[str, ...] | None) -> list[Hit]:
        store_id = self._store_id(collection)
        if store_id is None:
            return []
        params: dict = {"query": query, "max_num_results": k}
        if groups is not None:
            params["filters"] = {"type": "in", "key": "audience", "value": [PUBLIC, *groups]}
        hits = []
        for r in self.client.vector_stores.search(store_id, **params):
            attrs = r.attributes or {}
            text = "\n".join(c.text for c in r.content if getattr(c, "text", None))
            audience = attrs.get("audience", PUBLIC)
            hits.append(Hit(Chunk(
                id=f"{r.file_id}:{len(hits)}", collection=collection, source=r.filename,
                title=str(attrs.get("title") or r.filename), section=str(attrs.get("section", "")), text=text,
                acl=() if audience == PUBLIC else (str(audience),)), float(r.score)))
        return hits

    def collections(self) -> dict[str, int]:
        return {s.name or s.id: s.file_counts.completed for s in self.client.vector_stores.list(limit=100)}
