"""FastAPI application (Phase 7). A thin layer over the Phase 4-6 code: it adds persistence of the chat, orchestration, review endpoints
and honest capability reporting. It trains nothing and never invents a result: failed or unavailable analysis is stored and shown as such."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from src.api import schemas as S
from src.api.config import WORKSPACE, Settings
from src.api.runtime import AppRuntime
from src.api.services.evaluation import build_evaluation
from src.api.services.model_registry import ModelRegistry
from src.api.views import build_ctx, dep_counts, message_view, reviewers, suggestion_view, task_view
from src.reconciliation.models import ReconciliationError, StaleVersion
from src.temporal.normalize import normalize_temporal

ERR_STATUS = {"NOT_FOUND": 404, "ALREADY_RESOLVED": 409, "PREREQUISITE_PENDING": 409, "REFERENT_REQUIRED": 422, "UNRESOLVED_VALUE": 422,
              "ILLEGAL_TRANSITION": 409, "ALREADY_IN_STATE": 409, "MESSAGE_ID_REUSED": 409, "NO_PENDING_CHANGE": 409, "FIELD_NOT_EDITABLE": 422,
              "NO_SCENARIO": 409, "SCENARIO_FINISHED": 409, "UNSUPPORTED_OPERATION": 400, "NOT_YOUR_REVIEW": 403}


def _check_reviewer(rt: AppRuntime, p: Any, actor: str, *, dismissing: bool = False) -> None:
    """Only the person a suggestion lands on may accept it (see views.reviewers). The author of the message may also dismiss it,
    e.g. when the AI misread what they wrote. Nobody in particular affected -> anyone may decide."""
    ctx = build_ctx(rt)
    allowed = set(reviewers(p, ctx["tasks"], ctx["proposals"]))
    if dismissing and p.proposer_id:
        allowed.add(p.proposer_id)
    if allowed and actor not in allowed:
        names = ctx["names"]
        who = " or ".join(sorted(names.get(a, a) for a in allowed))
        raise ReconciliationError("NOT_YOUR_REVIEW", f"only {who} can {'dismiss' if dismissing else 'accept'} this suggestion")


def get_rt(request: Request) -> AppRuntime:
    return request.app.state.rt


def _err(code: str, message: str, status: int, details: Optional[dict] = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message, "details": details})


def _now_in(tz: str) -> str:
    try:
        return datetime.now(ZoneInfo(tz)).replace(microsecond=0).isoformat()
    except Exception:
        return datetime.now(ZoneInfo("UTC")).replace(microsecond=0).isoformat()


def _convert_edits(rt: AppRuntime, edits: Optional[dict[str, Any]], reference: Optional[str]) -> Optional[dict[str, Any]]:
    """UI edits use plain text for dates ('next Friday'); convert to Phase 4 TemporalValues using the message time as the anchor."""
    if not edits:
        return edits
    out = dict(edits)
    tz = rt.app.settings().get("timezone")
    cfg = rt.reconciler.phase4_config.get("temporal")
    for text_key, field in (("due_text", "due"), ("scheduled_text", "scheduled")):
        if text_key in out:
            raw = out.pop(text_key)
            out[field] = normalize_temporal(raw, reference_ts=reference, timezone=tz, config=cfg).to_dict() if raw else None
    if "owner_id" in out and out["owner_id"] is not None and out["owner_id"] not in {p["id"] for p in rt.app.participants()}:
        raise ReconciliationError("NOT_FOUND", f"unknown participant {out['owner_id']}")
    return out


def create_app(settings: Optional[Settings] = None, registry: Optional[ModelRegistry] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    rt = AppRuntime(settings, registry)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        rt.start()          # loads the checkpoints once; failures are recorded and reported by /api/system/capabilities
        yield

    app = FastAPI(title="Text2Task API", version="0.7.0", lifespan=lifespan,
                  description="Local, review-mode API over the Text2Task pipeline. Provisional SILVER models; no authentication (persona switching is not auth).")
    app.state.rt = rt
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(ReconciliationError)
    async def _reconciliation_error(_req: Request, e: ReconciliationError):
        return _err(e.code, str(e), ERR_STATUS.get(e.code, 400))

    @app.exception_handler(StaleVersion)
    async def _stale(_req: Request, e: StaleVersion):
        return _err("STALE_VERSION", "This task changed since you loaded it. Reload and try again.", 409,
                    {"task_id": e.task_id, "expected": e.expected, "actual": e.actual})

    api = APIRouter(prefix="/api")

    # ---------------------------------------------------------------- system
    @api.get("/system/capabilities")
    def capabilities(rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            return rt.registry.capabilities(rt.app.settings())

    @api.get("/evaluation")
    def evaluation(rt: AppRuntime = Depends(get_rt)):
        """Saved experiment results (read from results/, never computed or invented)."""
        return build_evaluation(rt.settings.results_dir)

    @api.get("/system/health")
    def health(rt: AppRuntime = Depends(get_rt)):
        return {"status": "ok", "time": time.time(), "workspace": WORKSPACE}

    # ---------------------------------------------------------------- workspace
    def _workspace(rt: AppRuntime) -> dict[str, Any]:
        ctx = build_ctx(rt)
        g = rt.graph.snapshot()
        from src.graph.workflow_state import compute_states
        states = {k: v.to_dict() for k, v in compute_states(g).items()}
        counts = dep_counts(g)
        tasks = [task_view(t, states.get(t.task_id), counts) for t in ctx["tasks"].values()]
        msgs = [message_view(m, rt, ctx) for m in rt.app.list_messages()]
        sugg = [suggestion_view(p, ctx) for p in ctx["proposals"].values() if p.status == "pending"]
        return {"participants": rt.app.participants(), "messages": msgs, "tasks": tasks, "suggestions": sugg, "settings": rt.app.settings(),
                "scenario": rt.scenarios.state(), "graph_meta": rt.graph.frontend()["meta"],
                "capabilities": rt.registry.capabilities(rt.app.settings())}

    @api.get("/workspace")
    def workspace(rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            return _workspace(rt)

    @api.post("/workspace/reset")
    def workspace_reset(rt: AppRuntime = Depends(get_rt)):
        rt.reset_workspace()
        with rt.lock:
            return _workspace(rt)

    @api.get("/participants")
    def participants(rt: AppRuntime = Depends(get_rt)):
        return rt.app.participants()

    @api.put("/participants")
    def upsert_participant(body: S.ParticipantModel, rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            return rt.app.upsert_participant(body.model_dump())

    @api.get("/settings")
    def get_settings(rt: AppRuntime = Depends(get_rt)):
        return rt.app.settings()

    @api.put("/settings")
    def put_settings(body: S.SettingsUpdate, rt: AppRuntime = Depends(get_rt)):
        from src.refine.config import PRESETS, STAGES
        if body.pipeline_preset is not None and body.pipeline_preset not in PRESETS:
            raise HTTPException(422, detail={"code": "UNKNOWN_PRESET", "message": f"unknown preset {body.pipeline_preset!r}; choose one of {sorted(PRESETS)}"})
        bad = sorted(set(body.refine_overrides or {}) - set(STAGES) - {"entity_source", "rule_dependency_linker"})
        if bad:
            raise HTTPException(422, detail={"code": "UNKNOWN_STAGE", "message": f"unknown refinement stage(s) {bad}; choose from {list(STAGES)}"})
        with rt.lock:
            return rt.app.set_settings({k: v for k, v in body.model_dump().items() if v is not None})

    # ---------------------------------------------------------------- messages
    def _analysis_view(rt: AppRuntime, mid: str) -> dict[str, Any]:
        m = rt.app.get_message(mid)
        if m is None:
            raise HTTPException(404, detail={"code": "NOT_FOUND", "message": f"no message {mid}"})
        ctx = build_ctx(rt)
        a = rt.app.latest_analysis(mid) or {}
        by_id = {e["id"]: e for e in (a.get("entities") or [])}
        rels = [{**r, "source_text": by_id.get(r["source_id"], {}).get("text"), "target_text": by_id.get(r["target_id"], {}).get("text")} for r in (a.get("relations") or [])]
        props = [suggestion_view(ctx["proposals"][i], ctx) for i in (a.get("proposal_ids") or []) if i in ctx["proposals"]]
        return {"message": message_view(m, rt, ctx), "entities": a.get("entities"), "relations": rels, "no_link": a.get("no_link"),
                "candidates": a.get("candidates"), "refinement": a.get("refinement"), "proposals": props, "provenance": a.get("provenance") or {}, "model_versions": a.get("model_versions") or {},
                "error": a.get("error") or m.get("error"), "run_id": a.get("run_id"), "duration_ms": a.get("duration_ms"),
                "classes_supported": ["TASK", "PERSON", "TEMPORAL"],
                "classes_not_produced": ["GROUP", "EVENT", "ARTIFACT"],
                "score_note": "Model scores are uncalibrated softmax values, not probabilities."}

    @api.post("/messages", status_code=201)
    def post_message(body: S.MessageCreate, rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            ids = {p["id"] for p in rt.app.participants()}
            if body.sender_id not in ids or any(r not in ids for r in body.recipient_ids):
                raise ReconciliationError("NOT_FOUND", "unknown sender or recipient")
            tz = rt.app.settings().get("timezone", "UTC")
            created = body.created_at
            if created:
                try:
                    dt = datetime.fromisoformat(created)
                except ValueError:
                    raise ReconciliationError("FIELD_NOT_EDITABLE", f"created_at is not an ISO-8601 time: {created!r}")
                created = (dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo(tz))).isoformat()      # a naive time means workspace-local time
            msg = rt.app.add_message({"id": rt.app.next_message_id(), "sender_id": body.sender_id, "recipient_ids": body.recipient_ids, "text": body.text,
                                      "created_at": created or _now_in(tz), "mode": body.mode, "status": "received", "in_reply_to": body.in_reply_to})
            rt.pipeline.process(msg)          # scripted free text has no scripted extraction -> status 'no_extraction' (never invented)
            return _analysis_view(rt, msg["id"])

    @api.post("/messages/{mid}/retry")
    def retry_message(mid: str, rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            m = rt.app.get_message(mid)
            if m is None:
                raise ReconciliationError("NOT_FOUND", f"no message {mid}")
            if m["status"] in ("analysis_failed", "received"):
                scripted = None
                if m.get("scenario_id"):
                    fx = rt.scenarios.fixture(m["scenario_id"])
                    scripted = fx["messages"][m["scenario_step"] - 1]["scripted"]
                rt.pipeline.process(m, scripted=scripted)
            return _analysis_view(rt, mid)

    @api.get("/messages/{mid}/analysis")
    def message_analysis(mid: str, rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            return _analysis_view(rt, mid)

    # ---------------------------------------------------------------- tasks
    @api.get("/tasks")
    def tasks(assignee_id: Optional[str] = None, status: Optional[str] = None, rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            g = rt.graph.snapshot()
            from src.graph.workflow_state import compute_states
            states = {k: v.to_dict() for k, v in compute_states(g).items()}
            counts = dep_counts(g)
            out = [task_view(t, states.get(t.task_id), counts) for t in rt.store.list_tasks(WORKSPACE, owner_id=assignee_id)]
            return [t for t in out if status is None or t["ui_status"] == status]

    @api.get("/tasks/{tid}")
    def task_detail(tid: str, rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            t = rt.store.get_task(WORKSPACE, tid)
            if t is None:
                raise ReconciliationError("NOT_FOUND", f"no task {tid}")
            g = rt.graph.snapshot()
            from src.graph.workflow_state import compute_states
            states = {k: v.to_dict() for k, v in compute_states(g).items()}
            view = task_view(t, states.get(tid), dep_counts(g))
            msg = rt.app.get_message(t.source_message_id) if t.source_message_id else None
            ctx = build_ctx(rt)
            edges = [{"id": e.edge_id, "prerequisite": e.prerequisite, "dependent": e.dependent, "kind": e.kind, "evidence": e.evidence,
                      "source_message_id": e.source_message_id, "source_kind": e.source_kind, "reason": e.reason}
                     for e in g.edges if tid in (e.prerequisite, e.dependent)]
            return {**view, "source_message": message_view(msg, rt, ctx) if msg else None, "edges": edges,
                    "history": [h.to_dict() for h in rt.store.history_for(WORKSPACE, tid)], "provenance": t.provenance}

    @api.get("/tasks/{tid}/history")
    def task_history(tid: str, rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            if rt.store.get_task(WORKSPACE, tid) is None:
                raise ReconciliationError("NOT_FOUND", f"no task {tid}")
            return [h.to_dict() for h in rt.store.history_for(WORKSPACE, tid)]

    @api.patch("/tasks/{tid}")
    def patch_task(tid: str, body: S.TaskPatch, rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            t = rt.store.get_task(WORKSPACE, tid)
            if t is None:
                raise ReconciliationError("NOT_FOUND", f"no task {tid}")
            m = rt.app.get_message(t.source_message_id) if t.source_message_id else None
            changes = _convert_edits(rt, dict(body.changes), m["created_at"] if m else None)
            rt.reconciler.manual_edit(WORKSPACE, tid, body.actor_id, body.expected_version, changes, note="edited in the UI")
            rt.scenarios.record_action({"type": "manual_edit", "task_id": tid, "changes": changes, "actor": body.actor_id})
            return task_detail(tid, rt)

    # ---------------------------------------------------------------- suggestions
    @api.get("/suggestions")
    def suggestions(status: str = "pending", rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            ctx = build_ctx(rt)
            out = [suggestion_view(p, ctx) for p in ctx["proposals"].values()]
            return out if status == "all" else [s for s in out if s["status"] == status]

    @api.post("/suggestions/{pid}/accept")
    def accept(pid: str, body: S.AcceptBody, rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            p = rt.store.get_proposal(WORKSPACE, pid)
            if p is None:
                raise ReconciliationError("NOT_FOUND", f"no suggestion {pid}")
            if p.status == "pending":
                _check_reviewer(rt, p, body.actor_id)
            m = rt.app.get_message(p.message_id)
            edits = _convert_edits(rt, body.edits, m["created_at"] if m else None)
            result = rt.reconciler.accept(WORKSPACE, pid, body.actor_id, edits=edits, expected_version=body.expected_version, idempotency_key=body.idempotency_key)
            if not result.get("replayed"):
                rt.scenarios.record_action({"type": "accept", "proposal_id": pid, "actor": body.actor_id, "edits": edits, "expected_version": body.expected_version})
            ctx = build_ctx(rt)
            return {"result": result, "suggestion": suggestion_view(rt.store.get_proposal(WORKSPACE, pid), ctx)}

    @api.post("/suggestions/{pid}/dismiss")
    def dismiss(pid: str, body: S.DismissBody, rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            p = rt.store.get_proposal(WORKSPACE, pid)
            if p is not None and p.status == "pending":
                _check_reviewer(rt, p, body.actor_id, dismissing=True)
            rt.reconciler.dismiss(WORKSPACE, pid, body.actor_id, body.reason)
            rt.scenarios.record_action({"type": "dismiss", "proposal_id": pid, "actor": body.actor_id, "reason": body.reason})
            return suggestion_view(rt.store.get_proposal(WORKSPACE, pid), build_ctx(rt))

    # ---------------------------------------------------------------- dependencies
    @api.get("/dependencies")
    def dependencies(step: Optional[int] = None, rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            st = rt.app.scenario_state()
            if step is not None and st["scenario_id"] and step != st["step"] and str(step) in st["snapshots"]:
                return {**st["snapshots"][str(step)], "snapshot_step": step}
            return rt.graph.frontend()

    @api.post("/dependencies", status_code=201)
    def add_dependency(body: S.EdgeCreate, rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            r = rt.graph.editor().add_dependency(WORKSPACE, body.prerequisite_task_id, body.dependent_task_id, body.actor_id, evidence=body.evidence)
            if r.get("applied"):
                rt.scenarios.record_action({"type": "add_dependency", "prerequisite": body.prerequisite_task_id, "dependent": body.dependent_task_id,
                                            "actor": body.actor_id, "evidence": body.evidence})
            return {"decision": r, "graph": rt.graph.frontend()}

    @api.delete("/dependencies/{edge_id}")
    def remove_dependency(edge_id: str, actor_id: str, reason: str = "", rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            r = rt.graph.editor().remove_dependency(WORKSPACE, edge_id, actor_id, reason)
            if r.get("applied"):
                rt.scenarios.record_action({"type": "remove_dependency", "edge_id": edge_id, "actor": actor_id, "reason": reason})
            return {"decision": r, "graph": rt.graph.frontend()}

    @api.post("/dependencies/{edge_id}/reconsider")
    def reconsider(edge_id: str, body: S.EdgeAction, rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            r = rt.graph.editor().reconsider(WORKSPACE, edge_id, body.actor_id)
            if r.get("applied"):
                rt.scenarios.record_action({"type": "reconsider", "edge_id": edge_id, "actor": body.actor_id})
            return {"decision": r, "graph": rt.graph.frontend()}

    @api.get("/impact")
    def impact(task_id: str, status: str, rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            if status not in ("open", "in_progress", "completed", "cancelled"):
                raise ReconciliationError("FIELD_NOT_EDITABLE", f"unknown status {status}")
            try:
                return rt.graph.impact(task_id, status)
            except KeyError:
                raise ReconciliationError("NOT_FOUND", f"no task {task_id}")

    # ---------------------------------------------------------------- scenarios
    @api.get("/scenarios")
    def scenarios(rt: AppRuntime = Depends(get_rt)):
        return {"scenarios": rt.scenarios.list(), "state": rt.scenarios.state()}

    @api.post("/scenarios/reset")
    def scenario_reset(rt: AppRuntime = Depends(get_rt)):
        with rt.lock:
            return rt.scenarios.reset()

    @api.post("/scenarios/step")
    def scenario_step(rt: AppRuntime = Depends(get_rt)):
        return rt.scenarios.step()

    @api.post("/scenarios/previous")
    def scenario_previous(rt: AppRuntime = Depends(get_rt)):
        return rt.scenarios.previous()

    @api.post("/scenarios/play")
    def scenario_play(rt: AppRuntime = Depends(get_rt)):
        return rt.scenarios.play()

    @api.post("/scenarios/{sid}/load")
    def scenario_load(sid: str, rt: AppRuntime = Depends(get_rt)):
        try:
            return rt.scenarios.load(sid)
        except KeyError:
            raise ReconciliationError("NOT_FOUND", f"no scenario {sid}")

    app.include_router(api)

    # ---------------------------------------------------------------- static frontend (built app)
    dist: Path = settings.frontend_dist
    if dist.is_dir() and (dist / "index.html").is_file():
        from fastapi.staticfiles import StaticFiles
        if (dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            f = dist / path
            return FileResponse(f if f.is_file() else dist / "index.html")
    return app
