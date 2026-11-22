#!/usr/bin/env python3
"""Fine-tune DistilBERT for Text2Task BIO entity extraction.

The script intentionally performs provenance and leakage checks before it
imports PyTorch/Transformers or downloads a model. Provisional SILVER and
strict GOLD evaluation are separate, provenance-labelled modes.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model_training.entity_extractor import (  # noqa: E402
    detect_device,
    data_fingerprints,
    load_config,
    make_dataset_class,
    metric_context,
    prediction_records,
    preflight,
    read_jsonl,
    seed_everything,
    seqeval_metrics,
    trainer_compute_metrics,
    trainer_tokenizer_kwarg,
    training_arguments_kwargs,
    validate_tokenizer_alignment,
    write_json,
    write_jsonl,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/entity_training.yaml"))
    parser.add_argument("--mode", choices=("provisional_silver", "gold_evaluation"), help="Override config evaluation mode")
    parser.add_argument("--resume-from-checkpoint", type=Path, help="Resume an interrupted run from a Trainer checkpoint")
    parser.add_argument("--preflight-only", action="store_true", help="Validate data/provenance without importing ML dependencies")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    mode = args.mode or str(config["evaluation"]["mode"])
    context = metric_context(config, mode)
    result_base = Path(config["paths"]["results"])
    model_base = Path(config["paths"]["model_output"])
    result_dir = result_base / mode
    model_dir = model_base / mode
    result_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)
    audit = preflight(config, mode=mode)
    audit.update({
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "config_path": str(args.config),
        "requested_action": "distilbert_fine_tuning",
        "experiment_mode": mode,
    })
    write_json(result_dir / "training_preflight.json", audit)
    if not audit["passed"]:
        blocked = {
            "status": "BLOCKED_BEFORE_TRAINING",
            "reason": "preflight_failed",
            "errors": audit["errors"],
            "blockers": audit["blockers"],
            "weights_created": False,
            "metrics_created": False,
            "timestamp": audit["timestamp"],
        }
        write_json(model_dir / "TRAINING_BLOCKED.json", blocked)
        print("Training blocked before model download or optimization.")
        for value in audit["errors"]:
            print(f"  ERROR: {value}")
        for value in audit["blockers"]:
            print(f"  BLOCKER: {value}")
        raise SystemExit(2)
    if args.preflight_only:
        print("Preflight passed; training was not requested in preflight-only mode.")
        return

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
        import seqeval
    except ImportError as error:
        write_json(result_dir / "dependency_error.json", {
            "status": "BLOCKED_MISSING_DEPENDENCIES",
            "error": str(error),
            "required": ["torch", "transformers", "accelerate", "seqeval", "numpy"],
        })
        raise SystemExit(f"Missing training dependency: {error}")

    training = config["training"]
    seed = int(training["seed"])
    seed_everything(seed)
    model_name = config["model"]["name"]
    tokenizer = AutoTokenizer.from_pretrained(model_name, use_fast=True)
    data_dir = Path(config["paths"]["entity_data"])
    train_rows = read_jsonl(data_dir / "train.jsonl")
    validation_rows = read_jsonl(data_dir / "validation.jsonl")
    validate_tokenizer_alignment(train_rows, tokenizer)
    validate_tokenizer_alignment(validation_rows, tokenizer)
    max_length = int(config["data"]["max_length"])
    TokenRows = make_dataset_class(torch)
    train_dataset = TokenRows(train_rows, tokenizer, max_length)
    validation_dataset = TokenRows(validation_rows, tokenizer, max_length)

    label_to_id = {str(label): int(value) for label, value in audit["label_to_id"].items()}
    id_to_label = {value: label for label, value in label_to_id.items()}
    model = AutoModelForTokenClassification.from_pretrained(
        model_name,
        num_labels=len(label_to_id),
        id2label=id_to_label,
        label2id=label_to_id,
    )
    max_overlap_layers = max(int(row["layer_count"]) for row in train_rows + validation_rows)
    model.config.text2task_max_overlap_layers = max_overlap_layers
    model.config.text2task_overlap_strategy = config["data"]["overlap_strategy"]
    model.config.text2task_window_stride = int(config["data"]["stride"])
    model.config.text2task_experiment_mode = mode
    model.config.text2task_metric_provenance = context
    device = detect_device(torch)
    checkpoints_dir = model_dir / "checkpoints"
    argument_values = {
        "output_dir": str(checkpoints_dir),
        "learning_rate": float(training["learning_rate"]),
        "num_train_epochs": float(training["num_train_epochs"]),
        "per_device_train_batch_size": int(training["per_device_train_batch_size"]),
        "per_device_eval_batch_size": int(training["per_device_eval_batch_size"]),
        "gradient_accumulation_steps": int(training["gradient_accumulation_steps"]),
        "weight_decay": float(training["weight_decay"]),
        "optim": "adamw_torch",
        "warmup_ratio": float(training.get("warmup_ratio", 0.0)),
        "evaluation_strategy": training["evaluation_strategy"],
        "save_strategy": training["save_strategy"],
        "logging_strategy": training["logging_strategy"],
        "logging_steps": int(training["logging_steps"]),
        "load_best_model_at_end": bool(training["load_best_model_at_end"]),
        "metric_for_best_model": f"{context['metric_prefix']}_f1",
        "greater_is_better": bool(training["greater_is_better"]),
        "save_total_limit": int(training["save_total_limit"]),
        "seed": seed,
        "data_seed": int(training["data_seed"]),
        "report_to": [],
        "remove_unused_columns": True,
        "save_safetensors": True,
        "dataloader_pin_memory": device == "cuda",
    }
    training_args = TrainingArguments(**training_arguments_kwargs(TrainingArguments, argument_values))
    collator = DataCollatorForTokenClassification(tokenizer=tokenizer, padding=True, label_pad_token_id=-100)
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=validation_dataset,
        data_collator=collator,
        compute_metrics=trainer_compute_metrics(id_to_label, str(context["metric_prefix"])),
        **trainer_tokenizer_kwarg(Trainer, tokenizer),
    )
    started = datetime.now(timezone.utc)
    train_result = trainer.train(resume_from_checkpoint=str(args.resume_from_checkpoint) if args.resume_from_checkpoint else None)
    finished = datetime.now(timezone.utc)
    trainer.save_model(str(model_dir))
    tokenizer.save_pretrained(str(model_dir))
    evaluation = trainer.predict(validation_dataset, metric_key_prefix=f"{context['metric_prefix']}_validation")
    overall, per_entity, predicted, references = seqeval_metrics(
        evaluation.predictions, evaluation.label_ids, id_to_label
    )
    predictions_path = result_dir / f"{context['metric_prefix']}_validation_predictions.jsonl"
    write_jsonl(predictions_path, prediction_records(validation_rows, predicted, references))
    metrics = {
        "status": "COMPLETED",
        "model_name": model_name,
        "device": device,
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "finished_at": finished.isoformat().replace("+00:00", "Z"),
        "duration_seconds": (finished - started).total_seconds(),
        "best_checkpoint": trainer.state.best_model_checkpoint,
        "best_metric": trainer.state.best_metric,
        "experiment_mode": mode,
        "evaluation_provenance": context,
        f"{context['metric_prefix']}_overall": overall,
        f"{context['metric_prefix']}_per_entity": per_entity,
        "trainer_train_metrics": train_result.metrics,
        "trainer_validation_metrics": evaluation.metrics,
        "versions": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "seqeval": getattr(seqeval, "__version__", "unknown"),
            "numpy": np.__version__,
        },
        "hyperparameters": config,
        "max_overlap_layers": max_overlap_layers,
        "data_fingerprints_before": audit["data_fingerprints"],
        "data_fingerprints_after": data_fingerprints(config),
    }
    metrics["annotation_inputs_unchanged"] = metrics["data_fingerprints_before"] == metrics["data_fingerprints_after"]
    if not metrics["annotation_inputs_unchanged"]:
        raise RuntimeError("annotation inputs changed during training; refusing to publish results")
    write_json(result_dir / "training_metrics.json", metrics)
    write_json(result_dir / "training_log.json", {"experiment_mode": mode, "log_history": trainer.state.log_history})
    write_json(model_dir / "label_mappings.json", {"label_to_id": label_to_id, "id_to_label": id_to_label})
    write_json(model_dir / "training_metadata.json", metrics)
    blocked_path = model_dir / "TRAINING_BLOCKED.json"
    if blocked_path.exists():
        blocked_path.unlink()
    write_json(model_base / "ACTIVE_PROVISIONAL_MODEL.json", {
        "model_path": str(model_dir),
        "experiment_mode": mode,
        "is_final_research_model": bool(context["is_final_research_metric"]),
        "metric_provenance": context,
    })
    print(json.dumps({
        f"{context['metric_prefix']}_overall": overall,
        "metric_provenance": context,
        "best_checkpoint": trainer.state.best_model_checkpoint,
        "device": device,
    }, indent=2))


if __name__ == "__main__":
    main()
