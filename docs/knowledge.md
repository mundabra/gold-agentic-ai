# Knowledge retrieval (RAG)

Agents answer from company documents, cite the passage they used, and only ever see documents the signed-in user may read. It is a platform feature: any app declares its document collections in its manifest, and its agents get one tool, `search_knowledge`.

```text
apps/<app>/knowledge/*.md ──► chunks ──► embeddings (/v1/embeddings) ──► pgvector (knowledge.chunks)
agent ──► MCP search_knowledge(collection, query) ──► passages this user may read, each with a citation
```

## Built from standard parts

| Part | What GOLD uses | Why |
|---|---|---|
| Vector store | **pgvector**, in the Postgres GOLD already runs | Widely deployed and supported by managed Postgres services. No new system to run, back up or secure. |
| Embeddings | The **OpenAI-compatible `/v1/embeddings` API**, through the same endpoint as every model (the `gold-embed` alias on the LiteLLM gateway) | Any embedding model: hosted, or yours on vLLM or NVIDIA NIM. Changing it is configuration. |
| Agent access | One **MCP tool**, `search_knowledge` | Works with any model and any agent framework. The OpenAI Agents SDK calls it natively. |
| Existing knowledge bases (optional) | The **OpenAI Vector Stores API**, for example a managed knowledge base exposed through LiteLLM's `/v1/vector_stores` | Search what your company already runs, without copying it into GOLD. |

The Agents SDK's own `FileSearchTool` isn't used: it only works with OpenAI models on the Responses API, against OpenAI-hosted vector stores. GOLD's agents use Chat Completions with any model.

## Declare a collection

In the app's manifest:

```yaml
knowledge:
  sales-playbook:
    path: knowledge          # a folder in the app, with Markdown or text files
    description: How we sell. Prices and discounts, volume licences, objections, account management.
```

Each file can say who may read it, in front matter:

```markdown
---
title: Discount approval matrix (internal)
audience: sales-leadership          # a group, or a list of groups; leave it out for everyone
---
```

When `mcp-knowledge` starts it loads every declared collection: it splits each document at its headings (and long sections at paragraphs), embeds only passages that are new or changed, and removes passages whose text is gone. `gold knowledge sync` does the same from your machine.

## Search, as the user

`search_knowledge(collection, query, k)` returns the closest passages, each with its title, section, source file, score and a `cite` such as `[Pricing and discounts › Discounts a rep can give]`. Agents are told to quote the `cite` after each sentence that uses the passage, and the chat UI lists the sources under the answer.

Access is enforced inside the store. The filter is part of the SQL query, so a passage the user's groups don't allow is never returned:

| Situation | What the search can return |
|---|---|
| Sign-in off (`GOLD_AUTH_MODE=none`) | Every passage (no user to filter by) |
| Signed-in user | Passages with no audience, and passages for any of the user's groups |
| Sign-in on, but no user on the request | Only passages with no audience |

The user's groups come from sign-in (the OIDC groups claim, or the groups header behind a proxy). In demo mode they come from `GOLD_DEMO_USERS`: `margaret.park@example.com=sales|sales-leadership`.

## Measure retrieval

Each collection can have an `eval.jsonl`: questions with the document that should answer them (and optionally the groups to search as).

```bash
gold knowledge eval sales-playbook -k 3 --min-hit-rate 0.9
```

It reports the hit rate (the right document in the top k) and MRR (how high it ranks). Measured on the Sales playbook, 24 September 2026, 14 questions over 6 documents (21 passages), stored in pgvector:

| Embeddings | Hit rate @1 | Hit rate @3 | MRR |
|---|---|---|---|
| `qwen3-embedding-8b` (4,096 dimensions) on a hosted OpenAI-compatible API | 100% | 100% | 1.00 |
| The scripted stand-in (bag of words; no model) | 86% | 86% | 0.86 |

The corpus is small and was written with the questions, so this shows the method works end to end rather than being a benchmark. Write questions your users actually ask, and gate changes to documents or the embedding model on them.

## Commands

```bash
gold knowledge sync                                   # load every app's collections (only changes are embedded)
gold knowledge list                                   # what apps declare, and what the store holds
gold knowledge search sales-playbook "discount without approval" --as-groups sales
gold knowledge eval sales-playbook
gold knowledge reset                                  # after changing the embedding model, then sync
```

## Settings

| Variable | Default | Purpose |
|---|---|---|
| `GOLD_KNOWLEDGE_URL` | `postgresql://gold_knowledge:…@postgres:5432/gold` | The store: `postgresql://` (pgvector), `vectorstores+https://host/v1` (a knowledge base behind the OpenAI Vector Stores API, search only), or `memory://` (tests) |
| `GOLD_EMBEDDING_MODEL` | `gold-embed` | The embedding model at `GOLD_LLM_BASE_URL` |
| `GOLD_KNOWLEDGE_MCP_URL` | `http://mcp-knowledge:8000/mcp` | Where agents find the knowledge tool |
| `GOLD_KNOWLEDGE_SYNC` | `true` | Load the apps' collections when `mcp-knowledge` starts |
| `GOLD_KNOWLEDGE_API_KEY` | `GOLD_LLM_API_KEY` | Key for a `vectorstores+` knowledge base |
| `GOLD_KNOWLEDGE_ADAPTERS` | empty | Your own store: `scheme=my_package.store:MyStore` |

## Database

`deploy/postgres/07-knowledge.sh` enables the `vector` extension and creates the `gold_knowledge` login, which owns the `knowledge` schema and nothing else. It can't read business data, and GOLD's other logins can't read knowledge. The table is created on first sync with the embedding model's dimension and an HNSW index (for up to 2,000 dimensions; larger embeddings are searched exactly, which is fine for thousands of passages). Use the `pgvector/pgvector` Postgres image, or any managed Postgres with the extension.

## Add a store

A store is one class with five methods (`upsert`, `delete`, `fingerprints`, `search`, `collections`) and must apply the group filter inside the store. See `gold/knowledge/pgvector.py` (about 100 lines), and register yours with `GOLD_KNOWLEDGE_ADAPTERS`. The tests in `tests/test_knowledge.py` run the same checks against every store.

## Limits

- Markdown and text only. Convert PDFs and Word documents first (for example with a document converter in your ingestion pipeline), or put them in a knowledge base you search through the Vector Stores API.
- Pure vector search, no keyword blend or re-ranking yet.
- A search-only (`vectorstores+`) knowledge base enforces access only if the service applies attribute filters. GOLD sends `audience in ["public", ...groups]`; don't connect services that ignore it to restricted documents.
