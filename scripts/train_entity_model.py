#!/usr/bin/env python3
"""Train/evaluate a TASK/PERSON/TEMPORAL token tagger with strict, lenient, and token metrics.

Checkpoints are selected by validation LENIENT overall F1 (override with --select-metric).
Validation is whatever ``<data-dir>/validation.jsonl`` contains; the test split is never touched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model_training.entity_extractor import (  # noqa: E402
    detect_device, prediction_records, seed_everything, seqeval_metrics,
    trainer_tokenizer_kwarg, training_arguments_kwargs, write_json, write_jsonl,
)
from src.model_training.span_metrics import evaluate, format_table  # noqa: E402

ENTITY_TYPES = ["TASK", "PERSON", "TEMPORAL"]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", type=Path, default=Path("data/model_ready/entities_mailex_v1"))
    p.add_argument("--model-name", default="distilbert/distilbert-base-uncased")
    p.add_argument("--run-name", required=True)
    p.add_argument("--model-root", type=Path, default=Path("models/text2task-distilbert/phase2"))
    p.add_argument("--results-root", type=Path, default=Path("results/entity_extraction/phase2"))
    p.add_argument("--learning-rate", type=float, default=5e-5)
    p.add_argument("--epochs", type=int, default=12)
    p.add_argument("--warmup-ratio", type=float, default=0.1)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--batch-size", type=int, default=4)
    p.add_argument("--grad-accum", type=int, default=4)
    p.add_argument("--seed", type=int, default=20261101)
    p.add_argument("--class-weighting", choices=["none", "sqrt_inverse"], default="none")
    p.add_argument("--select-metric", default="lenient_f1")
    p.add_argument("--max-train-rows", type=int, help="smoke-test only")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    label_map = json.loads((args.data_dir / "label_map.json").read_text(encoding="utf-8"))
    labels = label_map["labels"]
    label_to_id = {label: int(i) for label, i in label_map["label_to_id"].items()}
    id_to_label = {i: label for label, i in label_to_id.items()}
    train_rows = read_jsonl(args.data_dir / "train.jsonl")
    validation_rows = read_jsonl(args.data_dir / "validation.jsonl")
    if args.max_train_rows:
        train_rows = train_rows[: args.max_train_rows]
    if {r["thread_id"] for r in train_rows} & {r["thread_id"] for r in validation_rows}:
        raise SystemExit("cross-split thread overlap")
    if any(r["layer_count"] != 1 for r in train_rows + validation_rows):
        raise SystemExit("single-layer rows only")

    import torch
    from transformers import (
        AutoModelForTokenClassification, AutoTokenizer, DataCollatorForTokenClassification, Trainer, TrainingArguments,
    )

    seed_everything(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(args.model_name, use_fast=True)
    if tokenizer.convert_ids_to_tokens(train_rows[0]["input_ids"]) != train_rows[0]["tokens"]:
        raise SystemExit(
            "tokenizer mismatch: the stored input_ids come from the DistilBERT uncased vocabulary; "
            "rebuild the dataset for a different encoder"
        )

    class Rows(torch.utils.data.Dataset):
        def __init__(self, source):
            self.features = [{
                "input_ids": r["input_ids"], "attention_mask": r["attention_mask"],
                "labels": [-100 if lab is None else label_to_id[lab] for lab in r["labels"]],
            } for r in source]
        def __len__(self): return len(self.features)
        def __getitem__(self, i): return self.features[i]

    model = AutoModelForTokenClassification.from_pretrained(
        args.model_name, num_labels=len(labels), id2label=id_to_label, label2id=label_to_id,
    )
    model_dir = args.model_root / args.run_name
    result_dir = args.results_root / args.run_name
    model_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    device = detect_device(torch)

    steps_per_epoch = math.ceil(len(train_rows) / (args.batch_size * args.grad_accum))
    total_steps = steps_per_epoch * args.epochs
    values = {
        "output_dir": str(model_dir / "checkpoints"), "learning_rate": args.learning_rate,
        "num_train_epochs": float(args.epochs), "per_device_train_batch_size": args.batch_size,
        "per_device_eval_batch_size": args.batch_size, "gradient_accumulation_steps": args.grad_accum,
        "weight_decay": args.weight_decay, "optim": "adamw_torch", "lr_scheduler_type": "linear",
        "warmup_steps": int(round(args.warmup_ratio * total_steps)),
        "evaluation_strategy": "epoch", "save_strategy": "epoch", "logging_strategy": "epoch",
        "load_best_model_at_end": True, "metric_for_best_model": args.select_metric, "greater_is_better": True,
        "save_total_limit": 2, "seed": args.seed, "data_seed": args.seed, "report_to": [],
        "remove_unused_columns": True, "save_safetensors": True, "group_by_length": True,
    }
    training_args = TrainingArguments(**training_arguments_kwargs(TrainingArguments, values))

    counts = Counter(lab for r in train_rows for lab in r["labels"] if lab is not None)
    if args.class_weighting == "sqrt_inverse":
        class_weights = [math.sqrt(counts["O"] / max(1, counts[lab])) for lab in labels]
    else:
        class_weights = [1.0] * len(labels)

    class WeightedTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            targets = inputs.pop("labels")
            outputs = model(**inputs)
            loss = torch.nn.CrossEntropyLoss(
                weight=torch.tensor(class_weights, dtype=outputs.logits.dtype, device=outputs.logits.device),
                ignore_index=-100,
            )(outputs.logits.view(-1, model.config.num_labels), targets.view(-1))
            return (loss, outputs) if return_outputs else loss

    def compute_metrics(eval_prediction):
        _, _, predicted, references = seqeval_metrics(eval_prediction.predictions, eval_prediction.label_ids, id_to_label)
        result = evaluate(predicted, references, ENTITY_TYPES)
        out = {
            "lenient_f1": result["overall"]["lenient"]["f1"], "strict_f1": result["overall"]["strict"]["f1"],
            "token_f1": result["overall"]["token"]["f1"],
            "predicted_b_labels": float(sum(1 for row in predicted for lab in row if lab.startswith("B-"))),
        }
        for t in ENTITY_TYPES:
            out[f"{t.lower()}_lenient_f1"] = result["per_type"][t]["lenient"]["f1"]
        return out

    trainer = (WeightedTrainer if args.class_weighting != "none" else Trainer)(
        model=model, args=training_args, train_dataset=Rows(train_rows), eval_dataset=Rows(validation_rows),
        data_collator=DataCollatorForTokenClassification(tokenizer=tokenizer, padding=True, label_pad_token_id=-100),
        compute_metrics=compute_metrics, **trainer_tokenizer_kwarg(Trainer, tokenizer),
    )
    started = datetime.now(timezone.utc)
    train_result = trainer.train()
    finished = datetime.now(timezone.utc)
    trainer.save_model(str(model_dir))
    tokenizer.save_pretrained(str(model_dir))

    prediction = trainer.predict(Rows(validation_rows), metric_key_prefix="validation")
    _, _, predicted, references = seqeval_metrics(prediction.predictions, prediction.label_ids, id_to_label)
    write_jsonl(result_dir / "validation_predictions.jsonl", prediction_records(validation_rows, predicted, references))
    scored = evaluate(predicted, references, ENTITY_TYPES)
    predicted_counts = Counter(lab for row in predicted for lab in row)
    reference_counts = Counter(lab for row in references for lab in row)
    stats_path = args.data_dir / "statistics.json"
    metrics = {
        "status": "COMPLETED", "run_name": args.run_name, "device": device,
        "started_at": started.isoformat(), "finished_at": finished.isoformat(),
        "duration_seconds": (finished - started).total_seconds(),
        "hyperparameters": {
            "model_name": args.model_name, "learning_rate": args.learning_rate, "epochs": args.epochs,
            "warmup_steps": values["warmup_steps"], "weight_decay": args.weight_decay,
            "batch_size": args.batch_size, "grad_accum": args.grad_accum, "seed": args.seed,
            "class_weighting": args.class_weighting, "select_metric": args.select_metric,
        },
        "optimizer_steps": trainer.state.global_step, "best_checkpoint": trainer.state.best_model_checkpoint,
        "best_metric": trainer.state.best_metric,
        "train_rows": len(train_rows), "validation_rows": len(validation_rows),
        "dataset_version": json.loads(stats_path.read_text(encoding="utf-8")).get("version") if stats_path.exists() else None,
        "data_hashes": {s: hashlib.sha256((args.data_dir / f"{s}.jsonl").read_bytes()).hexdigest() for s in ("train", "validation")},
        "scores": scored,
        "predicted_label_distribution": dict(sorted(predicted_counts.items())),
        "reference_label_distribution": dict(sorted(reference_counts.items())),
        "provenance": {"quality_tier": "MAILEX_DERIVED", "is_final_research_metric": False,
                       "note": "Validation labels are MailEx-derived and incomplete; see docs/phase1_labels.md."},
        "train_metrics": train_result.metrics,
    }
    write_json(result_dir / "metrics.json", metrics)
    write_json(result_dir / "training_log.json", {"log_history": trainer.state.log_history})
    (result_dir / "scores.md").write_text(format_table(scored) + "\n", encoding="utf-8")
    print(format_table(scored))
    print(json.dumps({"best_checkpoint": metrics["best_checkpoint"], "best_metric": metrics["best_metric"],
                      "duration_seconds": metrics["duration_seconds"], "device": device}, indent=2))


if __name__ == "__main__":
    main()
