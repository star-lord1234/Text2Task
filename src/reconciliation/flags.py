"""Reconciliation flags (Phase 5). Same Flag contract as Phase 4, new codes, each with a clarification question."""

from __future__ import annotations

from typing import Optional

from src.pipeline.contracts import Flag

TEMPLATES: dict[str, tuple[str, str, str]] = {
    # code: (severity, message, question)
    "AMBIGUOUS_REFERENT": ("warn", "Several tasks could be what this message refers to ({candidates}); no task was changed.", "Which task does '{text}' refer to ({candidates})?"),
    "NO_REFERENT": ("warn", "No existing task matches this message; no task was changed.", "Which task does '{text}' refer to, if any?"),
    "REFERENT_PENDING_REVIEW": ("warn", "The task this refers to is still awaiting review ({candidates}).", "Accept the pending task ({candidates}) first, then re-check this message."),
    "POSSIBLE_DUPLICATE": ("warn", "This looks similar to an existing task ({candidates}).", "Is this a new task or the same as {candidates}?"),
    "ACKNOWLEDGES_EXISTING_TASK": ("info", "The owner acknowledged an existing task ({candidates}); no new task was proposed.", "Nothing needed."),
    "CLAIMS_UNASSIGNED_TASK": ("info", "{detail} offered to take the unassigned task {candidates}.", "Nothing needed."),
    "RESTATED_EXISTING_TASK": ("info", "This restates {candidates}; no new task was proposed.", "Nothing needed."),
    "RESTATED_WITH_DIFFERENT_DATE": ("warn", "This restates {candidates} but with a different date ({detail}).", "Should the date of {candidates} change to the new one?"),
    "CONFLICTING_PROPOSAL": ("warn", "A different change to the same field is already pending ({detail}).", "Which change is right: the earlier one or this one?"),
    "THIRD_PARTY_COMPLETION": ("warn", "Completion was reported by someone other than the owner.", "Can the owner confirm that {title} is done?"),
    "ILLEGAL_TRANSITION": ("warn", "A task that is {detail} cannot be changed this way; nothing was changed.", "Is this a new request instead?"),
    "TASK_ALREADY_CLOSED": ("warn", "The task is already {detail}; nothing was changed.", "Is this a new task?"),
    "ALREADY_IN_STATE": ("info", "The task is already in this state ({detail}).", "Nothing needed."),
    "UNRESOLVED_NEW_DATE": ("warn", "The new date could not be resolved ({detail}); the current date was kept.", "What is the exact new date?"),
    "UNRESOLVED_NEW_OWNER": ("warn", "The new owner could not be resolved ({detail}).", "Who should own {title}?"),
    "UNAUTHORIZED_CONFIRMER": ("warn", "The reply came from someone who is not a creator or owner of the task ({detail}).", "Can the creator or owner confirm the change?"),
    "REOPEN_REQUESTED": ("warn", "A completed task is described as not done; reopening is not supported.", "Should {title} be recreated as a new task?"),
    "PROPOSAL_DECLINED": ("warn", "The pending change appears to be declined by this reply.", "Should the pending change be dismissed?"),
    "NO_PENDING_PROPOSAL": ("info", "There is no pending change to answer.", "Nothing needed."),
    "DEPENDENCY_ENDPOINT_UNMATCHED": ("warn", "A dependency was mentioned but both tasks could not be identified ({detail}).", "Which tasks are linked by this dependency?"),
    "SELF_DEPENDENCY": ("warn", "A task cannot depend on itself.", "Which two different tasks are meant?"),
    "TENTATIVE_REQUEST": ("info", "Phrased as a question or suggestion.", "Nothing needed."),
}


def rflag(code: str, field: str, *, evidence: Optional[str] = None, **fmt) -> dict:
    sev, message, question = TEMPLATES[code]
    base = {"candidates": "", "text": "this message", "detail": "", "title": "this task"}
    base.update({k: v for k, v in fmt.items() if v is not None})
    return Flag(code=code, severity=sev, field=field, message=message.format(**base), question=question.format(**base),
                evidence=evidence).to_dict()
