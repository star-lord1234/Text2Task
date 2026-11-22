#!/usr/bin/env python3
"""Run a same-example overfit test on the reviewed 20-email diagnostic set.

This is a pipeline-capacity diagnostic, never a held-out accuracy estimate.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model_training.entity_extractor import (  # noqa: E402
    detect_device,
    prediction_records,
    seed_everything,
    seqeval_metrics,
    trainer_compute_metrics,
    trainer_tokenizer_kwarg,
    training_arguments_kwargs,
    write_json,
    write_jsonl,
)


LABELS = ["O", "B-TASK", "I-TASK", "B-PERSON", "I-PERSON", "B-TEMPORAL", "I-TEMPORAL"]
LABEL_TO_ID = {label: index for index, label in enumerate(LABELS)}
ID_TO_LABEL = {index: label for label, index in LABEL_TO_ID.items()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/diagnostics/entity_pipeline/three_class_20_model_ready.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/entity_extraction/memorization_20"))
    parser.add_argument("--model-dir", type=Path, default=Path("models/text2task-distilbert/memorization_20_diagnostic"))
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261101)
    parser.add_argument("--pass-f1", type=float, default=0.95)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    args = parse_args()
    if not args.input.is_file():
        raise SystemExit(f"Missing diagnostic data: {args.input}; run scripts/audit_entity_pipeline.py first")
    rows = read_jsonl(args.input)
    if len(rows) != 20 or len({row["source_record_id"] for row in rows}) != 20:
        raise SystemExit("Memorization test requires exactly 20 unique source records")
    if any(row["layer_count"] != 1 or row["layer_index"] != 0 for row in rows):
        raise SystemExit("Memorization test requires a genuinely single-layer dataset")
    invalid = sorted({label for row in rows for label in row["labels"] if label is not None} - set(LABELS))
    if invalid:
        raise SystemExit(f"Unexpected diagnostic labels: {invalid}")

    try:
        import numpy as np
        import torch
        import transformers
        from transformers import (
            AutoModelForTokenClassification,
            AutoTokenizer,
            DataCollatorForTokenClassification,
            Trainer,
            TrainingArguments,
        )
    except ImportError as error:
        raise SystemExit(f"Missing training dependency: {error}")

    seed_everything(args.seed)
    tokenizer = AutoTokenizer.from_pretrained("distilbert/distilbert-base-uncased", use_fast=True)
    for row in rows:
        if tokenizer.convert_ids_to_tokens(row["input_ids"]) != row["tokens"]:
            raise ValueError(f"{row['id']}: tokenizer IDs/tokens differ")

    class DiagnosticRows(torch.utils.data.Dataset):
        def __init__(self, values: list[dict[str, Any]]):
            self.values = values
            self.features = []
            for row in values:
                label_ids = [-100 if label is None else LABEL_TO_ID[label] for label in row["labels"]]
                self.features.append({
                    "input_ids": list(row["input_ids"]),
                    "attention_mask": list(row["attention_mask"]),
                    "labels": label_ids,
                })

        def __len__(self) -> int:
            return len(self.features)

        def __getitem__(self, index: int) -> dict[str, list[int]]:
            return self.features[index]

    dataset = DiagnosticRows(rows)
    model = AutoModelForTokenClassification.from_pretrained(
        "distilbert/distilbert-base-uncased",
        num_labels=len(LABELS),
        id2label=ID_TO_LABEL,
        label2id=LABEL_TO_ID,
    )
    initial_classifier = model.classifier.weight.detach().cpu().clone()
    initial_encoder = model.distilbert.transformer.layer[0].attention.q_lin.weight.detach().cpu().clone()
    model.config.text2task_experiment_mode = "memorization_20_diagnostic"
    model.config.text2task_metric_provenance = {
        "annotation_tier": "SILVER",
        "evaluation_design": "same examples used for training and measurement",
        "is_held_out": False,
        "is_final_research_metric": False,
    }
    device = detect_device(torch)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.model_dir.mkdir(parents=True, exist_ok=True)
    argument_values = {
        "output_dir": str(args.output_dir / "checkpoints"),
        "learning_rate": args.learning_rate,
        "num_train_epochs": float(args.epochs),
        "per_device_train_batch_size": args.batch_size,
        "per_device_eval_batch_size": args.batch_size,
        "gradient_accumulation_steps": 1,
        "weight_decay": 0.0,
        "optim": "adamw_torch",
        "evaluation_strategy": "epoch",
        "save_strategy": "no",
        "logging_strategy": "steps",
        "logging_steps": 10,
        "load_best_model_at_end": False,
        "seed": args.seed,
        "data_seed": args.seed,
        "report_to": [],
        "remove_unused_columns": True,
        "dataloader_pin_memory": device == "cuda",
        "save_safetensors": True,
    }
    training_args = TrainingArguments(**training_arguments_kwargs(TrainingArguments, argument_values))
    collator = DataCollatorForTokenClassification(tokenizer=tokenizer, padding=True, label_pad_token_id=-100)
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        eval_dataset=dataset,
        data_collator=collator,
        compute_metrics=trainer_compute_metrics(ID_TO_LABEL, "same_example"),
        **trainer_tokenizer_kwarg(Trainer, tokenizer),
    )
    started = datetime.now(timezone.utc)
    train_result = trainer.train()
    finished = datetime.now(timezone.utc)
    trainer.save_model(str(args.model_dir))
    tokenizer.save_pretrained(str(args.model_dir))
    prediction = trainer.predict(dataset, metric_key_prefix="same_example_memorization")
    overall, per_entity, predicted, references = seqeval_metrics(prediction.predictions, prediction.label_ids, ID_TO_LABEL)
    exported = prediction_records(rows, predicted, references)
    write_jsonl(args.output_dir / "predictions.jsonl", exported)
    prediction_counts = Counter(label for sequence in predicted for label in sequence)
    reference_counts = Counter(label for sequence in references for label in sequence)
    classifier_delta = float((model.classifier.weight.detach().cpu() - initial_classifier).norm())
    encoder_delta = float((model.distilbert.transformer.layer[0].attention.q_lin.weight.detach().cpu() - initial_encoder).norm())
    grad_norms = [float(item["grad_norm"]) for item in trainer.state.log_history if "grad_norm" in item]
    passed = overall["f1"] >= args.pass_f1 and prediction_counts["B-TASK"] > 0 and prediction_counts["B-PERSON"] > 0 and prediction_counts["B-TEMPORAL"] > 0
    result = {
        "status": "PASSED" if passed else "FAILED",
        "full_retraining_gate_open": passed,
        "disclaimer": "Same-example memorization result; not held-out accuracy and not a GOLD metric.",
        "annotation_tier": "SILVER",
        "human_verified": False,
        "is_held_out": False,
        "records": len(rows),
        "rows": len(rows),
        "single_layer": True,
        "entity_types": ["TASK", "PERSON", "TEMPORAL"],
        "bio_labels": LABELS,
        "device": device,
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "finished_at": finished.isoformat().replace("+00:00", "Z"),
        "duration_seconds": (finished - started).total_seconds(),
        "hyperparameters": {
            "model": "distilbert/distilbert-base-uncased",
            "epochs": args.epochs,
            "learning_rate": args.learning_rate,
            "batch_size": args.batch_size,
            "weight_decay": 0.0,
            "seed": args.seed,
            "pass_entity_f1": args.pass_f1,
        },
        "same_example_overall": overall,
        "same_example_per_entity": per_entity,
        "prediction_label_counts": dict(sorted(prediction_counts.items())),
        "reference_label_counts": dict(sorted(reference_counts.items())),
        "gradient_evidence": {
            "logged_grad_norm_count": len(grad_norms),
            "minimum_logged_grad_norm": min(grad_norms) if grad_norms else None,
            "maximum_logged_grad_norm": max(grad_norms) if grad_norms else None,
            "classifier_weight_delta_norm": classifier_delta,
            "first_encoder_q_weight_delta_norm": encoder_delta,
        },
        "optimizer_steps": trainer.state.global_step,
        "train_metrics": train_result.metrics,
        "prediction_metrics": prediction.metrics,
        "versions": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "numpy": np.__version__,
        },
    }
    results_path = args.output_dir / "results.json"
    write_json(results_path, result)
    write_json(args.output_dir / "training_log.json", {"log_history": trainer.state.log_history})
    write_json(args.model_dir / "diagnostic_metadata.json", result)
    # Re-read the normalized JSON written by the shared serializer so NumPy
    # scalar values in Trainer metrics cannot break the final console report.
    print(results_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
