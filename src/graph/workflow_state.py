"""Derived workflow state (Phase 6): ready / blocked / done, computed from the strict graph and never stored.

A task is blocked while any accepted prerequisite is open or in progress. A CANCELLED prerequisite never satisfies a
dependency: if nothing else is incomplete the task shows `blocked_cancelled_prereq` (needs review), it is not unblocked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.graph.graph_builder import WorkflowGraph, task_sort_key

OPEN = ("open", "in_progress")
DERIVED = ("ready", "blocked", "blocked_cancelled_prereq", "done", "cancelled")


@dataclass
class NodeState:
    task_id: str
    lifecycle: str
    derived: str
    blocked_by: list[str] = field(default_factory=list)          # direct prerequisites that are not completed (open/in_progress)
    cancelled_prereqs: list[str] = field(default_factory=list)   # direct prerequisites that were cancelled
    root_blockers: list[str] = field(default_factory=list)       # incomplete ancestors with nothing incomplete before them

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "lifecycle": self.lifecycle, "derived": self.derived, "blocked_by": self.blocked_by,
                "cancelled_prereqs": self.cancelled_prereqs, "root_blockers": self.root_blockers}


@dataclass
class StateDiff:
    became_ready: list[str] = field(default_factory=list)
    became_blocked: list[str] = field(default_factory=list)
    became_review: list[str] = field(default_factory=list)       # now blocked_cancelled_prereq
    became_done: list[str] = field(default_factory=list)
    became_cancelled: list[str] = field(default_factory=list)
    changed: dict[str, tuple[str, str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"became_ready": self.became_ready, "became_blocked": self.became_blocked, "became_review": self.became_review,
                "became_done": self.became_done, "became_cancelled": self.became_cancelled,
                "changed": {k: list(v) for k, v in self.changed.items()}}


def compute_states(graph: WorkflowGraph) -> dict[str, NodeState]:
    tasks = graph.tasks
    states: dict[str, NodeState] = {}
    for tid, t in tasks.items():
        if t.status == "completed":
            states[tid] = NodeState(tid, t.status, "done")
            continue
        if t.status == "cancelled":
            states[tid] = NodeState(tid, t.status, "cancelled")
            continue
        pre = graph.prerequisites_of(tid)
        incomplete = [p for p in pre if tasks[p].status in OPEN]
        cancelled = [p for p in pre if tasks[p].status == "cancelled"]
        derived = "blocked" if incomplete else ("blocked_cancelled_prereq" if cancelled else "ready")
        states[tid] = NodeState(tid, t.status, derived, blocked_by=incomplete, cancelled_prereqs=cancelled)
    for tid, s in states.items():
        if s.derived == "blocked":
            roots = [a for a in graph.ancestors_of(tid) if states[a].derived in ("ready", "blocked_cancelled_prereq")]
            s.root_blockers = sorted(roots, key=task_sort_key)
    return states


def diff_states(before: dict[str, NodeState], after: dict[str, NodeState]) -> StateDiff:
    d = StateDiff()
    for tid in sorted(after, key=task_sort_key):
        b, a = before.get(tid), after[tid]
        if b is None or b.derived == a.derived:
            continue
        d.changed[tid] = (b.derived, a.derived)
        {"ready": d.became_ready, "blocked": d.became_blocked, "blocked_cancelled_prereq": d.became_review,
         "done": d.became_done, "cancelled": d.became_cancelled}[a.derived].append(tid)
    return d


def impact_of(graph: WorkflowGraph, task_id: str, new_status: str) -> StateDiff:
    """Pure what-if: which derived states change if `task_id` moved to `new_status`? Touches no store."""
    return diff_states(compute_states(graph), compute_states(graph.with_task_status(task_id, new_status)))
