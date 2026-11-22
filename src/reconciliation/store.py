"""SQLite task store (Phase 5): stable ids, versioned updates, append-only history, idempotency.

All mutating primitives must run inside ``with store.transaction():`` so a failed change writes
nothing. History rows are immutable (SQLite triggers reject UPDATE/DELETE). The only clock read
in this package is the injectable audit clock; it is never used to interpret message dates.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Mapping, Optional, Sequence

from src.reconciliation.models import (DependencyEdge, HistoryEvent, ProposedOperation, SCHEMA_VERSION, StaleVersion,
                                       Task)

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS counters (workspace_id TEXT, name TEXT, value INTEGER, PRIMARY KEY (workspace_id, name));
CREATE TABLE IF NOT EXISTS tasks (
  workspace_id TEXT NOT NULL, task_id TEXT NOT NULL, thread_id TEXT NOT NULL, title TEXT NOT NULL, aliases TEXT NOT NULL,
  owner_id TEXT, due TEXT, scheduled TEXT, status TEXT NOT NULL, source_message_id TEXT, evidence_text TEXT,
  version INTEGER NOT NULL, created_by TEXT, created_at TEXT, last_touched_message_id TEXT, last_touched_seq INTEGER NOT NULL DEFAULT 0,
  provenance TEXT, pending_changes TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (workspace_id, task_id));
CREATE TABLE IF NOT EXISTS proposals (
  workspace_id TEXT NOT NULL, proposal_id TEXT NOT NULL, message_id TEXT NOT NULL, operation TEXT NOT NULL, task_id TEXT,
  field TEXT, before TEXT, after TEXT, base_version INTEGER, payload TEXT, evidence TEXT, match TEXT, flags TEXT,
  needs_confirmation_from TEXT, status TEXT NOT NULL, source_kind TEXT, proposer_id TEXT, note TEXT, created_at TEXT,
  resolved_at TEXT, resolved_by TEXT, resolution_note TEXT, PRIMARY KEY (workspace_id, proposal_id));
CREATE TABLE IF NOT EXISTS history (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL, task_id TEXT NOT NULL, proposal_id TEXT,
  message_id TEXT, actor TEXT, operation TEXT NOT NULL, field TEXT NOT NULL, before TEXT, after TEXT,
  timestamp TEXT NOT NULL, source_kind TEXT NOT NULL, note TEXT);
CREATE TRIGGER IF NOT EXISTS history_no_update BEFORE UPDATE ON history
  BEGIN SELECT RAISE(ABORT, 'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS history_no_delete BEFORE DELETE ON history
  BEGIN SELECT RAISE(ABORT, 'history is append-only'); END;
CREATE TABLE IF NOT EXISTS dependencies (
  workspace_id TEXT NOT NULL, edge_id TEXT NOT NULL, dependent_task_id TEXT NOT NULL, prerequisite_task_id TEXT NOT NULL,
  status TEXT NOT NULL, evidence TEXT, source_message_id TEXT, source_kind TEXT, score REAL, reason TEXT, proposal_id TEXT,
  PRIMARY KEY (workspace_id, edge_id));
CREATE TABLE IF NOT EXISTS processed_messages (
  workspace_id TEXT NOT NULL, message_id TEXT NOT NULL, thread_id TEXT NOT NULL, text_hash TEXT NOT NULL, seq INTEGER NOT NULL,
  PRIMARY KEY (workspace_id, message_id));
CREATE TABLE IF NOT EXISTS idempotency_keys (
  workspace_id TEXT NOT NULL, key TEXT NOT NULL, result TEXT, PRIMARY KEY (workspace_id, key));
"""

# The two statements that make history append-only. Exposed so a deliberate workspace reset can drop and re-create them atomically.
HISTORY_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS history_no_update BEFORE UPDATE ON history BEGIN SELECT RAISE(ABORT, 'history is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS history_no_delete BEFORE DELETE ON history BEGIN SELECT RAISE(ABORT, 'history is append-only'); END",
)


def _j(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)


def _l(v: Optional[str]) -> Any:
    return None if v is None else json.loads(v)


def system_clock() -> str:
    """Audit clock (UTC). Used for history/proposal timestamps ONLY, never for interpreting message dates."""
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    def __init__(self, path: str = ":memory:", clock: Optional[Callable[[], str]] = None):
        self.path = path
        self.clock = clock or system_clock
        self.conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.execute("INSERT OR IGNORE INTO schema_meta VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        self._lock = threading.RLock()
        self._depth = 0

    # ------------------------------------------------------------------ transactions
    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            outer = self._depth == 0
            if outer:
                self.conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield
            except BaseException:
                self._depth -= 1
                if outer:
                    self.conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outer:
                    self.conn.execute("COMMIT")

    def close(self) -> None:
        self.conn.close()

    def now(self) -> str:
        return self.clock()

    # ------------------------------------------------------------------ tasks
    def next_task_id(self, ws: str) -> str:
        cur = self.conn.execute("SELECT value FROM counters WHERE workspace_id=? AND name='task'", (ws,)).fetchone()
        n = (cur["value"] if cur else 0) + 1
        self.conn.execute("INSERT OR REPLACE INTO counters VALUES (?, 'task', ?)", (ws, n))
        return f"T-{n}"

    @staticmethod
    def _task(row: sqlite3.Row) -> Task:
        return Task(task_id=row["task_id"], workspace_id=row["workspace_id"], thread_id=row["thread_id"], title=row["title"],
                    aliases=_l(row["aliases"]) or [], owner_id=row["owner_id"], due=_l(row["due"]), scheduled=_l(row["scheduled"]),
                    status=row["status"], source_message_id=row["source_message_id"], evidence_text=row["evidence_text"] or "",
                    version=row["version"], created_by=row["created_by"], created_at=row["created_at"],
                    last_touched_message_id=row["last_touched_message_id"], last_touched_seq=row["last_touched_seq"],
                    provenance=_l(row["provenance"]) or {}, pending_changes=_l(row["pending_changes"]) or {})

    def insert_task(self, t: Task) -> None:
        self.conn.execute(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (t.workspace_id, t.task_id, t.thread_id, t.title, _j(t.aliases), t.owner_id, _j(t.due) if t.due is not None else None,
             _j(t.scheduled) if t.scheduled is not None else None, t.status, t.source_message_id, t.evidence_text, t.version,
             t.created_by, t.created_at, t.last_touched_message_id, t.last_touched_seq, _j(t.provenance), _j(t.pending_changes)))

    def get_task(self, ws: str, task_id: str) -> Optional[Task]:
        row = self.conn.execute("SELECT * FROM tasks WHERE workspace_id=? AND task_id=?", (ws, task_id)).fetchone()
        return self._task(row) if row else None

    def list_tasks(self, ws: str, thread_id: Optional[str] = None, status: Optional[Sequence[str]] = None,
                   owner_id: Optional[str] = None) -> list[Task]:
        q, args = "SELECT * FROM tasks WHERE workspace_id=?", [ws]
        if thread_id is not None:
            q += " AND thread_id=?"; args.append(thread_id)
        if owner_id is not None:
            q += " AND owner_id=?"; args.append(owner_id)
        if status:
            q += f" AND status IN ({','.join('?' * len(status))})"; args += list(status)
        q += " ORDER BY CAST(SUBSTR(task_id, 3) AS INTEGER)"
        return [self._task(r) for r in self.conn.execute(q, args)]

    _COLUMNS = {"title": "title", "aliases": "aliases", "owner_id": "owner_id", "due": "due", "scheduled": "scheduled",
                "status": "status", "pending_changes": "pending_changes", "evidence_text": "evidence_text"}

    def update_task(self, ws: str, task_id: str, expected_version: int, fields: Mapping[str, Any]) -> int:
        """Version-checked update. Returns the new version. Raises StaleVersion (nothing written)."""
        row = self.conn.execute("SELECT version FROM tasks WHERE workspace_id=? AND task_id=?", (ws, task_id)).fetchone()
        if row is None:
            raise KeyError(f"unknown task {task_id}")
        if row["version"] != expected_version:
            raise StaleVersion(task_id, expected_version, row["version"])
        sets, args = ["version=version+1"], []
        for k, v in fields.items():
            if k not in self._COLUMNS:
                raise KeyError(f"field not updatable: {k}")
            sets.append(f"{self._COLUMNS[k]}=?")
            args.append(_j(v) if k in ("aliases", "due", "scheduled", "pending_changes") and v is not None else v)
        self.conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE workspace_id=? AND task_id=?", (*args, ws, task_id))
        return expected_version + 1

    def touch_task(self, ws: str, task_id: str, message_id: str, seq: int) -> None:
        """Retrieval metadata only (not versioned, not history): which message last mentioned the task."""
        self.conn.execute("UPDATE tasks SET last_touched_message_id=?, last_touched_seq=? WHERE workspace_id=? AND task_id=?",
                          (message_id, seq, ws, task_id))

    # ------------------------------------------------------------------ proposals
    def insert_proposal(self, p: ProposedOperation) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO proposals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (p.workspace_id, p.proposal_id, p.message_id, p.operation, p.task_id, p.field, _j(p.before), _j(p.after), p.base_version,
             _j(p.payload), _j(p.evidence), _j(p.match), _j(p.flags), _j(p.needs_confirmation_from), p.status, p.source_kind,
             p.proposer_id, p.note, p.created_at, p.resolved_at, p.resolved_by, p.resolution_note))
        return cur.rowcount == 1

    @staticmethod
    def _proposal(r: sqlite3.Row) -> ProposedOperation:
        return ProposedOperation(
            proposal_id=r["proposal_id"], workspace_id=r["workspace_id"], message_id=r["message_id"], operation=r["operation"],
            task_id=r["task_id"], field=r["field"], before=_l(r["before"]), after=_l(r["after"]), base_version=r["base_version"],
            payload=_l(r["payload"]) or {}, evidence=_l(r["evidence"]) or {}, match=_l(r["match"]) or {}, flags=_l(r["flags"]) or [],
            needs_confirmation_from=_l(r["needs_confirmation_from"]) or [], status=r["status"], source_kind=r["source_kind"],
            proposer_id=r["proposer_id"], note=r["note"] or "", created_at=r["created_at"], resolved_at=r["resolved_at"],
            resolved_by=r["resolved_by"], resolution_note=r["resolution_note"])

    def get_proposal(self, ws: str, proposal_id: str) -> Optional[ProposedOperation]:
        r = self.conn.execute("SELECT * FROM proposals WHERE workspace_id=? AND proposal_id=?", (ws, proposal_id)).fetchone()
        return self._proposal(r) if r else None

    def list_proposals(self, ws: str, *, status: Optional[str] = None, message_id: Optional[str] = None,
                       task_id: Optional[str] = None, operation: Optional[str] = None) -> list[ProposedOperation]:
        q, args = "SELECT * FROM proposals WHERE workspace_id=?", [ws]
        for col, val in (("status", status), ("message_id", message_id), ("task_id", task_id), ("operation", operation)):
            if val is not None:
                q += f" AND {col}=?"; args.append(val)
        q += " ORDER BY rowid"
        return [self._proposal(r) for r in self.conn.execute(q, args)]

    def update_proposal(self, ws: str, proposal_id: str, **fields: Any) -> None:
        allowed = {"status", "resolved_at", "resolved_by", "resolution_note", "task_id", "base_version", "note", "payload", "flags", "after"}
        sets, args = [], []
        for k, v in fields.items():
            if k not in allowed:
                raise KeyError(k)
            sets.append(f"{k}=?")
            args.append(_j(v) if k in ("payload", "flags", "after") else v)
        self.conn.execute(f"UPDATE proposals SET {', '.join(sets)} WHERE workspace_id=? AND proposal_id=?", (*args, ws, proposal_id))

    # ------------------------------------------------------------------ history (append-only)
    def append_history(self, ws: str, task_id: str, *, operation: str, field: str, before: Any, after: Any, actor: Optional[str],
                       source_kind: str, proposal_id: Optional[str] = None, message_id: Optional[str] = None, note: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO history (workspace_id, task_id, proposal_id, message_id, actor, operation, field, before, after, timestamp,"
            " source_kind, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (ws, task_id, proposal_id, message_id, actor, operation, field, _j(before), _j(after), self.now(), source_kind, note))
        return cur.lastrowid

    def history_for(self, ws: str, task_id: str) -> list[HistoryEvent]:
        rows = self.conn.execute("SELECT * FROM history WHERE workspace_id=? AND task_id=? ORDER BY event_id", (ws, task_id))
        return [HistoryEvent(r["event_id"], r["workspace_id"], r["task_id"], r["proposal_id"], r["message_id"], r["actor"],
                             r["operation"], r["field"], _l(r["before"]), _l(r["after"]), r["timestamp"], r["source_kind"], r["note"] or "")
                for r in rows]

    @staticmethod
    def reconstruct(events: Sequence[HistoryEvent]) -> dict[str, Any]:
        """Rebuild task state purely from history (used to prove history is complete and chain-consistent)."""
        state: dict[str, Any] = {}
        for e in events:
            if e.field == "__create__":
                state = json.loads(json.dumps(e.after))
                state.setdefault("pending_changes", {})
                continue
            if e.field.startswith("pending_"):
                pending = dict(state.get("pending_changes") or {})
                key = e.field[len("pending_"):]
                if e.after is None:
                    pending.pop(key, None)
                else:
                    pending[key] = e.after
                state["pending_changes"] = pending
            else:
                state[e.field] = e.after
        return state

    # ------------------------------------------------------------------ dependencies
    def insert_dependency(self, d: DependencyEdge) -> bool:
        cur = self.conn.execute("INSERT OR IGNORE INTO dependencies VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                (d.workspace_id, d.edge_id, d.dependent_task_id, d.prerequisite_task_id, d.status, d.evidence,
                                 d.source_message_id, d.source_kind, d.score, d.reason, d.proposal_id))
        return cur.rowcount == 1

    def list_dependencies(self, ws: str, status: Optional[str] = None) -> list[DependencyEdge]:
        q, args = "SELECT * FROM dependencies WHERE workspace_id=?", [ws]
        if status:
            q += " AND status=?"; args.append(status)
        return [DependencyEdge(r["edge_id"], r["workspace_id"], r["dependent_task_id"], r["prerequisite_task_id"], r["status"],
                               r["evidence"] or "", r["source_message_id"], r["source_kind"], r["score"], r["reason"] or "",
                               r["proposal_id"]) for r in self.conn.execute(q + " ORDER BY rowid", args)]

    def update_dependency(self, ws: str, edge_id: str, **fields: Any) -> None:
        allowed = {"status", "reason", "evidence", "source_message_id", "source_kind", "score", "proposal_id"}
        bad = set(fields) - allowed
        if bad:
            raise KeyError(", ".join(sorted(bad)))
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            self.conn.execute(f"UPDATE dependencies SET {sets} WHERE workspace_id=? AND edge_id=?", (*fields.values(), ws, edge_id))

    def set_dependency_status(self, ws: str, edge_id: str, status: str, reason: str = "") -> None:
        self.conn.execute("UPDATE dependencies SET status=?, reason=? WHERE workspace_id=? AND edge_id=?", (status, reason, ws, edge_id))

    # ------------------------------------------------------------------ messages & idempotency
    def get_processed(self, ws: str, message_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM processed_messages WHERE workspace_id=? AND message_id=?", (ws, message_id)).fetchone()

    def mark_processed(self, ws: str, message_id: str, thread_id: str, text_hash: str) -> int:
        """Record a message; returns its 1-based ordinal within its thread."""
        n = self.conn.execute("SELECT COUNT(*) AS n FROM processed_messages WHERE workspace_id=? AND thread_id=?", (ws, thread_id)).fetchone()["n"]
        self.conn.execute("INSERT INTO processed_messages VALUES (?,?,?,?,?)", (ws, message_id, thread_id, text_hash, n + 1))
        return n + 1

    def current_seq(self, ws: str, thread_id: str) -> int:
        return self.conn.execute("SELECT COUNT(*) AS n FROM processed_messages WHERE workspace_id=? AND thread_id=?", (ws, thread_id)).fetchone()["n"]

    def get_idempotent(self, ws: str, key: str) -> Optional[Any]:
        r = self.conn.execute("SELECT result FROM idempotency_keys WHERE workspace_id=? AND key=?", (ws, key)).fetchone()
        return None if r is None else _l(r["result"])

    def save_idempotent(self, ws: str, key: str, result: Any) -> None:
        self.conn.execute("INSERT OR REPLACE INTO idempotency_keys VALUES (?,?,?)", (ws, key, _j(result)))

    # ------------------------------------------------------------------ counts (for invariant tests)
    def counts(self, ws: str) -> dict[str, int]:
        out = {}
        for t in ("tasks", "proposals", "history", "dependencies", "processed_messages"):
            out[t] = self.conn.execute(f"SELECT COUNT(*) AS n FROM {t} WHERE workspace_id=?", (ws,)).fetchone()["n"]
        return out
