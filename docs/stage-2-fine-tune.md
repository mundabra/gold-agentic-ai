# Stage 2: Specialise with fine-tuning

**Goal:** find out whether a small open model you own can write SQL for *your* schema and conventions as well as the hosted model from stage 1, at a lower cost per question. The evaluation set decides; nothing switches until it passes.

## Why fine-tune

A general model knows SQL. It does not know that your `amount` column excludes tax, or that "last year" means the last closed fiscal year. Definitions in the prompt fix a lot of that (see stage 1). Fine-tuning goes further: the conventions end up in the model's weights, so prompts get shorter and a 7B–32B model can do the job of a much larger one.

Only the **SQL model** is fine-tuned. The orchestrator and agents keep a general model with strong tool calling.

## 1. Collect question/SQL pairs

Good sources: queries analysts have already approved, BI dashboards (each tile is a question and a query), and query logs you are allowed to use. Start from `finetune/seed_pairs.jsonl` (30 examples) to see the format:

```json
{"question": "Which city had the highest revenue overall?", "sql": "SELECT ... "}
```

A real fine-tune needs hundreds to a few thousand pairs. Paraphrase each question several ways ("revenue by city", "which city earned most") and cover every table and business term.

## 2. Build the dataset

```bash
docker compose up -d postgres          # the builder runs every query against the database
gold dataset finetune/seed_pairs.jsonl --out finetune/data
```

```text
27 training and 3 validation examples written to finetune/data/
```

The builder:

- **runs every query** and drops the ones that fail;
- **refuses questions from the evaluation set**, so `gold eval` stays an honest test;
- writes each example with **exactly the prompt GOLD sends in production** (`gold/sql_model.py`): same system prompt, same schema format, same definitions block.

Build the dataset with the same `GOLD_SQL_*` settings you will serve with, because they shape the prompt. `--no-definitions` builds examples without the definitions block.

That last point matters more than any hyperparameter. A model fine-tuned on one prompt and served with another loses much of what it learned. If you train with a different prompt (for example bare questions, no schema), serve it the same way:

```bash
GOLD_SQL_SYSTEM_PROMPT="You are a SQL assistant. Answer the question with a single PostgreSQL query."
GOLD_SQL_INCLUDE_SCHEMA=false
GOLD_SQL_PASS_DEFINITIONS=false      # only if you trained on bare questions
```

## 3. Train a LoRA adapter

`finetune/train_lora.py` is a reference recipe with Hugging Face TRL and PEFT for one GPU. It is not run in CI.

```bash
pip install "trl>=0.20" peft datasets accelerate
python finetune/train_lora.py --base-model Qwen/Qwen2.5-Coder-7B-Instruct \
  --data finetune/data --out adapters/gold-sql
```

You can also upload `finetune/data/*.jsonl` (chat-format JSONL) to any fine-tuning service.

Good starting points: a code-focused instruct model of 7B–32B parameters, LoRA rank 16, 2–3 epochs, learning rate 2e-4. Watch the validation loss: if it rises while training loss falls, the model is memorising rather than learning.

## 4. Plug it in and prove it

Serve the adapter under the name `gold-sql` (stage 3, or any hosting that supports LoRA adapters), then point GOLD's SQL role at it. The agents don't change.

- **Through the gateway** (`--profile gateway`): set `SQL_API_BASE` to the server's URL and `SQL_MODEL=openai/gold-sql` in `.env`. On Kubernetes, edit the `gold-sql` entry in `gateway.models`.
- **Directly:** set `GOLD_SQL_MODEL=gold-sql` and point `GOLD_LLM_BASE_URL` at a server that also hosts the general model.

Then:

```bash
gold eval --model gold-sql --min-accuracy 0.95
gold eval --system http://localhost:8080
```

Switch production traffic only when the fine-tuned model matches or beats the stage 1 baseline **on the held-out evaluation set**. Put the first command in CI so a new adapter can never ship if it makes answers worse.

## What a fine-tune cannot fix

A fine-tuned model learns the patterns it was shown. If no training question asks for an average, it may never write `AVG` correctly on your tables. Look at the misses in `results/eval-*/report.md`, add pairs that cover them, and retrain. The fix is usually **data coverage**, not a bigger LoRA rank.

→ [Stage 3: Own the inference](stage-3-own-inference.md)
