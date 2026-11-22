#!/usr/bin/env python3
"""Train the versioned single-layer TASK/PERSON/TEMPORAL extractor."""

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
    trainer_compute_metrics, trainer_tokenizer_kwarg, training_arguments_kwargs,
    write_json, write_jsonl,
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/entity_training_v2_three_class.json"))
    parser.add_argument("--epochs", type=int)
    parser.add_argument("--run-name", default="epoch3")
    parser.add_argument(
        "--class-weighting", choices=["none", "sqrt_inverse"], default="none",
        help="Optional diagnostic weighting that upweights rare BIO boundaries.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    epochs = args.epochs or int(config["epochs"])
    data_dir = Path(config["data_dir"])
    train_path, validation_path = data_dir / "train.jsonl", data_dir / "validation.jsonl"
    label_map = json.loads((data_dir / "label_map.json").read_text(encoding="utf-8"))
    labels = label_map["labels"]
    label_to_id = {label: int(index) for label, index in label_map["label_to_id"].items()}
    id_to_label = {index: label for label, index in label_to_id.items()}
    train_rows, validation_rows = read_jsonl(train_path), read_jsonl(validation_path)
    if not train_rows or not validation_rows:
        raise SystemExit("v2 model-ready train/validation rows are required")
    if any(row["layer_count"] != 1 or row["layer_index"] != 0 for row in train_rows + validation_rows):
        raise SystemExit("v2 training accepts single-layer rows only")
    train_threads = {row["thread_id"] for row in train_rows}
    validation_threads = {row["thread_id"] for row in validation_rows}
    if train_threads & validation_threads:
        raise SystemExit("cross-split thread overlap")

    import numpy as np
    import torch
    from transformers import (
        AutoModelForTokenClassification, AutoTokenizer, DataCollatorForTokenClassification,
        Trainer, TrainingArguments,
    )

    seed_everything(int(config["seed"]))
    tokenizer = AutoTokenizer.from_pretrained(config["model_name"], use_fast=True)
    for row in train_rows + validation_rows:
        if tokenizer.convert_ids_to_tokens(row["input_ids"]) != row["tokens"]:
            raise ValueError(f"{row['id']}: tokenizer alignment mismatch")
        invalid = {label for label in row["labels"] if label is not None} - set(labels)
        if invalid:
            raise ValueError(f"{row['id']}: invalid v2 labels {invalid}")

    class Rows(torch.utils.data.Dataset):
        def __init__(self, source: list[dict[str, Any]]):
            self.features = [{
                "input_ids": row["input_ids"],
                "attention_mask": row["attention_mask"],
                "labels": [-100 if label is None else label_to_id[label] for label in row["labels"]],
            } for row in source]
        def __len__(self): return len(self.features)
        def __getitem__(self, index): return self.features[index]

    train_dataset, validation_dataset = Rows(train_rows), Rows(validation_rows)
    model = AutoModelForTokenClassification.from_pretrained(
        config["model_name"], num_labels=len(labels), id2label=id_to_label, label2id=label_to_id,
    )
    model.config.text2task_version = config["version"]
    model.config.text2task_entity_types = config["entity_types"]
    model.config.text2task_single_layer = True
    model.config.text2task_metric_provenance = config["evaluation_provenance"]
    model_base = Path(config["model_dir"]) / args.run_name
    result_base = Path(config["results_dir"]) / args.run_name
    model_base.mkdir(parents=True, exist_ok=True)
    result_base.mkdir(parents=True, exist_ok=True)
    device = detect_device(torch)
    values = {
        "output_dir": str(model_base / "checkpoints"),
        "learning_rate": float(config["learning_rate"]), "num_train_epochs": float(epochs),
        "per_device_train_batch_size": int(config["train_batch_size"]),
        "per_device_eval_batch_size": int(config["eval_batch_size"]),
        "gradient_accumulation_steps": int(config["gradient_accumulation_steps"]),
        "weight_decay": float(config["weight_decay"]), "optim": "adamw_torch",
        "evaluation_strategy": "epoch", "save_strategy": "epoch", "logging_strategy": "steps",
        "logging_steps": 10, "load_best_model_at_end": True,
        "metric_for_best_model": config["metric_for_best_model"], "greater_is_better": True,
        "save_total_limit": 3, "seed": int(config["seed"]), "data_seed": int(config["data_seed"]),
        "report_to": [], "remove_unused_columns": True, "save_safetensors": True,
        "dataloader_pin_memory": device == "cuda",
    }
    training_args = TrainingArguments(**training_arguments_kwargs(TrainingArguments, values))
    train_label_counts = Counter(
        label for row in train_rows for label in row["labels"] if label is not None
    )
    if args.class_weighting == "sqrt_inverse":
        reference_count = float(train_label_counts["O"])
        class_weights = [math.sqrt(reference_count / max(1, train_label_counts[label])) for label in labels]
    else:
        class_weights = [1.0] * len(labels)

    class WeightedTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            labels_tensor = inputs.pop("labels")
            outputs = model(**inputs)
            logits = outputs.logits
            loss_function = torch.nn.CrossEntropyLoss(
                weight=torch.tensor(class_weights, dtype=logits.dtype, device=logits.device),
                ignore_index=-100,
            )
            loss = loss_function(logits.view(-1, model.config.num_labels), labels_tensor.view(-1))
            return (loss, outputs) if return_outputs else loss

    trainer_class = WeightedTrainer if args.class_weighting != "none" else Trainer
    trainer = trainer_class(
        model=model, args=training_args, train_dataset=train_dataset, eval_dataset=validation_dataset,
        data_collator=DataCollatorForTokenClassification(tokenizer=tokenizer, padding=True, label_pad_token_id=-100),
        compute_metrics=trainer_compute_metrics(id_to_label, "silver_v2_provisional"),
        **trainer_tokenizer_kwarg(Trainer, tokenizer),
    )
    started = datetime.now(timezone.utc)
    train_result = trainer.train()
    finished = datetime.now(timezone.utc)
    trainer.save_model(str(model_base))
    tokenizer.save_pretrained(str(model_base))
    prediction = trainer.predict(validation_dataset, metric_key_prefix="silver_v2_provisional_validation")
    overall, per_entity, predicted, references = seqeval_metrics(prediction.predictions, prediction.label_ids, id_to_label)
    write_jsonl(result_base / "validation_predictions.jsonl", prediction_records(validation_rows, predicted, references))
    predicted_counts = Counter(label for row in predicted for label in row)
    reference_counts = Counter(label for row in references for label in row)
    baseline = json.loads(Path("results/entity_extraction/provisional_silver/training_metrics.json").read_text(encoding="utf-8"))
    metrics = {
        "status": "COMPLETED", "version": config["version"], "run_name": args.run_name,
        "device": device, "started_at": started.isoformat().replace("+00:00", "Z"),
        "finished_at": finished.isoformat().replace("+00:00", "Z"),
        "duration_seconds": (finished - started).total_seconds(),
        "epochs": epochs, "optimizer_steps": trainer.state.global_step,
        "class_weighting": args.class_weighting,
        "class_weights": {label: weight for label, weight in zip(labels, class_weights)},
        "best_checkpoint": trainer.state.best_model_checkpoint, "best_metric": trainer.state.best_metric,
        "evaluation_provenance": config["evaluation_provenance"],
        "silver_v2_provisional_overall": overall,
        "silver_v2_provisional_per_entity": per_entity,
        "predicted_label_distribution": dict(sorted(predicted_counts.items())),
        "reference_label_distribution": dict(sorted(reference_counts.items())),
        "predicted_b_labels": sum(value for label, value in predicted_counts.items() if label.startswith("B-")),
        "reference_b_labels": sum(value for label, value in reference_counts.items() if label.startswith("B-")),
        "v1_baseline": baseline["silver_provisional_overall"],
        "f1_absolute_change_from_v1": overall["f1"] - baseline["silver_provisional_overall"]["f1"],
        "train_metrics": train_result.metrics, "prediction_metrics": prediction.metrics,
        "config": {
            **config, "epochs_executed": epochs, "run_name": args.run_name,
            "class_weighting": args.class_weighting,
        },
        "data_hashes": {
            "train": hashlib.sha256(train_path.read_bytes()).hexdigest(),
            "validation": hashlib.sha256(validation_path.read_bytes()).hexdigest(),
        },
        "human_gold_metrics": None,
    }
    write_json(result_base / "metrics.json", metrics)
    write_json(result_base / "training_log.json", {"log_history": trainer.state.log_history})
    write_json(model_base / "training_metadata.json", metrics)
    write_json(model_base / "label_mappings.json", {"label_to_id": label_to_id, "id_to_label": id_to_label})
    print(json.dumps({
        "silver_v2_provisional_overall": overall,
        "predicted_b_labels": metrics["predicted_b_labels"],
        "best_checkpoint": metrics["best_checkpoint"], "device": device,
    }, indent=2))


if __name__ == "__main__":
    main()
