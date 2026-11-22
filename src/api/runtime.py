"""Application runtime: owns the single store, reconciler, registry and services. One process, one workspace, one lock."""

from __future__ import annotations

import threading
from typing import Any, Optional

from src.api.config import WORKSPACE, Settings
from src.api.services.chat_store import AppStore
from src.api.services.graph import GraphService
from src.api.services.model_registry import ModelRegistry
from src.api.services.pipeline import PipelineService
from src.graph.graph_constraints import make_dependency_validator
from src.reconciliation.reconciler import Reconciler
from src.reconciliation.store import HISTORY_TRIGGERS, TaskStore, system_clock


class AppRuntime:
    def __init__(self, settings: Settings, registry: Optional[ModelRegistry] = None):
        self.settings = settings
        self.lock = threading.RLock()
        self.registry = registry or ModelRegistry(settings)
        self.store = TaskStore(settings.db_path, clock=settings.audit_clock)
        self.app = AppStore(self.store, settings.default_timezone)
        self.reconciler = Reconciler(self.store, dependency_validator=make_dependency_validator())
        self.pipeline = PipelineService(self)
        self.graph = GraphService(self)
        from src.api.services.scenarios import ScenarioService      # late import: scenarios use the services above
        self.scenarios = ScenarioService(self)

    def start(self) -> None:
        self.registry.load()

    # ------------------------------------------------------------------ reset
    def reset_workspace(self) -> None:
        """Wipe conversation, tasks, proposals, history and dependencies; keep participants and settings.

        History is append-only (SQLite triggers). A reset is the one deliberate exception: the triggers are dropped, the rows
        deleted and the triggers re-created inside ONE transaction, so immutability is back in force before anything else runs.
        """
        with self.lock, self.store.transaction():
            c = self.store.conn
            c.execute("DROP TRIGGER IF EXISTS history_no_delete")
            c.execute("DROP TRIGGER IF EXISTS history_no_update")
            for table in ("history", "tasks", "proposals", "dependencies", "processed_messages", "idempotency_keys", "counters", "messages", "analyses"):
                c.execute(f"DELETE FROM {table}")
            c.execute("UPDATE scenario_state SET scenario_id=NULL, step=0, transcript='[]', snapshots='{}' WHERE id=1")
            c.execute("DELETE FROM sqlite_sequence WHERE name IN ('history', 'messages')")      # ids restart: a replay is exactly reproducible
            for stmt in HISTORY_TRIGGERS:
                c.execute(stmt)
            self.store.clock = self.settings.audit_clock or system_clock
