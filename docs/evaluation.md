# Evaluation

GOLD treats accuracy as something you measure before every change, not something you assume. Two commands cover quality and performance.

## `gold eval`: quality

Each question in `evals/questions.jsonl` has a reference query that an analyst has checked:

```json
{"id": "q03", "question": "How many active customers do we have?", "sql": "SELECT COUNT(DISTINCT customer_id) FROM invoice WHERE ..."}
```

**Scoring is by result, not by SQL text.** GOLD runs the model's query and the reference query and compares the rows:
- same number of rows;
- each reference row's values appear in its own result row (rows are paired properly, not greedily);
- column order and extra columns don't matter;
- numbers are compared to two decimals;
- text is compared word by word, so "Jane Peacock" in one column matches first and last name in two.

Two ways to run it:

```bash
# The SQL step alone, in two arms: "bare" (question + schema) and "definitions" (+ glossary definitions)
gold eval --model gold-sql

# The whole running system: orchestrator, both agents, glossary and tools
gold eval --system http://localhost:8080
```

The gap between `bare` and `definitions` is the value of your glossary. The `system` score is what your users experience.

Reports go to `results/eval-<time>/report.md` (every miss, with the SQL that caused it) and `report.json`.

### As a quality gate

```bash
gold eval --model gold-sql --min-accuracy 0.95        # exits with an error below the bar
```

The gate checks the `definitions` arm by default, because that's what production sends. Use `--gate-arm bare` to gate on the other arm. Put it in CI so a new model, prompt or adapter can't ship if it makes answers worse.

### Where it runs

The CLI runs on your machine. It reads `.env` and reaches the Compose database on `localhost:5432`. Set `GOLD_DATABASE_URL` for any other database, and point `GOLD_LLM_BASE_URL` at an address your machine can reach: your provider, or `http://localhost:4000/v1` for the Compose gateway.

```bash
pip install -e .
docker compose up -d postgres
gold eval --model provider/good-sql-model
```

### Writing good questions

- 30 to 100 questions your users actually ask, in their words.
- Include the terms that cause arguments ("revenue", "active", "last quarter").
- Keep them out of training data. `gold dataset` refuses to train on them.
- Avoid questions with tied answers ("top 5" where 5th and 6th are equal); they grade inconsistently.

## `gold bench`: performance

```bash
gold bench --model gold-sql --concurrency 1,4,8 --requests 16 --price-in 0.20 --price-out 0.60
```

It sends real GOLD prompts (question + schema) to the SQL model at each concurrency level and reports p50 and p95 latency, requests per second, output tokens per second, errors, and **cost per 1,000 SQL generations**. A full answer takes about 8 to 12 model calls across the orchestrator and agents, so multiply accordingly, or read the token totals from `gold eval --system`.

For a deep serving benchmark (time to first token, inter-token latency, saturation curves), use a dedicated tool such as [NVIDIA AIPerf](https://github.com/ai-dynamo/aiperf) against the same endpoint.
