"""Collect every number the report uses into report/data/stats.json.

Reads only saved repository artefacts (datasets, training logs, evaluation outputs). Nothing is retrained or re-scored,
except dataset counts, which are recomputed directly from the JSONL files so they can be checked against the saved statistics.
Run from the repository root:  python report/scripts/extract_stats.py
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "report" / "data" / "stats.json"


def load(p: str):
    return json.loads((ROOT / p).read_text())


def jsonl(p: str):
    with (ROOT / p).open() as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def mailex_unified() -> dict:
    """MailEx as converted to the unified format: emails, threads, event types, emails without events."""
    out = {}
    for split, fname in (("train", "train"), ("dev", "dev"), ("test", "test")):
        emails, threads, events, empty, no_event = 0, set(), collections.Counter(), 0, 0
        for r in jsonl(f"data/unified/{fname}.jsonl"):
            emails += 1
            threads.add(r["thread_id"])
            ev = r.get("original_events") or {}
            if not ev:
                no_event += 1
            for etype in ev:
                events[etype] += 1
            if not (r.get("text") or "").strip():
                empty += 1
        out[split] = {"emails": emails, "threads": len(threads), "event_type_email_counts": dict(events),
                      "emails_without_events": no_event, "empty_text_emails": empty}
    return out


def bio_distribution(path: str) -> dict:
    c = collections.Counter()
    for r in jsonl(path):
        for lab in r["labels"]:
            if lab is not None:
                c[lab] += 1
    return dict(c)


def entity_counts_from_rows(path: str) -> dict:
    c = collections.Counter()
    for r in jsonl(path):
        for e in r.get("entities") or []:
            c[e["type"]] += 1
    return dict(c)


def silver_final() -> dict:
    """Six-class SILVER statistics as recorded by finalize_dataset (markdown report)."""
    text = (ROOT / "data/reports/final_dataset_statistics.md").read_text()
    out, split = {}, None
    for line in text.splitlines():
        m = re.match(r"^### (train|validation|test)\s*$", line)
        if m:
            split = m.group(1); out[split] = {}
            continue
        if split and line.startswith("Entity labels:"):
            out[split]["entities"] = json.loads(line.split("`")[1])
        if split and line.startswith("Relation labels:"):
            out[split]["relations"] = json.loads(line.split("`")[1])
        m = re.match(r"^- (Emails|Threads): (\d+)", line)
        if split and m:
            out[split][m.group(1).lower()] = int(m.group(2))
    return out


def curves() -> dict:
    out = {}
    runs = {
        "phase2_lr5e-5": "results/entity_extraction/phase2/mailex_v1_lr5e-5/training_log.json",
        "phase2_lr3e-5": "results/entity_extraction/phase2/mailex_v1_lr3e-5/training_log.json",
        "phase2_requests_only": "results/entity_extraction/phase2/mailex_v1_requests_only_lr5e-5/training_log.json",
        "v2_sqrt_weighted": "results/entity_extraction/entity_v2_three_class/epoch3_sqrt_weighted/training_log.json",
    }
    for name, p in runs.items():
        if not (ROOT / p).exists():
            continue
        hist = load(p)
        hist = hist.get("log_history", hist) if isinstance(hist, dict) else hist
        train = [{"epoch": h["epoch"], "loss": h["loss"]} for h in hist if "loss" in h and "eval_loss" not in h]
        ev = [{k: h[k] for k in h if k.startswith("eval_") or k == "epoch"} for h in hist if "eval_loss" in h]
        out[name] = {"train": train, "eval": ev, "source": p}
    out["relation_markers_sqrt"] = dict(load("results/relation_extraction/runs/markers_sqrt/training_summary.json"),
                                        source="results/relation_extraction/runs/markers_sqrt/training_summary.json")
    return out


def main() -> None:
    rel_eval = load("results/relation_extraction/evaluation/validation_markers_sqrt.json")
    stats = {
        "mailex_unified": mailex_unified(),
        "mailex_derived_entities": load("data/model_ready/entities_mailex_v1/statistics.json")["splits"],
        "mailex_derived_requests_only": load("data/model_ready/entities_mailex_v1_requests_only/statistics.json")["splits"],
        "mailex_derived_recount": {s: entity_counts_from_rows(f"data/model_ready/entities_mailex_v1/{s}.jsonl") for s in ("train", "validation")},
        "bio_token_distribution_mailex_train": bio_distribution("data/model_ready/entities_mailex_v1/train.jsonl"),
        "silver_v2_entities": load("data/model_ready/entities_v2_three_class/statistics.json")["splits"],
        "silver_final_six_class": silver_final(),
        "relation_dataset": load("data/model_ready/relations_v2_three_class/manifest.json")["splits"],
        "curves": curves(),
        "phase0_baseline": load("results/entity_extraction/baseline/phase0_baseline.json"),
        "phase2_dedup_rescore": load("results/entity_extraction/phase2/dedup_rescore.json"),
        "phase2_comparison": load("results/entity_extraction/phase2/comparison.json"),
        "relation_eval": rel_eval,
        "v2_sqrt_metrics": load("results/entity_extraction/entity_v2_three_class/epoch3_sqrt_weighted/metrics.json"),
        "phase4": load("results/phase4/report.json"),
        "phase7_5_summary": load("results/phase7_5/summary.json"),
        "phase7_5_silver": load("results/phase7_5/silver_validation.json"),
        "phase7_5_review_load": load("results/phase7_5/email_review_load.json"),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(stats, indent=1, default=str))
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
