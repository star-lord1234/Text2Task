"""Entity inference (Phase 2 checkpoints) as a library: load once, predict many times.

Moved out of scripts so the API and the CLIs share one implementation. Behaviour is unchanged: windowed token
classification, highest-confidence vote per sub-token span, BIO decoding into character-offset spans.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence


def decode(text: str, votes: dict[tuple[int, int], tuple[str, float]]) -> list[dict[str, Any]]:
    entities, current = [], None
    for (start, end), (label, confidence) in sorted(votes.items()):
        if label == "O":
            if current:
                entities.append(current)
                current = None
            continue
        prefix, entity_type = label.split("-", 1)
        continues = current is not None and prefix == "I" and current["type"] == entity_type
        if not continues:
            if current:
                entities.append(current)
            current = {"type": entity_type, "start": start, "end": end, "scores": [confidence]}
        else:
            current["end"] = end
            current["scores"].append(confidence)
    if current:
        entities.append(current)
    for index, entity in enumerate(entities, 1):
        entity["id"] = f"pred-e{index}"
        entity["text"] = text[entity["start"]:entity["end"]]
        scores = entity.pop("scores")
        entity["confidence"] = sum(scores) / len(scores) if scores else 0.0
    return entities


class EntityPredictor:
    """Loads a token-classification checkpoint once. ``predict`` returns TASK/PERSON/TEMPORAL spans with offsets."""

    def __init__(self, model_dir: str | Path, device: Optional[str] = None, max_length: int = 512, stride: int = 64):
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        self.model_dir = str(model_dir)
        self.torch = torch
        self.device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir, use_fast=True)
        self.model = AutoModelForTokenClassification.from_pretrained(self.model_dir).to(self.device).eval()
        self.id2label = {int(k): v for k, v in self.model.config.id2label.items()}
        self.max_length, self.stride = max_length, stride

    def predict(self, text: str) -> list[dict[str, Any]]:
        return decode(text, self.votes(text))

    def votes(self, text: str) -> dict[tuple[int, int], tuple[str, float]]:
        """Raw per-sub-token labels {(char_start, char_end): (label, confidence)} before BIO decoding (used by the audit and the Inspector)."""
        torch = self.torch
        enc = self.tokenizer(text, truncation=True, max_length=self.max_length, stride=self.stride, return_overflowing_tokens=True,
                             return_offsets_mapping=True, padding=False)
        votes: dict[tuple[int, int], tuple[str, float]] = {}
        for ids, att, offsets in zip(enc["input_ids"], enc["attention_mask"], enc["offset_mapping"]):
            with torch.no_grad():
                probs = torch.softmax(self.model(input_ids=torch.tensor([ids], device=self.device),
                                                 attention_mask=torch.tensor([att], device=self.device)).logits[0], -1)
                scores, label_ids = probs.max(-1)
            for offset, label_id, score in zip(offsets, label_ids.tolist(), scores.tolist()):
                start, end = int(offset[0]), int(offset[1])
                if start == end:
                    continue
                if (start, end) not in votes or score > votes[(start, end)][1]:
                    votes[(start, end)] = (self.id2label[label_id], float(score))
        return votes


def predict_entities(texts: Sequence[str], model_dir: str | Path, device: Optional[str] = None) -> list[list[dict[str, Any]]]:
    predictor = EntityPredictor(model_dir, device)
    return [predictor.predict(t) for t in texts]
