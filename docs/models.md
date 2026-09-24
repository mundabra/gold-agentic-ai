# Choosing models

GOLD asks for two roles, and each can be a different model:

| Role | Used by | What it needs | Setting |
|---|---|---|---|
| `gold-general` | The orchestrator and the agents | Reliable tool calling. Reasoning can help it plan. | `GOLD_ORCHESTRATOR_MODEL`, `GOLD_AGENT_MODEL` |
| `gold-sql` | The SQL agent's query writing | Correct SQL for your schema. Usually faster **without** reasoning. | `GOLD_SQL_MODEL` |

Any model behind an OpenAI-compatible API works. Pick with `gold eval` (accuracy) and `scripts/aiperf.sh` (speed), not by reputation.

## Reasoning: on for planning, usually off for SQL

Reasoning models think before they answer. For the SQL role, with the agreed definitions already in the prompt, that thinking mostly adds time. In GOLD's measurements, turning it off kept accuracy at 100%, halved the median latency, and removed the long tail ([evals/PERFORMANCE.md](../evals/PERFORMANCE.md#turning-reasoning-off)).

Each model family turns reasoning off differently. GOLD passes the switch through as extra request fields:

| Model family | `GOLD_SQL_EXTRA_BODY` |
|---|---|
| NVIDIA Nemotron 3 and 3.5 on vLLM or NIM | `{"chat_template_kwargs": {"enable_thinking": false}}` |
| Models that accept OpenAI's `reasoning_effort` | `{"reasoning_effort": "none"}` (or `"low"`) |

`GOLD_AGENT_EXTRA_BODY` does the same for the orchestrator and agents. Keep a switch only if `gold eval` holds.

## Open models on your GPUs: NVIDIA Nemotron

A ready-made Helm profile serves both roles with NVIDIA Nemotron models on vLLM, behind the LiteLLM gateway:

```bash
helm upgrade --install gold deploy/helm/gold -f deploy/helm/gold/profiles/nemotron.yaml
```

| Role | Model | GPUs | Notes |
|---|---|---|---|
| `gold-general` | [`nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-FP8`](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-FP8) | 4 × 80 GB class, or 1 × B200/B300 | Tool calling (`qwen3_coder` parser), reasoning on. NVIDIA Nemotron Open Model License. |
| `gold-sql` | [`nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16`](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16) | 1 | Mixture-of-experts with 3B active parameters; reasoning off. OpenMDW-1.1 licence. Needs vLLM 0.27.1 or later. |

The model ids and vLLM flags come from the model cards, with the context window reduced to what GOLD needs. The profile renders and lints in CI, but it hasn't been run on GPUs by the maintainers. Run `gold eval` and `scripts/aiperf.sh` before switching traffic. To specialise the SQL role further, fine-tune Nemotron 3.5 Lightning on your approved queries ([stage 2](stage-2-fine-tune.md)) and serve the adapter with `loraModules`.

**NVIDIA NIM** is the packaged alternative to running vLLM yourself. NIM containers serve the same OpenAI-compatible API on port 8000, so point a gateway entry's `apiBase` at the NIM service. NIM access needs an NVIDIA Developer Program membership or an NVIDIA AI Enterprise licence.

For safety models (NemoGuard content safety, topic control, jailbreak detection), see [guardrails](guardrails.md#stronger-rails-with-nvidia-nemoguard).
