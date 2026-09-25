# Talk to your Data

A GOLD sample app. Business users ask a question in plain English. The answer comes with the number, the business definition it used and the SQL it ran, so anyone can check it.

| Team | Typical questions |
|---|---|
| Finance | "What was revenue by region last quarter?" · "What is our average order value by country?" |
| Sales operations | "How much revenue did each sales rep bring in?" · "How many active customers do we have?" |
| Product and marketing | "Which product line earned the most last year?" · "How did units sold change month over month?" |

## Why it works

Most "talk to your data" demos get the SQL right and the business wrong. The query runs, but "revenue" meant something different to finance, "last year" was read as the calendar year, and "active customers" counted everyone. This app makes the **meaning** of a question part of the system:

1. **Agreed definitions first.** The Definitions agent looks up every business term in a governed glossary, with an owner per term, and finds analyst-approved example queries for similar questions, before any SQL is written.
2. **Governed execution.** The SQL agent writes one read-only query with a dedicated SQL model (`gold-sql`). SQLGlot allows one `SELECT` only, a dry run checks the planner's cost, and the database login can read permitted columns only.
3. **Shown work.** Every answer carries the definition, the SQL and a trace. Charts are drawn from the query's own rows, never from the model's text.
4. **Measured.** `gold eval` scores any model, or the whole running app, against questions with known-correct answers.
5. **Learns from its users.** "Not right" with corrected SQL goes to a review queue; once approved, the fix becomes a worked example for later questions ([feedback loop](../../docs/feedback.md)).

## Results

On 20 business questions over the sample database (24 September 2026; [every run and its caveats](evals/RESULTS.md)). "SQL step" scores the SQL model alone; "whole system" asks the running agents.

| What was tested | Question + schema only | + agreed definitions |
|---|---|---|
| SQL step, `deepseek-v4-flash` | 80–85% | 100% |
| SQL step, `gpt-oss-120b` | 85–90% | 100% |
| Whole system, end to end | — | 95% |

Without definitions, every miss was about business meaning, not SQL syntax. The set is small and the glossary was written with the questions, so treat this as a demonstration of the method and run `gold eval` on your own questions. Serving performance with NVIDIA AIPerf is in [PERFORMANCE.md](evals/PERFORMANCE.md).

## Inside

| Piece | File | What it does |
|---|---|---|
| Manifest | [`app.yaml`](app.yaml) | Agents, components, CLI commands, UI examples; `read_only: true` |
| Orchestrator instructions | [`instructions.md`](instructions.md) | Definitions first, then SQL; never refuse for lack of a definition |
| Definitions agent | [`agents/definitions_agent.py`](agents/definitions_agent.py) | Glossary terms and approved example queries |
| SQL agent | [`agents/sql_agent.py`](agents/sql_agent.py) | `generate_sql` with the SQL model, then `run_sql` |
| Data tools (MCP) | [`tools/data_tools.py`](tools/data_tools.py) | `describe_schema`, `run_sql` as the signed-in user |
| Glossary tools (MCP) | [`tools/glossary_tools.py`](tools/glossary_tools.py) | `search_glossary`, `find_verified_queries` |
| SQL checks | [`guards.py`](guards.py), [`db.py`](db.py) | SQLGlot read-only check, dry-run cost, single statement, row cap, masking |
| SQL prompt contract | [`sql_model.py`](sql_model.py) | Shared by the SQL agent, `gold eval` and `gold dataset`; a fine-tuned model depends on it |
| Evaluation | [`evaluate.py`](evaluate.py), [`evals/`](evals/) | `gold eval`, the held-out questions, published results |
| Performance | [`bench.py`](bench.py), [`aiperf.py`](aiperf.py) | `gold bench`, AIPerf payloads and summaries |
| Fine-tuning | [`dataset.py`](dataset.py), [`finetune/`](finetune/) | `gold dataset`, seed pairs, a LoRA recipe |
| Feedback | [`curation.py`](curation.py) | `gold feedback promote` and `export` |
| Example agent | [`examples/trends_agent.py`](examples/trends_agent.py) | Joins this app from the registry with no manifest change |

## Use it on your data

See [extending](../../docs/extending.md#use-your-own-database): a read-only login with column grants, your glossary, verified queries, and your own evaluation questions. The path from a hosted API to your own fine-tuned model is in the [three stages](../../docs/stage-1-api.md).
