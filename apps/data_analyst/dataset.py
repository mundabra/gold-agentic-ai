"""Stage 2: build a fine-tuning dataset for the SQL model.

Takes question/SQL pairs (from analysts, query logs you are allowed to use, or
a seed file), keeps only pairs whose SQL actually runs, and writes chat-format
JSONL using exactly the prompt GOLD will send in production (gold/sql_model.py).
Training and serving on the same prompt matters more than most hyperparameters.

Questions that appear in the evaluation set are refused, so the evaluation
stays an honest test of the fine-tuned model.
"""

import json
import random
from pathlib import Path

from apps.data_analyst import db, settings, sql_model
from apps.data_analyst.evaluate import definitions_for, load_questions


def _key(text: str) -> str:
    return " ".join(text.lower().split())


def build(pairs_path: str, out_dir: str = "results/finetune-data", eval_path: str = settings.EVAL_QUESTIONS,
          val_fraction: float = 0.1, seed: int = 7, with_definitions: bool = True) -> dict:
    pairs = load_questions(pairs_path)
    held_out = {_key(q["question"]) for q in load_questions(eval_path)} | {_key(q["sql"]) for q in load_questions(eval_path)}
    schema = db.describe_schema() if settings.SQL_INCLUDE_SCHEMA else ""

    kept, dropped = [], []
    seen = set()
    for pair in pairs:
        question, sql = pair["question"].strip(), sql_model.extract_sql(pair["sql"])
        if _key(question) in held_out or _key(sql) in held_out:
            dropped.append({"question": question, "reason": "in the evaluation set"})
            continue
        if _key(question) in seen:
            dropped.append({"question": question, "reason": "duplicate"})
            continue
        try:
            db.run_query(sql, 1)
        except Exception as exc:
            dropped.append({"question": question, "reason": f"SQL does not run: {str(exc).splitlines()[0]}"})
            continue
        seen.add(_key(question))
        defs = definitions_for(question) if with_definitions else ""
        messages = sql_model.messages(question, defs, schema) + [{"role": "assistant", "content": sql}]
        kept.append({"messages": messages})

    random.Random(seed).shuffle(kept)
    n_val = max(1, round(len(kept) * val_fraction)) if len(kept) > 1 and val_fraction > 0 else 0
    splits = {"val": kept[:n_val], "train": kept[n_val:]}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in splits.items():
        (out / f"{name}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return {"train": len(splits["train"]), "val": len(splits["val"]), "dropped": dropped, "out_dir": str(out)}
