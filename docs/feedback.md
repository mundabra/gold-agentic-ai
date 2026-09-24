# The feedback loop

GOLD gets better from the questions people actually ask:

```text
user marks an answer            analyst reviews                  every later question
"Not right" + the correct SQL ─▶ gold feedback promote ─▶ verified query ─▶ used as a worked example
                                                             │
                                                             └─▶ gold feedback export ─▶ gold dataset ─▶ fine-tuning (stage 2)
```

## For users

Under each answer the chat UI asks **Was this right?**

- **Useful** records that the answer was correct, along with the SQL that produced it.
- **Not right** opens a short form: what was wrong, and, for analysts, the correct SQL. A correction that isn't a single read-only query is refused on the spot.

Feedback goes into a review queue. Nothing changes until an analyst approves it.

## For analysts

```bash
export GOLD_CURATOR_DATABASE_URL=postgresql://gold_curator:gold_curator@localhost:5432/gold
gold feedback list                                   # what is waiting
gold feedback promote 7 --verified-by you@example.com        # approve: becomes a verified query
gold feedback promote 8 --verified-by you@example.com --sql "SELECT ..."   # approve with your own fix
gold feedback dismiss 9 --reviewed-by you@example.com        # close without changes
gold feedback export > approved.jsonl                # question/SQL pairs for gold dataset
```

`promote` checks the SQL before accepting it:
- it must be one read-only query;
- it must run;
- the question must not be in the evaluation set.

It then runs the same checks as `gold verify-queries` over every verified query. A "Useful" rating can be promoted as it is, using the SQL that ran.

## Who can do what

| Login | Used by | Can |
|---|---|---|
| `gold_reader` | The data tools | Read business data (read-only, column grants, row-level security). It can't see the feedback table. |
| `gold_feedback` | The orchestrator only | **Add** feedback. It can't read feedback back, or read anything else. |
| `gold_curator` | Analysts (`gold feedback ...`) | Read and close feedback, and add verified queries |

The logins are created by [`05-feedback.sh`](../deploy/postgres/05-feedback.sh). Set their passwords with `GOLD_FEEDBACK_PASSWORD` and `GOLD_CURATOR_PASSWORD`, or the `postgres.*Password` Helm values. Feedback is off unless `GOLD_FEEDBACK_DATABASE_URL` is set; Compose and the Helm chart set it for you.
