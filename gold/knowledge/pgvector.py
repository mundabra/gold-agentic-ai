"""pgvector store (postgresql://): the default, in the Postgres GOLD already runs.

One table, knowledge.chunks, created on first use with the embedding model's dimension and an
HNSW index for cosine distance. The access filter is part of the SQL, so a query can never
return a chunk the user's groups don't allow. Needs the vector extension and the knowledge
schema (deploy/postgres/07-knowledge.sh).
"""

import psycopg

from gold.knowledge import Chunk, Hit

TABLE = "knowledge.chunks"
HNSW_MAX_DIMENSIONS = 2000   # pgvector's limit for an HNSW index on vector


def _vector(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


class PgVectorStore:
    embeds_queries = False

    def __init__(self, url: str):
        self.url = url

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.url, connect_timeout=5)

    @staticmethod
    def _has_table(conn: psycopg.Connection) -> bool:
        return conn.execute("SELECT to_regclass(%s) IS NOT NULL", (TABLE,)).fetchone()[0]

    def _ensure(self, conn: psycopg.Connection, dimension: int) -> None:
        current = conn.execute("SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                               "WHERE attrelid = to_regclass(%s) AND attname = 'embedding'", (TABLE,)).fetchone()
        if current:
            if current[0] != f"vector({dimension})":
                raise ValueError(f"{TABLE} holds {current[0]} embeddings, but the embedding model returns "
                                 f"vector({dimension}). Run `gold knowledge reset` after changing GOLD_EMBEDDING_MODEL.")
            return
        conn.execute(f"""
            CREATE TABLE {TABLE} (
                id TEXT PRIMARY KEY, collection TEXT NOT NULL, source TEXT NOT NULL, title TEXT NOT NULL,
                section TEXT NOT NULL, text TEXT NOT NULL, acl TEXT[] NOT NULL DEFAULT '{{}}',
                hash TEXT NOT NULL, embedding vector({dimension}) NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        conn.execute(f"CREATE INDEX ON {TABLE} (collection)")
        if dimension <= HNSW_MAX_DIMENSIONS:
            conn.execute(f"CREATE INDEX ON {TABLE} USING hnsw (embedding vector_cosine_ops)")
        # Larger embeddings are searched exactly (no index): fine for thousands of passages; for more,
        # choose an embedding model with at most 2,000 dimensions.

    def upsert(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        with self._connect() as conn:
            self._ensure(conn, len(chunks[0].embedding or []))
            with conn.cursor() as cur:
                cur.executemany(
                    f"INSERT INTO {TABLE} (id, collection, source, title, section, text, acl, hash, embedding) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector) ON CONFLICT (id) DO UPDATE SET "
                    "collection = EXCLUDED.collection, source = EXCLUDED.source, title = EXCLUDED.title, "
                    "section = EXCLUDED.section, text = EXCLUDED.text, acl = EXCLUDED.acl, hash = EXCLUDED.hash, "
                    "embedding = EXCLUDED.embedding, updated_at = now()",
                    [(c.id, c.collection, c.source, c.title, c.section, c.text, list(c.acl), c.hash,
                      _vector(c.embedding or [])) for c in chunks])

    def delete(self, collection: str, ids: list[str]) -> None:
        with self._connect() as conn:
            if self._has_table(conn):
                conn.execute(f"DELETE FROM {TABLE} WHERE collection = %s AND id = ANY(%s)", (collection, ids))

    def fingerprints(self, collection: str) -> dict[str, str]:
        with self._connect() as conn:
            if not self._has_table(conn):
                return {}
            return dict(conn.execute(f"SELECT id, hash FROM {TABLE} WHERE collection = %s", (collection,)).fetchall())

    def search(self, collection: str, query: str, vector: list[float] | None, k: int,
               groups: tuple[str, ...] | None) -> list[Hit]:
        with self._connect() as conn:
            if not self._has_table(conn):
                return []
            rows = conn.execute(
                f"SELECT id, collection, source, title, section, text, acl, hash, 1 - (embedding <=> %(v)s::vector) "
                f"FROM {TABLE} WHERE collection = %(c)s "
                "AND (%(all)s OR acl = '{}' OR acl && %(g)s::text[]) "
                "ORDER BY embedding <=> %(v)s::vector LIMIT %(k)s",
                {"v": _vector(vector or []), "c": collection, "all": groups is None, "g": list(groups or ()), "k": k},
            ).fetchall()
        return [Hit(Chunk(id=r[0], collection=r[1], source=r[2], title=r[3], section=r[4], text=r[5],
                          acl=tuple(r[6]), hash=r[7]), float(r[8])) for r in rows]

    def collections(self) -> dict[str, int]:
        with self._connect() as conn:
            if not self._has_table(conn):
                return {}
            return dict(conn.execute(f"SELECT collection, COUNT(*) FROM {TABLE} GROUP BY 1 ORDER BY 1").fetchall())

    def reset(self) -> None:
        with self._connect() as conn:
            conn.execute(f"DROP TABLE IF EXISTS {TABLE}")
