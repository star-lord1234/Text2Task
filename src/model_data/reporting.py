"""Combined human-readable report for both model-data builders."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def _load(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def write_model_data_report(report_path: Path, entities_dir: Path, relations_dir: Path) -> None:
    entity_stats = _load(entities_dir / "statistics.json")
    relation_stats = _load(relations_dir / "statistics.json")
    lines = [
        "# Text2Task Model-Ready Data Statistics",
        "",
        "> Annotation warning: the current finalized corpus is AI-generated **SILVER**, including validation and test. "
        "These held-out splits preserve MailEx membership but are not human-gold evaluation sets.",
        "",
    ]
    if entity_stats:
        lines.extend([
            "## Model A — DistilBERT token classification",
            "",
            f"Tokenizer: `{entity_stats['tokenizer']}` using the official vocabulary SHA-256 "
            f"`{entity_stats['vocabulary_sha256']}`. Maximum length is {entity_stats['max_length']} with "
            f"stride {entity_stats['stride']}. Special-token labels are `-100`; the first entity piece receives "
            "`B-TYPE` and every remaining entity subword receives `I-TYPE`.",
            "",
            "Overlaps are not overwritten. Interval-coloring creates the minimum greedy set of deterministic, "
            "non-overlapping BIO layers, each traceable to the same source email.",
            "",
            "| Split | Emails | Threads | Rows | Entities | Emails with overlap layers | Max layers | Multi-window emails |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for split in ("train", "validation", "test"):
            values = entity_stats["splits"][split]
            lines.append(
                f"| {split} | {values['source_records']} | {values['threads']} | {values['model_rows']} | "
                f"{values['entities']} | {values['records_requiring_overlap_layers']} | {values['maximum_layers']} | "
                f"{values['records_requiring_multiple_windows']} |"
            )
        lines.extend(["", "Every emitted BIO row was reconstructed from its labeled offsets and checked against the original entity spans.", ""])
    if relation_stats:
        lines.extend([
            "## Model B — relation classification",
            "",
            f"Entity source: `{relation_stats['entity_source']}`. Negative sampling ratio: "
            f"{relation_stats['negative_ratio']}:1 (seed {relation_stats['seed']}). All positive edges are retained. "
            "NONE examples are sampled only from inference-valid endpoint pairs.",
            "",
            "| Split | Emails | Threads | Valid candidates | Kept rows | Positives | NONE | ASSIGNED | DUE | SCHEDULED | DEPENDS |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for split in ("train", "validation", "test"):
            values = relation_stats["splits"][split]
            labels = values["label_counts"]
            lines.append(
                f"| {split} | {values['source_records']} | {values['threads']} | {values['all_type_valid_candidates']} | "
                f"{values['model_rows']} | {values['positive_rows']} | {labels.get('NONE', 0)} | "
                f"{labels.get('ASSIGNED_TO', 0)} | {labels.get('DUE_ON', 0)} | {labels.get('SCHEDULED_ON', 0)} | "
                f"{labels.get('DEPENDS_ON', 0)} |"
            )
        lines.extend([
            "",
            "Each row stores the untouched email text, typed `[E1_*]`/`[E2_*]` marked text, exact entity offsets, "
            "source record/thread IDs, and relation evidence for positive labels. The CLI also accepts per-split "
            "predicted-entity files; gold relations are then transferred only through exact type-and-span matches.",
            "",
            "## Split integrity",
            "",
            "The builders read `train.jsonl`, `validation.jsonl`, and `test.jsonl` separately and assert their "
            "original MailEx source splits (`train`, `dev`, `test`). Entity pairs are created only within one email, "
            "so no pair or example can cross a split or thread boundary.",
            "",
        ])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
