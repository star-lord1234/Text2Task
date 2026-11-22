#!/usr/bin/env python3
"""Cross-score Phase 2 runs on both label definitions and bootstrap row-level uncertainty."""
import json, random, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.model_training.span_metrics import evaluate  # noqa: E402

R = Path("results/entity_extraction/phase2")
TYPES = ["TASK", "PERSON", "TEMPORAL"]
RUNS = {"run1_lr5e-5 (+commitments)": "mailex_v1_lr5e-5", "run2_lr3e-5 (+commitments)": "mailex_v1_lr3e-5",
        "run3_lr5e-5 (requests only)": "mailex_v1_requests_only_lr5e-5"}


def load(name):
    return {r["id"]: r for r in map(json.loads, (R / name / "validation_predictions.jsonl").read_text().splitlines())}


data = {k: load(v) for k, v in RUNS.items()}
ids = sorted(data["run1_lr5e-5 (+commitments)"])
assert ids == sorted(data["run3_lr5e-5 (requests only)"]) == sorted(data["run2_lr3e-5 (+commitments)"]), "row ids differ"
for i in ids:
    lens = {len(d[i]["tokens"]) for d in data.values()}
    assert len(lens) == 1 and all(data[k][i]["tokens"] == data["run1_lr5e-5 (+commitments)"][i]["tokens"] for k in data), i
ref_full = {i: data["run1_lr5e-5 (+commitments)"][i]["references"] for i in ids}
ref_req = {i: data["run3_lr5e-5 (requests only)"][i]["references"] for i in ids}


def score(run, refs, rows=None):
    rows = rows or ids
    return evaluate([data[run][i]["predictions"] for i in rows], [refs[i] for i in rows], TYPES)


def cell(res, t=None, m="lenient"):
    b = res["overall"] if t is None else res["per_type"][t]
    return b[m]["f1"]


out = {"label_definitions": {"full (+commitments)": "primary dev labels", "requests_only": "dev labels without commitment TASKs"}, "scores": {}}
for defname, refs in (("full (+commitments)", ref_full), ("requests_only", ref_req)):
    out["scores"][defname] = {}
    print(f"\n### Scored against: {defname} labels")
    for run in RUNS:
        res = score(run, refs)
        out["scores"][defname][run] = res
        sup = {t: res["per_type"][t]["strict"]["support"] for t in TYPES}
        print(f"{run:32s} lenient overall {cell(res):.3f} | TASK {cell(res,'TASK'):.3f} PERSON {cell(res,'PERSON'):.3f} TEMPORAL {cell(res,'TEMPORAL'):.3f} | strict overall {cell(res,m='strict'):.3f} TASK {cell(res,'TASK',m='strict'):.3f} | support {sup}")

# paired bootstrap over rows: run3 minus run1, on each model's matching definition AND on the controlled PERSON/TEMPORAL spans
random.seed(20261103)
B = 400
pairs = {
    "TASK, each on its own labels (run3/requests-only vs run1/full)": ("TASK", "own"),
    "PERSON (controlled)": ("PERSON", "own"),
    "TEMPORAL (controlled)": ("TEMPORAL", "own"),
    "OVERALL, each on its own labels": (None, "own"),
}
print("\n### Paired bootstrap, lenient F1: run3 minus run1 (400 resamples of dev rows)")
for label, (t, _) in pairs.items():
    diffs = []
    for _ in range(B):
        rows = [random.choice(ids) for _ in ids]
        a = evaluate([data["run3_lr5e-5 (requests only)"][i]["predictions"] for i in rows], [ref_req[i] for i in rows], TYPES)
        b = evaluate([data["run1_lr5e-5 (+commitments)"][i]["predictions"] for i in rows], [ref_full[i] for i in rows], TYPES)
        diffs.append(cell(a, t) - cell(b, t))
    diffs.sort()
    lo, mid, hi = diffs[int(.025 * B)], diffs[B // 2], diffs[int(.975 * B)]
    out.setdefault("bootstrap_run3_minus_run1_lenient", {})[label] = {"median": mid, "ci95": [lo, hi]}
    print(f"{label:62s} median {mid:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]")

# also the run1-vs-run2 difference under the same bootstrap (hyperparameter noise reference)
diffs = []
for _ in range(B):
    rows = [random.choice(ids) for _ in ids]
    a = evaluate([data["run1_lr5e-5 (+commitments)"][i]["predictions"] for i in rows], [ref_full[i] for i in rows], TYPES)
    b = evaluate([data["run2_lr3e-5 (+commitments)"][i]["predictions"] for i in rows], [ref_full[i] for i in rows], TYPES)
    diffs.append(cell(a) - cell(b))
diffs.sort()
out["bootstrap_run1_minus_run2_lenient_overall"] = {"median": diffs[B // 2], "ci95": [diffs[int(.025 * B)], diffs[int(.975 * B)]]}
print(f"{'Reference: run1 minus run2, OVERALL, both on full labels':62s} median {diffs[B//2]:+.3f}  95% CI [{diffs[int(.025*B)]:+.3f}, {diffs[int(.975*B)]:+.3f}]")

# how many commitment-derived TASK spans does each model predict?
def tasks(run): return sum(1 for i in ids for lab in data[run][i]["predictions"] if lab == "B-TASK")
print("\nPredicted B-TASK counts:", {r: tasks(r) for r in RUNS}, "| reference B-TASK full:", sum(1 for i in ids for l in ref_full[i] if l=='B-TASK'), "requests-only:", sum(1 for i in ids for l in ref_req[i] if l=='B-TASK'))
(R / "comparison.json").write_text(json.dumps(out, indent=2, sort_keys=True))
