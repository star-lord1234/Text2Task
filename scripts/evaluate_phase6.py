#!/usr/bin/env python3
"""Phase 6 evaluation. FUNCTIONAL: graph validity and derived-state correctness against independent oracles,
scripted scenarios, and a SYNTHETIC comparison for the optional E5 edge selection.

There is no labelled dependency data (all 7 labelled DEPENDS_ON examples are TASK->EVENT; the Phase 5 corpus replay produced
no edges), so accepted-edge precision/recall cannot be computed and nothing here is semantic accuracy.
"""
from __future__ import annotations

import argparse, json, random, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))

from src.graph.graph_builder import WorkflowGraph  # noqa: E402
from src.graph.graph_constraints import baseline_greedy_select, e5_select, milp_optimum, make_dependency_validator  # noqa: E402
from src.graph.scenario_runner import WS, run_graph_scenario  # noqa: E402
from src.reconciliation.reconciler import Reconciler  # noqa: E402
from src.reconciliation.scenario_runner import run_scenario  # noqa: E402
from src.reconciliation.store import TaskStore  # noqa: E402


def scenarios():
    sc = json.loads((ROOT / "tests/fixtures/graph_scenarios.json").read_text())["scenarios"]
    results = [run_graph_scenario(s) for s in sc]
    chat = []
    for s in json.loads((ROOT / "tests/fixtures/reconciliation_scenarios.json").read_text())["scenarios"]:
        if s["name"].startswith(("32_", "33_", "34_")):
            rec = Reconciler(TaskStore(":memory:"), dependency_validator=make_dependency_validator())
            chat.append(run_scenario(s, reconciler=rec))
    return {"graph_scenarios": len(sc), "graph_scenarios_passed": sum(r["passed"] for r in results),
            "failed": [r["name"] for r in results if not r["passed"]],
            "chat_dependency_scenarios": len(chat), "chat_dependency_scenarios_passed": sum(r["passed"] for r in chat)}


def oracle_fuzz(seeds=300, steps=40):
    import test_graph_oracle as T
    violations, decisions, state_checks, codes, held_without_reason = [], 0, 0, Counter(), 0
    accepted_total = held_total = 0
    for seed in range(seeds):
        f = T.Fuzz(5000 + seed)
        try:
            for _ in range(steps):
                f.step(); f.check(); decisions += 1; state_checks += len(f.status)
        except AssertionError as e:
            violations.append({"seed": 5000 + seed, "error": str(e)[:200]})
        g = WorkflowGraph.from_store(f.store, T.WS)
        accepted_total += len(g.accepted()); held_total += len(g.held())
        held_without_reason += sum(1 for e in g.held() if not e.reason)
        for h in g.held():
            codes[h.reason.split(":")[0]] += 1
    return {"seeds": seeds, "steps_per_seed": steps, "edit_decisions_checked_against_oracle": decisions,
            "derived_state_comparisons": state_checks, "oracle_violations": len(violations), "violations": violations[:5],
            "accepted_edges_final": accepted_total, "held_edges_final": held_total, "held_edges_without_reason": held_without_reason,
            "held_reason_codes": dict(codes.most_common())}


def synthetic_e5(instances=300, seed=11):
    rng = random.Random(seed)
    agg = {m: Counter() for m in ("accept_all", "baseline_greedy", "e5")}
    gaps_exact, gaps_greedy, milp_checked, e5_better_total, greedy_instances = [], [], 0, 0, 0
    for _ in range(instances):
        n = rng.randint(5, 9)
        order = list(range(n)); rng.shuffle(order)
        name = [f"n{i}" for i in range(n)]
        pos = {name[i]: order[i] for i in range(n)}              # hidden true order
        cand = {}
        for i in range(n):                                         # correct edges: forward in the hidden order
            for j in range(n):
                if pos[name[i]] < pos[name[j]] and rng.random() < 0.35:
                    cand[(name[i], name[j])] = (round(rng.uniform(0.45, 1.0), 2), True)
        for (u, v), (_, ok) in list(cand.items()):                 # incorrect: reversed copies and extra backward edges
            if rng.random() < 0.4 and (v, u) not in cand:
                cand[(v, u)] = (round(rng.uniform(0.2, 0.8), 2), False)
        for _ in range(rng.randint(0, 3)):
            u, v = rng.sample(name, 2)
            if (u, v) not in cand:
                cand[(u, v)] = (round(rng.uniform(0.2, 0.8), 2), pos[u] < pos[v])
        triples = [(u, v, s) for (u, v), (s, _) in cand.items()]
        truth = {e: ok for e, (_, ok) in cand.items()}
        sets = {"accept_all": {(u, v) for u, v, _ in triples},
                "baseline_greedy": {(u, v) for u, v, _ in baseline_greedy_select(triples)}}
        e5 = e5_select(triples, exact_max_edges=14)
        sets["e5"] = {(u, v) for u, v, _ in e5["kept"]}
        import networkx as nx
        for m, kept in sets.items():
            g = nx.DiGraph(); g.add_edges_from(kept)
            a = agg[m]
            a["instances"] += 1
            a["cyclic_result"] += (not nx.is_directed_acyclic_graph(g))
            a["incorrect_candidates"] += sum(not ok for ok in truth.values())
            a["correct_candidates"] += sum(truth.values())
            a["incorrect_edges_removed"] += sum(1 for e, ok in truth.items() if not ok and e not in kept)
            a["correct_edges_lost"] += sum(1 for e, ok in truth.items() if ok and e not in kept)
            a["incorrect_edges_kept"] += sum(1 for e, ok in truth.items() if not ok and e in kept)
        tot = lambda ks: sum(s for u, v, s in triples if (u, v) in ks)
        used_greedy = any(c["method"] == "greedy" for c in e5["components"])
        greedy_instances += used_greedy
        if len(triples) <= 16:
            milp_checked += 1
            (gaps_greedy if used_greedy else gaps_exact).append(milp_optimum(triples) - tot(sets["e5"]))
        e5_better_total += tot(sets["e5"]) > tot(sets["baseline_greedy"]) + 1e-9
    out = {"instances": instances, "NOTE": "synthetic graphs with injected wrong edges; measures constraint handling, NOT extraction accuracy",
           "methods": {m: dict(v) for m, v in agg.items()}, "e5_total_score_higher_than_greedy_in_instances": e5_better_total,
           "instances_where_e5_used_greedy_fallback": greedy_instances,
           "milp_cross_checked_instances": milp_checked,
           "milp_check_exact_only": {"instances": len(gaps_exact), "max_abs_gap_to_milp_optimum": max((abs(g) for g in gaps_exact), default=0.0)},
           "milp_check_greedy_fallback": {"instances": len(gaps_greedy), "max_gap_to_milp_optimum": max(gaps_greedy, default=0.0),
                                          "note": "components above exact_max_candidate_edges use a heuristic and can be suboptimal"}}
    for m, v in out["methods"].items():
        v["incorrect_removed_rate"] = round(v["incorrect_edges_removed"] / max(v["incorrect_candidates"], 1), 4)
        v["correct_lost_rate"] = round(v["correct_edges_lost"] / max(v["correct_candidates"], 1), 4)
    return out


def corpus_note():
    p = ROOT / "results/phase5/report.json"
    if not p.is_file():
        return {"available": False}
    c = json.loads(p.read_text()).get("corpus_replay", {})
    return {"available": True, "messages_replayed": c.get("messages"), "ADD_DEPENDENCY_proposals": c.get("ops", {}).get("ADD_DEPENDENCY", 0),
            "DEPENDENCY_ENDPOINT_UNMATCHED_flags": c.get("flags", {}).get("DEPENDENCY_ENDPOINT_UNMATCHED", 0),
            "SELF_DEPENDENCY_flags": c.get("flags", {}).get("SELF_DEPENDENCY", 0),
            "labelled_DEPENDS_ON_examples": "4 train / 0 validation / 3 test, all TASK->EVENT (not producible by the 3-class entity model)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "results/phase6")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    report = {"provenance": "functional / provisional; no labelled dependency data exists",
              "scenarios": scenarios(), "oracle_fuzz": oracle_fuzz(), "e5_synthetic": synthetic_e5(), "real_corpus": corpus_note()}
    (a.out / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=1, default=str))


if __name__ == "__main__":
    main()
