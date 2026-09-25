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

## Turning reasoning off

GOLD sends model-specific switches with `GOLD_SQL_EXTRA_BODY`. This model accepts `{"reasoning_effort": "none"}`; NVIDIA Nemotron on vLLM uses `{"chat_template_kwargs": {"enable_thinking": false}}`. Two runs of each setting, same day (24 requests per level):

| | Reasoning on (default) | Reasoning off |
|---|---|---|
| Accuracy, SQL step with definitions (`gold eval`) | 100% | **100%** |
| Accuracy, SQL step without definitions | 80% | **90%** |
| Median, one request at a time | 1.08–1.61 s | **0.79–0.81 s** |
| p99, one request at a time | 6.30–13.30 s | **1.81–2.45 s** |
| Under 3 s, one request at a time | 67–92% | **100%** |
| Reasoning share of output tokens | 64–75% | **0%** |
| Median at 4 and 8 at a time | 1.08–1.93 s | 0.72–2.41 s |
| p99 at 4 and 8 at a time | 5.01–16.49 s | 1.35–11.73 s |

**What it says:** for this model and these questions, reasoning bought nothing. With the agreed definitions in the prompt, the model got every question right without thinking, at about half the latency and a fraction of the tail when requests don't compete. At 4 and 8 concurrent requests, both settings vary widely from run to run. There, time to first token rises, which points to queueing in the shared hosted service rather than to the model.

## What to do about it

1. **Try reasoning off first** (`GOLD_SQL_EXTRA_BODY`), and keep it only if `gold eval` holds.
2. **Fine-tune** ([stage 2](../../../docs/stage-2-fine-tune.md)): a small model trained on your approved SQL answers directly.
3. **Own capacity** ([stage 3](../../../docs/stage-3-own-inference.md)): on a shared hosted API the same configuration swung from a 1.35 s to an 11.73 s p99 between runs. Dedicated GPUs are how latency becomes predictable.

Measure each change the same way:

```bash
scripts/aiperf.sh                                          # the same sweep against your endpoint
gold eval --model "$GOLD_SQL_MODEL" --min-accuracy 0.95    # and prove accuracy did not drop
```

## Read these numbers with care

- A hosted API over the public internet adds network time and shares capacity with other customers. Your own GPUs will behave differently.
- 24 requests per level is enough to see the shape, not to pin down p99, and a shared hosted API is noisy: repeat runs moved p99 several-fold. Use `REQUESTS=200` or more, repeated, for decisions.
- Per-token latency and output throughput come from the server's own token counts (`--use-server-token-count`).
- One SQL generation is one of about 8 to 12 model calls in a full answer. The orchestrator and agents make the rest, and `gold eval --system` reports their total tokens and time.
