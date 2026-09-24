# Evaluation results

Every run below used the 20 questions in [`questions.jsonl`](questions.jsonl) against the sample database, on 24 September 2026. Scores come from `gold eval`, which runs the model's query and the reference query and compares their results ([how scoring works](../docs/evaluation.md)).

**Setup:** open-weight models through a hosted OpenAI-compatible API. `gpt-oss-120b` for the orchestrator and agents, `deepseek-v4-flash` as the SQL model unless stated. Temperature 0, one run per row.

## Final results (current code)

| What was tested | bare | definitions | system |
|---|---|---|---|
| SQL step, `deepseek-v4-flash` | 80% (16/20) | **100%** (20/20) | |
| SQL step, `gpt-oss-120b` | 90% (18/20) | **100%** (20/20) | |
| Whole system end to end (`gold eval --system`) | | | **90%** (18/20) |

- **bare**: question and schema only.
- **definitions**: the same, plus the matching glossary definitions, as GOLD sends in production.
- **system**: the running orchestrator, Definitions agent, SQL agent and tools; graded on the query the agents actually ran.

**Misses in the bare arm** were all about business meaning:
- "last year" computed as `MAX(year) - 1` or from `CURRENT_DATE`;
- "active customers" counted as everyone who ever bought;
- "never active in the last 12 months" measured from today, not from the latest data.

**The two system misses** were runs where a specialist call did not complete under concurrent load. Asked again, both questions returned the correct answer. This is counted as a miss, because it is one.

## How the numbers moved during the day

Publishing only the final row would hide the part that matters most: the evaluation is how problems were found.

| Run | Change before it | deepseek bare / definitions | gpt-oss bare / definitions | system |
|---|---|---|---|---|
| 1 | First version | 65% / 95% | 85% / 85% | — |
| 2 | Harness fixes: SQL token budget 512 → 2048 (reasoning models returned empty SQL); one ambiguous question reworded; glossary matching changed to exact phrases first (a loose match had turned "customers" into "active customers") | 70% / 100% | 90% / 100% | — |
| 3 | Same code through the LiteLLM gateway | 80% / 100% | — | — |
| 4 | Security hardening: the database login can no longer read personal-data columns; one over-broad glossary synonym ("active") removed | 65% / 90% | 90% / 95% | 80% |
| 5 | Grader compares names as words ("Jane Peacock" in one column = first and last name in two); glossary synonyms "been active", "were active" added after run 4 showed the gap | 80% / 100% | 90% / 100% | 90% |

## Read these numbers with care

- **Twenty questions is a small set.** Scores move by 10 to 15 points between identical runs in the bare arm.
- **The glossary and the questions were written together.** The glossary's SQL hints encode the same conventions as the reference queries. That is what a governed glossary is for, but it means the definitions arm measures *whether the model follows the agreed definitions*. It does not measure open-ended SQL skill.
- **Run 5 includes a glossary change made after seeing run 4's misses.** That is the intended workflow (evaluate, find the gap, fix the glossary), but the final definitions score is no longer on unseen data.
- **Your data will differ.** Write questions your users actually ask, keep them out of training data, and run `gold eval` yourself.
