"""Stage 2: fine-tune a small open model into GOLD's SQL writer with LoRA.

A reference recipe built on Hugging Face TRL + PEFT. It needs a GPU and is not
run in this repository's CI. Use it as-is on one GPU, or take the dataset from
`gold dataset` to any fine-tuning service that accepts chat-format JSONL.

    pip install "trl>=0.20" peft datasets accelerate
    python finetune/train_lora.py --base-model Qwen/Qwen2.5-Coder-7B-Instruct \
        --data finetune/data --out adapters/gold-sql

Then serve the adapter (docs/stage-3-own-inference.md) and gate the switch with
`gold eval --model gold-sql --min-accuracy <your bar>`.
"""

import argparse

from datasets import load_dataset
from peft import LoraConfig
from trl import SFTConfig, SFTTrainer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", required=True, help="Hugging Face id or local path of an instruct model")
    parser.add_argument("--data", default="finetune/data", help="folder with train.jsonl and val.jsonl from `gold dataset`")
    parser.add_argument("--out", default="adapters/gold-sql")
    parser.add_argument("--epochs", type=float, default=3)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--rank", type=int, default=16)
    args = parser.parse_args()

    data = load_dataset("json", data_files={"train": f"{args.data}/train.jsonl", "validation": f"{args.data}/val.jsonl"})
    trainer = SFTTrainer(
        model=args.base_model,
        train_dataset=data["train"],
        eval_dataset=data["validation"],
        peft_config=LoraConfig(
            r=args.rank,
            lora_alpha=args.rank * 2,
            lora_dropout=0.05,
            target_modules="all-linear",
            task_type="CAUSAL_LM",
        ),
        args=SFTConfig(
            output_dir=args.out,
            num_train_epochs=args.epochs,
            learning_rate=args.lr,
            per_device_train_batch_size=4,
            gradient_accumulation_steps=4,
            eval_strategy="epoch",
            save_strategy="epoch",
            logging_steps=10,
            bf16=True,
            report_to="none",
        ),
    )
    trainer.train()
    trainer.save_model(args.out)
    print(f"LoRA adapter saved to {args.out}")


if __name__ == "__main__":
    main()
