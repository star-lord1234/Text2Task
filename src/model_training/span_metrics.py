"""Strict, lenient, and token-level entity metrics for BIO label sequences.

All positions are indices into the label sequence (WordPiece tokens), exactly
as in the prediction files written by the training scripts.

Metric definitions
------------------
strict         Predicted span equals a reference span (same type, same start/end).
               Decoding follows seqeval's default convention, so this reproduces
               the earlier seqeval F1 numbers.
lenient        Same type and span IoU >= ``iou_threshold`` (default 0.5).
               One-to-one: each reference span matches at most one predicted span.
overlap_any    Same type and at least one shared token. One-to-one. This is a
               diagnostic that separates "found the right place" from "got the
               boundaries right"; it is not a headline metric.
token          Per-type token-level precision/recall/F1 ignoring B/I prefixes.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping, Sequence

Span = tuple[str, int, int]  # (type, start inclusive, end exclusive)


def decode_spans(labels: Sequence[str]) -> list[Span]:
    """Decode BIO labels to spans using seqeval's default (lenient-start) rules.

    A span starts at a ``B-X`` or at an ``I-X`` that does not continue an open
    span of the same type X. It ends when the next label is not ``I-X``.
    """
    spans: list[Span] = []
    current_type: str | None = None
    start = 0
    for index, label in enumerate(labels):
        if label == "O" or label is None or "-" not in label:
            if current_type is not None:
                spans.append((current_type, start, index))
                current_type = None
            continue
        prefix, entity_type = label.split("-", 1)
        if prefix == "B" or current_type != entity_type:
            if current_type is not None:
                spans.append((current_type, start, index))
            current_type, start = entity_type, index
        # prefix == "I" and same type: the open span continues
    if current_type is not None:
        spans.append((current_type, start, len(labels)))
    return spans


def _counts(precision_hits: int, predicted: int, recall_hits: int, reference: int) -> dict[str, float]:
    precision = precision_hits / predicted if predicted else 0.0
    recall = recall_hits / reference if reference else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": precision, "recall": recall, "f1": f1,
        "predicted": predicted, "support": reference, "matched": precision_hits,
    }


def _iou(a: Span, b: Span) -> float:
    overlap = min(a[2], b[2]) - max(a[1], b[1])
    if overlap <= 0:
        return 0.0
    union = (a[2] - a[1]) + (b[2] - b[1]) - overlap
    return overlap / union


def _overlap(a: Span, b: Span) -> int:
    return max(0, min(a[2], b[2]) - max(a[1], b[1]))


def _match_count(predicted: Sequence[Span], reference: Sequence[Span], score, threshold: float) -> int:
    """Greedy one-to-one matching, best score first, same type only."""
    candidates = []
    for pi, p in enumerate(predicted):
        for ri, r in enumerate(reference):
            if p[0] != r[0]:
                continue
            value = score(p, r)
            if value >= threshold and value > 0:
                candidates.append((value, pi, ri))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    used_p: set[int] = set()
    used_r: set[int] = set()
    for _, pi, ri in candidates:
        if pi in used_p or ri in used_r:
            continue
        used_p.add(pi)
        used_r.add(ri)
    return len(used_p)


def _token_type(label: str) -> str | None:
    if label is None or label == "O" or "-" not in label:
        return None
    return label.split("-", 1)[1]


def evaluate(
    predictions: Sequence[Sequence[str]],
    references: Sequence[Sequence[str]],
    entity_types: Iterable[str],
    iou_threshold: float = 0.5,
) -> dict[str, object]:
    """Compute all metrics. Returns ``{"overall": {...}, "per_type": {type: {...}}}``.

    Each metric entry is ``{"strict": {...}, "lenient": {...}, "overlap_any": {...}, "token": {...}}``
    with precision/recall/f1/predicted/support/matched.
    """
    if len(predictions) != len(references):
        raise ValueError("predictions and references must have the same number of rows")
    types = list(entity_types)
    pred_n: dict[str, int] = defaultdict(int)
    ref_n: dict[str, int] = defaultdict(int)
    hits = {name: defaultdict(int) for name in ("strict", "lenient", "overlap_any")}
    token_tp: dict[str, int] = defaultdict(int)
    token_pred: dict[str, int] = defaultdict(int)
    token_ref: dict[str, int] = defaultdict(int)

    for pred_row, ref_row in zip(predictions, references):
        if len(pred_row) != len(ref_row):
            raise ValueError("prediction and reference rows must have equal length")
        pred_spans = decode_spans(pred_row)
        ref_spans = decode_spans(ref_row)
        for t in types:
            p_t = [s for s in pred_spans if s[0] == t]
            r_t = [s for s in ref_spans if s[0] == t]
            pred_n[t] += len(p_t)
            ref_n[t] += len(r_t)
            hits["strict"][t] += len(set(p_t) & set(r_t))
            hits["lenient"][t] += _match_count(p_t, r_t, _iou, iou_threshold)
            hits["overlap_any"][t] += _match_count(p_t, r_t, lambda a, b: float(_overlap(a, b) > 0), 1.0)
        for p_label, r_label in zip(pred_row, ref_row):
            pt, rt = _token_type(p_label), _token_type(r_label)
            if pt:
                token_pred[pt] += 1
            if rt:
                token_ref[rt] += 1
            if pt and pt == rt:
                token_tp[pt] += 1

    def build(selected: Sequence[str]) -> dict[str, dict[str, float]]:
        out = {}
        for name in ("strict", "lenient", "overlap_any"):
            h = sum(hits[name][t] for t in selected)
            out[name] = _counts(h, sum(pred_n[t] for t in selected), h, sum(ref_n[t] for t in selected))
        tp = sum(token_tp[t] for t in selected)
        out["token"] = _counts(tp, sum(token_pred[t] for t in selected), tp, sum(token_ref[t] for t in selected))
        return out

    return {
        "iou_threshold": iou_threshold,
        "overall": build(types),
        "per_type": {t: build([t]) for t in types},
    }


def format_table(result: Mapping[str, object]) -> str:
    """Markdown table of F1 (P/R) per type for the four metrics."""
    rows = ["| Type | Support | Strict F1 | Lenient F1 | Overlap-any F1 | Token F1 |", "|---|---:|---:|---:|---:|---:|"]
    blocks = list(result["per_type"].items()) + [("OVERALL", result["overall"])]  # type: ignore[union-attr]
    for name, block in blocks:
        rows.append(
            f"| {name} | {block['strict']['support']} | {block['strict']['f1']:.4f} | "
            f"{block['lenient']['f1']:.4f} | {block['overlap_any']['f1']:.4f} | {block['token']['f1']:.4f} |"
        )
    return "\n".join(rows)
