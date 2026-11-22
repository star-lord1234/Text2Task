#!/usr/bin/env python3
"""Phase 3 Step 5: evaluate neural vs rule relation linking (provisional SILVER).

Mode A: reference (annotated) entity spans, FULL validation candidate set (no negative sampling).
Mode B: entity spans predicted by the three-class entity checkpoint; relations scored against gold relations.
Test split is refused unless --allow-test is passed.
"""
from __future__ import annotations

import argparse, importlib.util, json, random, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import torch  # noqa: E402

from src.baselines.rule_relations import predict_rules  # noqa: E402
from src.model_data.token_classification import read_jsonl  # noqa: E402
from src.model_training.relation_classifier import LABELS, RelationPredictor, encode_rows, predict_probs, prf  # noqa: E402

SCOPE = {("TASK", "PERSON"), ("TASK", "TEMPORAL")}


def iou(a, b):
    inter = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    union = max(a["end"], b["end"]) - min(a["start"], b["start"])
    return inter / union if union else 0.0


def boot(per_thread, labels_fn, n=1000, seed=0):
    """Thread-level bootstrap of (micro, macro) F1; per_thread: {thread: [(gold,pred)...]}."""
    rng = random.Random(seed)
    keys = sorted(per_thread)
    out = []
    for _ in range(n):
        g, p = [], []
        for k in (rng.choice(keys) for _ in keys):
            for a, b in per_thread[k]:
                g.append(a); p.append(b)
        m = prf(g, p)
        out.append((m["micro_positive"]["f1"], m["macro_positive_f1"]))
    return out


def ci(xs):
    xs = sorted(xs)
    return [xs[int(0.025 * len(xs))], xs[int(0.975 * len(xs)) - 1]]


def mode_a(rows, predictor):
    items = encode_rows(rows, predictor.tokenizer)
    probs = predict_probs(predictor.model, items, predictor.tokenizer.pad_token_id, predictor.device)
    neural = [LABELS[max(range(len(LABELS)), key=lambda k: p[k])] for p in probs]
    by_rec = defaultdict(dict)
    for r in rows:
        for e in (r["source_entity"], r["target_entity"]):
            by_rec[r["source_record_id"]][e["id"]] = e
    rule_map, unresolved = {}, 0
    for rec, ents in by_rec.items():
        text = next(r["text"] for r in rows if r["source_record_id"] == rec)
        res = predict_rules(text, list(ents.values()))
        unresolved += len(res["unresolved"])
        for rel in res["relations"]:
            if rel["label"] != "DEPENDS_ON":
                rule_map[(rec, rel["source_id"], rel["target_id"])] = rel["label"]
    rule = [rule_map.get((r["source_record_id"], r["source_entity"]["id"], r["target_entity"]["id"]), "NONE") for r in rows]
    gold = [r["label"] for r in rows]
    thread = [r["thread_id"] for r in rows]
    res = {"n_rows": len(rows), "neural": prf(gold, neural), "rule": prf(gold, rule), "rule_unresolved_assignments": unresolved}
    pt_n, pt_r = defaultdict(list), defaultdict(list)
    for t, g, n, r in zip(thread, gold, neural, rule):
        pt_n[t].append((g, n)); pt_r[t].append((g, r))
    bn, br = boot(pt_n, None), boot(pt_r, None)
    res["bootstrap_thread_95ci"] = {
        "neural_micro": ci([x[0] for x in bn]), "neural_macro": ci([x[1] for x in bn]),
        "rule_micro": ci([x[0] for x in br]), "rule_macro": ci([x[1] for x in br]),
        "delta_micro_neural_minus_rule": ci([a[0] - b[0] for a, b in zip(bn, br)]),
        "delta_macro_neural_minus_rule": ci([a[1] - b[1] for a, b in zip(bn, br)])}
    errors = [{"id": r["id"], "gold": g, "neural": n, "rule": u, "source": r["source_entity"]["text"],
               "target": r["target_entity"]["text"], "target_type": r["target_entity"]["type"], "ambiguous": r.get("ambiguous"),
               "context": r["text"][max(0, min(r["source_entity"]["start"], r["target_entity"]["start"]) - 80):
                                    max(r["source_entity"]["end"], r["target_entity"]["end"]) + 60]}
              for r, g, n, u in zip(rows, gold, neural, rule) if g != n or g != u]
    return res, errors


from src.model_training.entity_inference import predict_entities  # noqa: E402  (moved into the library)


def match(pred, gold, mode):
    if pred["type"] != gold["type"]:
        return False
    if mode == "strict":
        return (pred["start"], pred["end"]) == (gold["start"], gold["end"])
    if mode == "overlap":
        return min(pred["end"], gold["end"]) > max(pred["start"], gold["start"])
    return iou(pred, gold) >= 0.5


def mode_b(records, predictor, entity_model, device):
    ents_pred = predict_entities([r["text"] for r in records], entity_model, device)
    out = {}
    for system in ("neural", "rule"):
        for strict in ("strict", "lenient", "overlap"):
            tp = fp = fn = covered = total = 0
            per = defaultdict(lambda: [0, 0, 0])
            for rec, pents in zip(records, ents_pred):
                gents = {e["id"]: e for e in rec["text2task_annotations"]["entities"]}
                gold = []
                for rel in rec["text2task_annotations"]["relations"]:
                    s, t = gents.get(rel["source_entity_id"]), gents.get(rel["target_entity_id"])
                    if s and t and (s["type"], t["type"]) in SCOPE and rel["type"] in LABELS:
                        gold.append((s, t, rel["type"]))
                if system == "neural":
                    preds = predictor.predict(rec["text"], pents)["relations"]
                else:
                    preds = predict_rules(rec["text"], pents)["relations"]
                    preds = [p for p in preds if p["label"] != "DEPENDS_ON"]
                pmap = {e["id"]: e for e in pents}
                matched_gold = set()
                for p in preds:
                    ps, pt = pmap[p["source_id"]], pmap[p["target_id"]]
                    hit = next((i for i, (gs, gt, gl) in enumerate(gold) if gl == p["label"] and match(ps, gs, strict) and match(pt, gt, strict)), None)
                    if hit is not None and hit not in matched_gold:
                        matched_gold.add(hit); tp += 1; per[p["label"]][0] += 1
                    else:
                        fp += 1; per[p["label"]][1] += 1
                fn += len(gold) - len(matched_gold)
                for i, (gs, gt, gl) in enumerate(gold):
                    if i not in matched_gold:
                        per[gl][2] += 1
                    total += 1
                    covered += any(match(e, gs, strict) for e in pents) and any(match(e, gt, strict) for e in pents)
            def f(t, p_, n):
                P = t / (t + p_) if t + p_ else 0.0; R = t / (t + n) if t + n else 0.0
                return {"precision": P, "recall": R, "f1": 2 * P * R / (P + R) if P + R else 0.0, "tp": t, "fp": p_, "fn": n}
            out[f"{system}_{strict}"] = {
                "micro": f(tp, fp, fn), "per_label": {l: f(*per[l]) for l in LABELS[1:]},
                "gold_relations": total, "candidate_recall_both_endpoints_detected": covered / total if total else 0.0}
    out["entity_model"] = str(entity_model)
    out["n_predicted_entities"] = sum(len(e) for e in ents_pred)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--split", default="validation", choices=["validation", "test"])
    ap.add_argument("--allow-test", action="store_true")
    ap.add_argument("--entity-model", type=Path, default=ROOT / "models/text2task-distilbert/entity_v2_three_class/epoch3_sqrt_weighted")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data/model_ready/relations_v2_three_class")
    ap.add_argument("--out", type=Path, default=ROOT / "results/relation_extraction/evaluation")
    ap.add_argument("--skip-mode-b", action="store_true")
    ap.add_argument("--min-score", type=float)
    a = ap.parse_args()
    if a.split == "test" and not a.allow_test:
        raise SystemExit("Refusing to read the test split without --allow-test (final-evaluation gate).")
    predictor = RelationPredictor(a.model, threshold=a.min_score)
    rows = read_jsonl(a.data_dir / f"{a.split}.jsonl")
    res_a, errors = mode_a(rows, predictor)
    report = {"provenance": "SILVER (MailEx-derived) - provisional, not human-grounded", "split": a.split,
              "model": str(a.model), "model_version": predictor.version, "mode_A_reference_spans": res_a}
    if not a.skip_mode_b:
        final = read_jsonl(ROOT / "data/final" / f"{a.split}.jsonl")
        keep = {r["source_record_id"] for r in rows}
        report["mode_B_predicted_spans"] = mode_b([r for r in final if r["id"] in keep], predictor, a.entity_model, predictor.device)
    a.out.mkdir(parents=True, exist_ok=True)
    tag = a.model.name
    (a.out / f"{a.split}_{tag}.json").write_text(json.dumps(report, indent=2))
    (a.out / f"{a.split}_{tag}_errors.jsonl").write_text("\n".join(json.dumps(e) for e in errors))
    n, r = res_a["neural"], res_a["rule"]
    print(f"Mode A n={res_a['n_rows']}  neural micro={n['micro_positive']['f1']:.3f} macro={n['macro_positive_f1']:.3f} | rule micro={r['micro_positive']['f1']:.3f} macro={r['macro_positive_f1']:.3f}")
    for l in LABELS[1:]:
        print(f"  {l:13s} neural P/R/F={n[l]['precision']:.2f}/{n[l]['recall']:.2f}/{n[l]['f1']:.2f} rule P/R/F={r[l]['precision']:.2f}/{r[l]['recall']:.2f}/{r[l]['f1']:.2f} support={n[l]['support']}")
    if "mode_B_predicted_spans" in report:
        for k, v in report["mode_B_predicted_spans"].items():
            if isinstance(v, dict):
                print(f"  ModeB {k}: micro F1={v['micro']['f1']:.3f} P={v['micro']['precision']:.3f} R={v['micro']['recall']:.3f} cand_recall={v['candidate_recall_both_endpoints_detected']:.3f}")


if __name__ == "__main__":
    main()
