#!/usr/bin/env python3
"""Audit train/dev leakage (exact + near-duplicate emails) and rescore runs on a deduplicated dev set."""
import argparse, collections, hashlib, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.model_training.span_metrics import evaluate  # noqa: E402

TYPES = ["TASK", "PERSON", "TEMPORAL"]
norm = lambda t: re.sub(r"\W+", " ", t.lower()).strip()


def shingles(t, k=6):
    w = norm(t).split()
    return {hash(" ".join(w[i:i + k])) for i in range(max(1, len(w) - k + 1))}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--records-dir", type=Path, default=Path("data/mailex_v1/records"))
    p.add_argument("--runs", nargs="*", default=["mailex_v1_lr5e-5", "mailex_v1_lr3e-5", "mailex_v1_requests_only_lr5e-5"])
    p.add_argument("--results-root", type=Path, default=Path("results/entity_extraction/phase2"))
    p.add_argument("--containment", type=float, default=0.8)
    p.add_argument("--out", type=Path, default=Path("results/entity_extraction/phase2/leakage_audit.json"))
    a = p.parse_args()
    load = lambda s: [json.loads(l) for l in (a.records_dir / f"{s}.jsonl").read_text().splitlines() if l.strip()]
    tr, dv = load("train"), load("validation")
    exact_train = {hashlib.md5(norm(r["text"]).encode()).hexdigest() for r in tr}
    index = collections.defaultdict(set)
    for i, r in enumerate(tr):
        for h in shingles(r["text"]):
            index[h].add(i)
    leaked, repeats, seen = set(), set(), set()
    for r in dv:
        h = hashlib.md5(norm(r["text"]).encode()).hexdigest()
        if h in exact_train:
            leaked.add(r["id"])
        sh = shingles(r["text"])
        if len(sh) >= 5:
            cnt = collections.Counter(i for x in sh for i in index.get(x, ()))
            if cnt and cnt.most_common(1)[0][1] / len(sh) >= a.containment:
                leaked.add(r["id"])
        if h in seen:
            repeats.add(r["id"])
        seen.add(h)
    drop = leaked | repeats
    keep = {r["id"] for r in dv} - drop
    report = {"dev_emails": len(dv), "copies_of_train": len(leaked), "within_dev_repeats": len(repeats), "kept": len(keep), "runs": {}}
    for run in a.runs:
        rows = [json.loads(l) for l in (a.results_root / run / "validation_predictions.jsonl").read_text().splitlines()]
        clean = [r for r in rows if r["source_record_id"] in keep]
        full_e = evaluate([r["predictions"] for r in rows], [r["references"] for r in rows], TYPES)
        clean_e = evaluate([r["predictions"] for r in clean], [r["references"] for r in clean], TYPES)
        report["runs"][run] = {"full_dev": full_e, "deduplicated_dev": clean_e, "rows_full": len(rows), "rows_clean": len(clean)}
        f = lambda e, m: round(e["overall"][m]["f1"], 3)
        print(f"{run:34s} lenient {f(full_e,'lenient')} -> {f(clean_e,'lenient')} | strict {f(full_e,'strict')} -> {f(clean_e,'strict')}")
    report["leaked_ids"] = sorted(leaked)
    a.out.write_text(json.dumps(report, indent=2, sort_keys=True))
    print({k: v for k, v in report.items() if k not in ("runs", "leaked_ids")})


main()
