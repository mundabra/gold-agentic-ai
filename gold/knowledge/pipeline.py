"""Documents to searchable chunks, and questions to passages.

Chunking is deliberately simple and predictable: Markdown is split at headings, and long
sections at paragraph boundaries. Each chunk remembers its document title and heading path,
which is what an answer cites. Front matter sets the title and who may read the document:

    ---
    title: Discount approval matrix
    audience: sales-leadership      # a group, or a list of groups; leave out for everyone
    ---
"""

import re
from collections.abc import Awaitable, Callable
from pathlib import Path

import yaml
from openai import AsyncOpenAI

from gold import config
from gold.knowledge import Chunk, Collection, Hit, Store, fingerprint

Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]
MAX_CHARS = 1200
SUFFIXES = {".md", ".markdown", ".txt"}


def _front_matter(text: str) -> tuple[dict, str]:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end > 0:
            return yaml.safe_load(text[4:end]) or {}, text[end + 4:].lstrip("\n")
    return {}, text


def _pack(paragraphs: list[str]) -> list[str]:
    """Paragraphs joined into pieces of at most MAX_CHARS (a longer paragraph stays whole)."""
    pieces, current = [], ""
    for p in paragraphs:
        if current and len(current) + len(p) + 2 > MAX_CHARS:
            pieces.append(current)
            current = p
        else:
            current = f"{current}\n\n{p}" if current else p
    return pieces + ([current] if current else [])


def chunk_document(collection: str, source: str, text: str, default_acl: tuple[str, ...] = ()) -> list[Chunk]:
    meta, body = _front_matter(text)
    audience = meta.get("audience", default_acl) or ()
    acl = tuple(sorted([audience] if isinstance(audience, str) else audience))
    title = str(meta.get("title") or "")
    sections: list[tuple[list[str], list[str]]] = [([], [])]   # (heading path, paragraphs)
    path: list[tuple[int, str]] = []
    for block in re.split(r"\n\s*\n", body):
        block = block.strip()
        heading = re.match(r"^(#{1,6})\s+(.+)$", block.splitlines()[0]) if block else None
        if heading:
            level, name = len(heading.group(1)), heading.group(2).strip()
            if level == 1 and not title:
                title = name
            elif level > 1:
                path = [(lvl, n) for lvl, n in path if lvl < level] + [(level, name)]
            sections.append(([n for _, n in path], []))
            rest = "\n".join(block.splitlines()[1:]).strip()
            if rest:
                sections[-1][1].append(rest)
        elif block:
            sections[-1][1].append(block)
    title = title or Path(source).stem.replace("-", " ").replace("_", " ").capitalize()
    chunks: list[Chunk] = []
    for heading_path, paragraphs in sections:
        section = " › ".join(heading_path)
        for piece in _pack(paragraphs):
            chunks.append(Chunk(
                id=fingerprint(collection, source, str(len(chunks))), collection=collection, source=source,
                title=title, section=section, text=piece, acl=acl,
                hash=fingerprint(config.EMBEDDING_MODEL, title, section, piece, *acl),
            ))
    return chunks


def load_folder(collection: Collection) -> list[Chunk]:
    folder = Path(collection.path)
    chunks: list[Chunk] = []
    for file in sorted(p for p in folder.rglob("*") if p.suffix.lower() in SUFFIXES and p.is_file()):
        chunks += chunk_document(collection.name, str(file.relative_to(folder)),
                                 file.read_text(encoding="utf-8"), collection.acl)
    return chunks


async def embed(texts: list[str], batch: int = 64) -> list[list[float]]:
    """Embeddings from the same OpenAI-compatible endpoint as every model call (GOLD_EMBEDDING_MODEL).

    A client per call: the start-up sync and live searches run on different event loops, and an
    HTTP client's connections belong to the loop that opened them."""
    vectors: list[list[float]] = []
    async with AsyncOpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY) as client:
        for start in range(0, len(texts), batch):
            resp = await client.embeddings.create(model=config.EMBEDDING_MODEL, input=texts[start:start + batch])
            vectors += [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]
    return vectors


def _embedding_text(c: Chunk) -> str:
    # Title and section go in with the text: "Approval levels" means more inside "Discount policy".
    return "\n".join(x for x in (c.title, c.section, c.text) if x)


async def sync(store: Store, collection: Collection, embedder: Embedder = embed) -> dict:
    """Make the store match the folder: embed new or changed chunks, delete stale ones."""
    chunks = load_folder(collection)
    stored = store.fingerprints(collection.name)
    changed = [c for c in chunks if stored.get(c.id) != c.hash]
    if changed:
        vectors = await embedder([_embedding_text(c) for c in changed])
        for c, v in zip(changed, vectors):
            c.embedding = v
        store.upsert(changed)
    stale = sorted(set(stored) - {c.id for c in chunks})
    if stale:
        store.delete(collection.name, stale)
    return {"collection": collection.name, "chunks": len(chunks), "embedded": len(changed), "deleted": len(stale)}


async def search(store: Store, collection: str, query: str, k: int = 5, groups: tuple[str, ...] | None = None,
                 embedder: Embedder = embed) -> list[Hit]:
    k = max(1, min(k, 20))
    if store.embeds_queries:
        return store.search(collection, query, None, k, groups)
    [vector] = await embedder([query])
    return store.search(collection, query, vector, k, groups)
