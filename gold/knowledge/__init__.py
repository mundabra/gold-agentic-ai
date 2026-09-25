"""Knowledge retrieval (RAG) for any app: documents in, cited passages out.

    documents (Markdown) -> chunks -> embeddings (OpenAI-compatible /v1/embeddings) -> pgvector
    agent -> MCP search_knowledge(collection, query) -> the passages this user may read, with sources

The store is chosen by the scheme of GOLD_KNOWLEDGE_URL:

    postgresql://...                 pgvector in the Postgres GOLD already runs (the default)
    vectorstores+https://gateway/v1  a knowledge base served through the OpenAI Vector Stores API,
                                     for example a managed one behind LiteLLM (search only)
    memory://                        in-process, for tests

Every chunk carries an access list (the groups allowed to read it; empty means everyone), and
every search is filtered by the signed-in user's groups inside the store.
"""

import hashlib
import importlib
from dataclasses import dataclass, field
from typing import Protocol

from gold import config


@dataclass
class Chunk:
    id: str                     # stable: collection, source and position
    collection: str
    source: str                 # file name or URL the passage came from
    title: str                  # document title
    section: str                # heading path inside the document
    text: str
    acl: tuple[str, ...] = ()   # groups that may read it; empty = everyone
    hash: str = ""              # content fingerprint, so unchanged chunks are not re-embedded
    embedding: list[float] | None = None


@dataclass
class Hit:
    chunk: Chunk
    score: float                # cosine similarity, higher is closer

    def public(self) -> dict:
        c = self.chunk
        return {"title": c.title, "section": c.section, "source": c.source, "score": round(self.score, 3),
                "text": c.text, "cite": f"[{c.title} › {c.section}]" if c.section else f"[{c.title}]"}


class Store(Protocol):
    """What a store implements. `groups=None` means no access filter. A search-only store
    (one filled by its own pipeline) raises NotImplementedError from upsert and delete."""

    def upsert(self, chunks: list[Chunk]) -> None: ...
    def delete(self, collection: str, ids: list[str]) -> None: ...
    def fingerprints(self, collection: str) -> dict[str, str]: ...   # chunk id -> hash
    def search(self, collection: str, query: str, vector: list[float] | None, k: int,
               groups: tuple[str, ...] | None) -> list[Hit]: ...           # vector is None when embeds_queries
    embeds_queries: bool                                            # True if the store embeds the query itself
    def collections(self) -> dict[str, int]: ...                    # name -> chunk count


ADAPTERS = {
    "memory": "gold.knowledge.memory:MemoryStore",
    "postgresql": "gold.knowledge.pgvector:PgVectorStore",
    "postgres": "gold.knowledge.pgvector:PgVectorStore",
    "vectorstores": "gold.knowledge.vector_stores:VectorStoresApi",
}


def register(scheme: str, target: str) -> None:
    """Make a store available under a URL scheme: target is "module:Class", constructed with the URL."""
    ADAPTERS[scheme] = target


for _pair in config.env("GOLD_KNOWLEDGE_ADAPTERS", "").split(","):
    if "=" in _pair:
        register(*[p.strip() for p in _pair.split("=", 1)])


def open_store(url: str | None = None) -> Store:
    url = url or config.KNOWLEDGE_URL
    scheme = url.split("://", 1)[0].split("+", 1)[0]
    if scheme not in ADAPTERS:
        raise ValueError(f"No knowledge store adapter for '{scheme}://'. Known: {', '.join(sorted(ADAPTERS))}")
    module, _, cls = ADAPTERS[scheme].partition(":")
    return getattr(importlib.import_module(module), cls)(url)


def allowed(acl: tuple[str, ...] | list[str], groups: tuple[str, ...] | None) -> bool:
    """The access rule every adapter applies: no filter, a public chunk, or a shared group."""
    return groups is None or not acl or bool(set(acl) & set(groups))


def fingerprint(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]


@dataclass
class Collection:
    """A corpus declared by an app (app.yaml `knowledge:`), synced into the store on start-up."""

    name: str
    path: str
    description: str = ""
    acl: tuple[str, ...] = field(default_factory=tuple)   # default for documents without `audience`
