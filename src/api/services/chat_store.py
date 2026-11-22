"""App-level tables (Phase 7) living in the SAME SQLite file as the Phase 5 task store.

participants, messages, analyses, scenario_state, settings. Task/proposal/history/dependency tables are Phase 5's and untouched.
"""

from __future__ import annotations

import json
from typing import Any, Optional, Sequence

from src.reconciliation.store import TaskStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS participants (id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT, color TEXT NOT NULL, sort INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, sender_id TEXT NOT NULL, recipient_ids TEXT NOT NULL, text TEXT NOT NULL,
  created_at TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL, error TEXT, scenario_id TEXT, scenario_step INTEGER,
  thread_id TEXT NOT NULL, in_reply_to TEXT, expected TEXT);
CREATE TABLE IF NOT EXISTS analyses (
  run_id TEXT PRIMARY KEY, message_id TEXT NOT NULL, mode TEXT NOT NULL, entities TEXT, relations TEXT, no_link TEXT, candidates TEXT,
  proposal_ids TEXT, provenance TEXT, model_versions TEXT, error TEXT, duration_ms REAL, audit_at TEXT);
CREATE TABLE IF NOT EXISTS scenario_state (id INTEGER PRIMARY KEY CHECK (id = 1), scenario_id TEXT, step INTEGER NOT NULL, transcript TEXT NOT NULL, snapshots TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT);
"""

DEFAULT_PARTICIPANTS = [
    {"id": "riya", "name": "Riya", "role": "Project Lead", "color": "#6c5ce7"},
    {"id": "anushree", "name": "Anushree", "role": "Data Engineer", "color": "#00a38c"},
    {"id": "bianca", "name": "Bianca", "role": "ML Engineer", "color": "#e17055"},
]
DEFAULT_SETTINGS = {"timezone": "UTC", "allow_rule_fallback": False, "rule_dependency_linker": True, "pipeline_preset": "hybrid", "refine_overrides": {}}


def _j(v: Any) -> Optional[str]:
    return None if v is None else json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)


def _l(v: Optional[str]) -> Any:
    return None if v is None else json.loads(v)


class AppStore:
    def __init__(self, store: TaskStore, default_timezone: str = "UTC"):
        self.store = store
        self.conn = store.conn
        self.conn.executescript(SCHEMA)
        if "refinement" not in {r["name"] for r in self.conn.execute("PRAGMA table_info(analyses)")}:
            self.conn.execute("ALTER TABLE analyses ADD COLUMN refinement TEXT")          # Phase 7.5: raw vs refined output and the rules that ran
        with store.transaction():
            if not self.conn.execute("SELECT 1 FROM participants LIMIT 1").fetchone():
                for i, p in enumerate(DEFAULT_PARTICIPANTS):
                    self.conn.execute("INSERT INTO participants VALUES (?,?,?,?,?)", (p["id"], p["name"], p["role"], p["color"], i))
            if not self.conn.execute("SELECT 1 FROM scenario_state").fetchone():
                self.conn.execute("INSERT INTO scenario_state VALUES (1, NULL, 0, '[]', '{}')")
            for k, v in {**DEFAULT_SETTINGS, "timezone": default_timezone}.items():
                self.conn.execute("INSERT OR IGNORE INTO app_settings VALUES (?, ?)", (k, _j(v)))

    # ---------------------------------------------------------------- participants
    def participants(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute("SELECT id, name, role, color FROM participants ORDER BY sort")]

    def upsert_participant(self, p: dict[str, Any]) -> dict[str, Any]:
        with self.store.transaction():
            row = self.conn.execute("SELECT sort FROM participants WHERE id=?", (p["id"],)).fetchone()
            sort = row["sort"] if row else self.conn.execute("SELECT COALESCE(MAX(sort),-1)+1 AS n FROM participants").fetchone()["n"]
            self.conn.execute("INSERT OR REPLACE INTO participants VALUES (?,?,?,?,?)", (p["id"], p["name"], p.get("role"), p["color"], sort))
        return {k: p.get(k) for k in ("id", "name", "role", "color")}

    # ---------------------------------------------------------------- settings
    def settings(self) -> dict[str, Any]:
        return {r["key"]: _l(r["value"]) for r in self.conn.execute("SELECT key, value FROM app_settings")}

    def set_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        with self.store.transaction():
            for k, v in values.items():
                self.conn.execute("INSERT OR REPLACE INTO app_settings VALUES (?,?)", (k, _j(v)))
        return self.settings()

    # ---------------------------------------------------------------- messages
    def next_message_id(self) -> str:
        n = self.conn.execute("SELECT COALESCE(MAX(seq),0)+1 AS n FROM messages").fetchone()["n"]
        return f"m{n}"

    @staticmethod
    def _msg(r) -> dict[str, Any]:
        d = dict(r)
        d["recipient_ids"] = _l(d["recipient_ids"]) or []
        d["expected"] = _l(d.get("expected"))
        d.pop("seq", None)
        return d

    def add_message(self, m: dict[str, Any]) -> dict[str, Any]:
        with self.store.transaction():
            self.conn.execute(
                "INSERT INTO messages (id, sender_id, recipient_ids, text, created_at, mode, status, error, scenario_id, scenario_step, thread_id, in_reply_to, expected)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (m["id"], m["sender_id"], _j(m.get("recipient_ids", [])), m["text"], m["created_at"], m["mode"], m.get("status", "received"), m.get("error"),
                 m.get("scenario_id"), m.get("scenario_step"), m.get("thread_id", "default"), m.get("in_reply_to"), _j(m.get("expected"))))
        return self.get_message(m["id"])

    def get_message(self, mid: str) -> Optional[dict[str, Any]]:
        r = self.conn.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
        return self._msg(r) if r else None

    def list_messages(self) -> list[dict[str, Any]]:
        return [self._msg(r) for r in self.conn.execute("SELECT * FROM messages ORDER BY seq")]

    def update_message(self, mid: str, **fields: Any) -> None:
        allowed = {"status", "error"}
        with self.store.transaction():
            for k, v in fields.items():
                if k not in allowed:
                    raise KeyError(k)
                self.conn.execute(f"UPDATE messages SET {k}=? WHERE id=?", (v, mid))

    # ---------------------------------------------------------------- analyses
    def save_analysis(self, a: dict[str, Any]) -> None:
        with self.store.transaction():
            self.conn.execute("INSERT OR REPLACE INTO analyses (run_id, message_id, mode, entities, relations, no_link, candidates, proposal_ids, provenance, model_versions, error, duration_ms, audit_at, refinement) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (a["run_id"], a["message_id"], a["mode"], _j(a.get("entities")), _j(a.get("relations")), _j(a.get("no_link")), _j(a.get("candidates")),
                               _j(a.get("proposal_ids")), _j(a.get("provenance")), _j(a.get("model_versions")), a.get("error"), a.get("duration_ms"), a.get("audit_at"), _j(a.get("refinement"))))

    def latest_analysis(self, mid: str) -> Optional[dict[str, Any]]:
        r = self.conn.execute("SELECT * FROM analyses WHERE message_id=? ORDER BY rowid DESC LIMIT 1", (mid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        for k in ("entities", "relations", "no_link", "candidates", "proposal_ids", "provenance", "model_versions", "refinement"):
            d[k] = _l(d.get(k))
        return d

    # ---------------------------------------------------------------- scenario state
    def scenario_state(self) -> dict[str, Any]:
        r = self.conn.execute("SELECT * FROM scenario_state WHERE id=1").fetchone()
        return {"scenario_id": r["scenario_id"], "step": r["step"], "transcript": _l(r["transcript"]), "snapshots": _l(r["snapshots"])}

    def set_scenario_state(self, scenario_id: Optional[str], step: int, transcript: Sequence[Any], snapshots: dict[str, Any]) -> None:
        with self.store.transaction():
            self.conn.execute("UPDATE scenario_state SET scenario_id=?, step=?, transcript=?, snapshots=? WHERE id=1",
                              (scenario_id, step, _j(list(transcript)), _j(snapshots)))
