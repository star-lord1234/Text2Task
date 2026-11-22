"""Task reconciliation (Phase 5): turn messages into proposed operations, apply reviewed ones atomically.

Review mode only: ``process_message`` never changes a task; it persists *proposals*. A reviewer calls
``accept`` / ``edit_and_accept`` / ``dismiss``. ``accept`` is one transaction with a version check, an
idempotency key and append-only history. Ambiguous or missing referents never modify any task.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from src.pipeline.contracts import MessageEnvelope
from src.pipeline.identity_resolution import FIRST_SINGULAR, ParticipantRegistry, resolve_assignee
from src.pipeline.uncertainty import load_config as load_phase4_config, temporal_flags
from src.reconciliation.context_cues import context_completion, owner_acknowledgement
from src.reconciliation.cues import IntentHit, Sentence, classify_sentence, split_sentences
from src.reconciliation.flags import rflag
from src.reconciliation.matcher import MatchResult, Matcher, content_tokens, stem
from src.reconciliation.models import (ALLOWED_TRANSITIONS, DependencyEdge, ProposedOperation, ReconcileResult,
                                       ReconciliationError, StaleVersion, Task)
from src.reconciliation.store import TaskStore
from src.temporal.normalize import normalize_temporal

RESOLVED_ASSIGNEE = ("RESOLVED", "RESOLVED_SENDER", "RESOLVED_RECIPIENT")
DATE_FIELDS = ("due", "scheduled")
GENERIC_COMMITMENT = re.compile(r"^(?:take care of|take care|handle|work on|deal with|look after|take over|take|own|pick up|get (?:it|this|that) done|do|sort (?:it )?out)\b", re.I)
COMMITMENT_NOISE = {"take", "care", "handle", "work", "deal", "look", "pick", "own", "get", "done", "do", "sort", "it", "this", "that", "over"}
CLAUSE_CUE = re.compile(r"\b(?:once|after|when|as soon as|following)\s+(.+)$", re.I)
DATE_PREP = re.compile(r"(?:\bto|\buntil|\btill|\bby|\bfor|\bon|\bback to|\bis|\bnow|\bbe)\s*$", re.I)


def load_config(path: Optional[Path] = None) -> dict[str, Any]:
    path = path or Path(__file__).resolve().parents[2] / "configs" / "phase5.json"
    return json.loads(Path(path).read_text())


def _h(*parts: Any) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]


def _dkey(tv: Optional[Mapping[str, Any]]):
    """Comparable identity of a normalised date value (None when unresolved)."""
    if not tv or tv.get("status") != "RESOLVED":
        return None
    return (tv.get("value"), tv.get("start"), tv.get("end"))


def _guard_overwrite(old: Optional[Mapping[str, Any]], new: Optional[Mapping[str, Any]]) -> None:
    if old and old.get("status") == "RESOLVED" and (new is None or new.get("status") != "RESOLVED"):
        raise ReconciliationError("UNRESOLVED_VALUE", "refusing to overwrite a resolved date with an unresolved one; "
                                                      "edit the proposal with a resolved date or dismiss it")


class _Ctx:
    def __init__(self, ws, env, thread, seq, registry, source_kind, tasks, p4cfg, options=None):
        self.ws, self.env, self.thread, self.seq = ws, env, thread, seq
        self.registry, self.source_kind, self.tasks, self.p4cfg = registry, source_kind, tasks, p4cfg
        self.options = dict(options or {})                   # Phase 7.5: {"context_lifecycle": bool, "clause_hints": [...]}; empty = Phase 5 behaviour


VOLUNTEER_CUE = re.compile(r"^\W*(?:(?:sure|ok|okay|yes|yep|yeah|great|thanks|thank you)\b\W*)?(?:i\s+(?:can|will|shall|am going to|am happy to|'m going to|'m happy to)|i'll|i'd be happy to|happy to|let me)\b", re.I)


class Reconciler:
    def __init__(self, store: TaskStore, config: Optional[Mapping[str, Any]] = None, matcher: Optional[Matcher] = None,
                 dependency_validator=None, phase4_config: Optional[Mapping[str, Any]] = None):
        self.store = store
        self.config = dict(config) if config is not None else load_config()
        if self.config.get("auto_apply"):
            raise ReconciliationError("AUTO_APPLY_DISABLED", "Phase 5 supports review mode only")
        self.matcher = matcher or Matcher(self.config)
        self.dependency_validator = dependency_validator or self._default_dependency_validator
        self.phase4_config = dict(phase4_config) if phase4_config is not None else load_phase4_config()

    # ================================================================== process
    def process_message(self, envelope: MessageEnvelope, entities: Sequence[Mapping[str, Any]], candidates: Sequence[Any],
                        registry: Optional[ParticipantRegistry] = None, *, workspace_id: str = "default",
                        source_kind: str = "neural", options: Optional[Mapping[str, Any]] = None) -> ReconcileResult:
        ws, mid = workspace_id, envelope.message_id
        thread = envelope.thread_id or "default"
        text_hash = hashlib.sha256(envelope.text.encode("utf-8")).hexdigest()
        with self.store.transaction():
            prev = self.store.get_processed(ws, mid)
            if prev is not None:
                if prev["text_hash"] != text_hash:
                    raise ReconciliationError("MESSAGE_ID_REUSED", f"{mid} was already processed with different text")
                props = self.store.list_proposals(ws, message_id=mid)
                return ReconcileResult(mid, [p for p in props if p.status != "no_action"],
                                       [p for p in props if p.status == "no_action"], replayed=True)
            seq = self.store.mark_processed(ws, mid, thread, text_hash)
            ctx = _Ctx(ws, envelope, thread, seq, registry or ParticipantRegistry([]), source_kind,
                       self.store.list_tasks(ws, thread_id=thread), self.phase4_config, options)
            built: list[ProposedOperation] = []
            for sent in split_sentences(envelope.text):
                built.extend(self._sentence(ctx, sent, entities, candidates))
            result = ReconcileResult(mid)
            for p in built:
                p.created_at = self.store.now()
                p.status = "pending" if (p.operation != "NO_ACTION" or p.review_required) else "no_action"
                self.store.insert_proposal(p)
                (result.no_actions if p.status == "no_action" else result.proposals).append(p)
            for tid in {p.task_id for p in built if p.task_id and p.match.get("outcome") == "MATCHED"}:
                self.store.touch_task(ws, tid, mid, seq)
            return result

    # ------------------------------------------------------------------ sentence dispatch
    def _sentence(self, ctx: _Ctx, sent: Sentence, entities, candidates) -> list[ProposedOperation]:
        ents = [e for e in entities if e["start"] >= sent.start and e["end"] <= sent.end]
        temporals = [e for e in ents if e["type"] == "TEMPORAL"]
        cands = [c for c in candidates if sent.start <= c.task_span["start"] and c.task_span["end"] <= sent.end]
        hit = classify_sentence(
            sent.text, has_task_candidate=bool(cands), candidate_has_due=any(c.due is not None for c in cands),
            candidate_assignee_resolved=any(c.assignee.status in RESOLVED_ASSIGNEE for c in cands), n_temporal=len(temporals),
            temporal_texts=[e["text"] for e in temporals],
            imperative_candidate=any(c.task_span["id"] in ctx.options.get("imperative_ids", ()) for c in cands))
        refref = [h for h in ctx.options.get("clause_hints", []) if h.get("kind") == "reference_reference"
                  and sent.start <= h["dependent_range"][0] and h["prerequisite_range"][1] <= sent.end]
        if refref:
            made = self._reference_dependency(ctx, sent, refref[0])
            if made:
                return made
        if ctx.options.get("context_lifecycle") and hit.op == "NO_ACTION":
            owner_task = owner_acknowledgement(sent.text, ctx.tasks, ctx.env.sender_id) if not cands else None
            if owner_task is not None:
                return [self._prop(ctx, sent, "NO_ACTION", task=owner_task, key="ctx_ack",
                                   flags=[rflag("ACKNOWLEDGES_EXISTING_TASK", "duplicate", candidates=owner_task.task_id)],
                                   note=f"owner acknowledges {owner_task.task_id} (no task phrase needed)")]
            alt = context_completion(sent.text, ctx.tasks)
            if alt is not None:
                hit = alt
        ctx_args = (ctx, sent, hit, ents, temporals, cands)
        handlers = {"CREATE_TASK": self._create, "COMPLETE_TASK": self._status_change, "CANCEL_TASK": self._status_change,
                    "UPDATE_STATUS": self._status_change, "UPDATE_ASSIGNEE": self._assignee, "DATE_CHANGE": self._date_change,
                    "CONFIRM": self._confirm, "DECLINE": self._decline, "ADD_DEPENDENCY": self._dependency, "REOPEN": self._reopen}
        if hit.op in handlers:
            return handlers[hit.op](*ctx_args)
        if cands or (hit.reason and hit.reason != "no actionable cue"):
            return [self._no_action(ctx, sent, hit.reason or "no actionable cue", note=f"cue_set={hit.cue}" if hit.cue else "")]
        return []

    # ------------------------------------------------------------------ helpers
    def _prop(self, ctx: _Ctx, sent: Sentence, op: str, *, task: Optional[Task] = None, key: str = "", **kw) -> ProposedOperation:
        pid = "P-" + _h(ctx.ws, ctx.env.message_id, sent.index, op, task.task_id if task else "", key)
        p = ProposedOperation(proposal_id=pid, workspace_id=ctx.ws, message_id=ctx.env.message_id, operation=op,
                              task_id=task.task_id if task else None, base_version=task.version if task else None,
                              source_kind=ctx.source_kind, proposer_id=ctx.env.sender_id,
                              evidence={"sentence": sent.text, "start": sent.start, "end": sent.end,
                                        "message_id": ctx.env.message_id})
        for k, v in kw.items():
            setattr(p, k, v)
        p.payload = {**p.payload, "seq": ctx.seq, "thread_id": ctx.thread, "reference_ts": ctx.env.timestamp,
                     "timezone": ctx.env.timezone}
        return p

    def _no_action(self, ctx, sent, reason, *, flags=None, task=None, note="", key="") -> ProposedOperation:
        return self._prop(ctx, sent, "NO_ACTION", task=task, key=key or reason, flags=flags or [], note=reason + (f" | {note}" if note else ""))

    def _tokens(self, sent: Sentence, hit: IntentHit, ents) -> list[str]:
        spans = [(e["start"] - sent.start, e["end"] - sent.start) for e in ents if e["type"] in ("TEMPORAL", "PERSON")]
        if hit.cue_span:
            spans.append(hit.cue_span)
        toks = content_tokens(sent.text, spans)
        if hit.op == "DATE_CHANGE":          # "move the deadline to Friday": 'deadline/due/date' name the field, not the task
            toks = [t for t in toks if t not in {"deadline", "due", "date", "time"}]
        return toks

    def _match(self, ctx: _Ctx, sent: Sentence, hit: IntentHit, ents, op: str, tasks: Optional[Sequence[Task]] = None,
               tokens: Optional[Sequence[str]] = None, text: Optional[str] = None) -> MatchResult:
        return self.matcher.match(self.store, ctx.ws, ctx.tasks if tasks is None else tasks, sentence=text or sent.text,
                                  tokens=self._tokens(sent, hit, ents) if tokens is None else tokens, speaker_id=ctx.env.sender_id,
                                  in_reply_to=ctx.env.in_reply_to, current_seq=ctx.seq, op=op)

    def _unmatched(self, ctx, sent, hit, op, m: MatchResult, ents, intended: Optional[dict] = None) -> ProposedOperation:
        """AMBIGUOUS_REFERENT -> a review proposal naming candidates (accept needs edits={'task_id': ...});
        NO_REFERENT -> NO_ACTION + flag. No task is ever changed here."""
        pending = self._pending_creates(ctx, sent, m)
        flags: list[dict] = []
        if m.outcome == "AMBIGUOUS_REFERENT":
            cands = ", ".join(r["task_id"] for r in m.ranked)
            flags.append(rflag("AMBIGUOUS_REFERENT", "referent", evidence=m.reason, candidates=cands, text=sent.text))
            intended = intended or {}
            flags += intended.get("flags", [])
            p = self._prop(ctx, sent, op if op != "DATE_CHANGE" else "PROPOSE_DUE_DATE_CHANGE", flags=flags, match=m.to_dict(),
                           field=intended.get("field"), after=intended.get("after"), note="referent must be chosen by the reviewer")
            p.payload.update(intended.get("payload", {}))
            p.payload["needs_referent"] = True
            p.payload["intent"] = op
            return p
        if pending:
            flags.append(rflag("REFERENT_PENDING_REVIEW", "referent", candidates=", ".join(pending), text=sent.text))
        else:
            f = rflag("NO_REFERENT", "referent", evidence=m.reason, text=sent.text)
            if op not in ("COMPLETE_TASK", "CANCEL_TASK"):
                f["severity"] = "info"      # an unmatched date/status/owner remark is not consequential; completion/cancellation is
            flags.append(f)
        return self._prop(ctx, sent, "NO_ACTION", flags=flags, match=m.to_dict(), note=f"{op} without a matching task", key=op)

    def _pending_creates(self, ctx: _Ctx, sent: Sentence, m: MatchResult) -> list[str]:
        out = []
        toks = set(content_tokens(sent.text))
        for p in self.store.list_proposals(ctx.ws, status="pending", operation="CREATE_TASK"):
            if p.payload.get("thread_id") != ctx.thread:
                continue
            if toks & set(content_tokens(p.payload.get("title", ""), drop_filler=False)) or ctx.seq - p.payload.get("seq", 0) < 3:
                out.append(p.proposal_id)
        return out

    # ------------------------------------------------------------------ CREATE
    def _create(self, ctx, sent, hit, ents, temporals, cands) -> list[ProposedOperation]:
        out: list[ProposedOperation] = []
        created = []
        restated: dict[str, str] = {}                     # candidate -> existing task it merely restates (Phase 7.5: lets a dependency point at it)
        for c in cands:
            tokens = content_tokens(c.title, drop_filler=False)
            m = self.matcher.match(self.store, ctx.ws, ctx.tasks, sentence=c.title, tokens=tokens, speaker_id=ctx.env.sender_id,
                                   in_reply_to=None, current_seq=ctx.seq, op="CREATE_TASK", allow_anaphora=False)
            owner = c.assignee.participant_id
            flags = [dict(f.to_dict()) for f in c.flags]
            if hit.tentative:
                flags.append(rflag("TENTATIVE_REQUEST", "request"))
            snapshot = {"title": c.title, "owner_id": owner, "due": c.due.to_dict() if c.due else None,
                        "scheduled": c.scheduled.to_dict() if c.scheduled else None, "evidence_text": c.evidence_text,
                        "candidate_id": c.candidate_id, "assignee": c.assignee.to_dict(), "phase4_provenance": c.provenance}
            ack = self._owner_acknowledgement(ctx, sent, c) if m.outcome != "MATCHED" else None
            if ack and ack[0] == "ACK":
                out.append(self._prop(ctx, sent, "NO_ACTION", task=ack[1], key=c.candidate_id, match=m.to_dict(),
                                      flags=[rflag("ACKNOWLEDGES_EXISTING_TASK", "duplicate", candidates=ack[1].task_id)],
                                      note=f"owner acknowledges {ack[1].task_id}"))
                continue
            claim = None if ack else self._claim_unowned(ctx, sent, c, m)      # applies whether or not the title also matched strongly
            if claim is not None:
                out.append(claim)
                continue
            if ack and ack[0] == "DATE_DIFFERS":
                m = MatchResult("MATCHED", ack[1].task_id, [], "owner restates the task with another date")
            elif ack and ack[0] == "AMBIGUOUS":
                flags.append(rflag("POSSIBLE_DUPLICATE", "duplicate", candidates=", ".join(t.task_id for t in ack[1]),
                                   detail="you own several tasks about this; not treated as an acknowledgement"))
            elif ack and ack[0] == "DIFFERENT_ACTION":
                flags.append(rflag("POSSIBLE_DUPLICATE", "duplicate", candidates=ack[1].task_id, detail="same object, different action"))
            if m.outcome == "MATCHED":
                t = next(x for x in ctx.tasks if x.task_id == m.task_id)
                if t.status in ("open", "in_progress"):
                    same_owner = owner is None or owner == t.owner_id
                    new_due = _dkey(snapshot["due"])
                    date_differs = new_due is not None and _dkey(t.due) is not None and new_due != _dkey(t.due)
                    if same_owner and not date_differs:
                        restated[c.candidate_id] = t.task_id
                        out.append(self._prop(ctx, sent, "NO_ACTION", task=t, key=c.candidate_id,
                                              flags=[rflag("RESTATED_EXISTING_TASK", "duplicate", candidates=t.task_id)],
                                              match=m.to_dict(), note=f"restates {t.task_id}"))
                        continue
                    if same_owner and date_differs:
                        fl = [rflag("RESTATED_WITH_DIFFERENT_DATE", "due", candidates=t.task_id,
                                    detail=f"{(t.due or {}).get('raw')} -> {snapshot['due']['raw']}")]
                        p = self._prop(ctx, sent, "PROPOSE_DUE_DATE_CHANGE", task=t, key=c.candidate_id, field="due", before=t.due,
                                       after=snapshot["due"], flags=fl + flags, match=m.to_dict(),
                                       needs_confirmation_from=sorted(({t.created_by, t.owner_id} - {None, ctx.env.sender_id})),
                                       note="restated request with a different deadline")
                        p.payload.update({"direct": False, "field": "due"})
                        out.append(p)
                        continue
                flags.append(rflag("POSSIBLE_DUPLICATE", "duplicate", candidates=t.task_id,
                                   detail="closed task" if t.status in ("completed", "cancelled") else "different owner"))
            elif m.outcome == "AMBIGUOUS_REFERENT":
                flags.append(rflag("POSSIBLE_DUPLICATE", "duplicate", candidates=", ".join(r["task_id"] for r in m.ranked)))
            p = self._prop(ctx, sent, "CREATE_TASK", key=c.candidate_id, field="__create__", after=snapshot, flags=flags, match=m.to_dict(),
                           note=f"evidence={hit.extras.get('evidence')}")
            p.payload.update({"candidate_id": c.candidate_id, "title": c.title, "owner_id": owner, "due": snapshot["due"],
                              "scheduled": snapshot["scheduled"], "evidence_text": c.evidence_text,
                              "provenance": {"phase4": c.provenance, "assignee": c.assignee.to_dict()}})
            out.append(p)
            created.append(c)
            clause = self._clause_dependency(ctx, sent, c, p, ents) or self._hint_dependency(ctx, sent, c, p, ents)
            if clause is not None:
                out.append(clause)
        return out + self._candidate_dependencies(ctx, sent, cands, {x.candidate_id for x in created}, restated, out)

    def _owner_acknowledgement(self, ctx, sent, c):
        """A first-person commitment to something the speaker already owns is an acknowledgement, not a new task.

        Returns ("ACK", task) only when the speaker owns exactly ONE open task sharing the object AND the commitment is generic
        ("take care of", "handle") or uses the same verb. Several candidate tasks, or a different action on the same object,
        are never silently merged: they return AMBIGUOUS / DIFFERENT_ACTION so the new task is created and flagged.
        """
        me = ctx.env.sender_id
        if not me or not FIRST_SINGULAR.search(sent.text):
            return None
        if c.assignee.participant_id not in (None, me):
            return None
        mine = [t for t in ctx.tasks if t.status in ("open", "in_progress") and t.owner_id == me]
        wanted = set(content_tokens(c.title, drop_filler=False)) - COMMITMENT_NOISE
        sharing = [t for t in mine if wanted & set(content_tokens(t.title, drop_filler=False))]
        if not sharing:
            return None
        if len(sharing) > 1:
            return ("AMBIGUOUS", sharing)
        t = sharing[0]
        new_due, old_due = (_dkey(c.due.to_dict()) if c.due else None), _dkey(t.due)
        first = lambda text: stem((re.findall(r"[a-z]+", text.lower()) or [""])[0])
        same_action = bool(GENERIC_COMMITMENT.match(c.title.strip())) or first(c.title) == first(t.title)
        if not same_action:
            return ("DIFFERENT_ACTION", t)
        if new_due is not None and old_due is not None and new_due != old_due:
            return ("DATE_DIFFERS", t)                    # the owner restates the task with another deadline
        return ("ACK", t)

    def _claim_unowned(self, ctx, sent, c, create_match: MatchResult):
        """'I can review the slides' about an existing UNASSIGNED task: propose assigning it to the speaker instead of a duplicate.

        One clear unowned task with the same action -> UPDATE_ASSIGNEE (subject to review). Several equally plausible unowned tasks ->
        a review proposal that lists the candidates and changes nothing until the reviewer chooses. Tasks owned by someone, closed
        tasks, a different action, or a non-first-person sentence never match.
        """
        me = ctx.env.sender_id
        if not me or not VOLUNTEER_CUE.match(sent.text) or c.assignee.participant_id not in (None, me):
            return None                                   # needs 'I can/I'll/I will...' leading the sentence; 'Ellen and I spoke' or 'I could leave' is not a claim
        pool = [t for t in ctx.tasks if t.status in ("open", "in_progress") and t.owner_id is None]
        if not pool:
            return None
        tokens = [t for t in content_tokens(c.title, drop_filler=False) if t not in COMMITMENT_NOISE]
        if not tokens:
            return None
        mr = self.matcher.match(self.store, ctx.ws, pool, sentence=c.title, tokens=tokens, speaker_id=me, in_reply_to=None,
                                current_seq=ctx.seq, op="UPDATE_ASSIGNEE", allow_anaphora=False)
        if mr.outcome == "NO_REFERENT":
            return None
        first = lambda text: stem((re.findall(r"[a-z]+", text.lower()) or [""])[0])
        candidates = [t for t in pool if t.task_id in {r["task_id"] for r in mr.ranked}] or pool
        if not (GENERIC_COMMITMENT.match(c.title.strip()) or any(first(c.title) == first(t.title) for t in candidates)):
            return None                                       # a different action on the same object is a new task
        info = rflag("CLAIMS_UNASSIGNED_TASK", "owner_id", candidates=", ".join(t.task_id for t in candidates), detail=ctx.env.sender_id)
        if mr.outcome == "MATCHED":
            t = next(x for x in pool if x.task_id == mr.task_id)
            return self._prop(ctx, sent, "UPDATE_ASSIGNEE", task=t, key=c.candidate_id, field="owner_id", before=None, after=me, flags=[info],
                              match=mr.to_dict(), note=f"{me} volunteers for the unassigned {t.task_id}")
        ids = ", ".join(r["task_id"] for r in mr.ranked)
        p = self._prop(ctx, sent, "UPDATE_ASSIGNEE", key=c.candidate_id, field="owner_id", before=None, after=me,
                       flags=[rflag("AMBIGUOUS_REFERENT", "referent", evidence=mr.reason, candidates=ids, text=sent.text)],
                       match=mr.to_dict(), note="several unassigned tasks could be meant; the reviewer must choose")
        p.payload.update({"needs_referent": True, "intent": "UPDATE_ASSIGNEE"})
        return p

    def _clause_dependency(self, ctx, sent, c, create_proposal, ents):
        """'<new task> once/after/when <clause>' where the clause names an EXISTING task -> ADD_DEPENDENCY (new task depends on it).

        Only an unambiguous match proposes an edge. A clause that matches several tasks is flagged for review; a clause that matches
        nothing (an event, a date, "when you can") proposes nothing. The dependent does not exist yet, so accepting the edge
        requires accepting the creation first.
        """
        tail = ctx.env.text[c.task_span["end"]:sent.end]
        m = CLAUSE_CUE.search(tail)
        if not m:
            return None
        return self._clause_edge(ctx, sent, c, create_proposal, m.group(1).strip(" .!?;,"), c.task_span["end"] + m.start(1), ents)

    def _hint_dependency(self, ctx, sent, c, create_proposal, ents):
        """Phase 7.5: the refinement stage found a prerequisite clause anywhere in the sentence ('After you finish X, ...', 'B once A')."""
        for h in ctx.options.get("clause_hints", []):
            if h.get("kind") != "task_reference" or h.get("dependent_entity_id") != c.task_span["id"]:
                continue
            a, b = h["prerequisite_range"]
            if not (sent.start <= a and b <= sent.end):
                continue
            p = self._clause_edge(ctx, sent, c, create_proposal, ctx.env.text[a:b].strip(" .!?;,"), a, ents, strip_names=True)
            if p is not None:
                p.payload["rule"] = h.get("rule")
                return p
        return None

    def _participant_words(self, ctx) -> set[str]:
        words: set[str] = set()
        for p in getattr(ctx.registry, "participants", []):
            words |= {w.lower() for w in re.findall(r"[A-Za-z]+", p.display_name)} | {str(p.id).lower()}
        return words

    def _clause_edge(self, ctx, sent, c, create_proposal, clause, base, ents, *, strip_names=False):
        spans = [(e["start"] - base, e["end"] - base) for e in ents if e["type"] in ("PERSON", "TEMPORAL") and e["start"] >= base]
        names = self._participant_words(ctx) if strip_names else set()      # the Phase 5 path keeps names (unchanged behaviour)
        tokens = [t for t in content_tokens(clause, spans) if t not in names]
        if not tokens:
            return None
        pool = [t for t in ctx.tasks if t.status != "cancelled"]
        mr = self.matcher.match(self.store, ctx.ws, pool, sentence=clause, tokens=tokens, speaker_id=ctx.env.sender_id,
                                in_reply_to=None, current_seq=ctx.seq, op="ADD_DEPENDENCY", allow_anaphora=False)
        if mr.outcome == "NO_REFERENT":
            return None
        if mr.outcome == "AMBIGUOUS_REFERENT":
            ids = ", ".join(r["task_id"] for r in mr.ranked)
            return self._prop(ctx, sent, "NO_ACTION", key=f"clause:{c.candidate_id}", match=mr.to_dict(),
                              flags=[rflag("DEPENDENCY_ENDPOINT_UNMATCHED", "dependency", detail=f"the prerequisite clause matches several tasks ({ids})")],
                              note="prerequisite clause is ambiguous")
        t = next(x for x in pool if x.task_id == mr.task_id)
        p = self._prop(ctx, sent, "ADD_DEPENDENCY", key=f"{c.candidate_id}>{t.task_id}", field="dependency", match=mr.to_dict(),
                       after={"dependent": c.candidate_id, "prerequisite": t.task_id}, note=f"prerequisite clause '{clause}' matches {t.task_id}")
        p.payload.update({"dependent_create_pid": create_proposal.proposal_id, "prerequisite_task_id": t.task_id, "evidence": sent.text,
                          "provenance": "rule"})
        return p

    def _reference_dependency(self, ctx, sent, h) -> list[ProposedOperation]:
        """'Deployment can't start until the test server is set up': both sides refer to EXISTING tasks; propose the edge only if both match uniquely."""
        names = self._participant_words(ctx)
        res = {}
        for side, key in (("dependent", "dependent_text"), ("prerequisite", "prerequisite_text")):
            toks = [t for t in content_tokens(h[key], drop_filler=True) if t not in names]
            res[side] = self.matcher.match(self.store, ctx.ws, ctx.tasks, sentence=h[key], tokens=toks, speaker_id=ctx.env.sender_id, in_reply_to=None,
                                           current_seq=ctx.seq, op="ADD_DEPENDENCY", allow_anaphora=False) if toks else None
        if any(r is None or r.outcome != "MATCHED" for r in res.values()) or res["dependent"].task_id == res["prerequisite"].task_id:
            return []
        dep, pre = res["dependent"].task_id, res["prerequisite"].task_id
        t = next(x for x in ctx.tasks if x.task_id == dep)
        p = self._prop(ctx, sent, "ADD_DEPENDENCY", task=t, key=f"{dep}>{pre}", field="dependency", after={"dependent": dep, "prerequisite": pre},
                       match={"left": res["dependent"].to_dict(), "right": res["prerequisite"].to_dict(), "outcome": "MATCHED"},
                       note=f"clause dependency ({h.get('pattern')}) between existing tasks")
        p.payload.update({"dependent_task_id": dep, "prerequisite_task_id": pre, "evidence": sent.text, "provenance": "rule", "rule": h.get("rule")})
        return [p]

    def _candidate_dependencies(self, ctx, sent, cands, created_ids, restated=None, siblings=None) -> list[ProposedOperation]:
        out = []
        restated = restated or {}
        for c in cands:
            for d in c.dependencies:
                pre = d["prerequisite_candidate_id"]
                if c.candidate_id in created_ids and pre in restated:
                    # the prerequisite merely restates an EXISTING task: the edge points at that task (no duplicate task is made)
                    tid = restated[pre]
                    p = self._prop(ctx, sent, "ADD_DEPENDENCY", key=f"{c.candidate_id}>{tid}", field="dependency", flags=[],
                                   note=f"clause dependency; the prerequisite restates {tid}", after={"dependent": c.candidate_id, "prerequisite": tid})
                    p.payload.update({"dependent_create_pid": self._create_pid(ctx, sent, c.candidate_id), "prerequisite_task_id": tid,
                                      "evidence": d.get("evidence_text"), "provenance": d.get("provenance", "rule")})
                    out.append(p)
                    continue
                if c.candidate_id not in created_ids or pre not in created_ids:
                    continue
                p = self._prop(ctx, sent, "ADD_DEPENDENCY", key=f"{c.candidate_id}>{pre}", field="dependency",
                               note="phase4 rule-path dependency (proposed, unvalidated)",
                               flags=[], after={"dependent": c.candidate_id, "prerequisite": pre})
                p.payload.update({"dependent_candidate_id": c.candidate_id, "prerequisite_candidate_id": pre,
                                  "evidence": d.get("evidence_text"), "provenance": d.get("provenance", "rule")})
                p.payload["requires_creates"] = [self._create_pid(ctx, sent, c.candidate_id), self._create_pid(ctx, sent, pre)]
                out.append(p)
        return out

    @staticmethod
    def _create_pid(ctx, sent, candidate_id: str) -> str:
        """Deterministic id of the CREATE_TASK proposal for a candidate (mirrors _prop())."""
        return "P-" + _h(ctx.ws, ctx.env.message_id, sent.index, "CREATE_TASK", "", candidate_id)

    # ------------------------------------------------------------------ COMPLETE / CANCEL / STATUS
    def _status_change(self, ctx, sent, hit, ents, temporals, cands) -> list[ProposedOperation]:
        op = hit.op
        target = {"COMPLETE_TASK": "completed", "CANCEL_TASK": "cancelled", "UPDATE_STATUS": hit.extras.get("new_status", "in_progress")}[op]
        m = self._match(ctx, sent, hit, ents, op)
        if m.outcome != "MATCHED":
            return [self._unmatched(ctx, sent, hit, op, m, ents, {"field": "status", "after": target})]
        t = next(x for x in ctx.tasks if x.task_id == m.task_id)
        if t.status == target:
            return [self._prop(ctx, sent, "NO_ACTION", task=t, key=op, match=m.to_dict(), note=f"{t.task_id} is already {target}",
                               flags=[rflag("ALREADY_IN_STATE", "status", detail=target)])]
        if target not in ALLOWED_TRANSITIONS[t.status]:
            return [self._prop(ctx, sent, "NO_ACTION", task=t, key=op, match=m.to_dict(), note=f"{t.status} -> {target} not allowed",
                               flags=[rflag("ILLEGAL_TRANSITION", "status", detail=t.status, title=t.title)])]
        flags = []
        if op == "COMPLETE_TASK" and t.owner_id and ctx.env.sender_id and ctx.env.sender_id != t.owner_id:
            flags.append(rflag("THIRD_PARTY_COMPLETION", "status", title=t.title, detail=f"reported by {ctx.env.sender_id}, owner {t.owner_id}"))
        p = self._prop(ctx, sent, op, task=t, field="status", before=t.status, after=target, flags=flags, match=m.to_dict(),
                       note=f"cue={hit.cue!r}")
        return [p]

    def _reopen(self, ctx, sent, hit, ents, temporals, cands) -> list[ProposedOperation]:
        m = self._match(ctx, sent, hit, ents, "COMPLETE_TASK")
        if m.outcome == "MATCHED":
            t = next(x for x in ctx.tasks if x.task_id == m.task_id)
            if t.status == "completed":
                return [self._prop(ctx, sent, "NO_ACTION", task=t, key="reopen", match=m.to_dict(),
                                   flags=[rflag("REOPEN_REQUESTED", "status", title=t.title)], note="reopening is not supported")]
        return [self._no_action(ctx, sent, "statement that something is not done; no completed task is contradicted", key="not-done")]

    # ------------------------------------------------------------------ UPDATE_ASSIGNEE
    def _assignee(self, ctx, sent, hit, ents, temporals, cands) -> list[ProposedOperation]:
        persons = [e for e in ents if e["type"] == "PERSON"]
        res = resolve_assignee(persons, {"start": sent.start, "end": sent.end, "text": sent.text}, ctx.env, ctx.registry)
        resolved = res.status in RESOLVED_ASSIGNEE and bool(res.participant_id)
        new_owner = res.participant_id if resolved else None
        extra_flags = [] if resolved else [rflag("UNRESOLVED_NEW_OWNER", "owner_id", detail=res.basis or res.status)]
        m = self._match(ctx, sent, hit, ents, "UPDATE_ASSIGNEE")
        if m.outcome != "MATCHED":
            return [self._unmatched(ctx, sent, hit, "UPDATE_ASSIGNEE", m, ents,
                                    {"field": "owner_id", "after": new_owner, "flags": extra_flags, "payload": {"assignee": res.to_dict()}})]
        t = next(x for x in ctx.tasks if x.task_id == m.task_id)
        if t.status in ("completed", "cancelled"):
            return [self._prop(ctx, sent, "NO_ACTION", task=t, key="assign", match=m.to_dict(),
                               flags=[rflag("TASK_ALREADY_CLOSED", "owner_id", detail=t.status)], note="closed task")]
        if resolved:
            if new_owner == t.owner_id:
                return [self._prop(ctx, sent, "NO_ACTION", task=t, key="assign", match=m.to_dict(),
                                   flags=[rflag("ALREADY_IN_STATE", "owner_id", detail=f"owner is already {t.owner_id}")], note="same owner")]
            flags = [rflag("TENTATIVE_REQUEST", "request")] if hit.tentative else []
            p = self._prop(ctx, sent, "UPDATE_ASSIGNEE", task=t, field="owner_id", before=t.owner_id, after=new_owner,
                           flags=flags, match=m.to_dict(), note=f"new owner via {res.basis}")
            p.payload["assignee"] = res.to_dict()
            return [p]
        p = self._prop(ctx, sent, "UPDATE_ASSIGNEE", task=t, field="owner_id", before=t.owner_id, after=None, match=m.to_dict(),
                       flags=[rflag("UNRESOLVED_NEW_OWNER", "owner_id", title=t.title, detail=res.basis or res.status)],
                       note="new owner unresolved; reviewer must supply owner_id")
        p.payload["assignee"] = res.to_dict()
        return [p]

    # ------------------------------------------------------------------ DATE CHANGE
    def _new_temporal(self, ctx, sent, temporals, relation_hint):
        ents = sorted(temporals, key=lambda e: e["start"])
        groups: list[list[dict]] = []
        for e in ents:
            if groups:
                gap = ctx.env.text[groups[-1][-1]["end"]:e["start"]]
                if re.fullmatch(r"[\s,]*(?:at|@)?[\s,]*", gap, re.I):
                    groups[-1].append(e)
                    continue
            groups.append([e])
        chosen = None
        for g in groups:
            if DATE_PREP.search(ctx.env.text[max(sent.start, g[0]["start"] - 14):g[0]["start"]]):
                chosen = g
        if chosen is None and len(groups) == 1:
            chosen = groups[0]
        if chosen is None:
            return None, None
        raw = ctx.env.text[chosen[0]["start"]:chosen[-1]["end"]]
        tv = normalize_temporal(raw, reference_ts=ctx.env.timestamp, timezone=ctx.env.timezone, relation_hint=relation_hint,
                                config=ctx.p4cfg.get("temporal"))
        return tv, raw

    def _date_change(self, ctx, sent, hit, ents, temporals, cands) -> list[ProposedOperation]:
        m = self._match(ctx, sent, hit, ents, "DATE_CHANGE")
        if m.outcome != "MATCHED":
            hint = hit.extras.get("field_hint") or "due"
            label = "DUE_ON" if hint == "due" else "SCHEDULED_ON"
            tv, raw = self._new_temporal(ctx, sent, temporals, label)
            intended = {"field": hint, "after": tv.to_dict() if tv else None, "payload": {"direct": False, "field": hint, "raw": raw}}
            if tv is None or tv.status != "RESOLVED":
                intended["flags"] = [rflag("UNRESOLVED_NEW_DATE", hint, detail=f"'{raw}' is {tv.status if tv else 'ambiguous'}")]
            return [self._unmatched(ctx, sent, hit, "DATE_CHANGE", m, ents, intended)]
        t = next(x for x in ctx.tasks if x.task_id == m.task_id)
        return [self._date_proposal(ctx, sent, hit, ents, temporals, t, m)]

    def _date_proposal(self, ctx, sent, hit, ents, temporals, t: Task, m: MatchResult, *, counter_of: Optional[str] = None) -> ProposedOperation:
        if t.status in ("completed", "cancelled"):
            return self._prop(ctx, sent, "NO_ACTION", task=t, key="date", match=m.to_dict(),
                              flags=[rflag("TASK_ALREADY_CLOSED", "due", detail=t.status)], note="closed task")
        hint = hit.extras.get("field_hint")
        if hint is None:
            hint = "scheduled" if (t.scheduled and not t.due) else "due"
        label = "DUE_ON" if hint == "due" else "SCHEDULED_ON"
        tv, raw = self._new_temporal(ctx, sent, temporals, label)
        current = getattr(t, hint)
        if tv is None:
            p = self._prop(ctx, sent, "PROPOSE_DUE_DATE_CHANGE", task=t, field=hint, before=current, after=None, match=m.to_dict(),
                           flags=[rflag("UNRESOLVED_NEW_DATE", hint, detail="several dates in the sentence, none clearly the new one")],
                           note="new date ambiguous")
            p.payload.update({"direct": False, "field": hint})
            return p
        after = tv.to_dict()
        flags = [f.to_dict() for f in temporal_flags(tv, hint, label, "", ctx.p4cfg)]
        if tv.status != "RESOLVED":
            flags.append(rflag("UNRESOLVED_NEW_DATE", hint, detail=f"'{raw}' is {tv.status}"))
        if tv.status == "RESOLVED" and _dkey(after) == _dkey(current):
            return self._prop(ctx, sent, "NO_ACTION", task=t, key="date", match=m.to_dict(), note="task already has this date",
                              flags=[rflag("ALREADY_IN_STATE", hint, detail=f"{hint} is already {raw}")])
        creators = {t.created_by, t.owner_id} - {None}
        speaker = ctx.env.sender_id
        direct = (not hit.tentative) and speaker in creators
        needs = sorted(creators - {speaker}) if not direct else []
        pend = t.pending_changes.get(hint)
        other_pending = [p for p in self.store.list_proposals(ctx.ws, status="pending", task_id=t.task_id, operation="PROPOSE_DUE_DATE_CHANGE")
                         if p.payload.get("field") == hint and p.proposer_id != speaker]
        if (pend and pend.get("proposer_id") != speaker and _dkey(pend.get("value")) != _dkey(after)) or other_pending or counter_of:
            flags.append(rflag("CONFLICTING_PROPOSAL", hint, detail=(counter_of or (pend or {}).get("proposal_id") or other_pending[0].proposal_id)))
        if hit.tentative:
            flags.append(rflag("TENTATIVE_REQUEST", hint))
        p = self._prop(ctx, sent, "PROPOSE_DUE_DATE_CHANGE", task=t, field=hint, before=current, after=after, flags=flags,
                       match=m.to_dict(), needs_confirmation_from=needs,
                       note=("direct change by creator/owner" if direct else "proposal needs confirmation") + f"; cue={hit.cue!r}")
        p.payload.update({"direct": direct, "field": hint, "raw": raw})
        return p

    # ------------------------------------------------------------------ CONFIRM / DECLINE
    def _pending_info(self, ctx: _Ctx) -> dict[str, list[dict[str, Any]]]:
        """task_id -> pending changes (applied pending_changes plus unreviewed PROPOSE proposals)."""
        info: dict[str, list[dict]] = {}
        for t in ctx.tasks:
            for fld, pc in (t.pending_changes or {}).items():
                info.setdefault(t.task_id, []).append({"field": fld, "value": pc.get("value"), "proposer_id": pc.get("proposer_id"),
                                                       "proposal_id": pc.get("proposal_id"), "applied": True,
                                                       "needs": pc.get("needs_confirmation_from") or []})
        for p in self.store.list_proposals(ctx.ws, status="pending", operation="PROPOSE_DUE_DATE_CHANGE"):
            if p.task_id and not p.payload.get("direct") and p.after and p.payload.get("thread_id") == ctx.thread:
                info.setdefault(p.task_id, []).append({"field": p.field, "value": p.after, "proposer_id": p.proposer_id,
                                                       "proposal_id": p.proposal_id, "applied": False, "needs": p.needs_confirmation_from})
        return info

    def _confirm(self, ctx, sent, hit, ents, temporals, cands) -> list[ProposedOperation]:
        info = self._pending_info(ctx)
        if not info:
            return [self._no_action(ctx, sent, "acknowledgement with no pending change", flags=[rflag("NO_PENDING_PROPOSAL", "confirm")], key="confirm")]
        pool = [t for t in ctx.tasks if t.task_id in info]
        if len(pool) == 1 and not ctx.env.in_reply_to:
            m = MatchResult("MATCHED", pool[0].task_id, [{"task_id": pool[0].task_id, "score": 100.0, "signals": {"single_pending_change": 100.0}}],
                            "only one task has a pending change")
        else:
            m = self._match(ctx, sent, hit, ents, "CONFIRM_DUE_DATE_CHANGE", tasks=pool)
            if m.outcome != "MATCHED" and len(pool) == 1:
                m = MatchResult("MATCHED", pool[0].task_id, m.ranked, "only one task has a pending change")
        if m.outcome != "MATCHED":
            return [self._unmatched(ctx, sent, hit, "CONFIRM_DUE_DATE_CHANGE", m, ents)]
        t = next(x for x in ctx.tasks if x.task_id == m.task_id)
        pend = sorted(info[t.task_id], key=lambda x: (not x["applied"], x["proposal_id"] or ""))[-1]
        field = pend["field"]
        # a reply that names a different date is a counter-proposal, not a confirmation
        if temporals:
            tv, raw = self._new_temporal(ctx, sent, temporals, "DUE_ON" if field == "due" else "SCHEDULED_ON")
            if tv is not None and tv.status == "RESOLVED" and _dkey(tv.to_dict()) != _dkey(pend["value"]):
                hit2 = IntentHit(op="DATE_CHANGE", tentative=True, extras={"field_hint": field})
                return [self._date_proposal(ctx, sent, hit2, ents, temporals, t, m, counter_of=pend["proposal_id"])]
        speaker = ctx.env.sender_id
        flags = []
        if speaker and speaker == pend["proposer_id"]:
            return [self._prop(ctx, sent, "NO_ACTION", task=t, key="selfconfirm", match=m.to_dict(),
                               flags=[rflag("UNAUTHORIZED_CONFIRMER", field, detail="the proposer cannot confirm their own change")],
                               note="self-confirmation")]
        if pend["needs"] and speaker not in pend["needs"]:
            flags.append(rflag("UNAUTHORIZED_CONFIRMER", field, detail=f"{speaker} is not one of {', '.join(pend['needs'])}"))
        p = self._prop(ctx, sent, "CONFIRM_DUE_DATE_CHANGE", task=t, field=field, before=getattr(t, field), after=pend["value"],
                       flags=flags, match=m.to_dict(), note=f"confirms {pend['proposal_id']}")
        p.payload.update({"field": field, "pending_proposal_id": pend["proposal_id"], "pending_applied": pend["applied"],
                          "requires_proposal": None if pend["applied"] else pend["proposal_id"]})
        return [p]

    def _decline(self, ctx, sent, hit, ents, temporals, cands) -> list[ProposedOperation]:
        info = self._pending_info(ctx)
        if not info:
            return [self._no_action(ctx, sent, "decline with no pending change", flags=[rflag("NO_PENDING_PROPOSAL", "decline")], key="decline")]
        pool = [t for t in ctx.tasks if t.task_id in info]
        m = (MatchResult("MATCHED", pool[0].task_id, [], "only one task has a pending change") if len(pool) == 1
             else self._match(ctx, sent, hit, ents, "CONFIRM_DUE_DATE_CHANGE", tasks=pool))
        if m.outcome != "MATCHED":
            return [self._unmatched(ctx, sent, hit, "CONFIRM_DUE_DATE_CHANGE", m, ents)]
        t = next(x for x in ctx.tasks if x.task_id == m.task_id)
        pend = info[t.task_id][-1]
        p = self._prop(ctx, sent, "NO_ACTION", task=t, key="decline", match=m.to_dict(), flags=[rflag("PROPOSAL_DECLINED", pend["field"])],
                       note=f"decline of {pend['proposal_id']}")
        p.payload.update({"pending_proposal_id": pend["proposal_id"], "field": pend["field"]})
        return [p]

    # ------------------------------------------------------------------ DEPENDENCY (cue-based)
    def _dependency(self, ctx, sent, hit, ents, temporals, cands) -> list[ProposedOperation]:
        res: dict[str, MatchResult] = {}
        for side in ("left", "right"):
            text = hit.extras.get(side, "")
            toks = content_tokens(text, drop_filler=False)
            res[side] = self.matcher.match(self.store, ctx.ws, ctx.tasks, sentence=text, tokens=toks, speaker_id=ctx.env.sender_id,
                                           in_reply_to=ctx.env.in_reply_to, current_seq=ctx.seq, op="ADD_DEPENDENCY", allow_anaphora=bool(side == "left" and not toks))
        if any(r.outcome != "MATCHED" for r in res.values()):
            detail = ", ".join(f"{k}:{v.outcome}" for k, v in res.items())
            return [self._no_action(ctx, sent, "dependency endpoints not both identified",
                                    flags=[rflag("DEPENDENCY_ENDPOINT_UNMATCHED", "dependency", detail=detail)], key="dep")]
        dep, pre = res["left"].task_id, res["right"].task_id
        if dep == pre:
            return [self._no_action(ctx, sent, "self-dependency", flags=[rflag("SELF_DEPENDENCY", "dependency")], key="dep")]
        t = next(x for x in ctx.tasks if x.task_id == dep)
        p = self._prop(ctx, sent, "ADD_DEPENDENCY", task=t, key=f"{dep}>{pre}", field="dependency",
                       after={"dependent": dep, "prerequisite": pre}, match={"left": res["left"].to_dict(), "right": res["right"].to_dict(), "outcome": "MATCHED"},
                       note="explicit prerequisite wording")
        p.payload.update({"dependent_task_id": dep, "prerequisite_task_id": pre, "evidence": sent.text, "provenance": "rule"})
        return [p]

    # ================================================================== review actions
    def accept(self, workspace_id: str, proposal_id: str, actor: str, *, expected_version: Optional[int] = None,
               edits: Optional[Mapping[str, Any]] = None, idempotency_key: Optional[str] = None) -> dict[str, Any]:
        ws = workspace_id
        with self.store.transaction():
            key = idempotency_key or f"accept:{proposal_id}"
            prior = self.store.get_idempotent(ws, key)
            if prior is not None:
                return {**prior, "replayed": True}
            p = self.store.get_proposal(ws, proposal_id)
            if p is None:
                raise ReconciliationError("NOT_FOUND", proposal_id)
            if p.status != "pending":
                raise ReconciliationError("ALREADY_RESOLVED", f"{proposal_id} is {p.status}")
            result = self._apply(ws, p, actor, expected_version, dict(edits or {}))
            self.store.update_proposal(ws, proposal_id, status="applied", resolved_at=self.store.now(), resolved_by=actor,
                                       resolution_note="edited" if edits else None)
            self.store.save_idempotent(ws, key, result)
            return result

    edit_and_accept = accept

    def dismiss(self, workspace_id: str, proposal_id: str, actor: str, reason: str = "") -> None:
        with self.store.transaction():
            p = self.store.get_proposal(workspace_id, proposal_id)
            if p is None:
                raise ReconciliationError("NOT_FOUND", proposal_id)
            if p.status != "pending":
                raise ReconciliationError("ALREADY_RESOLVED", f"{proposal_id} is {p.status}")
            self.store.update_proposal(workspace_id, proposal_id, status="dismissed", resolved_at=self.store.now(),
                                       resolved_by=actor, resolution_note=reason)

    def reject_pending_change(self, workspace_id: str, task_id: str, field: str, actor: str, *, expected_version: int,
                              reason: str = "") -> dict[str, Any]:
        """Clear an applied pending date change (e.g. after a decline). The active date stays as it was."""
        ws = workspace_id
        with self.store.transaction():
            t = self.store.get_task(ws, task_id)
            if t is None or field not in t.pending_changes:
                raise ReconciliationError("NOT_FOUND", f"no pending {field} change on {task_id}")
            old = t.pending_changes[field]
            pend = {k: v for k, v in t.pending_changes.items() if k != field}
            v = self.store.update_task(ws, task_id, expected_version, {"pending_changes": pend})
            eid = self.store.append_history(ws, task_id, operation="REJECT_PENDING_CHANGE", field=f"pending_{field}", before=old, after=None,
                                            actor=actor, source_kind="human", note=reason)
            return {"task_id": task_id, "version": v, "history_event_ids": [eid]}

    def manual_edit(self, workspace_id: str, task_id: str, actor: str, expected_version: int, changes: Mapping[str, Any], *,
                    idempotency_key: Optional[str] = None, note: str = "") -> dict[str, Any]:
        ws = workspace_id
        with self.store.transaction():
            if idempotency_key:
                prior = self.store.get_idempotent(ws, f"edit:{idempotency_key}")
                if prior is not None:
                    return {**prior, "replayed": True}
            t = self.store.get_task(ws, task_id)
            if t is None:
                raise ReconciliationError("NOT_FOUND", task_id)
            allowed = {"title", "owner_id", "due", "scheduled", "status"}
            if set(changes) - allowed:
                raise ReconciliationError("FIELD_NOT_EDITABLE", ", ".join(sorted(set(changes) - allowed)))
            if "status" in changes and changes["status"] != t.status and changes["status"] not in ALLOWED_TRANSITIONS[t.status]:
                raise ReconciliationError("ILLEGAL_TRANSITION", f"{t.status} -> {changes['status']}")
            version = self.store.update_task(ws, task_id, expected_version, dict(changes))
            ids = [self.store.append_history(ws, task_id, operation="MANUAL_EDIT", field=f, before=getattr(t, f), after=v, actor=actor,
                                             source_kind="human", note=note) for f, v in changes.items()]
            result = {"task_id": task_id, "version": version, "history_event_ids": ids, "applied": True}
            if idempotency_key:
                self.store.save_idempotent(ws, f"edit:{idempotency_key}", result)
            return result

    # ------------------------------------------------------------------ apply
    def _apply(self, ws: str, p: ProposedOperation, actor: str, expected_version: Optional[int], edits: dict[str, Any]) -> dict[str, Any]:
        op = p.operation
        kind = "human" if edits else p.source_kind
        note = p.note + (f" | reviewer edits: {json.dumps(edits, default=str, sort_keys=True)}" if edits else "")
        if op == "NO_ACTION":
            return {"proposal_id": p.proposal_id, "operation": op, "applied": False, "task_id": p.task_id}
        if op == "CREATE_TASK":
            return self._apply_create(ws, p, actor, edits, kind, note)
        if op == "ADD_DEPENDENCY":
            return self._apply_dependency(ws, p, actor, kind, note)

        referent_chosen = "task_id" in edits
        task_id = edits.get("task_id") or p.task_id
        if not task_id:
            raise ReconciliationError("REFERENT_REQUIRED", "this proposal has no task; accept with edits={'task_id': ...}")
        t = self.store.get_task(ws, task_id)
        if t is None:
            raise ReconciliationError("NOT_FOUND", task_id)
        ev = expected_version if expected_version is not None else (None if referent_chosen else p.base_version)
        req = p.payload.get("requires_proposal")
        if req and expected_version is None and not referent_chosen:
            # a confirmation made before its proposal was reviewed: the proposal's own acceptance legitimately bumped the
            # version, so expect the version it produced (any other change in between is still caught as stale).
            prereq = self.store.get_idempotent(ws, f"accept:{req}")
            if prereq and prereq.get("version") is not None:
                ev = prereq["version"]
        ev = t.version if ev is None else ev
        if ev != t.version:
            raise StaleVersion(task_id, ev, t.version)
        field = p.field
        events: list[int] = []

        def log(f, before, after, operation=op):
            events.append(self.store.append_history(ws, task_id, operation=operation, field=f, before=before, after=after, actor=actor,
                                                    source_kind=kind, proposal_id=p.proposal_id, message_id=p.message_id, note=note))

        fields: dict[str, Any] = {}
        if op in ("COMPLETE_TASK", "CANCEL_TASK", "UPDATE_STATUS"):
            target = edits.get("status") or p.after
            if t.status == target:
                raise ReconciliationError("ALREADY_IN_STATE", f"{task_id} is already {target}")
            if target not in ALLOWED_TRANSITIONS[t.status]:
                raise ReconciliationError("ILLEGAL_TRANSITION", f"{t.status} -> {target}")
            fields["status"] = target
            log("status", t.status, target)
        elif op == "UPDATE_ASSIGNEE":
            new_owner = edits.get("owner_id", p.after)
            if new_owner is None:
                raise ReconciliationError("UNRESOLVED_VALUE", "new owner is unresolved; accept with edits={'owner_id': ...}")
            if t.status in ("completed", "cancelled"):
                raise ReconciliationError("ILLEGAL_TRANSITION", f"cannot reassign a {t.status} task")
            fields["owner_id"] = new_owner
            log("owner_id", t.owner_id, new_owner)
        elif op in ("PROPOSE_DUE_DATE_CHANGE", "CONFIRM_DUE_DATE_CHANGE"):
            field = edits.get("field") or field or "due"
            if t.status in ("completed", "cancelled"):
                raise ReconciliationError("ILLEGAL_TRANSITION", f"cannot change dates of a {t.status} task")
            new_val = self._edited_value(p, edits)
            current = getattr(t, field)
            if op == "CONFIRM_DUE_DATE_CHANGE":
                req = p.payload.get("requires_proposal")
                if req:
                    dep = self.store.get_proposal(ws, req)
                    if dep is None or dep.status != "applied":
                        raise ReconciliationError("PREREQUISITE_PENDING", f"accept {req} first")
                pend = t.pending_changes.get(field)
                if pend is None:
                    raise ReconciliationError("NO_PENDING_CHANGE", f"{task_id} has no pending {field} change")
                new_val = new_val if "after" in edits or "after_raw" in edits else pend["value"]
                _guard_overwrite(current, new_val)
                fields[field] = new_val
                rest = {k: v for k, v in t.pending_changes.items() if k != field}
                fields["pending_changes"] = rest
                log(field, current, new_val)
                log(f"pending_{field}", pend, None)
            elif p.payload.get("direct"):
                _guard_overwrite(current, new_val)
                fields[field] = new_val
                log(field, current, new_val)
            else:
                if new_val is None:
                    raise ReconciliationError("UNRESOLVED_VALUE", "no new date; accept with edits={'after_raw': ...}")
                pending = dict(t.pending_changes)
                old = pending.get(field)
                pending[field] = {"value": new_val, "proposer_id": p.proposer_id, "proposal_id": p.proposal_id,
                                  "needs_confirmation_from": p.needs_confirmation_from}
                fields["pending_changes"] = pending
                log(f"pending_{field}", old, pending[field])
            for other in self.store.list_proposals(ws, status="pending", task_id=task_id):
                if other.proposal_id == p.proposal_id or other.payload.get("field") != field:
                    continue
                answers_this = other.operation == "CONFIRM_DUE_DATE_CHANGE" and other.payload.get("pending_proposal_id") == p.proposal_id
                if other.operation in ("PROPOSE_DUE_DATE_CHANGE", "CONFIRM_DUE_DATE_CHANGE") and not answers_this:
                    self.store.update_proposal(ws, other.proposal_id, status="superseded", resolved_at=self.store.now(), resolved_by=actor,
                                               resolution_note=f"superseded by {p.proposal_id}")
        else:  # pragma: no cover
            raise ReconciliationError("UNSUPPORTED_OPERATION", op)
        version = self.store.update_task(ws, task_id, ev, fields)
        self.store.touch_task(ws, task_id, p.message_id, p.payload.get("seq", t.last_touched_seq))
        if referent_chosen and not p.task_id:
            self.store.update_proposal(ws, p.proposal_id, task_id=task_id)
        return {"proposal_id": p.proposal_id, "operation": op, "task_id": task_id, "version": version, "history_event_ids": events, "applied": True}

    def _edited_value(self, p: ProposedOperation, edits: Mapping[str, Any]):
        if "after" in edits:
            return edits["after"]
        if "after_raw" in edits:
            tv = normalize_temporal(edits["after_raw"], reference_ts=p.payload.get("reference_ts"), timezone=p.payload.get("timezone"),
                                    config=self.phase4_config.get("temporal"))
            return tv.to_dict()
        return p.after

    def _apply_create(self, ws, p, actor, edits, kind, note) -> dict[str, Any]:
        pl = p.payload
        title = edits.get("title", pl["title"])
        task_id = self.store.next_task_id(ws)
        owner = edits.get("owner_id", pl.get("owner_id"))
        due = edits.get("due", pl.get("due"))
        sched = edits.get("scheduled", pl.get("scheduled"))
        now = self.store.now()
        task = Task(task_id=task_id, workspace_id=ws, thread_id=pl.get("thread_id", "default"), title=title, owner_id=owner, due=due,
                    scheduled=sched, status="open", source_message_id=p.message_id, evidence_text=pl.get("evidence_text", ""), version=1,
                    created_by=p.proposer_id, created_at=now, last_touched_message_id=p.message_id, last_touched_seq=pl.get("seq", 0),
                    provenance=pl.get("provenance", {}))
        self.store.insert_task(task)
        snapshot = {"title": title, "owner_id": owner, "due": due, "scheduled": sched, "status": "open", "thread_id": task.thread_id,
                    "created_by": p.proposer_id, "pending_changes": {}}
        eid = self.store.append_history(ws, task_id, operation="CREATE_TASK", field="__create__", before=None, after=snapshot, actor=actor,
                                        source_kind=kind, proposal_id=p.proposal_id, message_id=p.message_id, note=note)
        self.store.update_proposal(ws, p.proposal_id, task_id=task_id)
        return {"proposal_id": p.proposal_id, "operation": "CREATE_TASK", "task_id": task_id, "version": 1, "history_event_ids": [eid], "applied": True}

    def _resolve_candidate_task(self, ws: str, candidate_pid: str) -> Optional[str]:
        if candidate_pid.startswith("candidate:"):
            return None
        pr = self.store.get_proposal(ws, candidate_pid)
        return pr.task_id if pr and pr.status == "applied" else None

    def _apply_dependency(self, ws, p, actor, kind, note) -> dict[str, Any]:
        pl = p.payload
        dep, pre = pl.get("dependent_task_id"), pl.get("prerequisite_task_id")
        if pl.get("dependent_create_pid"):
            dep = self._resolve_candidate_task(ws, pl["dependent_create_pid"])
            pre = pl.get("prerequisite_task_id")
            if not dep:
                raise ReconciliationError("PREREQUISITE_PENDING", "accept the creation of the new task first")
        elif pl.get("requires_creates"):
            dep_pid, pre_pid = pl["requires_creates"]
            dep, pre = self._resolve_candidate_task(ws, dep_pid), self._resolve_candidate_task(ws, pre_pid)
            if not dep or not pre:
                raise ReconciliationError("PREREQUISITE_PENDING", "accept the task creations for both endpoints first")
        t = self.store.get_task(ws, dep)
        if t is None or self.store.get_task(ws, pre) is None:
            raise ReconciliationError("NOT_FOUND", f"dependency endpoints {dep}, {pre}")
        ok, reason = self.dependency_validator(self.store, ws, dep, pre)
        edge = DependencyEdge(edge_id="E-" + _h(ws, dep, pre), workspace_id=ws, dependent_task_id=dep, prerequisite_task_id=pre,
                              status="accepted" if ok else "rejected", evidence=pl.get("evidence") or "", source_message_id=p.message_id,
                              source_kind=kind, reason=reason, proposal_id=p.proposal_id)
        existing = next((d for d in self.store.list_dependencies(ws) if d.edge_id == edge.edge_id), None)
        if existing is None:
            self.store.insert_dependency(edge)
        elif existing.status == "accepted":
            edge.status, edge.reason = "accepted", "already accepted"      # a repeat proposal never demotes an accepted edge
        else:
            self.store.set_dependency_status(ws, edge.edge_id, edge.status, edge.reason)   # re-decision of a held/rejected edge
        eid = self.store.append_history(ws, dep, operation="ADD_DEPENDENCY", field="dependency", before=None, after=edge.to_dict(), actor=actor,
                                        source_kind=kind, proposal_id=p.proposal_id, message_id=p.message_id, note=note)
        self.store.update_proposal(ws, p.proposal_id, task_id=dep)
        return {"proposal_id": p.proposal_id, "operation": "ADD_DEPENDENCY", "task_id": dep, "edge_id": edge.edge_id, "edge_status": edge.status,
                "reason": reason, "history_event_ids": [eid], "applied": True}

    @staticmethod
    def _default_dependency_validator(store: TaskStore, ws: str, dependent: str, prerequisite: str) -> tuple[bool, str]:
        """Phase 5 placeholder: endpoints exist and differ. Phase 6 replaces this with cycle detection."""
        if dependent == prerequisite:
            return False, "self-dependency"
        return True, ""
