"""Relation classifier (Phase 3): DistilBERT with entity-marker pooling, metrics, and inference."""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import nn
from transformers import AutoModel, AutoTokenizer

from src.model_data.relation_classification import marked_text

LABELS = ["NONE", "ASSIGNED_TO", "DUE_ON", "SCHEDULED_ON"]
LABEL_TO_ID = {l: i for i, l in enumerate(LABELS)}
POSITIVE = LABELS[1:]
# Endpoint-type -> labels a pair may take (NONE always allowed).
TARGET_ALLOWED = {"PERSON": ["NONE", "ASSIGNED_TO"], "TEMPORAL": ["NONE", "DUE_ON", "SCHEDULED_ON"]}
MARKERS = ["[E1_TASK]", "[/E1_TASK]", "[E2_PERSON]", "[/E2_PERSON]", "[E2_TEMPORAL]", "[/E2_TEMPORAL]"]
POOLINGS = ("cls", "markers")


def seed_everything(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)


def detect_device() -> str:
    return "mps" if torch.backends.mps.is_available() else "cpu"


def build_tokenizer(name_or_path: str | Path):
    tok = AutoTokenizer.from_pretrained(str(name_or_path), use_fast=True)
    missing = [m for m in MARKERS if m not in tok.get_vocab()]
    if missing:
        tok.add_special_tokens({"additional_special_tokens": missing})
    return tok


def allowed_mask(target_type: str) -> list[bool]:
    allowed = TARGET_ALLOWED.get(target_type, ["NONE"])
    return [l in allowed for l in LABELS]


class RelationClassifier(nn.Module):
    def __init__(self, base_name: str | Path, tokenizer, pooling: str = "markers", dropout: float = 0.1, load_base: bool = True):
        super().__init__()
        if pooling not in POOLINGS:
            raise ValueError(f"pooling must be one of {POOLINGS}")
        self.pooling = pooling
        if load_base:
            self.encoder = AutoModel.from_pretrained(str(base_name))
        else:
            from transformers import AutoConfig
            self.encoder = AutoModel.from_config(AutoConfig.from_pretrained(str(base_name)))
        old = self.encoder.get_input_embeddings().weight.shape[0]
        if len(tokenizer) > old:
            self.encoder.resize_token_embeddings(len(tokenizer))
            if load_base:  # initialise new rows from the mean of existing embeddings
                with torch.no_grad():
                    emb = self.encoder.get_input_embeddings().weight
                    emb[old:] = emb[:old].mean(0, keepdim=True) + 0.02 * torch.randn_like(emb[old:])
        hidden = self.encoder.config.dim
        self.dropout = nn.Dropout(dropout)
        self.head = nn.Linear(hidden * (3 if pooling == "markers" else 1), len(LABELS))
        self.register_buffer("e1_id", torch.tensor(tokenizer.convert_tokens_to_ids("[E1_TASK]")), persistent=False)
        self.register_buffer("e2_ids", torch.tensor(tokenizer.convert_tokens_to_ids(["[E2_PERSON]", "[E2_TEMPORAL]"])), persistent=False)

    def forward(self, input_ids, attention_mask, label_mask):
        h = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        cls = h[:, 0]
        if self.pooling == "cls":
            feats = cls
        else:
            idx = torch.arange(h.size(0), device=h.device)
            p1 = (input_ids == self.e1_id).int().argmax(1)
            p2 = torch.isin(input_ids, self.e2_ids).int().argmax(1)
            feats = torch.cat([cls, h[idx, p1], h[idx, p2]], dim=-1)
        logits = self.head(self.dropout(feats))
        return logits.masked_fill(~label_mask, -1e4)


def encode_rows(rows: Sequence[Mapping[str, Any]], tokenizer, max_length: int = 512) -> list[dict[str, Any]]:
    items = []
    for row in rows:
        enc = tokenizer(row["marked_text"], truncation=True, max_length=max_length)
        ids = enc["input_ids"]
        e1 = tokenizer.convert_tokens_to_ids("[E1_TASK]")
        e2 = tokenizer.convert_tokens_to_ids(f"[E2_{row['target_entity']['type']}]")
        items.append({
            "input_ids": ids, "label": LABEL_TO_ID.get(row.get("label", "NONE"), 0),
            "label_mask": allowed_mask(row["target_entity"]["type"]),
            "representable": e1 in ids and e2 in ids,
        })
    return items


def collate(batch: Sequence[Mapping[str, Any]], pad_id: int, device: str):
    n = max(len(b["input_ids"]) for b in batch)
    ids = torch.full((len(batch), n), pad_id, dtype=torch.long)
    att = torch.zeros((len(batch), n), dtype=torch.long)
    for i, b in enumerate(batch):
        ids[i, : len(b["input_ids"])] = torch.tensor(b["input_ids"])
        att[i, : len(b["input_ids"])] = 1
    labels = torch.tensor([b["label"] for b in batch])
    mask = torch.tensor([b["label_mask"] for b in batch], dtype=torch.bool)
    return ids.to(device), att.to(device), mask.to(device), labels.to(device)


@torch.no_grad()
def predict_probs(model: RelationClassifier, items: Sequence[Mapping[str, Any]], pad_id: int, device: str, batch_size: int = 32) -> list[list[float]]:
    model.eval()
    out = []
    for i in range(0, len(items), batch_size):
        ids, att, mask, _ = collate(items[i:i + batch_size], pad_id, device)
        out.extend(torch.softmax(model(ids, att, mask), -1).cpu().tolist())
    return out


def prf(gold: Sequence[str], pred: Sequence[str]) -> dict[str, Any]:
    """Per-positive-label P/R/F1 with support, micro (positives only) and macro (labels with support)."""
    res: dict[str, Any] = {}
    tp_all = fp_all = fn_all = 0
    f1s = []
    for label in POSITIVE:
        tp = sum(g == label and p == label for g, p in zip(gold, pred))
        fp = sum(g != label and p == label for g, p in zip(gold, pred))
        fn = sum(g == label and p != label for g, p in zip(gold, pred))
        support = tp + fn
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        res[label] = {"precision": p, "recall": r, "f1": f, "support": support, "predicted": tp + fp, "tp": tp, "fp": fp, "fn": fn}
        tp_all += tp; fp_all += fp; fn_all += fn
        if support:
            f1s.append(f)
    p = tp_all / (tp_all + fp_all) if tp_all + fp_all else 0.0
    r = tp_all / (tp_all + fn_all) if tp_all + fn_all else 0.0
    res["micro_positive"] = {"precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0}
    res["macro_positive_f1"] = sum(f1s) / len(f1s) if f1s else 0.0
    none_total = sum(g == "NONE" for g in gold)
    res["NONE"] = {"support": none_total, "false_positive_rate": sum(g == "NONE" and p != "NONE" for g, p in zip(gold, pred)) / none_total if none_total else 0.0}
    res["confusion"] = {f"{g}->{p}": c for (g, p), c in sorted(Counter(zip(gold, pred)).items())}
    return res


def save_model(model: RelationClassifier, tokenizer, out_dir: Path, meta: Mapping[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out_dir / "model.pt")
    tokenizer.save_pretrained(out_dir)
    (out_dir / "relation_config.json").write_text(json.dumps(dict(meta), indent=2, sort_keys=True, default=str))


class RelationPredictor:
    """Load a saved checkpoint and score entity pairs. Softmax scores are NOT calibrated."""

    def __init__(self, model_dir: str | Path, device: str | None = None, threshold: float | None = None):
        model_dir = Path(model_dir)
        if not (model_dir / "model.pt").is_file():
            raise FileNotFoundError(f"No relation checkpoint at {model_dir}")
        self.meta = json.loads((model_dir / "relation_config.json").read_text())
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_dir), use_fast=True)
        # A release bundle carries config.json beside the checkpoint so inference
        # is completely offline. Older experiment folders can still fall back to
        # the original Hugging Face model identifier.
        architecture_source: str | Path = model_dir if (model_dir / "config.json").is_file() else self.meta["base_model"]
        self.model = RelationClassifier(architecture_source, self.tokenizer, self.meta["pooling"], load_base=False)
        self.model.load_state_dict(torch.load(model_dir / "model.pt", map_location="cpu", weights_only=True))
        self.device = device or detect_device()
        self.model.to(self.device).eval()
        self.version = self.meta.get("version", str(model_dir))
        self.threshold = threshold if threshold is not None else self.meta.get("min_positive_score")

    def predict(self, text: str, entities: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """Return {'relations': [...], 'no_link': [...], 'unrepresentable': [...]}."""
        tasks = [e for e in entities if e["type"] == "TASK"]
        targets = [e for e in entities if e["type"] in TARGET_ALLOWED]
        pairs = [(s, t) for s in tasks for t in targets if s["id"] != t["id"]]
        rows = [{"marked_text": marked_text(text, s, t), "target_entity": t, "source_entity": s} for s, t in pairs]
        items = encode_rows(rows, self.tokenizer)
        probs = predict_probs(self.model, items, self.tokenizer.pad_token_id, self.device)
        out = {"relations": [], "no_link": [], "unrepresentable": []}
        for (s, t), item, p in zip(pairs, items, probs):
            base = {"source_id": s["id"], "target_id": t["id"], "source_text": s["text"], "target_text": t["text"],
                    "model_version": self.version, "provenance": "neural"}
            if not item["representable"]:
                out["unrepresentable"].append(base)
                continue
            k = max(range(len(LABELS)), key=lambda i: p[i])
            label, score = LABELS[k], p[k]
            abstained = label != "NONE" and self.threshold is not None and score < self.threshold
            rec = dict(base, label=label, score=score, scores=dict(zip(LABELS, p)), abstained=abstained)
            if label == "NONE" or abstained:
                out["no_link"].append(rec)
            else:
                lo, hi = min(s["start"], t["start"]), max(s["end"], t["end"])
                out["relations"].append(dict(rec, evidence_text=text[lo:hi]))
        return out
