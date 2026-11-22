"""Scenario playback (Phase 7): deterministic load / step / previous / play / reset.

A scenario script supplies the messages and the SCRIPTED extraction (spans + links). Reconciliation, review, history and the graph are
the real code paths. Review actions taken by the presenter are recorded in a transcript so 'previous step' can rebuild the exact state:
reset, replay steps 1..n-1 and re-apply the recorded actions. History timestamps use a deterministic scenario clock.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from src.api.config import WORKSPACE
from src.reconciliation.models import ReconciliationError, StaleVersion

SIMULATED_REVIEWER = "simulated-reviewer"


class ScenarioClock:
    def __init__(self, base: str):
        self.base = datetime.fromisoformat(base)
        self.n = 0

    def now(self) -> str:
        self.n += 1
        return (self.base + timedelta(seconds=self.n)).isoformat()


class ScenarioService:
    def __init__(self, runtime: Any):
        self.rt = runtime
        self.dir: Path = runtime.settings.scenario_dir
        self._fixtures: dict[str, dict[str, Any]] = {}
        for f in sorted(self.dir.glob("*.json")):
            d = json.loads(f.read_text())
            self._fixtures[d["id"]] = d

    # ------------------------------------------------------------------ queries
    def list(self) -> list[dict[str, Any]]:
        return [{"id": d["id"], "title": d["title"], "description": d["description"], "steps": len(d["messages"]), "timezone": d.get("timezone")}
                for d in self._fixtures.values()]

    def fixture(self, sid: str) -> dict[str, Any]:
        if sid not in self._fixtures:
            raise KeyError(sid)
        return self._fixtures[sid]

    def state(self) -> dict[str, Any]:
        st = self.rt.app.scenario_state()
        out = {"scenario_id": st["scenario_id"], "step": st["step"], "total": None, "title": None, "next_message": None, "label": "SCRIPTED expectations, not model predictions"}
        if st["scenario_id"]:
            fx = self.fixture(st["scenario_id"])
            out.update(total=len(fx["messages"]), title=fx["title"])
            if st["step"] < len(fx["messages"]):
                nm = fx["messages"][st["step"]]
                out["next_message"] = {"sender": nm["sender"], "text": nm["text"]}
        return out

    # ------------------------------------------------------------------ helpers
    def _use_clock(self, fx: dict[str, Any]) -> None:
        self.rt.store.clock = ScenarioClock(fx["messages"][0]["created_at"]).now

    def _process_step(self, fx: dict[str, Any], k: int) -> dict[str, Any]:
        """Persist and analyse message k (1-based) of the script. Deterministic ids and timestamps."""
        rt = self.rt
        m = fx["messages"][k - 1]
        mid = f"{fx['id']}-{k}"
        rt.app.add_message({"id": mid, "sender_id": m["sender"], "recipient_ids": m.get("recipients", []), "text": m["text"], "created_at": m["created_at"],
                            "mode": "scripted", "status": "received", "scenario_id": fx["id"], "scenario_step": k, "thread_id": "default",
                            "in_reply_to": m.get("in_reply_to"), "expected": m.get("expected")})
        rt.app.update_message(mid, status="received")
        return rt.pipeline.process(rt.app.get_message(mid), scripted=m["scripted"])

    def _apply_action(self, a: dict[str, Any]) -> None:
        """Re-apply one recorded presenter action during a replay."""
        rt, t = self.rt, a["type"]
        try:
            if t == "accept":
                rt.reconciler.accept(WORKSPACE, a["proposal_id"], a["actor"], edits=a.get("edits"), expected_version=a.get("expected_version"))
            elif t == "dismiss":
                rt.reconciler.dismiss(WORKSPACE, a["proposal_id"], a["actor"], a.get("reason", ""))
            elif t == "manual_edit":
                task = rt.store.get_task(WORKSPACE, a["task_id"])
                rt.reconciler.manual_edit(WORKSPACE, a["task_id"], a["actor"], task.version, a["changes"])
            elif t == "add_dependency":
                rt.graph.editor().add_dependency(WORKSPACE, a["prerequisite"], a["dependent"], a["actor"], evidence=a.get("evidence", ""))
            elif t == "remove_dependency":
                rt.graph.editor().remove_dependency(WORKSPACE, a["edge_id"], a["actor"], a.get("reason", ""))
            elif t == "reconsider":
                rt.graph.editor().reconsider(WORKSPACE, a["edge_id"], a["actor"])
        except (ReconciliationError, StaleVersion):
            pass        # a replayed action that the original run also rejected has no effect; the state stays identical

    def _simulated_review(self, k: int, transcript: list[dict[str, Any]]) -> None:
        """'Play all' reviewer: accepts every reviewable proposal of step k, in creation order, as 'simulated-reviewer'."""
        rt = self.rt
        for p in rt.store.list_proposals(WORKSPACE, status="pending", message_id=f"{self._current_id()}-{k}"):
            if p.operation == "NO_ACTION":
                continue
            try:
                rt.reconciler.accept(WORKSPACE, p.proposal_id, SIMULATED_REVIEWER)
                transcript.append({"step": k, "type": "accept", "proposal_id": p.proposal_id, "actor": SIMULATED_REVIEWER})
            except (ReconciliationError, StaleVersion):
                continue

    def _current_id(self) -> str:
        return self.rt.app.scenario_state()["scenario_id"]

    def snapshot(self, step: Optional[int] = None) -> None:
        st = self.rt.app.scenario_state()
        if not st["scenario_id"]:
            return
        snaps = st["snapshots"]
        snaps[str(step if step is not None else st["step"])] = self.rt.graph.frontend()
        self.rt.app.set_scenario_state(st["scenario_id"], st["step"], st["transcript"], snaps)

    def record_action(self, action: dict[str, Any]) -> None:
        """Called by the API after a successful review / edit while a scenario is active."""
        st = self.rt.app.scenario_state()
        if not st["scenario_id"]:
            return
        transcript = st["transcript"] + [{"step": st["step"], **action}]
        self.rt.app.set_scenario_state(st["scenario_id"], st["step"], transcript, st["snapshots"])
        self.snapshot()

    # ------------------------------------------------------------------ operations
    def load(self, sid: str) -> dict[str, Any]:
        fx = self.fixture(sid)
        with self.rt.lock:
            self.rt.reset_workspace()
            self._use_clock(fx)
            self.rt.app.set_scenario_state(sid, 0, [], {"0": self.rt.graph.frontend()})
            if fx.get("timezone"):
                self.rt.app.set_settings({"timezone": fx["timezone"]})
        return self.state()

    def step(self) -> dict[str, Any]:
        with self.rt.lock:
            st = self.rt.app.scenario_state()
            if not st["scenario_id"]:
                raise ReconciliationError("NO_SCENARIO", "load a scenario first")
            fx = self.fixture(st["scenario_id"])
            if st["step"] >= len(fx["messages"]):
                raise ReconciliationError("SCENARIO_FINISHED", "no more messages in this scenario")
            k = st["step"] + 1
            self.snapshot()                                    # state at the end of the previous step, including its review actions
            self.rt.app.set_scenario_state(st["scenario_id"], k, st["transcript"], st["snapshots"])
            self._process_step(fx, k)
            self.snapshot(k)
        return self.state()

    def reset(self) -> dict[str, Any]:
        st = self.rt.app.scenario_state()
        return self.load(st["scenario_id"]) if st["scenario_id"] else self.state()

    def previous(self) -> dict[str, Any]:
        with self.rt.lock:
            st = self.rt.app.scenario_state()
            if not st["scenario_id"] or st["step"] == 0:
                return self.state()
            self._replay(st["scenario_id"], st["step"] - 1, st["transcript"])
        return self.state()

    def _replay(self, sid: str, upto: int, transcript: list[dict[str, Any]]) -> None:
        fx = self.fixture(sid)
        kept = [a for a in transcript if a["step"] <= upto]
        self.rt.reset_workspace()
        self._use_clock(fx)
        self.rt.app.set_scenario_state(sid, 0, kept, {"0": self.rt.graph.frontend()})
        snaps: dict[str, Any] = {"0": self.rt.graph.frontend()}
        for k in range(1, upto + 1):
            self.rt.app.set_scenario_state(sid, k, kept, snaps)
            self._process_step(fx, k)
            for a in [x for x in kept if x["step"] == k]:
                self._apply_action(a)
            snaps[str(k)] = self.rt.graph.frontend()
        self.rt.app.set_scenario_state(sid, upto, kept, snaps)
        if fx.get("timezone"):
            self.rt.app.set_settings({"timezone": fx["timezone"]})

    def play(self) -> dict[str, Any]:
        """Run every remaining step with a clearly labelled simulated reviewer."""
        with self.rt.lock:
            st = self.rt.app.scenario_state()
            if not st["scenario_id"]:
                raise ReconciliationError("NO_SCENARIO", "load a scenario first")
            fx = self.fixture(st["scenario_id"])
            transcript = list(st["transcript"])
            snaps = dict(st["snapshots"])
            for k in range(st["step"] + 1, len(fx["messages"]) + 1):
                self.rt.app.set_scenario_state(st["scenario_id"], k, transcript, snaps)
                self._process_step(fx, k)
                self._simulated_review(k, transcript)
                snaps[str(k)] = self.rt.graph.frontend()
                self.rt.app.set_scenario_state(st["scenario_id"], k, transcript, snaps)
        return self.state()
