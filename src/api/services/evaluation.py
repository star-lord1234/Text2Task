"""Evaluation dashboard data: reads the SAVED experiment files under results/ and reshapes them. It computes and invents nothing;
a file that is missing is reported as missing, and limitations are the text of the reports' own Limitations sections."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

PROVENANCE = "SILVER (MailEx-derived) - provisional agreement with silver labels, not human-verified accuracy"


def _load(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _limitations(md: Path) -> list[str]:
    try:
        text = md.read_text()
    except OSError:
        return []
    m = re.search(r"^## Limitations[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not m:
        return []
    items: list[str] = []
    for line in m.group(1).splitlines():
        if line.startswith("- "):
            items.append(line[2:].strip())
        elif line.startswith("  ") and items and line.strip():
            items[-1] += " " + line.strip()
    return items


def _prf(d: Optional[dict]) -> Optional[dict]:
    if not d:
        return None
    out = {k: d[k] for k in ("precision", "recall", "f1", "support") if k in d}
    if "f1" not in out and "f1-score" in d:                        # seqeval's classification report spells it f1-score
        out["f1"] = d["f1-score"]
    return out


def build_evaluation(results_dir: Path) -> dict[str, Any]:
    r = Path(results_dir)
    out: dict[str, Any] = {"provenance": PROVENANCE, "sources": [], "missing": []}

    def src(p: Path) -> Path:
        out["sources"].append(str(p.relative_to(r.parent)) if r.parent in p.parents else str(p))
        return p

    # --- entity extraction
    ent: dict[str, Any] = {"available": False}
    m = _load(src(r / "entity_extraction/entity_v2_three_class/epoch3_sqrt_weighted/metrics.json"))
    if m:
        per = m.get("silver_v2_provisional_per_entity", {})
        ent = {"available": True, "model": "DistilBERT three-class (entity-v2.0.0, epoch 3, sqrt class weights)",
               "metric": "entity-level seqeval P/R/F1 on SILVER-v2 validation (provisional)",
               "overall": _prf(m.get("silver_v2_provisional_overall")),
               "per_type": {k: _prf(per.get(k)) for k in ("PERSON", "TASK", "TEMPORAL") if k in per},
               "v1_comparison": m.get("v1_baseline"), "trained_epochs": m.get("epochs"), "device": m.get("device"),
               "human_verified": (m.get("evaluation_provenance") or {}).get("human_verified")}
    b = _load(src(r / "entity_extraction/baseline/rule_based_E1_validation.json"))
    if b:
        ent["rule_baseline"] = {"name": b.get("baseline"), "split": b.get("split"), "rows": b.get("rows"),
                                "lenient_f1": b["overall"]["lenient"]["f1"], "strict_f1": b["overall"]["strict"]["f1"],
                                "per_type_lenient_f1": {k: v["lenient"]["f1"] for k, v in b["per_type"].items()}}
    p2 = _load(src(r / "entity_extraction/phase2/dedup_rescore.json"))
    if p2:
        ent["mailex_runs"] = [{"run": name, "lenient_f1": v["full"]["lenient"]["f1"], "strict_f1": v["full"]["strict"]["f1"],
                               "overlap_f1": v["full"]["overlap_any"]["f1"]} for name, v in p2.items() if isinstance(v, dict) and "full" in v]
    ent["note"] = ("These runs use different label sets and tagging schemes (three-class v2 vs earlier MailEx runs), so the numbers "
                   "are listed side by side but are not directly comparable.")
    out["entities"] = ent
    if not ent["available"]:
        out["missing"].append("entity_extraction metrics")

    # --- relations
    rel: dict[str, Any] = {"available": False}
    rv = _load(src(r / "relation_extraction/evaluation/validation_markers_sqrt.json"))
    if rv:
        a = rv["mode_A_reference_spans"]
        lab = lambda s: {k: _prf(a[s].get(k)) for k in ("ASSIGNED_TO", "DUE_ON", "SCHEDULED_ON")}
        bb = rv["mode_B_predicted_spans"]
        rel = {"available": True, "model": rv.get("model_version"), "split": rv.get("split"), "pairs": a.get("n_rows"),
               "mode_a": {"neural": {"per_label": lab("neural"), "micro_f1": a["neural"]["micro_positive"]["f1"], "macro_f1": a["neural"]["macro_positive_f1"],
                                     "none_false_positive_rate": a["neural"]["NONE"]["false_positive_rate"]},
                          "rule": {"per_label": lab("rule"), "micro_f1": a["rule"]["micro_positive"]["f1"], "macro_f1": a["rule"]["macro_positive_f1"]},
                          "bootstrap_95ci": a.get("bootstrap_thread_95ci")},
               "mode_b": {k: {"micro_f1": bb[k]["micro"]["f1"] if isinstance(bb[k].get("micro"), dict) else None,
                              "candidate_recall": bb[k].get("candidate_recall_both_endpoints_detected")}
                          for k in ("neural_strict", "neural_lenient", "neural_overlap", "rule_strict", "rule_lenient", "rule_overlap") if k in bb},
               "limitations": _limitations(src(r / "relation_extraction/RESULTS.md"))}
    else:
        out["missing"].append("relation_extraction evaluation")
    out["relations"] = rel

    # --- downstream rule-based phases
    phases = []
    for key, title in (("phase4", "Temporal and owner resolution"), ("phase5", "Task reconciliation"), ("phase6", "Dependency graph")):
        rep = _load(src(r / key / "report.json"))
        if rep is None:
            out["missing"].append(f"{key} report")
            phases.append({"id": key, "title": title, "available": False})
            continue
        phases.append({"id": key, "title": title, "available": True, "provenance": rep.get("provenance"),
                       "sections": {k: v for k, v in rep.items() if isinstance(v, dict) and k != "provenance"},
                       "limitations": _limitations(r / key / "REPORT.md")})
    out["phases"] = phases
    out["statement"] = ("Every number is agreement with provisional SILVER labels or the outcome of developer-authored functional checks. "
                        "No human-verified GOLD evaluation exists, so none of these are final research results.")
    return out
