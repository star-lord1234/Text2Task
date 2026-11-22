"""Check that key numbers quoted in the report equal the values in the saved results (via report/data/stats.json).

Each check recomputes a value from the source data, formats it the way the report prints it, and asserts that the
formatted string occurs in the named chapter. Run from the repository root:  python report/scripts/verify_numbers.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
S = json.loads((ROOT / "report/data/stats.json").read_text())
CH = {p.stem: p.read_text() for p in (ROOT / "report/chapters").glob("*.tex")}
ALL = "\n".join(CH.values())

f3 = lambda x: f"{x:.3f}"
f2 = lambda x: f"{x:.2f}"
num = lambda x: f"{x:,}"
d = S["phase2_dedup_rescore"]
rel = S["relation_eval"]["mode_A_reference_spans"]
b = S["phase0_baseline"]
v2 = lambda run: b[f"results/entity_extraction/entity_v2_three_class/{run}/validation_predictions.jsonl"]
u = S["mailex_unified"]
p75 = S["phase7_5_summary"]
sil = S["phase7_5_silver"]["results"]
bio = S["bio_token_distribution_mailex_train"]

checks = [
    # dataset
    ("emails train", num(u["train"]["emails"]), "04_dataset"),
    ("emails dev", str(u["dev"]["emails"]), "04_dataset"),
    ("emails test", str(u["test"]["emails"]), "04_dataset"),
    ("threads train", num(u["train"]["threads"]), "04_dataset"),
    ("no-event train", str(u["train"]["event_type_email_counts"]["O"]), "04_dataset"),
    ("empty train", str(u["train"]["empty_text_emails"]), "04_dataset"),
    ("Request_Action train", str(u["train"]["event_type_email_counts"]["Request_Action"]), "04_dataset"),
    ("BIO total tokens", num(sum(bio.values())), "04_dataset"),
    ("O share", f"{100 * bio['O'] / sum(bio.values()):.1f}\\%", "04_dataset"),
    ("TASK span tokens", num(bio["B-TASK"] + bio["I-TASK"]), "04_dataset"),
    ("MailEx-derived TASK train", num(S["mailex_derived_entities"]["train"]["entity_counts"]["TASK"]), "05_preprocessing"),
    ("MailEx-derived PERSON dev", str(S["mailex_derived_entities"]["validation"]["entity_counts"]["PERSON"]), "05_preprocessing"),
    ("requests-only TASK train", num(S["mailex_derived_requests_only"]["train"]["entity_counts"]["TASK"]), "05_preprocessing"),
    ("PERSON rejected", num(S["mailex_derived_entities"]["train"]["mapping_stats"]["PERSON_rejected_not_a_name"]), "05_preprocessing"),
    ("commitments rejected", num(S["mailex_derived_entities"]["train"]["mapping_stats"]["commitment_candidates_rejected"]), "05_preprocessing"),
    ("relation DUE_ON train", str(S["relation_dataset"]["train"]["label_counts"]["DUE_ON"]), "04_dataset"),
    ("relation NONE sampled", num(S["relation_dataset"]["train"]["label_counts"]["NONE"]), "04_dataset"),
    # entity results
    ("run1 clean lenient", f3(d["run1 lr5e-5"]["clean"]["lenient"]["f1"]), "14_results"),
    ("run1 clean strict", f3(d["run1 lr5e-5"]["clean"]["strict"]["f1"]), "14_results"),
    ("run1 TASK lenient", f3(d["run1 lr5e-5"]["clean_per_type"]["TASK"]["lenient"]["f1"]), "14_results"),
    ("run2 clean lenient", f3(d["run2 lr3e-5"]["clean"]["lenient"]["f1"]), "14_results"),
    ("run3 clean strict", f3(d["run3 requests-only"]["clean"]["strict"]["f1"]), "14_results"),
    ("rule clean lenient", f3(d["rule baseline"]["clean"]["lenient"]["f1"]), "14_results"),
    ("run1 full lenient", f3(d["run1 lr5e-5"]["full"]["lenient"]["f1"]), "14_results"),
    ("run1 clean lenient precision", f3(d["run1 lr5e-5"]["clean"]["lenient"]["precision"]), "14_results"),
    ("run1 clean lenient recall", f3(d["run1 lr5e-5"]["clean"]["lenient"]["recall"]), "14_results"),
    ("v2 sqrt strict", f3(v2("epoch3_sqrt_weighted")["overall"]["strict"]["f1"]), "14_results"),
    ("v2 sqrt lenient", f3(v2("epoch3_sqrt_weighted")["overall"]["lenient"]["f1"]), "14_results"),
    ("v2 ep6 lenient", f3(v2("epoch6")["overall"]["lenient"]["f1"]), "14_results"),
    # relation results
    ("relation micro", f3(rel["neural"]["micro_positive"]["f1"]), "14_results"),
    ("relation macro", f3(rel["neural"]["macro_positive_f1"]), "14_results"),
    ("rule micro", f3(rel["rule"]["micro_positive"]["f1"]), "14_results"),
    ("ASSIGNED_TO F1", f2(rel["neural"]["ASSIGNED_TO"]["f1"]), "14_results"),
    ("SCHEDULED_ON F1", f2(rel["neural"]["SCHEDULED_ON"]["f1"]), "14_results"),
    ("NONE FPR", f"{100 * rel['neural']['NONE']['false_positive_rate']:.1f}\\%", "14_results"),
    ("NONE->ASSIGNED_TO", str(rel["neural"]["confusion"]["NONE->ASSIGNED_TO"]), "14_results"),
    ("relation best macro (training)", f"{S['curves']['relation_markers_sqrt']['history'][2]['macro_positive_f1']:.2f}", "08_models"),
    # live system
    ("hybrid holdout strict", f"{p75['live_scenarios_holdout']['hybrid']['ALL']['passed_strict']}/30", "14_results"),
    ("neural holdout strict", f"{p75['live_scenarios_holdout']['neural_only']['ALL']['passed_strict']}/30", "14_results"),
    ("rule holdout strict", f"{p75['live_scenarios_holdout']['rule_only']['ALL']['passed_strict']}/30", "14_results"),
    ("hybrid new strict", f"{p75['live_scenarios_new']['hybrid']['ALL']['passed_strict']} of 34", "14_results"),
    ("neural false tasks dev", str(p75["live_battery_v1"]["neural_only"]["ALL"]["spurious_tasks"]), "14_results"),
    ("hybrid email lenient", f3(sil["hybrid"]["scores"]["ALL"]["f1"]), "14_results"),
    ("neural email lenient", f3(sil["neural_only"]["scores"]["ALL"]["f1"]), "14_results"),
    ("hybrid email TASK F1", f3(sil["hybrid"]["scores"]["TASK"]["f1"]), "14_results"),
    # temporal
    ("temporal spans", str(S["phase4"]["corpus_temporal_coverage"]["n_spans"]), "10_rules"),
    ("resolved no anchor", f"{S['phase4']['corpus_temporal_coverage']['no_anchor']['RESOLVED']['pct']}\\%", "10_rules"),
]

failed = 0
for name, value, chapter in checks:
    ok = value in CH[chapter]
    failed += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {name:32s} {value:>10s}  ({chapter})")
print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
sys.exit(1 if failed else 0)
