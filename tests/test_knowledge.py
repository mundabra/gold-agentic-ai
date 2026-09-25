"""Knowledge retrieval: chunking, sync, access by group, and the same behaviour from every store."""

import asyncio
import json
import os
from pathlib import Path

import httpx
import psycopg
import pytest

from gold.knowledge import Collection, open_store, pipeline
from gold.knowledge.evaluate import run as run_eval
from gold.testing.scripted_model import hashed_embedding

DB_URL = os.environ.get("GOLD_DATABASE_URL", "postgresql://gold_reader:gold_reader@localhost:55432/gold")
KNOWLEDGE_URL = DB_URL.replace("gold_reader:gold_reader", "gold_knowledge:gold_knowledge")
PLAYBOOK = Path(__file__).parent.parent / "apps" / "sales_copilot" / "knowledge"


async def fake_embed(texts: list[str]) -> list[list[float]]:
    return [hashed_embedding(t) for t in texts]


def _pgvector_available() -> bool:
    try:
        with psycopg.connect(KNOWLEDGE_URL, connect_timeout=2) as conn:
            return conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone() is not None
    except psycopg.Error:
        return False


def test_markdown_is_split_at_headings_with_titles_and_access_lists():
    doc = "---\ntitle: Discounts\naudience: sales-leadership\n---\n# Ignored\n\nIntro.\n\n## Levels\n\nUp to 10%.\n\n### Above\n\nAsk."
    chunks = pipeline.chunk_document("c", "d.md", doc)
    assert [(c.title, c.section, c.text) for c in chunks] == [
        ("Discounts", "", "Intro."), ("Discounts", "Levels", "Up to 10%."), ("Discounts", "Levels › Above", "Ask.")]
    assert all(c.acl == ("sales-leadership",) for c in chunks)
    assert len({c.id for c in chunks}) == 3


def test_long_sections_are_split_at_paragraphs():
    body = "## Long\n\n" + "\n\n".join("word " * 60 for _ in range(10))
    chunks = pipeline.chunk_document("c", "long.md", body)
    assert len(chunks) > 1 and all(len(c.text) <= pipeline.MAX_CHARS for c in chunks)


def stores() -> list[str]:
    return ["memory://"] + ([KNOWLEDGE_URL] if _pgvector_available() else [])


@pytest.fixture(params=stores())
def store(request):
    s = open_store(request.param)
    if hasattr(s, "reset"):
        s.reset()
    yield s
    if hasattr(s, "reset"):
        s.reset()


def test_sync_embeds_only_what_changed(store, tmp_path):
    (tmp_path / "a.md").write_text("# A\n\n## One\n\nApples are red.\n\n## Two\n\nBananas are yellow.")
    collection = Collection(name="fruit", path=str(tmp_path))
    first = asyncio.run(pipeline.sync(store, collection, fake_embed))
    assert first == {"collection": "fruit", "chunks": 2, "embedded": 2, "deleted": 0}
    assert asyncio.run(pipeline.sync(store, collection, fake_embed))["embedded"] == 0
    (tmp_path / "a.md").write_text("# A\n\n## One\n\nApples are green.")
    assert asyncio.run(pipeline.sync(store, collection, fake_embed)) == \
        {"collection": "fruit", "chunks": 1, "embedded": 1, "deleted": 1}
    assert store.collections() == {"fruit": 1}


def test_search_finds_the_right_passage_and_respects_groups(store):
    asyncio.run(pipeline.sync(store, Collection(name="sales-playbook", path=str(PLAYBOOK)), fake_embed))
    search = lambda q, groups: asyncio.run(pipeline.search(store, "sales-playbook", q, 3, groups, fake_embed))  # noqa: E731
    top = search("How much discount can a rep give without asking anyone?", ("sales",))[0].public()
    assert top["source"] == "pricing-and-discounts.md" and top["cite"].startswith("[Pricing and discounts")
    restricted = "What is the lowest monthly price we accept for an Enterprise licence?"
    assert all(h.chunk.source != "discount-approval-matrix.md" for h in search(restricted, ("sales",)))
    assert all(h.chunk.source != "discount-approval-matrix.md" for h in search(restricted, ()))
    assert search(restricted, ("sales-leadership",))[0].chunk.source == "discount-approval-matrix.md"
    assert search(restricted, None)[0].chunk.source == "discount-approval-matrix.md"  # no sign-in: no filter


def test_retrieval_eval_reports_hit_rate_and_mrr(store):
    collection = Collection(name="sales-playbook", path=str(PLAYBOOK))
    asyncio.run(pipeline.sync(store, collection, fake_embed))
    report = asyncio.run(run_eval(store, collection, k=3, embedder=fake_embed))
    assert report["questions"] == 14 and 0 <= report["mrr"] <= report["hit_rate"] <= 1
    assert report["hit_rate"] >= 0.7   # a bag-of-words stand-in; real embedding models do better


def test_a_vector_stores_api_knowledge_base_is_searched_with_the_users_groups(monkeypatch):
    """The search-only adapter sends the query and an audience filter; the service embeds and searches."""
    from openai import OpenAI

    from gold.knowledge.vector_stores import VectorStoresApi

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/vector_stores"):
            return httpx.Response(200, json={"object": "list", "has_more": False, "data": [{
                "id": "vs_1", "object": "vector_store", "name": "handbook", "created_at": 0, "status": "completed",
                "usage_bytes": 0, "last_active_at": 0, "metadata": {},
                "file_counts": {"in_progress": 0, "completed": 2, "failed": 0, "cancelled": 0, "total": 2}}]})
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"object": "vector_store.search_results.page", "search_query": ["q"],
                                         "has_more": False, "next_page": None, "data": [{
            "file_id": "file_1", "filename": "leave.md", "score": 0.82,
            "attributes": {"title": "Leave policy", "section": "Parental leave", "audience": "public"},
            "content": [{"type": "text", "text": "Sixteen weeks, paid."}]}]})

    api = VectorStoresApi("vectorstores+http://gateway.example/v1")
    api.client = OpenAI(base_url="http://gateway.example/v1", api_key="x",
                        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    [hit] = api.search("handbook", "parental leave", None, 3, ("hr",))
    assert seen["filters"] == {"type": "in", "key": "audience", "value": ["public", "hr"]}
    assert seen["query"] == "parental leave" and seen["max_num_results"] == 3
    assert hit.public()["cite"] == "[Leave policy › Parental leave]" and hit.chunk.acl == ()
    assert api.collections() == {"handbook": 2}
    with pytest.raises(NotImplementedError):
        api.upsert([])


def test_unknown_store_schemes_are_refused():
    with pytest.raises(ValueError, match="No knowledge store adapter"):
        open_store("elastic://nowhere")
