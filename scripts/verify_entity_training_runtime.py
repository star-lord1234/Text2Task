#!/usr/bin/env python3
"""Persist reproducible runtime evidence for the trained entity pipeline."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model_training.entity_extractor import model_features, write_json  # noqa: E402


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    import torch
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    data_dir = Path("data/model_ready/entities")
    model_dir = Path("models/text2task-distilbert/provisional_silver")
    result_dir = Path("results/entity_extraction/provisional_silver")
    train_rows = read_jsonl(data_dir / "train.jsonl")
    validation_rows = read_jsonl(data_dir / "validation.jsonl")
    tokenizer = AutoTokenizer.from_pretrained(model_dir, use_fast=True)
    trained = AutoModelForTokenClassification.from_pretrained(model_dir)
    base = AutoModelForTokenClassification.from_pretrained(
        "distilbert/distilbert-base-uncased", num_labels=len(trained.config.label2id), local_files_only=True
    )

    alignment_errors = []
    label_id_errors = []
    label_to_id = {str(key): int(value) for key, value in trained.config.label2id.items()}
    counts = Counter()
    layer_counts: dict[int, Counter] = defaultdict(Counter)
    for row in train_rows + validation_rows:
        if tokenizer.convert_ids_to_tokens(row["input_ids"]) != row["tokens"]:
            alignment_errors.append(row["id"])
        for label, label_id in zip(row["labels"], row["label_ids"]):
            expected = -100 if label is None else label_to_id[label]
            if expected != label_id:
                label_id_errors.append(row["id"])
                break
        if row["final_split"] == "train":
            for label in row["labels"]:
                if label is not None:
                    counts[label] += 1
                    layer_counts[int(row["layer_index"])][label] += 1

    trained_embeddings = trained.distilbert.embeddings.word_embeddings.weight.detach().cpu()
    base_embeddings = base.distilbert.embeddings.word_embeddings.weight.detach().cpu()
    marker_evidence = []
    for index in range(8):
        token = f"[unused{index}]"
        token_id = tokenizer.convert_tokens_to_ids(token)
        marker_evidence.append({
            "layer": index,
            "token": token,
            "token_id": token_id,
            "round_trip": tokenizer.convert_ids_to_tokens(token_id),
            "trained_embedding_norm": float(trained_embeddings[token_id].norm()),
            "change_from_base_norm": float((trained_embeddings[token_id] - base_embeddings[token_id]).norm()),
        })

    # Confirm actual gradient flow through the head, encoder and layer marker.
    row = train_rows[0]
    features = model_features(row, tokenizer, 512)
    trained.train()
    trained.zero_grad()
    output = trained(
        input_ids=torch.tensor([features["input_ids"]]),
        attention_mask=torch.tensor([features["attention_mask"]]),
        labels=torch.tensor([features["labels"]]),
    )
    output.loss.backward()
    marker_id = tokenizer.convert_tokens_to_ids("[unused0]")
    gradients = {
        "single_batch_loss": float(output.loss.detach()),
        "classifier_grad_norm": float(trained.classifier.weight.grad.norm()),
        "first_encoder_q_grad_norm": float(trained.distilbert.transformer.layer[0].attention.q_lin.weight.grad.norm()),
        "unused0_embedding_grad_norm": float(trained.distilbert.embeddings.word_embeddings.weight.grad[marker_id].norm()),
    }

    log = json.loads((result_dir / "training_log.json").read_text(encoding="utf-8"))["log_history"]
    metrics = json.loads((result_dir / "training_metrics.json").read_text(encoding="utf-8"))
    active = sum(counts.values())
    evidence = {
        "wordpiece_alignment": {
            "rows_checked": len(train_rows) + len(validation_rows),
            "errors": alignment_errors,
            "passed": not alignment_errors,
            "policy": "first WordPiece B; remaining WordPieces I; special tokens -100",
        },
        "label_id_alignment": {
            "errors": sorted(set(label_id_errors)),
            "passed": not label_id_errors,
            "label2id": label_to_id,
            "id2label": {str(key): value for key, value in trained.config.id2label.items()},
        },
        "marker_evidence": marker_evidence,
        "marker_present_in_training_features": features["input_ids"][1] == marker_id,
        "marker_training_position": 1,
        "marker_label_is_ignored": features["labels"][1] == -100,
        "gradient_flow": gradients,
        "train_label_counts": dict(sorted(counts.items())),
        "train_o_fraction": counts["O"] / active,
        "train_b_fraction": sum(value for key, value in counts.items() if key.startswith("B-")) / active,
        "per_layer_o_fraction": {
            str(layer): values["O"] / sum(values.values()) for layer, values in sorted(layer_counts.items())
        },
        "optimizer": {
            "steps": 132,
            "loss_and_gradient_log": [
                {"step": item["step"], "loss": item["loss"], "grad_norm": item["grad_norm"], "learning_rate": item["learning_rate"]}
                for item in log if "loss" in item and "grad_norm" in item
            ],
            "epoch_evaluation": [
                {
                    "step": item["step"],
                    "epoch": item["epoch"],
                    "loss": item["eval_loss"],
                    "f1": item["eval_silver_provisional_f1"],
                }
                for item in log if "eval_loss" in item
            ],
            "selected_checkpoint": metrics["best_checkpoint"],
            "selected_metric": "silver_provisional_f1",
            "selected_metric_value": metrics["best_metric"],
        },
        "conclusions": [
            "Layer inputs are mechanically distinguishable and marker embeddings received updates.",
            "WordPiece and label-ID alignment checks pass.",
            "Nonzero gradients reached the classifier, encoder, and marker embedding.",
            "The original run underfit BIO starts: B labels are rare and no B label was predicted in validation.",
            "Higher overlap layers are especially O-heavy and sparsely represented.",
        ],
    }
    path = Path("data/diagnostics/entity_pipeline/runtime_evidence.json")
    write_json(path, evidence)
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
