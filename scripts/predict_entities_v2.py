#!/usr/bin/env python3
"""Run the versioned single-layer Text2Task v2 entity extractor."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).resolve().parents[1]))
from collections import defaultdict
from pathlib import Path
from typing import Any


DEMO_MESSAGES = [
    "Priya, please send the revised budget to finance by Tuesday.",
    "The report was filed yesterday and no further action is required.",
    "Morgan will schedule the kickoff meeting for next week.",
    "Do not publish the release notes tomorrow.",
    "Alex completed the audit last Friday.",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=Path("models/text2task-distilbert/entity_v2_three_class/epoch3_sqrt_weighted"))
    parser.add_argument("--text", action="append")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("results/entity_extraction/entity_v2_three_class/unseen_predictions.jsonl"))
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--stride", type=int, default=64)
    return parser.parse_args()


from src.model_training.entity_inference import decode  # noqa: E402  (moved into the library)


def main() -> None:
    args = parse_args()
    messages = list(args.text or [])
    if args.demo:
        messages.extend(DEMO_MESSAGES)
    if not messages:
        raise SystemExit("Provide --text or --demo")
    import torch
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.model, use_fast=True)
    model = AutoModelForTokenClassification.from_pretrained(args.model)
    device = torch.device("mps") if torch.backends.mps.is_available() else torch.device("cpu")
    model.to(device).eval()
    id_to_label = {int(key): value for key, value in model.config.id2label.items()}
    output = []
    for index, text in enumerate(messages):
        encoded = tokenizer(
            text, truncation=True, max_length=args.max_length, stride=args.stride,
            return_overflowing_tokens=True, return_offsets_mapping=True,
            return_attention_mask=True, padding=False,
        )
        votes: dict[tuple[int, int], tuple[str, float]] = {}
        for input_ids, attention_mask, offsets in zip(encoded["input_ids"], encoded["attention_mask"], encoded["offset_mapping"]):
            with torch.no_grad():
                logits = model(
                    input_ids=torch.tensor([input_ids], device=device),
                    attention_mask=torch.tensor([attention_mask], device=device),
                ).logits[0]
                probabilities = torch.softmax(logits, dim=-1)
                scores, label_ids = torch.max(probabilities, dim=-1)
            for offset, label_id, score in zip(offsets, label_ids.tolist(), scores.tolist()):
                start, end = map(int, offset)
                if start == end:
                    continue
                key = (start, end)
                if key not in votes or score > votes[key][1]:
                    votes[key] = (id_to_label[int(label_id)], float(score))
        output.append({
            "id": f"unseen-{index + 1:02d}", "text": text,
            "entities": decode(text, votes), "model": str(args.model),
            "device": str(device), "metric_provenance": getattr(model.config, "text2task_metric_provenance", None),
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in output:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
