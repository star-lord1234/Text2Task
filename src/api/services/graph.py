"""Graph service (Phase 7): thin wrappers over the Phase 6 snapshot, editor and what-if preview."""

from __future__ import annotations

from typing import Any, Optional

from src.api.config import WORKSPACE
from src.graph.graph_builder import WorkflowGraph
from src.graph.graph_editor import GraphEditor
from src.graph.serialize import to_frontend
from src.graph.workflow_state import compute_states, impact_of


class GraphService:
    def __init__(self, runtime: Any):
        self.rt = runtime
        self._editor: Optional[GraphEditor] = None

    def editor(self) -> GraphEditor:
        if self._editor is None or self._editor.store is not self.rt.store:
            self._editor = GraphEditor(self.rt.store)
        return self._editor

    def snapshot(self) -> WorkflowGraph:
        return WorkflowGraph.from_store(self.rt.store, WORKSPACE)

    def frontend(self) -> dict[str, Any]:
        g = self.snapshot()
        return to_frontend(g, compute_states(g))

    def states(self) -> dict[str, Any]:
        return {k: v.to_dict() for k, v in compute_states(self.snapshot()).items()}

    def impact(self, task_id: str, status: str) -> dict[str, Any]:
        g = self.snapshot()
        if task_id not in g.tasks:
            raise KeyError(task_id)
        return impact_of(g, task_id, status).to_dict()
