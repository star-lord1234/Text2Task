"""Builders that turn Phase 4-6 records into the shapes the UI consumes (plain-language summaries, provenance, unresolved fields)."""

from __future__ import annotations

from typing import Any, Optional

from src.api.config import WORKSPACE

UI_STATUS = {"open": "todo", "in_progress": "in_progress", "completed": "done", "cancelled": "canceled"}
KIND = {"CREATE_TASK": "create_task", "ADD_DEPENDENCY": "add_dependency", "NO_ACTION": "no_change"}
UPDATE_OPS = {"UPDATE_ASSIGNEE", "PROPOSE_DUE_DATE_CHANGE", "CONFIRM_DUE_DATE_CHANGE", "UPDATE_STATUS", "COMPLETE_TASK", "CANCEL_TASK"}


def date_text(tv: Optional[dict[str, Any]]) -> str:
    if not tv:
        return "no confirmed date"
    if tv.get("status") == "RESOLVED":
        return tv.get("value") or tv.get("start") or tv.get("raw") or "resolved"
    return f"“{tv.get('raw')}” ({str(tv.get('status', '')).lower().replace('_', ' ')})"


def _names(participants: list[dict[str, Any]]) -> dict[str, str]:
    return {p["id"]: p["name"] for p in participants}


def describe(p: Any, tasks: dict[str, Any], names: dict[str, str], proposals_by_id: dict[str, Any]) -> str:
    op, pl = p.operation, p.payload
    title = lambda tid: tasks[tid].title if tid in tasks else (tid or "a task")
    who = lambda uid: names.get(uid, uid) if uid else "unassigned"
    if op == "CREATE_TASK":
        return f"Create task “{pl.get('title')}” — {who(pl.get('owner_id'))}, due {date_text(pl.get('due'))}"
    if op == "PROPOSE_DUE_DATE_CHANGE":
        f = pl.get("field") or p.field or "due"
        mode = "Change" if pl.get("direct") else "Propose changing"
        return f"{mode} {f} of “{title(p.task_id)}” to {date_text(p.after)}" if p.task_id else f"{mode} {f}: {date_text(p.after)} (task to be chosen)"
    if op == "CONFIRM_DUE_DATE_CHANGE":
        return f"Confirm {p.field or 'due'} change of “{title(p.task_id)}” to {date_text(p.after)}"
    if op == "UPDATE_ASSIGNEE":
        verb = "Assign" if p.before is None else "Reassign"          # an unowned task is assigned, not reassigned
        return f"{verb} “{title(p.task_id)}” to {who(p.after)}" if p.task_id else f"{verb} to {who(p.after)} (task to be chosen)"
    if op in ("COMPLETE_TASK", "CANCEL_TASK", "UPDATE_STATUS"):
        word = {"COMPLETE_TASK": "done", "CANCEL_TASK": "cancelled", "UPDATE_STATUS": "in progress"}[op]
        return f"Mark “{title(p.task_id)}” {word}" if p.task_id else f"Mark {word} (task to be chosen)"
    if op == "ADD_DEPENDENCY":
        dep = tasks[pl["dependent_task_id"]].title if pl.get("dependent_task_id") in tasks else None
        if not dep and pl.get("dependent_create_pid") in proposals_by_id:
            dep = proposals_by_id[pl["dependent_create_pid"]].payload.get("title")
        if not dep and pl.get("dependent_candidate_id"):
            c = next((q for q in proposals_by_id.values() if q.payload.get("candidate_id") == pl["dependent_candidate_id"]), None)
            dep = c.payload.get("title") if c else None
        pre = tasks[pl["prerequisite_task_id"]].title if pl.get("prerequisite_task_id") in tasks else None
        if not pre and pl.get("prerequisite_candidate_id"):
            c = next((q for q in proposals_by_id.values() if q.payload.get("candidate_id") == pl["prerequisite_candidate_id"]), None)
            pre = c.payload.get("title") if c else None
        return f"“{dep or 'a task'}” depends on “{pre or 'a task'}” (prerequisite → dependent)"
    return p.note or "No change"


def unresolved(p: Any) -> list[str]:
    out = []
    pl = p.payload
    if p.operation == "CREATE_TASK":
        if not pl.get("owner_id"):
            out.append("assignee")
        due = pl.get("due")
        if due and due.get("status") != "RESOLVED":
            out.append("due")
    if p.operation == "UPDATE_ASSIGNEE" and p.after is None:
        out.append("assignee")
    if p.operation in ("PROPOSE_DUE_DATE_CHANGE", "CONFIRM_DUE_DATE_CHANGE") and (p.after is None or (isinstance(p.after, dict) and p.after.get("status") != "RESOLVED")):
        out.append("date")
    if pl.get("needs_referent"):
        out.append("task")
    return out


def _create_owner(proposals_by_id: dict[str, Any], pid: Optional[str] = None, candidate_id: Optional[str] = None) -> Optional[str]:
    if pid and pid in proposals_by_id:
        return proposals_by_id[pid].payload.get("owner_id")
    if candidate_id:
        c = next((q for q in proposals_by_id.values() if q.payload.get("candidate_id") == candidate_id and q.operation == "CREATE_TASK"), None)
        return c.payload.get("owner_id") if c else None
    return None


def reviewers(p: Any, tasks: dict[str, Any], proposals_by_id: dict[str, Any]) -> list[str]:
    """Who decides on a suggestion: the person it lands on, never a bystander.

    A new task is accepted by its assignee, a handover by the new owner, a status change or a new prerequisite by the owner of the
    task it affects, and a date change by the people whose agreement it needs (the creator/owner who did not ask for it). An empty
    list means nobody in particular is affected (e.g. an unassigned task), so any teammate may decide.
    """
    op, pl = p.operation, p.payload
    t = tasks.get(p.task_id) if p.task_id else None
    owner = t.owner_id if t else None
    out: list[Optional[str]]
    if op == "CREATE_TASK":
        out = [pl.get("owner_id")]
    elif op == "UPDATE_ASSIGNEE":
        out = [p.after if isinstance(p.after, str) else None]
    elif op == "PROPOSE_DUE_DATE_CHANGE":
        # a direct change lands on the owner. A request ("can we move it to Friday?") changes nothing yet: its author confirms that
        # the request was read correctly, and the people it needs agree through the CONFIRM step below.
        out = [owner] if pl.get("direct") or not p.needs_confirmation_from else [p.proposer_id or p.needs_confirmation_from[0]]
    elif op == "CONFIRM_DUE_DATE_CHANGE":
        pend = proposals_by_id.get(pl.get("pending_proposal_id") or "")
        if pend is not None:
            needs = list(pend.needs_confirmation_from)
        elif t is not None:
            needs = list(((t.pending_changes or {}).get(p.field or "due") or {}).get("needs_confirmation_from") or [])
        else:
            needs = []
        out = needs or [owner]
    elif op in ("COMPLETE_TASK", "UPDATE_STATUS"):
        out = [owner]
    elif op == "CANCEL_TASK":
        out = [owner, t.created_by if t else None]
    elif op == "ADD_DEPENDENCY":
        dep = pl.get("dependent_task_id")
        out = [tasks[dep].owner_id if dep in tasks else _create_owner(proposals_by_id, pl.get("dependent_create_pid"), pl.get("dependent_candidate_id"))]
    else:   # NO_ACTION / clarifications: the person who wrote the message is best placed to answer
        out = [owner or p.proposer_id]
    return sorted({x for x in out if x})


def prerequisites(p: Any, proposals_by_id: dict[str, Any]) -> list[dict[str, Any]]:
    pl, out = p.payload, []
    pend = [pl.get("requires_proposal"), pl.get("dependent_create_pid"), *(pl.get("requires_creates") or [])]
    for pid in pend:
        if pid and pid in proposals_by_id and proposals_by_id[pid].status != "applied":
            out.append({"proposal_id": pid, "status": proposals_by_id[pid].status, "summary": None})
    return out


def suggestion_view(p: Any, ctx: dict[str, Any]) -> dict[str, Any]:
    tasks, names, by_id = ctx["tasks"], ctx["names"], ctx["proposals"]
    warn = any(f["severity"] != "info" for f in p.flags)
    kind = KIND.get(p.operation) or ("update_task" if p.operation in UPDATE_OPS else "update_task")
    if p.operation == "NO_ACTION" and warn:
        kind = "clarification"
    if p.payload.get("needs_referent"):
        kind = "clarification"
    prov_stage = ctx["provenance"].get(p.message_id, {})
    return {
        "id": p.proposal_id, "message_id": p.message_id, "kind": kind, "operation": p.operation, "task_id": p.task_id, "field": p.field,
        "summary": describe(p, tasks, names, by_id), "status": p.status, "needs_review": warn or p.operation != "NO_ACTION",
        "source_kind": p.source_kind,
        "provenance": {"extraction": prov_stage.get("entities", p.source_kind), "linking": prov_stage.get("relations", p.source_kind),
                       "reconciliation": "rule (cue-based)", "applied_by": p.resolved_by if p.status == "applied" else None},
        "evidence": p.evidence, "flags": p.flags, "note": p.note, "before": p.before, "after": p.after, "base_version": p.base_version,
        "needs_confirmation_from": p.needs_confirmation_from, "unresolved": unresolved(p), "requires_referent": bool(p.payload.get("needs_referent")),
        "match": p.match, "must_accept_first": prerequisites(p, by_id), "direct": bool(p.payload.get("direct")),
        "resolved_by": p.resolved_by, "resolution_note": p.resolution_note, "created_at": p.created_at,
        "reviewer_ids": reviewers(p, tasks, by_id), "proposer_id": p.proposer_id,
    }


def build_ctx(rt: Any) -> dict[str, Any]:
    tasks = {t.task_id: t for t in rt.store.list_tasks(WORKSPACE)}
    proposals = {p.proposal_id: p for p in rt.store.list_proposals(WORKSPACE)}
    prov: dict[str, Any] = {}
    for m in rt.app.list_messages():
        a = rt.app.latest_analysis(m["id"])
        if a and a.get("provenance"):
            prov[m["id"]] = a["provenance"]
    return {"tasks": tasks, "names": _names(rt.app.participants()), "proposals": proposals, "provenance": prov}


def task_view(t: Any, state: Optional[dict[str, Any]], dep_counts: dict[str, dict[str, int]], source_text: Optional[str] = None) -> dict[str, Any]:
    st = state or {}
    derived = st.get("derived", t.status)
    ui = {"blocked": "blocked", "blocked_cancelled_prereq": "needs_review"}.get(derived) or UI_STATUS.get(t.status, t.status)
    return {"id": t.task_id, "title": t.title, "owner_id": t.owner_id, "lifecycle": t.status, "derived_state": derived, "ui_status": ui,
            "blocked_by": st.get("blocked_by", []), "cancelled_prereqs": st.get("cancelled_prereqs", []), "root_blockers": st.get("root_blockers", []),
            "due": t.due, "scheduled": t.scheduled, "version": t.version, "source_message_id": t.source_message_id, "created_by": t.created_by,
            "thread_id": t.thread_id, "evidence_text": t.evidence_text,
            "pending_changes": {k: {"value": v.get("value"), "proposer_id": v.get("proposer_id"), "proposal_id": v.get("proposal_id"),
                                    "needs_confirmation_from": v.get("needs_confirmation_from", [])} for k, v in (t.pending_changes or {}).items()},
            "blocks_count": dep_counts.get(t.task_id, {}).get("blocks", 0), "blocked_by_count": dep_counts.get(t.task_id, {}).get("blocked_by", 0),
            "last_touched_message_id": t.last_touched_message_id}


def dep_counts(graph: Any) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for e in graph.accepted():
        out.setdefault(e.prerequisite, {"blocks": 0, "blocked_by": 0})["blocks"] += 1
        out.setdefault(e.dependent, {"blocks": 0, "blocked_by": 0})["blocked_by"] += 1
    return out


def message_view(m: dict[str, Any], rt: Any, ctx: dict[str, Any]) -> dict[str, Any]:
    a = rt.app.latest_analysis(m["id"])
    props = [ctx["proposals"][i] for i in (a["proposal_ids"] if a else []) if i in ctx["proposals"]]
    items = [{"id": p.proposal_id, "operation": p.operation, "status": p.status, "summary": describe(p, ctx["tasks"], ctx["names"], ctx["proposals"]),
              "flag_codes": [f["code"] for f in p.flags], "warn": any(f["severity"] != "info" for f in p.flags), "task_id": p.task_id} for p in props]
    pending = [i for i in items if i["status"] == "pending"]
    ops = [p.operation for p in props]
    expected = m.get("expected")
    return {**{k: m[k] for k in ("id", "sender_id", "recipient_ids", "text", "created_at", "mode", "status", "error", "scenario_id", "scenario_step", "thread_id", "in_reply_to")},
            "proposals": items, "pending_count": len(pending), "applied_count": sum(i["status"] == "applied" for i in items),
            "no_change": [i["summary"] for i in items if i["status"] == "no_action"],
            "provenance": (a or {}).get("provenance", {}), "run_id": (a or {}).get("run_id"),
            "expected": expected, "matches_expectation": (None if not expected else sorted(ops) == sorted(expected.get("operations", [])))}
