# Serving performance

Measured with [NVIDIA AIPerf](https://github.com/ai-dynamo/aiperf) 0.13 on 24 September 2026, using `scripts/aiperf.sh`. The requests are GOLD's real SQL-model requests: the production system prompt, the schema, the business definitions and each of the 20 evaluation questions, streamed.

**Setup:** `deepseek-v4-flash` (a reasoning model) on a hosted OpenAI-compatible API, called over the public internet from a laptop. 24 requests per concurrency level, a 3-second latency target, one run.

**Latency** (per SQL generation):

| Concurrency | Requests | Errors | Req/s | Median | p90 | p99 | Under 3 s |
|---|---|---|---|---|---|---|---|
| 1 | 24 | 0 | 0.34 | 1.61 s | 5.40 s | 13.30 s | 67% |
| 4 | 24 | 0 | 1.03 | 1.93 s | 4.59 s | 11.20 s | 58% |
| 8 | 24 | 0 | 1.40 | 1.68 s | 4.08 s | 16.49 s | 79% |

**Streaming and tokens:**

| Concurrency | First token (median) | First SQL token (median) | Time per token | Output tokens/s | Reasoning share of output |
|---|---|---|---|---|---|
| 1 | 0.66 s | 1.40 s | 4.1 ms | 75 | 70% |
| 4 | 0.62 s | 1.67 s | 5.0 ms | 257 | 74% |
| 8 | 0.68 s | 1.46 s | 4.4 ms | 435 | 80% |

"Under 3 s" is goodput: the share of requests that finished within the target. It doesn't rise or fall steadily with concurrency here, because with 24 requests a handful of long-thinking questions decide it.

## What it says

- **Once it starts, it's fast.** The first token arrives in about 0.65 s, and each token after that takes about 4–5 ms.
- **Most of the work is thinking, not SQL.** About three quarters of the tokens this model generates are reasoning tokens. The first *SQL* token arrives at about 1.4–1.7 s, well after the first token.
- **The tail is long.** When a question makes the model think hard, a request takes 5 to 16 seconds. So only 58–79% of requests finish within 3 seconds, although none failed.

## What to do about it

This is the case for [stage 2](../docs/stage-2-fine-tune.md): a small model fine-tuned on your approved SQL doesn't need to reason its way to your conventions. It answers directly, which removes most of the output tokens and most of the tail. [Stage 3](../docs/stage-3-own-inference.md) then lets you size GPUs for the latency you need. Measure both changes the same way:

```bash
scripts/aiperf.sh                                          # the same sweep against your endpoint
gold eval --model gold-sql --min-accuracy 0.95             # and prove accuracy did not drop
```

## Read these numbers with care

- A hosted API over the public internet adds network time and shares capacity with other customers. Your own GPUs will behave differently.
- 24 requests per level is enough to see the shape, not to pin down p99. Use `REQUESTS=200` or more for decisions.
- Per-token latency and output throughput come from the server's own token counts (`--use-server-token-count`).
- One SQL generation is one of about 8 to 12 model calls in a full answer. The orchestrator and agents make the rest, and `gold eval --system` reports their total tokens and time.
