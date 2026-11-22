"""Draw every statistical chart of the report from report/data/stats.json (vector PDF).

No value is invented, smoothed or interpolated: each series is plotted exactly as saved by the training/evaluation code.
Run:  python report/scripts/make_charts.py   (needs matplotlib)
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
S = json.loads((ROOT / "report/data/stats.json").read_text())
OUT = ROOT / "report/figures/charts"
OUT.mkdir(parents=True, exist_ok=True)

NAVY, TEAL, GREY, OCHRE, RED, LIGHT = "#1F3A5F", "#2A7F7F", "#8C8C8C", "#B07D2B", "#A23B3B", "#C9D6E3"
PAL = [NAVY, TEAL, OCHRE, GREY, RED]
plt.rcParams.update({
    "font.family": "serif", "font.serif": ["TeX Gyre Pagella", "Palatino", "DejaVu Serif"], "font.size": 9,
    "axes.titlesize": 9.5, "axes.labelsize": 9, "legend.fontsize": 8, "xtick.labelsize": 8, "ytick.labelsize": 8,
    "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#444444", "axes.linewidth": 0.7,
    "axes.grid": True, "grid.color": "#E3E3E3", "grid.linewidth": 0.6, "axes.axisbelow": True,
    "pdf.fonttype": 42, "savefig.bbox": "tight", "savefig.pad_inches": 0.03, "legend.frameon": False,
})


def save(fig, name):
    fig.savefig(OUT / f"{name}.pdf")
    plt.close(fig)
    print("chart", name)


def bar_labels(ax, bars, fmt="{:.0f}", dy=0.0, size=7):
    for b in bars:
        h = b.get_height()
        ax.text(b.get_x() + b.get_width() / 2, h + dy, fmt.format(h), ha="center", va="bottom", fontsize=size, color="#333333")


# 1. MailEx event types ------------------------------------------------------------------------------------------
def mailex_events():
    u = S["mailex_unified"]
    types = sorted({t for s in u.values() for t in s["event_type_email_counts"]}, key=lambda t: -u["train"]["event_type_email_counts"].get(t, 0))
    label = {"O": "No event (O)"}
    fig, ax = plt.subplots(figsize=(6.3, 3.0))
    y = np.arange(len(types))
    h = 0.27
    for i, (split, col) in enumerate((("train", NAVY), ("dev", TEAL), ("test", OCHRE))):
        vals = [u[split]["event_type_email_counts"].get(t, 0) for t in types]
        ax.barh(y + (i - 1) * h, vals, h, color=col, label=f"{split} ({u[split]['emails']:,} emails)")
    ax.set_yticks(y, [label.get(t, t.replace("_", " ")) for t in types])
    ax.invert_yaxis()
    ax.set_xlabel("emails containing at least one event of the type")
    ax.legend(loc="lower right")
    ax.grid(axis="y", visible=False)
    save(fig, "mailex_event_types")


# 2. Entity distributions across label sets ---------------------------------------------------------------------
def entity_distribution():
    sets = [
        ("SILVER-v1 (6 classes, train)", S["silver_final_six_class"]["train"]["entities"]),
        ("SILVER-v2 (train)", S["silver_v2_entities"]["train"]["entity_counts"]),
        ("MailEx-derived (train)", S["mailex_derived_entities"]["train"]["entity_counts"]),
        ("MailEx-derived (dev)", S["mailex_derived_entities"]["validation"]["entity_counts"]),
    ]
    types = ["TASK", "PERSON", "TEMPORAL", "ARTIFACT", "GROUP", "EVENT"]
    fig, ax = plt.subplots(figsize=(6.3, 2.7))
    x = np.arange(len(types))
    w = 0.2
    for i, (name, c) in enumerate(sets):
        bars = ax.bar(x + (i - 1.5) * w, [c.get(t, 0) for t in types], w, color=PAL[i], label=name)
        bar_labels(ax, bars, dy=15, size=6)
    ax.set_xticks(x, types)
    ax.set_ylabel("entity spans")
    ax.legend(ncol=2, loc="upper right")
    save(fig, "entity_distribution")


# 3. BIO token imbalance -----------------------------------------------------------------------------------------
def bio_imbalance():
    c = S["bio_token_distribution_mailex_train"]
    order = ["O", "I-TASK", "I-TEMPORAL", "B-TASK", "B-PERSON", "B-TEMPORAL", "I-PERSON"]
    fig, ax = plt.subplots(figsize=(4.4, 2.6))
    vals = [c[k] for k in order]
    bars = ax.bar(order, vals, color=[GREY] + [NAVY if "TASK" in k else TEAL if "TEMP" in k else OCHRE for k in order[1:]])
    ax.set_yscale("log")
    ax.set_ylabel("WordPiece tokens (log scale)")
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v * 1.15, f"{v:,}", ha="center", fontsize=6.5)
    ax.tick_params(axis="x", rotation=30)
    ax.set_ylim(top=max(vals) * 4)
    ax.grid(axis="x", visible=False)
    save(fig, "bio_imbalance")


# 4. Relation label distribution ----------------------------------------------------------------------------------
def relation_distribution():
    r = S["relation_dataset"]
    labels = ["NONE", "ASSIGNED_TO", "SCHEDULED_ON", "DUE_ON"]
    fig, ax = plt.subplots(figsize=(6.3, 2.5))
    x = np.arange(len(labels))
    w = 0.26
    for i, (split, col) in enumerate((("train", NAVY), ("validation", TEAL), ("test", OCHRE))):
        vals = [r[split]["full_candidate_label_counts"][l] for l in labels]
        bars = ax.bar(x + (i - 1) * w, vals, w, color=col, label=split)
        bar_labels(ax, bars, dy=0, size=6)
    ax.set_yscale("log")
    ax.set_ylim(top=2e4)
    ax.set_xticks(x, labels)
    ax.set_ylabel("candidate pairs (log scale)")
    ax.legend(loc="upper right", ncol=3)
    ax.grid(axis="x", visible=False)
    save(fig, "relation_distribution")


# 5. Phase 2 curves (run 1) ----------------------------------------------------------------------------------------
def phase2_curves():
    c = S["curves"]["phase2_lr5e-5"]
    ep = [e["epoch"] for e in c["eval"]]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.3, 2.6))
    a1.plot([t["epoch"] for t in c["train"]], [t["loss"] for t in c["train"]], "-o", ms=3, color=NAVY, label="training loss (epoch mean)")
    a1.plot(ep, [e["eval_loss"] for e in c["eval"]], "-s", ms=3, color=OCHRE, label="validation loss")
    a1.set_yscale("log"); a1.set_xlabel("epoch"); a1.set_ylabel("cross-entropy (log)"); a1.set_title("(a) loss"); a1.legend()
    for key, lab, col, st in (("eval_lenient_f1", "overall lenient", NAVY, "-"), ("eval_strict_f1", "overall strict", NAVY, "--"),
                              ("eval_task_lenient_f1", "TASK lenient", OCHRE, "-"), ("eval_person_lenient_f1", "PERSON lenient", TEAL, "-"),
                              ("eval_temporal_lenient_f1", "TEMPORAL lenient", GREY, "-")):
        a2.plot(ep, [e[key] for e in c["eval"]], st, marker="o", ms=2.5, color=col, label=lab, lw=1.2)
    best = max(c["eval"], key=lambda e: e["eval_lenient_f1"])
    a2.axvline(best["epoch"], color="#999999", lw=0.8, ls=":")
    a2.text(best["epoch"] - 0.1, 0.71, f"selected epoch {int(best['epoch'])}", fontsize=7, color="#555555", ha="right")
    a2.set_xlabel("epoch"); a2.set_ylabel("F1 (dev, before deduplication)"); a2.set_title("(b) validation F1"); a2.set_ylim(0, 0.75)
    a2.legend(fontsize=6.5, loc="lower right")
    fig.tight_layout()
    save(fig, "phase2_training_curves")


# 6. Learning-rate / label-set comparison ------------------------------------------------------------------------
def phase2_runs():
    fig, ax = plt.subplots(figsize=(4.6, 2.6))
    for name, lab, col, st in (("phase2_lr5e-5", "Run 1: lr 5e-5, +commitments", NAVY, "-"), ("phase2_lr3e-5", "Run 2: lr 3e-5, +commitments", TEAL, "-"),
                               ("phase2_requests_only", "Run 3: lr 5e-5, requests only*", OCHRE, "--")):
        c = S["curves"][name]
        ax.plot([e["epoch"] for e in c["eval"]], [e["eval_lenient_f1"] for e in c["eval"]], st, marker="o", ms=2.5, color=col, label=lab)
    ax.set_xlabel("epoch"); ax.set_ylabel("overall lenient F1 (dev)"); ax.set_ylim(0.2, 0.62)
    ax.legend(loc="lower right", fontsize=7)
    ax.text(1, 0.215, "*scored on its own requests-only labels", fontsize=6.5, color="#555555")
    save(fig, "phase2_run_comparison")


# 7. Relation training ----------------------------------------------------------------------------------------------
def relation_training():
    h = S["curves"]["relation_markers_sqrt"]["history"]
    ep = [x["epoch"] for x in h]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.3, 2.5))
    a1.plot(ep, [x["train_loss"] for x in h], "-o", ms=3, color=NAVY)
    a1.set_xlabel("epoch"); a1.set_ylabel("training loss"); a1.set_title("(a) weighted cross-entropy"); a1.set_xticks(ep)
    a2.plot(ep, [x["macro_positive_f1"] for x in h], "-o", ms=3, color=NAVY, label="macro F1 (3 positive labels)")
    a2.plot(ep, [x["micro_positive_f1"] for x in h], "-s", ms=3, color=TEAL, label="micro F1 (positives)")
    a2.plot(ep, [x["none_fpr"] for x in h], "--^", ms=3, color=RED, label="false-link rate on NONE")
    a2.axvline(3, color="#999999", lw=0.8, ls=":"); a2.text(3.05, 0.9, "selected", fontsize=7, color="#555555")
    a2.set_xlabel("epoch"); a2.set_ylim(0, 1); a2.set_title("(b) validation"); a2.set_xticks(ep); a2.legend(fontsize=6.5, loc="center right")
    fig.tight_layout()
    save(fig, "relation_training")


# 8. Relation confusion matrices ----------------------------------------------------------------------------------
def relation_confusion():
    labels = ["NONE", "ASSIGNED_TO", "DUE_ON", "SCHEDULED_ON"]
    short = ["NONE", "ASSIGNED", "DUE_ON", "SCHED."]
    fig, axes = plt.subplots(1, 2, figsize=(6.3, 2.9))
    for ax, sysname, title in zip(axes, ("neural", "rule"), ("(a) neural, markers + sqrt weights", "(b) rule linker")):
        conf = S["relation_eval"]["mode_A_reference_spans"][sysname]["confusion"]
        m = np.array([[conf.get(f"{g}->{p}", 0) for p in labels] for g in labels], dtype=float)
        norm = m / m.sum(axis=1, keepdims=True)
        ax.imshow(norm, cmap="Blues", vmin=0, vmax=1)
        for i in range(4):
            for j in range(4):
                ax.text(j, i, f"{int(m[i, j])}", ha="center", va="center", fontsize=8, color="white" if norm[i, j] > 0.55 else "#222222")
        ax.set_xticks(range(4), short, rotation=25); ax.set_yticks(range(4), short)
        ax.set_xlabel("predicted"); ax.set_ylabel("reference (SILVER)"); ax.set_title(title); ax.grid(False)
    fig.tight_layout()
    save(fig, "relation_confusion")


# 9. Model iterations ---------------------------------------------------------------------------------------------
def model_iterations():
    b = S["phase0_baseline"]
    key = lambda run: f"results/entity_extraction/entity_v2_three_class/{run}/validation_predictions.jsonl"
    v1_six = 0.0077669902912621365   # models/text2task-distilbert/STATUS.json (six-class seqeval F1)
    left = [("SILVER-v1\n6-class", v1_six, None), ("v2 ep3\nunweighted", b[key("epoch3")]["overall"]["strict"]["f1"], b[key("epoch3")]["overall"]["lenient"]["f1"]),
            ("v2 ep6\nunweighted", b[key("epoch6")]["overall"]["strict"]["f1"], b[key("epoch6")]["overall"]["lenient"]["f1"]),
            ("v2 ep3\nsqrt-weighted", b[key("epoch3_sqrt_weighted")]["overall"]["strict"]["f1"], b[key("epoch3_sqrt_weighted")]["overall"]["lenient"]["f1"])]
    d = S["phase2_dedup_rescore"]
    right = [(lab, d[k]["clean"]["strict"]["f1"], d[k]["clean"]["lenient"]["f1"])
             for k, lab in (("rule baseline", "Rule\nbaseline"), ("run1 lr5e-5", "Run 1\nlr 5e-5"), ("run2 lr3e-5", "Run 2\nlr 3e-5"),
                            ("run3 requests-only", "Run 3\nreq. only*"))]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.3, 2.8), gridspec_kw={"width_ratios": [4, 4]})
    for ax, data, title in ((a1, left, "(a) SILVER lineage — SILVER-v1 dev (60 emails)"), (a2, right, "(b) MailEx-derived lineage — dedup. dev (349 emails)")):
        x = np.arange(len(data)); w = 0.38
        bs = ax.bar(x - w / 2, [d_[1] for d_ in data], w, color=NAVY, label="strict F1")
        bl = ax.bar(x + w / 2, [d_[2] if d_[2] is not None else 0 for d_ in data], w, color=TEAL, label="lenient F1 (IoU≥0.5)")
        bar_labels(ax, bs, "{:.3f}", dy=0.008, size=6); bar_labels(ax, [b_ for b_, d_ in zip(bl, data) if d_[2] is not None], "{:.3f}", dy=0.008, size=6)
        ax.set_xticks(x, [d_[0] for d_ in data], fontsize=7); ax.set_ylim(0, 0.65); ax.set_title(title, fontsize=8); ax.grid(axis="x", visible=False)
    a1.set_ylabel("overall entity F1"); a1.legend(loc="upper left")
    fig.tight_layout()
    save(fig, "model_iterations")


# 10. Phase 7.5 strict pass + behaviour ---------------------------------------------------------------------------
def phase75():
    s = S["phase7_5_summary"]
    sets = [("live_battery_v1", "development (24)"), ("live_scenarios_new", "new (34)"), ("live_scenarios_holdout", "holdout (30)")]
    cfgs = [("neural_only", "neural only"), ("refined", "refined"), ("hybrid", "hybrid"), ("rule_only", "rule only")]
    fig, ax = plt.subplots(figsize=(6.3, 2.5))
    x = np.arange(len(sets)); w = 0.2
    for i, (c, lab) in enumerate(cfgs):
        vals = [s[k][c]["ALL"]["passed_strict"] / s[k][c]["ALL"]["cases"] for k, _ in sets]
        bars = ax.bar(x + (i - 1.5) * w, vals, w, color=[GREY, OCHRE, NAVY, TEAL][i], label=lab)
        for b_, k in zip(bars, [k for k, _ in sets]):
            ax.text(b_.get_x() + b_.get_width() / 2, b_.get_height() + 0.015, f"{s[k][c]['ALL']['passed_strict']}", ha="center", fontsize=6.5)
    ax.set_xticks(x, [l for _, l in sets]); ax.set_ylabel("share of cases passed (strict)"); ax.set_ylim(0, 1.1)
    ax.legend(ncol=4, loc="lower center", bbox_to_anchor=(0.5, 1.0)); ax.grid(axis="x", visible=False)
    save(fig, "phase75_strict_pass")

    fig, axes = plt.subplots(1, 3, figsize=(6.3, 2.3))
    metrics = [("task_recall", "task recall", False), ("spurious_tasks", "false tasks", True), ("edge_recall", "edge recall", False)]
    for ax, (m, title, count) in zip(axes, metrics):
        for i, (c, lab) in enumerate((("neural_only", "neural only"), ("hybrid", "hybrid"))):
            vals = [s[k][c]["ALL"][m] or 0 for k, _ in sets]
            ax.bar(np.arange(3) + (i - 0.5) * 0.36, vals, 0.36, color=[GREY, NAVY][i], label=lab)
        ax.set_xticks(range(3), ["dev", "new", "holdout"]); ax.set_title(title); ax.grid(axis="x", visible=False)
        if not count:
            ax.set_ylim(0, 1.05)
    axes[0].legend(loc="lower center", bbox_to_anchor=(1.7, 1.12), ncol=2, fontsize=7)
    fig.tight_layout()
    save(fig, "phase75_behaviour")


# 11. Refinement on real emails ------------------------------------------------------------------------------------
def silver_refinement():
    r = S["phase7_5_silver"]["results"]
    types = ["TASK", "PERSON", "TEMPORAL", "ALL"]
    fig, ax = plt.subplots(figsize=(4.6, 2.5))
    x = np.arange(len(types)); w = 0.26
    for i, (c, lab) in enumerate((("neural_only", "neural only"), ("refined", "refined"), ("hybrid", "hybrid"))):
        bars = ax.bar(x + (i - 1) * w, [r[c]["scores"][t]["f1"] for t in types], w, color=[GREY, OCHRE, NAVY][i], label=lab)
        bar_labels(ax, bars, "{:.2f}", dy=0.006, size=6)
    ax.set_xticks(x, types); ax.set_ylabel("lenient F1 vs SILVER (60 emails)"); ax.set_ylim(0, 0.5); ax.legend(loc="upper left", ncol=3)
    ax.grid(axis="x", visible=False)
    save(fig, "silver_refinement")


# 12. Temporal resolution status (Phase 4) ------------------------------------------------------------------------
def temporal_status():
    t = S["phase4"]["corpus_temporal_coverage"]
    statuses = ["RESOLVED", "PARTIAL", "UNRESOLVED_NO_ANCHOR", "UNRESOLVED_EVENT_CONDITION", "AMBIGUOUS", "VAGUE", "UNPARSEABLE"]
    fig, ax = plt.subplots(figsize=(6.3, 2.5))
    y = np.arange(len(statuses)); h = 0.38
    for i, (k, lab, col) in enumerate((("no_anchor", "no message timestamp (corpus reality)", GREY), ("illustrative_anchor", "illustrative anchor 2001-11-15", NAVY))):
        ax.barh(y + (i - 0.5) * h, [t[k].get(s, {}).get("pct", 0) for s in statuses], h, color=col, label=lab)
    ax.set_yticks(y, [s.replace("_", " ").lower() for s in statuses]); ax.invert_yaxis()
    ax.set_xlabel(f"share of {t['n_spans']} TEMPORAL spans (%)"); ax.legend(loc="lower center", bbox_to_anchor=(0.45, 1.0), ncol=2); ax.grid(axis="y", visible=False)
    save(fig, "temporal_status")


# 13. Error anatomy, Phase 2 run 1 (docs/results_report.md §2.3) -------------------------------------------------
def error_anatomy():
    # Reference-side categories from the saved analysis of Run 1 on the original dev set (234 TASK, 169 PERSON, 130 TEMPORAL references).
    data = {"TASK": (76, 60, 51, 111), "PERSON": (98, 3, 3, 57), "TEMPORAL": (70, 31, 7, 61)}
    cats = ["exact", "near (IoU≥0.5)", "partial overlap", "no overlap"]
    fig, ax = plt.subplots(figsize=(5.2, 2.2))
    left = np.zeros(3)
    for i, cat in enumerate(cats):
        vals = np.array([data[t][i] for t in data])
        ax.barh(list(data), vals, left=left, color=[NAVY, TEAL, OCHRE, GREY][i], label=cat)
        left += vals
    ax.set_xlabel("predicted spans by best match against references (Run 1, original dev)")
    ax.legend(ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.25), fontsize=7); ax.invert_yaxis(); ax.grid(axis="y", visible=False)
    save(fig, "error_anatomy")


for fn in (mailex_events, entity_distribution, bio_imbalance, relation_distribution, phase2_curves, phase2_runs, relation_training,
           relation_confusion, model_iterations, phase75, silver_refinement, temporal_status, error_anatomy):
    fn()
