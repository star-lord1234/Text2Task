#!/usr/bin/env python3
"""Audit relation data (Phase 3, Step 1): support, offsets, leakage, endpoint types, length."""
from __future__ import annotations

import argparse, hashlib, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.model_data.relation_classification import VALID_PAIR_LABELS, marked_text  # noqa: E402
from src.model_data.token_classification import read_jsonl  # noqa: E402

SUPPORTED = {"TASK", "PERSON", "TEMPORAL"}
SPLITS = ("train", "validation", "test")


def norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--final-dir", type=Path, default=ROOT / "data/final")
    ap.add_argument("--relations-dir", type=Path, default=ROOT / "data/model_ready/relations")
    ap.add_argument("--out", type=Path, default=ROOT / "results/relation_extraction")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(ROOT / "models/text2task-distilbert/entity_v2_three_class/epoch3")

    report: dict = {"splits": {}}
    threads, texts = {}, {}
    for split in SPLITS:
        recs = read_jsonl(args.final_dir / f"{split}.jsonl")
        threads[split] = {r["thread_id"] for r in recs}
        texts[split] = {norm(r["text"]) for r in recs}
        ent_types, rel_counts, rel_dropped = Counter(), Counter(), Counter()
        bad_offsets = bad_evidence = 0
        explicit, ambiguous = Counter(), Counter()
        for r in recs:
            a = r["text2task_annotations"]
            ents = {e["id"]: e for e in a.get("entities") or []}
            for e in ents.values():
                ent_types[e["type"]] += 1
                if r["text"][e["start"]:e["end"]] != e["text"]:
                    bad_offsets += 1
            for rel in a.get("relations") or []:
                t = rel.get("type")
                s, d = ents.get(rel.get("source_entity_id")), ents.get(rel.get("target_entity_id"))
                if not s or not d:
                    rel_dropped["missing_endpoint"] += 1
                    continue
                rel_counts[t] += 1
                explicit[(t, rel.get("explicit_vs_inferred"))] += 1
                ambiguous[(t, bool(rel.get("ambiguous")))] += 1
                if s["type"] not in SUPPORTED or d["type"] not in SUPPORTED:
                    rel_dropped[f"{t}:{s['type']}->{d['type']}"] += 1
                ev = rel.get("relation_evidence")
                if isinstance(ev, dict) and r["text"][ev["start"]:ev["end"]] != ev["text"]:
                    bad_evidence += 1
        report["splits"][split] = {
            "records": len(recs), "threads": len(threads[split]),
            "entity_types": dict(ent_types), "relations_by_type": dict(rel_counts),
            "dropped_for_unsupported_endpoints_or_missing": dict(rel_dropped),
            "entity_offset_mismatches": bad_offsets, "evidence_not_in_text": bad_evidence,
            "explicit_vs_inferred": {f"{k[0]}|{k[1]}": v for k, v in explicit.items()},
            "ambiguous": {f"{k[0]}|{k[1]}": v for k, v in ambiguous.items()},
        }

    leak = {}
    for a, b in (("train", "validation"), ("train", "test"), ("validation", "test")):
        leak[f"{a}~{b}"] = {"shared_threads": len(threads[a] & threads[b]),
                            "exact_normalized_text_duplicates": len(texts[a] & texts[b])}
    report["leakage"] = leak

    # export checks
    exp = {}
    for split in SPLITS:
        rows = read_jsonl(args.relations_dir / f"{split}.jsonl")
        too_long = roundtrip_bad = 0
        lens = []
        types = Counter()
        for row in rows:
            s, t = row["source_entity"], row["target_entity"]
            types[f"{s['type']}->{t['type']}"] += 1
            if marked_text(row["text"], s, t) != row["marked_text"]:
                roundtrip_bad += 1
            n = len(tok(row["marked_text"], add_special_tokens=True)["input_ids"])
            lens.append(n)
            if n > 512:
                too_long += 1
        lens.sort()
        exp[split] = {"rows": len(rows), "pair_types": dict(types), "marker_roundtrip_failures": roundtrip_bad,
                      "over_512_tokens": too_long, "p50_len": lens[len(lens)//2], "p95_len": lens[int(len(lens)*.95)],
                      "max_len": lens[-1], "labels": dict(Counter(r["label"] for r in rows))}
    report["export_checks"] = exp
    (args.out / "audit.json").write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps(report, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
