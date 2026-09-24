# Stage 1: Start with an API

**Goal:** real answers from real models the same day, and a measured baseline to judge every later change against.

> With a hosted model, the schema, the question, the definitions and the query results are sent to that provider. Check this against your data policy before connecting production data.

## Why start here

A hosted API needs no GPUs, no model operations and no procurement. It tells you quickly whether the use case works for your users, and which questions the model gets wrong. That list of wrong answers is what stage 2 is built from.

## 1. Choose models

GOLD uses models in two roles:

| Role | Setting | What it needs |
|---|---|---|
| Orchestrator and agents | `GOLD_ORCHESTRATOR_MODEL`, `GOLD_AGENT_MODEL` | Reliable **tool calling**. Pick a model your provider documents as supporting function calling. |
| SQL writer | `GOLD_SQL_MODEL` | Good SQL. Can be smaller and cheaper, or the same model. |

Any provider with an OpenAI-compatible Chat Completions API works. Put the endpoint in `.env`:

```bash
GOLD_LLM_BASE_URL=https://your-provider.example/v1
GOLD_LLM_API_KEY=your-key
GOLD_ORCHESTRATOR_MODEL=provider/model-with-tool-calling
GOLD_AGENT_MODEL=provider/model-with-tool-calling
GOLD_SQL_MODEL=provider/good-sql-model
```

```bash
docker compose up --build        # http://localhost:8080
```

> **Reasoning models** think before they answer and spend tokens doing it. If `gold eval` shows empty SQL, raise `GOLD_SQL_MAX_TOKENS` (default 2048).

## 2. Measure a baseline

The engineer commands run on your machine against the Compose database (published on `localhost:5432`). They read `.env` too.

```bash
pip install -e .
gold eval --model provider/good-sql-model            # the SQL step, with and without definitions
gold eval --system http://localhost:8080             # the whole running system
```

```text
| Arm         | Accuracy | Correct | p50 latency | Avg tokens |
|-------------|----------|---------|-------------|------------|
| bare        | 80%      | 16/20   | 2.25 s      | 642        |
| definitions | 100%     | 20/20   | 1.77 s      | 637        |
```

- **bare**: the question and the schema only.
- **definitions**: the same, plus the agreed business definitions GOLD adds in production.

The gap between the two arms is the value of your glossary. Open `results/eval-*/report.md` to see each miss and the SQL that caused it. See [evaluation.md](evaluation.md) for how scoring works.

## 3. Check speed and cost

```bash
gold bench --model provider/good-sql-model --concurrency 1,4,8 \
  --price-in 0.20 --price-out 0.60      # your provider's price per million tokens
```

```text
| Concurrency | p50     | p95      | Req/s | Output tok/s | Errors |
|-------------|---------|----------|-------|--------------|--------|
| 1           | 3.834 s | 13.917 s | 0.19  | 72.8         | 0      |
| 4           | 1.778 s | 14.194 s | 0.66  | 210.8        | 0      |
| 8           | 2.321 s | 4.95 s   | 1.62  | 497.1        | 0      |
```

<sub>Example output for one SQL model on one hosted API, one run. The cost column (per 1,000 SQL generations) appears when you pass prices. Your numbers will differ.</sub>

## 4. Write your own evaluation questions

`evals/questions.jsonl` has 20 questions about the sample data. For your own data, write 30 to 100 questions your users actually ask, each with a reference query an analyst has approved:

```json
{"id": "q01", "question": "What was revenue by region last quarter?", "sql": "SELECT ..."}
```

Keep this set out of any training data. `gold dataset` refuses to train on it.

## When to move to stage 2

- Accuracy has plateaued, and the misses are about **your** schema and conventions, not general SQL.
- Cost per question matters at your expected volume.
- You want a model you own and can version.

→ [Stage 2: Specialise with fine-tuning](stage-2-fine-tune.md)
