"""Manual dependency edits (Phase 6): add / remove / reconsider an edge.

Same rules as chat-derived edges: one transaction, the shared validator, an idempotency key, and an append-only history
event on the dependent task with ``source_kind='human'``. A refused edge is STORED as `rejected` with its reason and
cycle path (shown as "held for review"); removal also keeps the row (`rejected`, reason `REMOVED: ...`) so evidence survives.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from src.graph.graph_builder import WorkflowGraph, make_edge_id
from src.graph.graph_constraints import EdgeDecision, validate_new_edge
from src.reconciliation.models import DependencyEdge, ReconciliationError
from src.reconciliation.store import TaskStore


class GraphEditor:
    def __init__(self, store: TaskStore, validator: Optional[Callable[[WorkflowGraph, str, str], EdgeDecision]] = None):
        self.store = store
        self.validator = validator or validate_new_edge

    # ------------------------------------------------------------------ helpers
    def _row(self, ws: str, edge_id: str) -> Optional[DependencyEdge]:
        return next((d for d in self.store.list_dependencies(ws) if d.edge_id == edge_id), None)

    def _history(self, ws: str, dependent: str, op: str, before: Any, after: Any, actor: str, note: str) -> Optional[int]:
        if self.store.get_task(ws, dependent) is None:
            return None
        return self.store.append_history(ws, dependent, operation=op, field="dependency", before=before, after=after, actor=actor,
                                         source_kind="human", note=note)

    def _replay(self, ws: str, kind: str, key: Optional[str]):
        if key is None:
            return None
        prior = self.store.get_idempotent(ws, f"graphedit:{kind}:{key}")
        return None if prior is None else {**prior, "replayed": True}

    def _save(self, ws: str, kind: str, key: Optional[str], result: dict[str, Any]) -> dict[str, Any]:
        if key is not None:
            self.store.save_idempotent(ws, f"graphedit:{kind}:{key}", result)
        return result

    # ------------------------------------------------------------------ add
    def add_dependency(self, ws: str, prerequisite: str, dependent: str, actor: str, *, evidence: str = "",
                       source_message_id: Optional[str] = None, idempotency_key: Optional[str] = None, note: str = "") -> dict[str, Any]:
        with self.store.transaction():
            prior = self._replay(ws, "add", idempotency_key)
            if prior:
                return prior
            graph = WorkflowGraph.from_store(self.store, ws)
            decision = self.validator(graph, prerequisite, dependent)
            eid = make_edge_id(ws, dependent, prerequisite)
            row = self._row(ws, eid)
            if row is not None and row.status == "accepted":
                return self._save(ws, "add", idempotency_key, {"edge_id": eid, "status": "accepted", "applied": False, "code": "DUPLICATE",
                                                               "reason": decision.reason, "cycle_path": [], "warnings": []})
            status = "accepted" if decision.accepted else "rejected"
            edge = DependencyEdge(eid, ws, dependent, prerequisite, status, evidence, source_message_id, "human", None, decision.reason)
            before = row.to_dict() if row else None
            if row is None:
                self.store.insert_dependency(edge)
            else:
                self.store.update_dependency(ws, eid, status=status, reason=decision.reason, evidence=evidence or row.evidence,
                                             source_message_id=source_message_id or row.source_message_id, source_kind="human")
            hid = self._history(ws, dependent, "ADD_DEPENDENCY", before, edge.to_dict(), actor, (note + " " + decision.reason).strip())
            return self._save(ws, "add", idempotency_key, {"edge_id": eid, "status": status, "applied": True, "code": decision.code,
                                                           "reason": decision.reason, "cycle_path": decision.cycle_path,
                                                           "warnings": decision.warnings, "history_event_id": hid})

    # ------------------------------------------------------------------ remove
    def remove_dependency(self, ws: str, edge_id: str, actor: str, reason: str = "", *, idempotency_key: Optional[str] = None) -> dict[str, Any]:
        with self.store.transaction():
            prior = self._replay(ws, "remove", idempotency_key)
            if prior:
                return prior
            row = self._row(ws, edge_id)
            if row is None:
                raise ReconciliationError("NOT_FOUND", f"no dependency edge {edge_id}")
            if row.status == "rejected":
                return self._save(ws, "remove", idempotency_key, {"edge_id": edge_id, "status": "rejected", "applied": False, "reason": row.reason})
            why = f"REMOVED: by {actor}" + (f" ({reason})" if reason else "")
            self.store.update_dependency(ws, edge_id, status="rejected", reason=why)
            after = {**row.to_dict(), "status": "rejected", "reason": why}
            hid = self._history(ws, row.dependent_task_id, "REMOVE_DEPENDENCY", row.to_dict(), after, actor, why)
            return self._save(ws, "remove", idempotency_key, {"edge_id": edge_id, "status": "rejected", "applied": True, "reason": why, "history_event_id": hid})

    # ------------------------------------------------------------------ reconsider a held / proposed edge
    def reconsider(self, ws: str, edge_id: str, actor: str, *, idempotency_key: Optional[str] = None) -> dict[str, Any]:
        with self.store.transaction():
            prior = self._replay(ws, "reconsider", idempotency_key)
            if prior:
                return prior
            row = self._row(ws, edge_id)
            if row is None:
                raise ReconciliationError("NOT_FOUND", f"no dependency edge {edge_id}")
            if row.status == "accepted":
                return self._save(ws, "reconsider", idempotency_key, {"edge_id": edge_id, "status": "accepted", "applied": False, "code": "DUPLICATE"})
            graph = WorkflowGraph.from_store(self.store, ws)
            decision = self.validator(graph, row.prerequisite_task_id, row.dependent_task_id)
            status = "accepted" if decision.accepted else "rejected"
            self.store.update_dependency(ws, edge_id, status=status, reason=decision.reason, source_kind="human")
            after = {**row.to_dict(), "status": status, "reason": decision.reason}
            hid = self._history(ws, row.dependent_task_id, "RECONSIDER_DEPENDENCY", row.to_dict(), after, actor, decision.reason)
            return self._save(ws, "reconsider", idempotency_key, {"edge_id": edge_id, "status": status, "applied": True, "code": decision.code,
                                                                   "reason": decision.reason, "cycle_path": decision.cycle_path,
                                                                   "warnings": decision.warnings, "history_event_id": hid})
