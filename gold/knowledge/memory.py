"""In-process store (memory://): for tests. Everything is lost on restart."""

import math

from gold.knowledge import Chunk, Hit, allowed


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class MemoryStore:
    embeds_queries = False

    def __init__(self, url: str = "memory://"):
        self.chunks: dict[str, Chunk] = {}

    def upsert(self, chunks: list[Chunk]) -> None:
        for c in chunks:
            self.chunks[c.id] = c

    def delete(self, collection: str, ids: list[str]) -> None:
        for i in ids:
            if i in self.chunks and self.chunks[i].collection == collection:
                del self.chunks[i]

    def fingerprints(self, collection: str) -> dict[str, str]:
        return {c.id: c.hash for c in self.chunks.values() if c.collection == collection}

    def search(self, collection: str, query: str, vector: list[float] | None, k: int,
               groups: tuple[str, ...] | None) -> list[Hit]:
        hits = [Hit(c, cosine(vector or [], c.embedding or [])) for c in self.chunks.values()
                if c.collection == collection and allowed(c.acl, groups)]
        return sorted(hits, key=lambda h: h.score, reverse=True)[:k]

    def collections(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for c in self.chunks.values():
            counts[c.collection] = counts.get(c.collection, 0) + 1
        return counts
