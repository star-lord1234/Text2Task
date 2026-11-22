"""Workflow graph snapshot (Phase 6): a derived, in-memory NetworkX view of the Phase 5 store.

SQLite stays the single source of truth; a snapshot is rebuilt per request (hundreds of nodes at most).
The *strict* graph holds ACCEPTED edges only and is what readiness is computed from. Proposed and rejected
("held for review") edges live in a review layer: kept, serialised, never used for derived states.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Optional, Sequence

import networkx as nx

from src.graph.graph_constraints import edge_warnings
from src.reconciliation.models import Task
from src.reconciliation.store import TaskStore


def task_sort_key(tid: str) -> tuple[int, str]:
    tail = tid.rsplit("-", 1)[-1]
    return (int(tail) if tail.isdigit() else 10 ** 9, tid)


def make_edge_id(workspace: str, dependent: str, prerequisite: str) -> str:
    """Identical to the id Phase 5 assigns, so one pair is one row everywhere."""
    return "E-" + hashlib.sha1("|".join((workspace, dependent, prerequisite)).encode("utf-8")).hexdigest()[:12]


@dataclass
class EdgeRecord:
    edge_id: str
    prerequisite: str
    dependent: str
    status: str                              # proposed | accepted | rejected
    evidence: str = ""
    source_message_id: Optional[str] = None
    source_kind: str = "rule"
    score: Optional[float] = None
    reason: str = ""
    proposal_id: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    redundant: bool = False
    dangling: bool = False                   # an endpoint is not a known task

    @property
    def kind(self) -> str:
        return {"accepted": "accepted", "proposed": "proposed", "rejected": "held"}.get(self.status, self.status)


class WorkflowGraph:
    def __init__(self, workspace: str, tasks: Mapping[str, Task], edges: Iterable[EdgeRecord]):
        self.workspace = workspace
        self.tasks: dict[str, Task] = dict(sorted(tasks.items(), key=lambda kv: task_sort_key(kv[0])))
        self.edges: list[EdgeRecord] = sorted(edges, key=lambda e: (task_sort_key(e.prerequisite), task_sort_key(e.dependent), e.edge_id))
        self.strict = nx.DiGraph()
        self.strict.add_nodes_from(self.tasks)
        for e in self.edges:
            e.dangling = e.prerequisite not in self.tasks or e.dependent not in self.tasks
            if e.status == "accepted" and not e.dangling:
                self.strict.add_edge(e.prerequisite, e.dependent, edge_id=e.edge_id)
        self.acyclic = nx.is_directed_acyclic_graph(self.strict)
        try:
            self.cycle: list[str] = [u for u, _v in nx.find_cycle(self.strict)] if not self.acyclic else []
        except nx.NetworkXNoCycle:   # pragma: no cover
            self.cycle = []
        self.integrity = {"acyclic": self.acyclic, "cycle": self.cycle,
                          "dangling_edges": [e.edge_id for e in self.edges if e.dangling and e.status == "accepted"]}
        reduction = nx.transitive_reduction(self.strict) if self.acyclic else None
        for e in self.edges:
            if e.dangling or e.status == "rejected":
                continue
            e.warnings = edge_warnings(self.tasks, self.strict, e.prerequisite, e.dependent)
            e.redundant = "REDUNDANT_TRANSITIVE" in e.warnings
            if reduction is not None and e.status == "accepted":
                e.redundant = not reduction.has_edge(e.prerequisite, e.dependent)

    # ---------------------------------------------------------------- construction
    @classmethod
    def from_store(cls, store: TaskStore, workspace: str) -> "WorkflowGraph":
        tasks = {t.task_id: t for t in store.list_tasks(workspace)}
        edges = [EdgeRecord(d.edge_id, d.prerequisite_task_id, d.dependent_task_id, d.status, d.evidence, d.source_message_id,
                            d.source_kind or "rule", d.score, d.reason, d.proposal_id) for d in store.list_dependencies(workspace)]
        return cls(workspace, tasks, edges)

    def with_task_status(self, task_id: str, status: str) -> "WorkflowGraph":
        """What-if copy with one task's lifecycle status replaced (no store access, no history)."""
        tasks = dict(self.tasks)
        tasks[task_id] = replace(tasks[task_id], status=status)
        edges = [replace(e, warnings=[], redundant=False) for e in self.edges]
        return WorkflowGraph(self.workspace, tasks, edges)

    # ---------------------------------------------------------------- views
    def edges_by_status(self, status: str) -> list[EdgeRecord]:
        return [e for e in self.edges if e.status == status]

    def accepted(self) -> list[EdgeRecord]:
        return self.edges_by_status("accepted")

    def proposed(self) -> list[EdgeRecord]:
        return self.edges_by_status("proposed")

    def held(self) -> list[EdgeRecord]:
        return self.edges_by_status("rejected")

    def get_edge(self, prerequisite: str, dependent: str) -> Optional[EdgeRecord]:
        return next((e for e in self.edges if e.prerequisite == prerequisite and e.dependent == dependent), None)

    # ---------------------------------------------------------------- queries
    def prerequisites_of(self, task_id: str) -> list[str]:
        return sorted(self.strict.predecessors(task_id), key=task_sort_key) if task_id in self.strict else []

    def dependents_of(self, task_id: str) -> list[str]:
        return sorted(self.strict.successors(task_id), key=task_sort_key) if task_id in self.strict else []

    def ancestors_of(self, task_id: str) -> list[str]:
        return sorted(nx.ancestors(self.strict, task_id), key=task_sort_key) if task_id in self.strict else []

    def descendants_of(self, task_id: str) -> list[str]:
        return sorted(nx.descendants(self.strict, task_id), key=task_sort_key) if task_id in self.strict else []

    def topological_order(self) -> Optional[list[str]]:
        """Deterministic topological order; None when the stored accepted edges are cyclic (reported, not hidden)."""
        if not self.acyclic:
            return None
        return list(nx.lexicographical_topological_sort(self.strict, key=task_sort_key))

    def layers(self) -> Optional[dict[str, int]]:
        if not self.acyclic:
            return None
        out = {}
        for i, gen in enumerate(nx.topological_generations(self.strict)):
            for n in gen:
                out[n] = i
        return out

    def longest_chain(self) -> Optional[list[str]]:
        if not self.acyclic or not self.strict:
            return None
        return nx.dag_longest_path(self.strict)
