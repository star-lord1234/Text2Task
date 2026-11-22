#!/usr/bin/env python3
"""Phase 4 functional/provisional evaluation. Uses train+validation only; the test split is never read.

Reports: fixture pass rate, corpus temporal coverage, assignee-resolution distribution, flag rates,
and a validation selective-prediction table for relation scores (SILVER, uncalibrated softmax).
"""
from __future__ import annotations

import argparse, json, random, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))

from src.baselines.rule_relations import predict_rules  # noqa: E402
from src.model_data.token_classification import read_jsonl  # noqa: E402
from src.model_training.relation_classifier import LABELS, RelationPredictor, encode_rows, predict_probs  # noqa: E402
from src.pipeline.contracts import MessageEnvelope  # noqa: E402
from src.pipeline.identity_resolution import registry_from_mailex_record  # noqa: E402
from src.pipeline.task_fields import build_task_candidates  # noqa: E402
from src.pipeline.uncertainty import load_config  # noqa: E402
from src.temporal.normalize import normalize_temporal  # noqa: E402

ILLUSTRATIVE_ANCHOR = "2001-11-15T09:00:00"   # NOT a real message time; exercises the relative-date paths only
SCOPE_TYPES = {"TASK", "PERSON", "TEMPORAL"}


def fixtures_pass_rate():
    cases = json.loads((ROOT / "tests/fixtures/temporal_cases.json").read_text())["cases"]
    ok = 0
    for c in cases:
        tv = normalize_temporal(c["raw"], reference_ts=c["ref"], timezone=c["tz"])
        e = c["expect"]
        good = tv.status == e["status"] and all(getattr(tv, k) == e[k] for k in ("granularity", "value", "start", "end", "part_of_day", "in_past", "deadline_phrase") if k in e)
        good = good and all(a in tv.assumptions for a in e.get("assumptions_include", []))
        ok += good
    return {"cases": len(cases), "passed": ok}


def corpus_coverage():
    spans = []
    for sp in ("train", "validation"):
        for r in read_jsonl(ROOT / f"data/final/{sp}.jsonl"):
            spans += [e["text"] for e in r["text2task_annotations"]["entities"] if e["type"] == "TEMPORAL"]
    out = {"n_spans": len(spans), "n_distinct": len({s.lower() for s in spans})}
    for name, ref in (("no_anchor", None), ("illustrative_anchor", ILLUSTRATIVE_ANCHOR)):
        c = Counter(normalize_temporal(s, reference_ts=ref).status for s in spans)
        out[name] = {k: {"n": v, "pct": round(100 * v / len(spans), 1)} for k, v in c.most_common()}
    bad = Counter(s.lower() for s in spans if normalize_temporal(s, reference_ts=ILLUSTRATIVE_ANCHOR).status == "UNPARSEABLE")
    out["unparseable_distinct"] = len(bad)
    out["unparseable_top"] = bad.most_common(40)
    needs = sum(normalize_temporal(s).status in ("UNRESOLVED_NO_ANCHOR", "PARTIAL") for s in spans)
    out["share_needing_anchor_or_year_pct"] = round(100 * needs / len(spans), 1)
    return out


def candidate_stats(records, predictor, anchor, cfg):
    stats = {"tasks": 0, "assignee": Counter(), "assignee_basis": Counter(), "flags": Counter(), "review_required": 0,
             "due": Counter(), "scheduled": Counter(), "has_due": 0, "has_scheduled": 0, "reinterpreted": 0,
             "disagreement": 0, "with_any_flag": 0}
    for rec in records:
        ents = [e for e in rec["text2task_annotations"]["entities"] if e["type"] in SCOPE_TYPES]
        registry, sender, recips = registry_from_mailex_record(rec)
        env = MessageEnvelope(rec["id"], rec["text"], sender, recips, anchor, None)
        neural = predictor.predict(rec["text"], ents)["relations"]
        rules = predict_rules(rec["text"], ents)["relations"]
        for c in build_task_candidates(env, ents, neural, registry, primary_source="neural", comparator_relations=rules, config=cfg):
            stats["tasks"] += 1
            stats["assignee"][c.assignee.status] += 1
            stats["assignee_basis"][c.assignee.basis] += 1
            for f in c.flags:
                stats["flags"][f.code] += 1
            stats["review_required"] += c.review_required
            stats["with_any_flag"] += bool(c.flags)
            if c.due:
                stats["has_due"] += 1; stats["due"][c.due.status] += 1
            if c.scheduled:
                stats["has_scheduled"] += 1; stats["scheduled"][c.scheduled.status] += 1
            stats["reinterpreted"] += bool(c.provenance["label_reinterpretations"])
            stats["disagreement"] += any(f.code == "MODEL_DISAGREEMENT" for f in c.flags)
    n = max(stats["tasks"], 1)
    stats["review_rate_pct"] = round(100 * stats["review_required"] / n, 1)
    stats["disagreement_rate_pct"] = round(100 * stats["disagreement"] / n, 1)
    for k in ("assignee", "assignee_basis", "flags", "due", "scheduled"):
        stats[k] = dict(stats[k].most_common())
    return stats


def selective_table(rows, predictor, thresholds, boots=300, seed=0):
    items = encode_rows(rows, predictor.tokenizer)
    probs = predict_probs(predictor.model, items, predictor.tokenizer.pad_token_id, predictor.device)
    recs = []
    for r, p in zip(rows, probs):
        k = max(range(len(LABELS)), key=lambda i: p[i])
        recs.append((r["thread_id"], r["label"], LABELS[k], p[k]))
    total_gold_pos = sum(1 for _, g, _, _ in recs if g != "NONE")
    pred_pos = [x for x in recs if x[2] != "NONE"]
    by_thread = defaultdict(list)
    for x in recs:
        by_thread[x[0]].append(x)
    rng = random.Random(seed)

    def metrics(sub, t, gold_pos):
        kept = [x for x in sub if x[2] != "NONE" and x[3] >= t]
        tp = sum(1 for x in kept if x[1] == x[2])
        return (tp / len(kept) if kept else None, tp / gold_pos if gold_pos else 0.0, len(kept))

    table = []
    keys = sorted(by_thread)
    for t in thresholds:
        prec, rec, n = metrics(recs, t, total_gold_pos)
        ps, rs = [], []
        for _ in range(boots):
            sub = [x for k in (rng.choice(keys) for _ in keys) for x in by_thread[k]]
            gp = sum(1 for x in sub if x[1] != "NONE")
            p_, r_, _ = metrics(sub, t, gp)
            if p_ is not None:
                ps.append(p_)
            rs.append(r_)
        ci = lambda v: [sorted(v)[int(.025 * len(v))], sorted(v)[max(int(.975 * len(v)) - 1, 0)]] if v else None
        table.append({"min_score": t, "predicted_links_kept": n, "share_of_predicted_links_kept": round(n / len(pred_pos), 3),
                      "precision": prec, "precision_ci95": ci(ps), "recall": rec, "recall_ci95": ci(rs)})
    return {"n_pairs": len(recs), "gold_positives": total_gold_pos, "predicted_positives": len(pred_pos), "table": table}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, default=ROOT / "models/text2task-relations/ACTIVE")
    ap.add_argument("--out", type=Path, default=ROOT / "results/phase4")
    a = ap.parse_args()
    cfg = load_config()
    predictor = RelationPredictor(a.model)
    val_rows = read_jsonl(ROOT / "data/model_ready/relations_v2_three_class/validation.jsonl")
    keep = {r["source_record_id"] for r in val_rows}
    val_records = [r for r in read_jsonl(ROOT / "data/final/validation.jsonl") if r["id"] in keep]
    report = {"provenance": "SILVER/MailEx-derived, provisional; functional checks, not human-grounded accuracy",
              "split_used": "train+validation (test never read)", "relation_model": predictor.version,
              "fixtures": fixtures_pass_rate(), "corpus_temporal_coverage": corpus_coverage(),
              "candidates_no_anchor": candidate_stats(val_records, predictor, None, cfg),
              "candidates_illustrative_anchor": candidate_stats(val_records, predictor, ILLUSTRATIVE_ANCHOR, cfg),
              "selective_prediction_validation": selective_table(val_rows, predictor, [0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99])}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: report[k] for k in ("fixtures",)}, indent=1))
    print("coverage no-anchor:", {k: v["pct"] for k, v in report["corpus_temporal_coverage"]["no_anchor"].items()})
    print("coverage illustrative:", {k: v["pct"] for k, v in report["corpus_temporal_coverage"]["illustrative_anchor"].items()})
    for k in ("candidates_no_anchor", "candidates_illustrative_anchor"):
        s = report[k]; print(k, "tasks", s["tasks"], "review%", s["review_rate_pct"], "assignee", s["assignee"], "flags", s["flags"])
    for row in report["selective_prediction_validation"]["table"]:
        print(row)


if __name__ == "__main__":
    main()
