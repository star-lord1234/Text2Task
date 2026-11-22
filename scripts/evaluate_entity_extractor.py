#!/usr/bin/env python3
"""Evaluate a trained Text2Task entity extractor on human-reviewed GOLD data."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model_training.entity_extractor import (  # noqa: E402
    human_gold,
    load_config,
    make_dataset_class,
    metric_context,
    prediction_records,
    read_jsonl,
    seqeval_metrics,
    trainer_tokenizer_kwarg,
    validate_tokenizer_alignment,
    write_json,
    write_jsonl,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/entity_training.yaml"))
    parser.add_argument("--split", choices=("validation", "test"), default="validation")
    parser.add_argument("--mode", choices=("provisional_silver", "gold_evaluation"), default="gold_evaluation")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    context = metric_context(config, args.mode)
    result_dir = Path(config["paths"]["results"]) / args.mode
    result_dir.mkdir(parents=True, exist_ok=True)
    entity_dir = Path(config["paths"]["entity_data"])
    final_dir = Path(config["paths"]["final_data"])
    model_dir = Path(config["paths"]["model_output"]) / args.mode
    final_records = read_jsonl(final_dir / f"{args.split}.jsonl")
    gold_count = sum(human_gold(record) for record in final_records)
    gate = {
        "split": args.split,
        "emails": len(final_records),
        "human_reviewed_gold_emails": gold_count,
        "model_available": (model_dir / "config.json").is_file(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "experiment_mode": args.mode,
        "metric_provenance": context,
    }
    tiers = {str((record.get("annotation_provenance") or {}).get("quality_tier")) for record in final_records}
    if args.mode == "gold_evaluation" and gold_count != len(final_records):
        gate.update({"status": "BLOCKED", "reason": "evaluation_requires_fully_human_reviewed_gold"})
        write_json(result_dir / f"evaluation_{args.split}_blocked.json", gate)
        raise SystemExit(
            f"Evaluation blocked: {gold_count}/{len(final_records)} {args.split} emails are verified human GOLD"
        )
    if args.mode == "provisional_silver" and tiers - {"SILVER", "GOLD"}:
        gate.update({"status": "BLOCKED", "reason": "provisional_evaluation_contains_invalid_tier", "tiers": sorted(tiers)})
        write_json(result_dir / f"evaluation_{args.split}_blocked.json", gate)
        raise SystemExit(f"Evaluation blocked: unsupported annotation tiers {sorted(tiers)}")
    if not gate["model_available"]:
        gate.update({"status": "BLOCKED", "reason": "trained_model_not_found"})
        write_json(result_dir / f"evaluation_{args.split}_blocked.json", gate)
        raise SystemExit(f"Evaluation blocked: no trained model at {model_dir}")

    try:
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer, DataCollatorForTokenClassification, Trainer, TrainingArguments
    except ImportError as error:
        raise SystemExit(f"Missing evaluation dependency: {error}")
    rows = read_jsonl(entity_dir / f"{args.split}.jsonl")
    tokenizer = AutoTokenizer.from_pretrained(model_dir, use_fast=True)
    validate_tokenizer_alignment(rows, tokenizer)
    model = AutoModelForTokenClassification.from_pretrained(model_dir)
    id_to_label = {int(key): value for key, value in model.config.id2label.items()}
    TokenRows = make_dataset_class(torch)
    dataset = TokenRows(rows, tokenizer, int(config["data"]["max_length"]))
    eval_args = TrainingArguments(
        output_dir=str(result_dir / "evaluation_tmp"),
        per_device_eval_batch_size=int(config["training"]["per_device_eval_batch_size"]),
        report_to=[],
        remove_unused_columns=True,
        dataloader_pin_memory=torch.cuda.is_available(),
    )
    collator = DataCollatorForTokenClassification(tokenizer=tokenizer, padding=True, label_pad_token_id=-100)
    trainer = Trainer(
        model=model,
        args=eval_args,
        data_collator=collator,
        **trainer_tokenizer_kwarg(Trainer, tokenizer),
    )
    prediction = trainer.predict(dataset, metric_key_prefix=f"{context['metric_prefix']}_{args.split}")
    overall, per_entity, predicted, references = seqeval_metrics(prediction.predictions, prediction.label_ids, id_to_label)
    write_jsonl(
        result_dir / f"{context['metric_prefix']}_{args.split}_predictions.jsonl",
        prediction_records(rows, predicted, references),
    )
    report = {
        "status": "COMPLETED",
        "experiment_mode": args.mode,
        "metric_provenance": context,
        "split": args.split,
        "human_reviewed_gold_emails": gold_count,
        f"{context['metric_prefix']}_overall": overall,
        f"{context['metric_prefix']}_per_entity": per_entity,
        "trainer_metrics": prediction.metrics,
    }
    write_json(result_dir / f"evaluation_{context['metric_prefix']}_{args.split}.json", report)
    print(json.dumps(report, indent=2, default=lambda value: value.item() if hasattr(value, "item") else str(value)))


if __name__ == "__main__":
    main()
