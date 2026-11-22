#!/usr/bin/env python3
"""Run layer-aware Text2Task entity extraction on previously unseen text."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model_training.entity_extractor import layer_marker_token, load_config, write_jsonl  # noqa: E402


DEMO_MESSAGES = [
    "Priya, please send the revised budget to the finance team by Tuesday.",
    "After legal approves the contract, Morgan will schedule the kickoff meeting for next week.",
    "The deployment was canceled, so do not publish the release notes tomorrow.",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/entity_training.yaml"))
    parser.add_argument("--mode", choices=("provisional_silver", "gold_evaluation"), default="provisional_silver")
    parser.add_argument("--text", action="append", help="Unseen message; repeat for multiple messages")
    parser.add_argument("--input-jsonl", type=Path, help="JSONL objects with id and text")
    parser.add_argument("--output", type=Path, default=Path("results/entity_extraction/unseen_predictions.jsonl"))
    parser.add_argument("--demo", action="store_true", help="Predict three built-in unseen examples")
    parser.add_argument("--confidence-threshold", type=float, default=0.0)
    return parser.parse_args()


def load_messages(args: argparse.Namespace) -> list[dict[str, str]]:
    messages = []
    for index, text in enumerate(args.text or []):
        messages.append({"id": f"cli-{index:04d}", "text": text})
    if args.input_jsonl:
        with args.input_jsonl.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict) or not isinstance(value.get("text"), str):
                    raise SystemExit(f"{args.input_jsonl}:{line_number}: expected object with text")
                messages.append({"id": str(value.get("id") or f"file-{line_number:04d}"), "text": value["text"]})
    if args.demo:
        messages.extend({"id": f"demo-{index:04d}", "text": text} for index, text in enumerate(DEMO_MESSAGES))
    if not messages:
        raise SystemExit("Provide --text, --input-jsonl, or --demo")
    return messages


def decode_layer(text: str, token_votes: dict[tuple[int, int], tuple[str, float]], layer_index: int) -> list[dict[str, Any]]:
    ordered = sorted((start, end, label, confidence) for (start, end), (label, confidence) in token_votes.items())
    entities = []
    current = None
    for start, end, label, confidence in ordered:
        if label == "O":
            if current:
                entities.append(current)
                current = None
            continue
        prefix, entity_type = label.split("-", 1)
        continuing = current is not None and prefix == "I" and current["type"] == entity_type
        if not continuing:
            if current:
                entities.append(current)
            current = {
                "type": entity_type,
                "start": start,
                "end": end,
                "text": text[start:end],
                "layer_index": layer_index,
                "token_confidences": [confidence],
            }
        else:
            current["end"] = end
            current["text"] = text[current["start"]:end]
            current["token_confidences"].append(confidence)
    if current:
        entities.append(current)
    for entity in entities:
        values = entity.pop("token_confidences")
        entity["confidence"] = sum(values) / len(values)
    return entities


def predict_message(text: str, model: Any, tokenizer: Any, torch: Any, config: dict[str, Any], threshold: float) -> list[dict[str, Any]]:
    max_length = int(config["data"]["max_length"])
    stride = int(config["data"]["stride"])
    # Reserve one position for the layer marker inserted after [CLS].
    encoded = tokenizer(
        text,
        truncation=True,
        max_length=max_length - 1,
        stride=stride,
        return_overflowing_tokens=True,
        return_offsets_mapping=True,
        return_attention_mask=True,
        padding=False,
    )
    max_layers = int(getattr(model.config, "text2task_max_overlap_layers", 8))
    id_to_label = {int(key): value for key, value in model.config.id2label.items()}
    device = next(model.parameters()).device
    votes_by_layer: dict[int, dict[tuple[int, int], tuple[str, float]]] = defaultdict(dict)
    for layer_index in range(max_layers):
        marker_id = tokenizer.convert_tokens_to_ids(layer_marker_token(layer_index))
        if marker_id == tokenizer.unk_token_id:
            raise RuntimeError(f"Tokenizer lacks layer marker {layer_marker_token(layer_index)}")
        for input_ids, attention_mask, offsets in zip(encoded["input_ids"], encoded["attention_mask"], encoded["offset_mapping"]):
            layer_ids = input_ids[:1] + [marker_id] + input_ids[1:]
            layer_mask = attention_mask[:1] + [1] + attention_mask[1:]
            layer_offsets = offsets[:1] + [(0, 0)] + offsets[1:]
            with torch.no_grad():
                output = model(
                    input_ids=torch.tensor([layer_ids], device=device),
                    attention_mask=torch.tensor([layer_mask], device=device),
                )
                probabilities = torch.softmax(output.logits[0], dim=-1)
                confidence, predicted_ids = torch.max(probabilities, dim=-1)
            for offset, predicted_id, score in zip(layer_offsets, predicted_ids.tolist(), confidence.tolist()):
                start, end = int(offset[0]), int(offset[1])
                if start == end:
                    continue
                label = id_to_label[int(predicted_id)]
                if score < threshold:
                    label = "O"
                prior = votes_by_layer[layer_index].get((start, end))
                if prior is None or score > prior[1]:
                    votes_by_layer[layer_index][(start, end)] = (label, float(score))
    entities = []
    seen = set()
    for layer_index, votes in sorted(votes_by_layer.items()):
        for entity in decode_layer(text, votes, layer_index):
            key = (entity["type"], entity["start"], entity["end"])
            if key not in seen:
                seen.add(key)
                entity["id"] = f"pred-e{len(entities) + 1}"
                entities.append(entity)
    return entities


def main() -> None:
    args = parse_args()
    if not 0.0 <= args.confidence_threshold <= 1.0:
        raise SystemExit("--confidence-threshold must be between 0 and 1")
    config = load_config(args.config)
    model_dir = Path(config["paths"]["model_output"]) / args.mode
    if not (model_dir / "config.json").is_file():
        raise SystemExit(f"Inference blocked: no successfully trained model at {model_dir}")
    try:
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer
    except ImportError as error:
        raise SystemExit(f"Missing inference dependency: {error}")
    tokenizer = AutoTokenizer.from_pretrained(model_dir, use_fast=True)
    model = AutoModelForTokenClassification.from_pretrained(model_dir)
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device = torch.device("mps")
    elif torch.cuda.is_available():
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")
    model.to(device)
    model.eval()
    messages = load_messages(args)
    output = []
    for message in messages:
        output.append({
            "id": message["id"],
            "text": message["text"],
            "entities": predict_message(message["text"], model, tokenizer, torch, config, args.confidence_threshold),
            "model": str(model_dir),
            "device": str(device),
            "experiment_mode": getattr(model.config, "text2task_experiment_mode", args.mode),
            "metric_provenance": getattr(model.config, "text2task_metric_provenance", None),
        })
    write_jsonl(args.output, output)
    for item in output:
        print(json.dumps(item, ensure_ascii=False, indent=2))
    print(f"Saved {len(output)} predictions to {args.output.resolve()}")


if __name__ == "__main__":
    main()
