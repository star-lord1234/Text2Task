"""Edge validation for the dependency graph (Phase 6), plus the optional E5 consistency-aware edge selection.

Direction: ``T2 DEPENDS_ON T1`` is the graph edge T1 -> T2 (prerequisite -> dependent).
Structural problems (self-loop, unknown endpoint, duplicate, cycle) REJECT an edge; the rejection is recorded with its
reason and cycle path and the edge is kept for review, never silently dropped. Everything else is a WARNING.
A dependency is never inferred from date order; dates are only compared to raise a warning on an explicit edge.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional, Sequence

import networkx as nx

if TYPE_CHECKING:  # pragma: no cover
    from src.graph.graph_builder import WorkflowGraph
    from src.reconciliation.models import Task

OPEN_STATES = ("open", "in_progress")


def load_config(path: Optional[Path] = None) -> dict[str, Any]:
    path = path or Path(__file__).resolve().parents[2] / "configs" / "phase6.json"
    return json.loads(Path(path).read_text())


@dataclass
class EdgeDecision:
    accepted: bool
    code: str                                  # OK | SELF | UNKNOWN_ENDPOINT | DUPLICATE | CYCLE
    reason: str = ""
    cycle_path: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"accepted": self.accepted, "code": self.code, "reason": self.reason, "cycle_path": self.cycle_path, "warnings": self.warnings}


def _due_date(task: "Task") -> Optional[str]:
    due = task.due or {}
    if due.get("status") != "RESOLVED":
        return None
    v = due.get("value") or due.get("start")
    return str(v)[:10] if v else None


def edge_warnings(tasks: Mapping[str, "Task"], strict: nx.DiGraph, prerequisite: str, dependent: str) -> list[str]:
    """Non-structural findings for an (explicit) edge prerequisite -> dependent. Order is stable."""
    out: list[str] = []
    pre, dep = tasks.get(prerequisite), tasks.get(dependent)
    if pre is None or dep is None:
        return out
    if pre.status == "cancelled":
        out.append("PREREQUISITE_CANCELLED")
    if dep.status == "completed" and pre.status in OPEN_STATES:
        out.append("INCONSISTENT_COMPLETION")
    a, b = _due_date(pre), _due_date(dep)
    if a and b and a > b:
        out.append("PREREQUISITE_DUE_AFTER_DEPENDENT")
    if prerequisite in strict and dependent in strict:
        h = strict.copy()
        if h.has_edge(prerequisite, dependent):
            h.remove_edge(prerequisite, dependent)
        if nx.has_path(h, prerequisite, dependent):
            out.append("REDUNDANT_TRANSITIVE")
    return out


def validate_new_edge(graph: "WorkflowGraph", prerequisite: str, dependent: str) -> EdgeDecision:
    if prerequisite == dependent:
        return EdgeDecision(False, "SELF", f"SELF: {prerequisite} cannot depend on itself")
    if prerequisite not in graph.tasks or dependent not in graph.tasks:
        missing = [t for t in (prerequisite, dependent) if t not in graph.tasks]
        return EdgeDecision(False, "UNKNOWN_ENDPOINT", f"UNKNOWN_ENDPOINT: no such task(s) {', '.join(missing)} in this workspace")
    if graph.strict.has_edge(prerequisite, dependent):
        return EdgeDecision(False, "DUPLICATE", f"DUPLICATE: {prerequisite} -> {dependent} is already accepted")
    if nx.has_path(graph.strict, dependent, prerequisite):
        path = [prerequisite] + nx.shortest_path(graph.strict, dependent, prerequisite)
        return EdgeDecision(False, "CYCLE", f"CYCLE: adding {prerequisite} -> {dependent} closes the cycle {' -> '.join(path)}", cycle_path=path)
    return EdgeDecision(True, "OK", "", warnings=edge_warnings(graph.tasks, graph.strict, prerequisite, dependent))


def make_dependency_validator(config: Optional[Mapping[str, Any]] = None) -> Callable[..., tuple[bool, str]]:
    """Validator for ``Reconciler(dependency_validator=...)``: (store, ws, dependent, prerequisite) -> (ok, reason)."""
    from src.graph.graph_builder import WorkflowGraph

    def validator(store, ws: str, dependent: str, prerequisite: str) -> tuple[bool, str]:
        d = validate_new_edge(WorkflowGraph.from_store(store, ws), prerequisite, dependent)
        return d.accepted, d.reason
    return validator


# ======================================================================== optional E5
def _acyclic(edges: Sequence[tuple[str, str]]) -> bool:
    g = nx.DiGraph()
    g.add_edges_from(edges)
    return nx.is_directed_acyclic_graph(g)


def baseline_greedy_select(candidates: Sequence[tuple[str, str, float]], fixed: Sequence[tuple[str, str]] = ()) -> list[tuple[str, str, float]]:
    """Independent acceptance: take candidates in descending score (ties by id) if the graph stays acyclic. Order-dependent."""
    g = nx.DiGraph()
    g.add_edges_from(fixed)
    kept = []
    for u, v, w in sorted(candidates, key=lambda c: (-c[2], c[0], c[1])):
        if u == v or (u in g and v in g and nx.has_path(g, v, u)):
            continue
        g.add_edge(u, v)
        kept.append((u, v, w))
    return kept


def e5_select(candidates: Sequence[tuple[str, str, float]], fixed: Sequence[tuple[str, str]] = (), *, exact_max_edges: int = 16) -> dict[str, Any]:
    """Consistency-aware selection: the maximum-total-score acyclic subset of the candidate edges (fixed edges always kept).

    Per strongly connected component: exact enumeration when it has <= exact_max_edges candidate edges, otherwise
    a greedy cycle-breaking heuristic that repeatedly drops the lowest-score candidate on a cycle.
    Evidence/scores are inputs and are never altered. Returns the kept edges and which method handled each component.
    """
    fixed_set = {(u, v) for u, v in fixed}
    cand = {}
    for u, v, w in candidates:
        if u != v and (u, v) not in fixed_set:
            cand[(u, v)] = max(w, cand.get((u, v), w))
    fg = nx.DiGraph(); fg.add_edges_from(fixed_set)
    forced_out = [(e, w) for e, w in cand.items() if e[0] in fg and e[1] in fg and nx.has_path(fg, e[1], e[0])]
    for e, _ in forced_out:
        cand.pop(e)
    g = nx.DiGraph(); g.add_edges_from(fixed_set); g.add_edges_from(cand)
    kept = dict(cand)
    methods = []
    for comp in nx.strongly_connected_components(g):
        if len(comp) < 2:
            continue
        in_comp = {e: w for e, w in cand.items() if e[0] in comp and e[1] in comp}
        fixed_in = [e for e in fixed_set if e[0] in comp and e[1] in comp]
        if len(in_comp) <= exact_max_edges:
            edges = sorted(in_comp)
            best = None
            for mask in range(1 << len(edges)):
                chosen = [edges[i] for i in range(len(edges)) if mask >> i & 1]
                if not _acyclic(list(fixed_in) + chosen):
                    continue
                score = sum(in_comp[e] for e in chosen)
                key = (score, len(chosen), tuple(-i for i in range(0)))
                if best is None or key > best[0]:
                    best = (key, set(chosen))
            drop = set(edges) - best[1]
            methods.append({"component": sorted(comp), "method": "exact", "candidate_edges": len(edges)})
        else:
            h = nx.DiGraph(); h.add_edges_from(fixed_in); h.add_edges_from(in_comp)
            drop = set()
            while not nx.is_directed_acyclic_graph(h):
                cyc = nx.find_cycle(h)
                removable = [(e[0], e[1]) for e in cyc if (e[0], e[1]) in in_comp]
                e = min(removable, key=lambda x: (in_comp[x], x))
                h.remove_edge(*e); drop.add(e)
            methods.append({"component": sorted(comp), "method": "greedy", "candidate_edges": len(in_comp)})
        for e in drop:
            kept.pop(e, None)
    return {"kept": sorted((u, v, w) for (u, v), w in kept.items()), "dropped": sorted(
        [(u, v, w) for (u, v), w in cand.items() if (u, v) not in kept] + [(e[0], e[1], w) for e, w in forced_out]), "components": methods}


def milp_optimum(candidates: Sequence[tuple[str, str, float]], fixed: Sequence[tuple[str, str]] = ()) -> float:
    """Exact optimum total score via scipy.optimize.milp (MTZ ordering formulation); used only as a cross-check on small inputs."""
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp

    cand = {}
    for u, v, w in candidates:
        if u != v and (u, v) not in set(fixed):
            cand[(u, v)] = max(w, cand.get((u, v), w))
    edges = sorted(cand)
    if not edges:
        return 0.0                                    # nothing to choose: empty (or self-loop-only) candidate set
    fixed = list(dict.fromkeys(fixed))
    nodes = sorted({n for e in list(edges) + fixed for n in e})
    idx = {n: i for i, n in enumerate(nodes)}
    n, m, f = len(nodes), len(edges), len(fixed)
    big = n
    nv = m + n                                        # x_e (keep) then node potentials p_i
    c = np.zeros(nv); c[:m] = [-cand[e] for e in edges]
    rows, lo, hi = [], [], []
    for k, (u, v) in enumerate(edges):                # p_v - p_u >= 1 - big*(1-x_e)  ->  p_v - p_u - big*x_e >= 1 - big
        r = np.zeros(nv); r[m + idx[v]] = 1; r[m + idx[u]] = -1; r[k] = -big
        rows.append(r); lo.append(1 - big); hi.append(np.inf)
    for u, v in fixed:                                # fixed edges always enforce the ordering
        r = np.zeros(nv); r[m + idx[v]] = 1; r[m + idx[u]] = -1
        rows.append(r); lo.append(1); hi.append(np.inf)
    integrality = np.concatenate([np.ones(m), np.zeros(n)])
    bounds = Bounds(np.concatenate([np.zeros(m), np.zeros(n)]), np.concatenate([np.ones(m), np.full(n, n - 1)]))
    res = milp(c, constraints=LinearConstraint(np.array(rows), lo, hi) if rows else None, integrality=integrality, bounds=bounds)
    return float(-res.fun) if res.success else float("nan")
