#!/usr/bin/env python3
"""Phase 5 evaluation. FUNCTIONAL and PROVISIONAL: scripted scenarios, invariant fuzzing, and a corpus replay.

There is no labelled reconciliation data and the corpus holds almost no update messages, so nothing here is accuracy
against human judgement. The corpus replay reports rates and writes samples for qualitative reading. The test split is
never read (train + validation only).
"""
from __future__ import annotations

import argparse, json, random, re, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "tests"))

from src.model_data.token_classification import read_jsonl  # noqa: E402
from src.model_training.relation_classifier import RelationPredictor  # noqa: E402
from src.pipeline.contracts import MessageEnvelope, Participant  # noqa: E402
from src.pipeline.identity_resolution import ParticipantRegistry, _participant, _clean_mail_name  # noqa: E402
from src.pipeline.task_fields import build_task_candidates  # noqa: E402
from src.reconciliation.models import ReconciliationError, StaleVersion  # noqa: E402
from src.reconciliation.reconciler import Reconciler  # noqa: E402
from src.reconciliation.scenario_runner import run_scenario  # noqa: E402
from src.reconciliation.store import TaskStore  # noqa: E402

UPDATE_OPS = {"COMPLETE_TASK", "CANCEL_TASK", "UPDATE_STATUS", "UPDATE_ASSIGNEE", "PROPOSE_DUE_DATE_CHANGE", "CONFIRM_DUE_DATE_CHANGE"}


# ------------------------------------------------------------------ scenarios
def scenario_metrics():
    scenarios = json.loads((ROOT / "tests/fixtures/reconciliation_scenarios.json").read_text())["scenarios"]
    results = [run_scenario(s) for s in scenarios]
    n_ops_checks = sum(1 for s in scenarios for m in s["messages"] if "ops" in m.get("expect", {}))
    op_failures = sum(1 for r in results for f in r["failures"] if " operations " in f)
    invariant_failures = sum(1 for r in results for f in r["failures"] if "invariant" in f)
    overwrites = 0
    unresolved_over_resolved = 0
    ambiguous = 0
    op_counts = Counter()
    for r in results:
        st = r["store"]
        for p in st.list_proposals("w"):
            op_counts[p.operation] += 1
            if p.match.get("outcome") == "AMBIGUOUS_REFERENT":
                ambiguous += 1
            if p.status == "applied" and p.operation in UPDATE_OPS and p.match.get("outcome") != "MATCHED" and p.resolution_note != "edited":
                overwrites += 1   # applied to a task that was never matched and the reviewer did not choose it
        for t in st.list_tasks("w"):
            for e in st.history_for("w", t.task_id):
                if e.field in ("due", "scheduled") and isinstance(e.before, dict) and e.before.get("status") == "RESOLVED" \
                        and not (isinstance(e.after, dict) and e.after.get("status") == "RESOLVED") and e.source_kind != "human":
                    unresolved_over_resolved += 1
    dup_names = [r for r in results if r["name"].split("_")[0] in ("02", "03", "04", "28")]
    return {
        "scenarios": len(scenarios), "passed": sum(r["passed"] for r in results),
        "failed": [r["name"] for r in results if not r["passed"]],
        "message_operation_checks": n_ops_checks, "message_operation_mismatches": op_failures,
        "operation_accuracy": (n_ops_checks - op_failures) / max(n_ops_checks, 1),
        "duplicate_attempt_scenarios": len(dup_names),
        "extra_tasks_created_by_duplicate_attempts": sum(max(0, len(r["tasks"]) - 1) for r in dup_names),
        "incorrect_overwrite_count": overwrites, "resolved_dates_overwritten_by_unresolved": unresolved_over_resolved,
        "ambiguous_referent_proposals_raised": ambiguous, "invariant_failures": invariant_failures,
        "proposal_operation_counts": dict(op_counts.most_common()),
    }


def fuzz_metrics(seeds=200, steps=60):
    import test_reconciliation_invariants as T
    violations, steps_run, rejected, tasks, updated = [], 0, 0, 0, 0
    for seed in range(seeds):
        f = T.Fuzz(1000 + seed)
        try:
            for _ in range(steps):
                r = f.rng.random()
                if r < 0.45:
                    f.process(f.rng.choice(T.POOL))
                elif r < 0.85:
                    f.review()
                elif r < 0.93:
                    f.process(None, replay=True)
                else:
                    f.manual()
                f.check()
                steps_run += 1
        except AssertionError as e:
            violations.append({"seed": 1000 + seed, "error": str(e)[:200]})
        rejected += f.errors
        ts = f.store.list_tasks(T.WS)
        tasks += len(ts); updated += sum(t.version > 1 for t in ts)
    return {"seeds": seeds, "steps_per_seed": steps, "steps_executed": steps_run, "invariant_violations": len(violations),
            "violations": violations[:5], "review_actions_rejected_by_safety_checks": rejected,
            "tasks_created": tasks, "tasks_updated_after_creation": updated}


# ------------------------------------------------------------------ corpus replay
def _norm_registry(rec):
    """Low-trust registry with ids derived from the participant's normalised name so ids are stable across turns."""
    from src.pipeline.identity_resolution import registry_from_mailex_record
    reg, sender, recips = registry_from_mailex_record(rec)
    people, remap = [], {}
    for p in reg.participants:
        pid = re.sub(r"\W+", "_", p.display_name.lower()).strip("_") or p.id
        remap[p.id] = pid
        people.append(Participant(pid, p.display_name, p.aliases, p.emails, low_trust=True))
    uniq = {p.id: p for p in people}
    return ParticipantRegistry(list(uniq.values())), remap.get(sender), [remap[r] for r in recips]


def corpus_replay(predictor, sample_cap=40):
    recs = []
    for sp in ("train", "validation"):
        recs += read_jsonl(ROOT / f"data/final/{sp}.jsonl")
    threads = defaultdict(list)
    for r in recs:
        threads[r["thread_id"]].append(r)
    store = TaskStore(":memory:")
    rec = Reconciler(store)
    stats = {"threads": len(threads), "multi_turn_threads": sum(len(v) > 1 for v in threads.values()), "messages": 0,
             "ops": Counter(), "ops_multi_turn": Counter(), "flags": Counter(), "referent_outcomes": Counter(), "tasks_created": 0,
             "restatements": 0, "possible_duplicates": 0, "errors": Counter()}
    samples = {"updates": [], "no_action_flagged": [], "dup": [], "create": []}
    for tid, rs in threads.items():
        rs.sort(key=lambda r: r.get("turn_index", 0))
        prev = None
        for r in rs:
            ents = [e for e in r["text2task_annotations"]["entities"] if e["type"] in ("TASK", "PERSON", "TEMPORAL")]
            registry, sender, recips = _norm_registry(r)
            env = MessageEnvelope(r["id"], r["text"], sender, recips, None, None, tid, prev)
            rels = predictor.predict(r["text"], ents)["relations"]
            cands = build_task_candidates(env, ents, rels, registry, primary_source="neural", config=rec.phase4_config)
            try:
                res = rec.process_message(env, ents, cands, registry, workspace_id=tid, source_kind="neural")
            except ReconciliationError as e:
                stats["errors"][e.code] += 1
                prev = r["id"]
                continue
            stats["messages"] += 1
            multi = len(rs) > 1
            for p in res.proposals + res.no_actions:
                stats["ops"][p.operation] += 1
                if multi:
                    stats["ops_multi_turn"][p.operation] += 1
                for f in p.flags:
                    stats["flags"][f["code"]] += 1
                if p.operation in UPDATE_OPS or p.payload.get("needs_referent"):
                    stats["referent_outcomes"][p.match.get("outcome", "n/a")] += 1
                codes = {f["code"] for f in p.flags}
                if "RESTATED_EXISTING_TASK" in codes or "RESTATED_WITH_DIFFERENT_DATE" in codes:
                    stats["restatements"] += 1
                if "POSSIBLE_DUPLICATE" in codes:
                    stats["possible_duplicates"] += 1
                row = {"thread": tid, "turn": r.get("turn_index"), "sentence": p.evidence.get("sentence"), "operation": p.operation,
                       "flags": sorted(codes), "match": [(x["task_id"], x["score"]) for x in (p.match.get("ranked") or [])][:3],
                       "note": p.note[:90], "tasks_in_thread": [t.title for t in store.list_tasks(tid)][:4]}
                if p.operation in UPDATE_OPS and len(samples["updates"]) < sample_cap:
                    samples["updates"].append(row)
                elif p.operation == "NO_ACTION" and codes & {"NO_REFERENT", "REFERENT_PENDING_REVIEW", "ILLEGAL_TRANSITION"} and len(samples["no_action_flagged"]) < 20:
                    samples["no_action_flagged"].append(row)
                elif codes & {"POSSIBLE_DUPLICATE", "RESTATED_EXISTING_TASK", "RESTATED_WITH_DIFFERENT_DATE"} and len(samples["dup"]) < 15:
                    samples["dup"].append(row)
                elif p.operation == "CREATE_TASK" and len(samples["create"]) < 15 and random.Random(len(samples["create"]) + stats["messages"]).random() < 0.1:
                    samples["create"].append(row)
            for p in res.proposals:
                if p.operation == "CREATE_TASK":     # simulated reviewer: accept creations only, leave every update pending
                    try:
                        rec.accept(tid, p.proposal_id, "simulated-reviewer")
                        stats["tasks_created"] += 1
                    except (ReconciliationError, StaleVersion):
                        stats["errors"]["accept_failed"] += 1
            prev = r["id"]
    for k in ("ops", "ops_multi_turn", "flags", "referent_outcomes", "errors"):
        stats[k] = dict(stats[k].most_common())
    return stats, samples


def write_samples(path, samples):
    lines = ["# Phase 5 corpus-replay samples (qualitative reading only)", "",
             "Replay of train+validation threads: annotated v1 entities, Phase 3 neural relations, Phase 4 candidates, Phase 5 reconciler. "
             "A simulated reviewer accepted creations only. There is no ground truth; these rows are for reading, not scoring.", ""]
    for title, key in (("Update-type proposals", "updates"), ("Flagged NO_ACTION", "no_action_flagged"),
                       ("Duplicate / restatement handling", "dup"), ("Sample creations", "create")):
        lines += [f"## {title} ({len(samples[key])})", ""]
        for r in samples[key]:
            lines.append(f"- **{r['operation']}** `{r['thread']}` turn {r['turn']}: “{(r['sentence'] or '')[:160]}”  ")
            lines.append(f"  flags={r['flags']} match={r['match']} note={r['note']!r} tasks_in_thread={r['tasks_in_thread']}")
        lines.append("")
    path.write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "results/phase5")
    ap.add_argument("--skip-corpus", action="store_true")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    report = {"provenance": "functional / provisional: scripted scenarios, fuzzing, and corpus replay; no labelled reconciliation data",
              "scenarios": scenario_metrics(), "fuzz": fuzz_metrics()}
    print(json.dumps({k: report[k] for k in ("scenarios", "fuzz")}, indent=1)[:3000])
    if not a.skip_corpus:
        predictor = RelationPredictor(ROOT / "models/text2task-relations/ACTIVE")
        stats, samples = corpus_replay(predictor)
        report["corpus_replay"] = stats
        write_samples(a.out / "samples.md", samples)
        print(json.dumps(stats, indent=1))
    (a.out / "report.json").write_text(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
