"""Deterministic serialisation of a workflow graph (Phase 6): React-Flow-shaped JSON, plus DOT and Mermaid text.

No rendering library is used; drawing and layout (dagre/ELK) belong to the Phase 7 frontend. `layer` is a topological
generation, offered only as a layout hint. Output is sorted, so identical state gives identical text.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from src.graph.graph_builder import EdgeRecord, WorkflowGraph, task_sort_key
from src.graph.graph_constraints import load_config
from src.graph.workflow_state import NodeState, compute_states

SCHEMA = "phase6-v1"


def _due_text(d: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not d:
        return None
    return d.get("value") or d.get("start") or d.get("raw")


def _warning(code: str, cfg: Mapping[str, Any]) -> dict[str, str]:
    w = cfg.get("warnings", {}).get(code, {})
    return {"code": code, "severity": w.get("severity", "warn"), "message": w.get("message", code)}


def to_frontend(graph: WorkflowGraph, states: Optional[Mapping[str, NodeState]] = None, config: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    cfg = config or load_config()
    states = states or compute_states(graph)
    layers = graph.layers()
    nodes = []
    for tid, t in graph.tasks.items():
        s = states[tid]
        nodes.append({"id": tid, "title": t.title, "owner_id": t.owner_id, "status": t.status, "derived_state": s.derived,
                      "blocked_by": s.blocked_by, "cancelled_prereqs": s.cancelled_prereqs, "root_blockers": s.root_blockers,
                      "due": _due_text(t.due), "due_status": (t.due or {}).get("status"), "scheduled": _due_text(t.scheduled),
                      "layer": None if layers is None else layers.get(tid), "source_message_id": t.source_message_id,
                      "thread_id": t.thread_id, "version": t.version})
    edges = [{"id": e.edge_id, "source": e.prerequisite, "target": e.dependent, "kind": e.kind, "status": e.status, "evidence": e.evidence,
              "source_message_id": e.source_message_id, "source_kind": e.source_kind, "score": e.score, "reason": e.reason,
              "warnings": [_warning(w, cfg) for w in e.warnings], "redundant": e.redundant, "dangling": e.dangling} for e in graph.edges]
    return {"nodes": nodes, "edges": edges,
            "meta": {"schema": SCHEMA, "workspace": graph.workspace, "acyclic": graph.acyclic, "cycle": graph.cycle,
                     "node_count": len(nodes), "accepted_edges": len(graph.accepted()), "proposed_edges": len(graph.proposed()),
                     "held_edges": len(graph.held()), "dangling_accepted_edges": graph.integrity["dangling_edges"],
                     "ready": sorted((n["id"] for n in nodes if n["derived_state"] == "ready"), key=task_sort_key),
                     "blocked": sorted((n["id"] for n in nodes if n["derived_state"] == "blocked"), key=task_sort_key),
                     "needs_review": sorted((n["id"] for n in nodes if n["derived_state"] == "blocked_cancelled_prereq"), key=task_sort_key)}}


def _label(t, state: NodeState) -> str:
    return f"{t.task_id} {t.title[:40]} | {t.owner_id or 'unassigned'} | {state.derived}"


def to_dot(graph: WorkflowGraph, states: Optional[Mapping[str, NodeState]] = None) -> str:
    states = states or compute_states(graph)
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    lines = ["digraph workflow {", "  rankdir=LR;", '  node [shape=box, fontname="Helvetica"];']
    for tid, t in graph.tasks.items():
        lines.append(f'  "{tid}" [label="{esc(_label(t, states[tid]))}"];')
    for e in graph.edges:
        if e.dangling:
            continue
        style = {"accepted": "solid", "proposed": "dashed", "held": "dotted"}[e.kind]
        extra = f', color=red, label="{esc(e.reason.split(":")[0])}"' if e.kind == "held" else ""
        lines.append(f'  "{e.prerequisite}" -> "{e.dependent}" [style={style}{extra}];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def to_mermaid(graph: WorkflowGraph, states: Optional[Mapping[str, NodeState]] = None) -> str:
    states = states or compute_states(graph)
    nid = lambda t: re.sub(r"\W", "_", t)
    safe = lambda s: re.sub(r'["\[\]{}()|<>]', " ", s)
    lines = ["flowchart LR"]
    for tid, t in graph.tasks.items():
        lines.append(f'    {nid(tid)}["{safe(_label(t, states[tid]))}"]')
    for e in graph.edges:
        if e.dangling:
            continue
        a, b = nid(e.prerequisite), nid(e.dependent)
        if e.kind == "accepted":
            lines.append(f"    {a} --> {b}")
        elif e.kind == "proposed":
            lines.append(f"    {a} -.-> {b}")
        else:
            lines.append(f'    {a} -. "held: {safe(e.reason.split(":")[0])}" .-> {b}')
    return "\n".join(lines) + "\n"
