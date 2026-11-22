#!/usr/bin/env python3
"""Select diverse, provisional Text2Task candidates from cleaned MailEx.

MailEx annotations are used only as selection signals.  The emitted coverage
flags are provisional and explicitly require human verification; this script
does not create Text2Task gold labels.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SPLITS = ("train", "dev", "test")
DEFAULT_TARGETS = {"train": 450, "dev": 60, "test": 90}
DEFAULT_SEED = 20261030
SELECTION_VERSION = "1.0.0"

REQUEST_EVENTS = {
    "Request_Action",
    "Request_Data",
    "Request_Meeting",
    "Request_Action_Data",
    "Request_Meeting_Data",
}
ACTION_EVENTS = {"Request_Action", "Deliver_Action_Data", "Amend_Action_Data"}
PLANNED_EVENTS = {"Deliver_Action_Data", "Deliver_Meeting_Data"}
SCHEDULE_EVENTS = {"Request_Meeting", "Deliver_Meeting_Data", "Amend_Meeting_Data"}
UPDATE_EVENTS = {"Amend_Action_Data", "Amend_Meeting_Data", "Amend_Data"}
POTENTIAL_TASK_EVENTS = REQUEST_EVENTS | ACTION_EVENTS | PLANNED_EVENTS | UPDATE_EVENTS

FLAG_DESCRIPTIONS = {
    "explicit_actionable_request": "Request-like MailEx event or explicit request language.",
    "commitment_or_planned_action": "Future commitment/planning language or planned-action event.",
    "multiple_tasks": "At least two potential task event instances or multiple distinct request/action cues.",
    "task_ownership": "MailEx member/owner argument evidence or explicit ownership language.",
    "explicit_deadline": "Date/time event argument or deterministic deadline expression.",
    "scheduled_activity": "Meeting/schedule event or explicit scheduling language.",
    "temporal_expression": "Deterministic date, time, relative-time, or ordering expression.",
    "possible_prerequisite": "Action-conditioned dependency expression; connector alone is insufficient.",
    "action_update_across_thread": "Multi-turn thread with repeated action/update evidence.",
    "negated_canceled_or_completed": "Negated, canceled, completed, or status-update action language.",
    "ambiguous_ownership_or_deadline": "Action candidate with missing or vague owner/deadline evidence.",
    "no_actionable_tasks": "No relevant MailEx event and no deterministic action/request cue.",
    "multi_email_scenario": "Record belongs to a multi-turn thread with repeated action or update evidence.",
}

EXPLICIT_REQUEST_RE = re.compile(
    r"\b(?:please|could you|can you|would you|will you|need you to|let me know|"
    r"send me|provide me|remind me|make sure|do you mind)\b",
    re.I,
)
ACTION_CUE_RE = re.compile(
    r"\b(?:please|need(?:s|ed)? to|must|should|will|shall|plan(?:s|ned)? to|intend(?:s|ed)? to|"
    r"going to|send|provide|review|complete|finish|approve|call|meet|deliver|update|follow[ -]?up|"
    r"prepare|file|submit|check|confirm|schedule|create|forward|contact|restore|process|execute|"
    r"receive|agree|start|begin|leave|arrive|close|open|resolve|respond|reply)\b",
    re.I,
)
DEPENDENCY_ACTION_RE = re.compile(
    r"\b(?:please|need(?:s|ed)? to|must|should|plan(?:s|ned)? to|intend(?:s|ed)? to|going to|"
    r"send|sent|provide|review|complete|finish|approve|call|meet|deliver|update|follow[ -]?up|"
    r"prepare|file|submit|check|confirm|schedule|create|forward|contact|restore|process|execute|"
    r"receive|agree|start|begin|close|open|resolve|respond|reply|sign|compile|draft|request)\b",
    re.I,
)
COMMITMENT_RE = re.compile(
    r"\b(?:i|we|he|she|they)\s+(?:will|shall|plan to|intend to|am going to|are going to|"
    r"can|expect to|hope to|commit to)\b|\b(?:will|shall)\s+(?:send|provide|review|complete|"
    r"finish|call|meet|deliver|update|prepare|file|submit|check|confirm|schedule|create|forward)",
    re.I,
)
DEADLINE_PATTERNS = {
    "by_time_or_date": re.compile(
        r"\bby\s+(?:eod|cob|close of business|noon|midnight|today|tomorrow|tonight|"
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|next\s+\w+|"
        r"\d{1,2}(?::\d{2})?\s*(?:am|pm)|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b",
        re.I,
    ),
    "due_or_deadline": re.compile(r"\b(?:due|deadline|no later than)\b.{0,50}", re.I),
    "asap": re.compile(r"\b(?:asap|as soon as possible)\b", re.I),
}
TEMPORAL_PATTERNS = {
    "relative_time": re.compile(
        r"\b(?:today|tomorrow|tonight|yesterday|this\s+(?:morning|afternoon|evening|week|month)|"
        r"next\s+(?:week|month|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
        r"last\s+(?:week|month))\b",
        re.I,
    ),
    "weekday_or_month": re.compile(
        r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|"
        r"april|may|june|july|august|september|october|november|december)\b",
        re.I,
    ),
    "clock_or_numeric_date": re.compile(
        r"\b(?:\d{1,2}:\d{2}\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm)|"
        r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b",
        re.I,
    ),
    "ordering_connector": re.compile(r"\b(?:before|after|once|until|upon|prior to|following)\b", re.I),
}
SCHEDULE_RE = re.compile(
    r"\b(?:schedule|reschedule|meeting|appointment|conference call|calendar|lunch|dinner|"
    r"meet at|meet on|attend|session)\b",
    re.I,
)
STATUS_RE = re.compile(
    r"\b(?:completed|finished|done|cancell?ed|postponed|rescheduled|closed|resolved|"
    r"in progress|still working|status update|no longer|not yet|unable to|did not|didn't|"
    r"will not|won't|cannot|can't)\b",
    re.I,
)
NEGATION_RE = re.compile(
    r"\b(?:not|no longer|never|cannot|can't|won't|will not|did not|didn't|unable to|"
    r"cancel(?:ed|led)?|postponed)\b.{0,60}\b(?:send|provide|review|complete|finish|call|meet|"
    r"deliver|update|prepare|file|submit|check|confirm|schedule|create|forward|process|execute)\b",
    re.I,
)
AMBIGUOUS_OWNER_RE = re.compile(r"\b(?:someone|somebody|anyone|anybody|whoever|you guys|the team)\b", re.I)
VAGUE_TIME_RE = re.compile(
    r"\b(?:soon|sometime|when you can|when you get a chance|at your convenience|eventually|later)\b",
    re.I,
)
STRONG_DEPENDENCY_RE = re.compile(
    r"\b(?:depends? on|dependent on|contingent (?:on|upon)|prerequisite(?: for| to)?|"
    r"subject to|pending (?:approval|review|completion|receipt|confirmation))\b",
    re.I,
)
CONNECTOR_RE = re.compile(r"\b(?:before|after|once|until|upon|as soon as|prior to|when)\b", re.I)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/cleaned"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/candidates"))
    parser.add_argument("--coverage-csv", type=Path, default=Path("data/reports/coverage_report.csv"))
    parser.add_argument("--report-path", type=Path, default=Path("data/reports/candidate_selection.md"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--train-target", type=int, default=DEFAULT_TARGETS["train"])
    parser.add_argument("--dev-target", type=int, default=DEFAULT_TARGETS["dev"])
    parser.add_argument("--test-target", type=int, default=DEFAULT_TARGETS["test"])
    return parser.parse_args()


def seeded_key(seed: int, value: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}:{value}".encode("utf-8")).digest()[:8], "big")


def extract_matches(patterns: dict[str, re.Pattern[str]], text: str) -> list[dict[str, Any]]:
    matches = []
    for name, pattern in patterns.items():
        for match in pattern.finditer(text):
            matches.append(
                {
                    "pattern": name,
                    "span": [match.start(), match.end()],
                    "text": match.group(0),
                }
            )
    return sorted(matches, key=lambda item: (item["span"], item["pattern"]))


def dependency_matches(text: str) -> list[dict[str, Any]]:
    """Return plausible dependencies, rejecting connector-only coincidences.

    Strong dependency terms are accepted directly.  Temporal connectors such
    as "after" require action evidence on both sides within a local window, so
    phrases like "drinks after work" are not treated as task dependencies.
    """

    matches: list[dict[str, Any]] = []
    for match in STRONG_DEPENDENCY_RE.finditer(text):
        start, end = max(0, match.start() - 90), min(len(text), match.end() + 90)
        context = text[start:end]
        boilerplate = re.search(r"(?:terms of service|unsubscribe|yahoo!? groups)", context, re.I)
        if DEPENDENCY_ACTION_RE.search(context) and not boilerplate:
            matches.append(
                {
                    "pattern": "strong_dependency_term",
                    "connector": match.group(0),
                    "span": [match.start(), match.end()],
                    "context": context,
                    "confidence": "provisional_high",
                }
            )
    for match in CONNECTOR_RE.finditer(text):
        before = text[max(0, match.start() - 120) : match.start()]
        after = text[match.end() : min(len(text), match.end() + 120)]
        # "as soon as possible" is a deadline idiom, not evidence that one
        # task depends on another.  It is captured by DEADLINE_PATTERNS.
        if match.group(0).lower() == "as soon as" and re.match(r"\s+possible\b", after, re.I):
            continue
        before_action = list(DEPENDENCY_ACTION_RE.finditer(before))
        after_action = list(DEPENDENCY_ACTION_RE.finditer(after))
        clause_initial = not before.strip() or bool(re.search(r"[.!?;]\s*$", before))
        if not ((before_action and after_action) or (clause_initial and len(after_action) >= 2)):
            continue
        start = max(0, match.start() - 120)
        end = min(len(text), match.end() + 120)
        matches.append(
            {
                "pattern": "action_conditioned_temporal_connector",
                "connector": match.group(0),
                "span": [match.start(), match.end()],
                "context": text[start:end],
                "confidence": "provisional_medium",
            }
        )
    unique = {}
    for item in matches:
        unique[(tuple(item["span"]), item["pattern"])] = item
    return [unique[key] for key in sorted(unique)]


def event_signals(record: dict[str, Any]) -> dict[str, Any]:
    event_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    labeled_span_starts = 0
    for event_type, payload in record.get("original_events", {}).items():
        if not isinstance(payload, dict):
            continue
        labels_list = payload.get("labels", [])
        event_counts[event_type] += len(labels_list)
        for sequence in labels_list:
            active_role = None
            for label in sequence:
                if not isinstance(label, str) or label == "O":
                    active_role = None
                    continue
                tail = label.split(":")[-1].strip()
                match = re.match(r"([BI])-(.+)", tail)
                if not match:
                    active_role = None
                    continue
                prefix, role = match.group(1), match.group(2).strip()
                role_counts[role] += 1
                if prefix == "B" or active_role != role:
                    labeled_span_starts += 1
                active_role = role
    return {
        "event_occurrences": dict(sorted(event_counts.items())),
        "argument_role_token_counts": dict(sorted(role_counts.items())),
        "argument_span_start_count": labeled_span_starts,
    }


def analyze_record(record: dict[str, Any]) -> dict[str, Any]:
    text = record.get("text", "")
    raw_text = record.get("text_raw", text)
    event_data = event_signals(record)
    event_counts = Counter(event_data["event_occurrences"])
    role_counts = Counter(event_data["argument_role_token_counts"])
    deadline_hits = extract_matches(DEADLINE_PATTERNS, text)
    temporal_hits = extract_matches(TEMPORAL_PATTERNS, text)
    prerequisite_hits = dependency_matches(text)
    explicit_request_hits = list(EXPLICIT_REQUEST_RE.finditer(text))
    action_hits = list(ACTION_CUE_RE.finditer(text))
    commitment_hits = list(COMMITMENT_RE.finditer(text))
    status_hits = list(STATUS_RE.finditer(text))
    negation_hits = list(NEGATION_RE.finditer(text))

    relevant_event_count = sum(event_counts[event_type] for event_type in POTENTIAL_TASK_EVENTS)
    request_event_count = sum(event_counts[event_type] for event_type in REQUEST_EVENTS)
    action_event_count = sum(event_counts[event_type] for event_type in ACTION_EVENTS)
    planned_event_count = sum(event_counts[event_type] for event_type in PLANNED_EVENTS)
    schedule_event_count = sum(event_counts[event_type] for event_type in SCHEDULE_EVENTS)
    update_event_count = sum(event_counts[event_type] for event_type in UPDATE_EVENTS)

    ownership_roles = sum(
        count
        for role, count in role_counts.items()
        if role.lower() in {"action members", "deliver members", "deliver members", "meeting members", "data owner"}
    )
    date_time_roles = sum(
        count for role, count in role_counts.items() if role.lower().endswith((" date", " time"))
    )
    distinct_action_cues = {match.group(0).lower() for match in action_hits}
    no_relevant_annotations = relevant_event_count == 0
    no_action_signal = no_relevant_annotations and not explicit_request_hits and not commitment_hits and len(action_hits) == 0

    explicit_actionable = request_event_count > 0 or bool(explicit_request_hits)
    commitment = planned_event_count > 0 or bool(commitment_hits)
    multiple_tasks = relevant_event_count >= 2 or len(distinct_action_cues) >= 3
    ownership = ownership_roles > 0 or bool(
        re.search(r"\b(?:i|we|you|he|she|they|alice|bob|team)\s+(?:will|must|should|need to|can)\b", text, re.I)
    )
    explicit_deadline = date_time_roles > 0 or bool(deadline_hits)
    scheduled = schedule_event_count > 0 or bool(SCHEDULE_RE.search(text))
    temporal = bool(temporal_hits) or explicit_deadline
    status = update_event_count > 0 or bool(status_hits) or bool(negation_hits)
    actionable = relevant_event_count > 0 or explicit_actionable or commitment or len(action_hits) > 0
    ambiguous = actionable and (
        (ownership_roles == 0 and bool(AMBIGUOUS_OWNER_RE.search(text)))
        or (not explicit_deadline and bool(VAGUE_TIME_RE.search(text)))
        or (action_event_count > 0 and ownership_roles == 0 and date_time_roles == 0)
    )

    flags = {
        "explicit_actionable_request": explicit_actionable,
        "commitment_or_planned_action": commitment,
        "multiple_tasks": multiple_tasks,
        "task_ownership": ownership,
        "explicit_deadline": explicit_deadline,
        "scheduled_activity": scheduled,
        "temporal_expression": temporal,
        "possible_prerequisite": bool(prerequisite_hits),
        "action_update_across_thread": False,
        "negated_canceled_or_completed": status,
        "ambiguous_ownership_or_deadline": ambiguous,
        "no_actionable_tasks": no_action_signal,
        # Promoted only after the complete thread has been inspected.  Merely
        # belonging to an email thread is not enough to establish a useful
        # multi-email action scenario.
        "multi_email_scenario": False,
    }
    positive_count = sum(flags.values()) - int(flags["no_actionable_tasks"])
    length = len(record.get("tokens", []))
    score = (
        2.0 * int(explicit_actionable)
        + 2.0 * int(commitment)
        + 2.5 * int(multiple_tasks)
        + 1.5 * int(ownership)
        + 2.0 * int(explicit_deadline)
        + 1.5 * int(scheduled)
        + 1.0 * int(temporal)
        + 4.0 * int(bool(prerequisite_hits))
        + 2.5 * int(status)
        + 2.0 * int(ambiguous)
        + min(relevant_event_count, 4) * 0.5
        + (1.0 if 40 <= length <= 250 else 0.0)
    )
    if no_action_signal:
        score = 0.5 + (0.5 if length >= 15 else 0.0)
    complexity = "high" if positive_count >= 5 or multiple_tasks or prerequisite_hits else "medium" if positive_count >= 2 else "low"
    return {
        "flags": flags,
        "score": round(score, 3),
        "complexity_band": complexity,
        "signals": {
            **event_data,
            "relevant_event_instance_count": relevant_event_count,
            "request_event_instance_count": request_event_count,
            "action_event_instance_count": action_event_count,
            "planned_event_instance_count": planned_event_count,
            "deadline_matches": deadline_hits,
            "temporal_matches": temporal_hits,
            "prerequisite_matches": prerequisite_hits,
            "explicit_request_match_count": len(explicit_request_hits),
            "commitment_match_count": len(commitment_hits),
            "action_cue_match_count": len(action_hits),
            "status_or_negation_match_count": len(status_hits) + len(negation_hits),
            "no_relevant_mailex_annotation": no_relevant_annotations,
            "text_length_chars": len(text),
            "text_raw_length_chars": len(raw_text),
            "token_count": length,
        },
    }


def duplicate_keys(record: dict[str, Any]) -> set[str]:
    info = record.get("duplicate_info") or {}
    keys = set()
    if info.get("exact_group_id"):
        keys.add(info["exact_group_id"])
    if info.get("near_group_id"):
        keys.add(info["near_group_id"])
    return keys


def mailbox_source(record: dict[str, Any]) -> str:
    stem = Path(record.get("source_filename", "unknown")).stem
    return stem.split("_inbox", 1)[0] if "_inbox" in stem else stem.split("_", 1)[0]


def load_records(input_dir: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    records_by_split: dict[str, list[dict[str, Any]]] = {}
    analyses: dict[str, dict[str, Any]] = {}
    for split in SPLITS:
        path = input_dir / f"{split}.jsonl"
        if not path.is_file():
            raise ValueError(f"Missing cleaned input: {path}")
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for record in records:
            if record.get("source_split") != split:
                raise ValueError(f"Split mismatch for {record.get('id')} in {path}")
            if record["id"] in analyses:
                raise ValueError(f"Duplicate record ID: {record['id']}")
            analyses[record["id"]] = analyze_record(record)
        records_by_split[split] = records

    # Promote thread-level update evidence only after every turn is analyzed.
    thread_records: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for split, records in records_by_split.items():
        for record in records:
            thread_records[(split, record["thread_id"])].append(record)
    for members in thread_records.values():
        action_turns = 0
        update_turns = 0
        for record in members:
            analysis = analyses[record["id"]]
            flags = analysis["flags"]
            if flags["explicit_actionable_request"] or flags["commitment_or_planned_action"]:
                action_turns += 1
            if flags["negated_canceled_or_completed"] or analysis["signals"]["relevant_event_instance_count"] > 0:
                update_turns += 1
        thread_update = len(members) > 1 and (action_turns >= 2 or (action_turns >= 1 and update_turns >= 2))
        if thread_update:
            for record in members:
                analysis = analyses[record["id"]]
                analysis["flags"]["action_update_across_thread"] = True
                analysis["flags"]["multi_email_scenario"] = True
                analysis["score"] = round(analysis["score"] + 2.0, 3)
                positive_count = sum(analysis["flags"].values()) - int(
                    analysis["flags"]["no_actionable_tasks"]
                )
                analysis["complexity_band"] = (
                    "high"
                    if positive_count >= 5
                    or analysis["flags"]["multiple_tasks"]
                    or analysis["flags"]["possible_prerequisite"]
                    else "medium"
                    if positive_count >= 2
                    else "low"
                )
    return records_by_split, analyses


def quota_for(flag: str, target: int, available: int) -> int:
    proportions = {
        "possible_prerequisite": 0.08,
        "negated_canceled_or_completed": 0.10,
        "ambiguous_ownership_or_deadline": 0.12,
        "multiple_tasks": 0.15,
        "no_actionable_tasks": 0.15,
        "explicit_deadline": 0.15,
        "action_update_across_thread": 0.15,
        "scheduled_activity": 0.12,
        "commitment_or_planned_action": 0.18,
        "task_ownership": 0.22,
        "explicit_actionable_request": 0.28,
        "temporal_expression": 0.28,
    }
    return min(available, max(1, math.ceil(target * proportions[flag])))


def select_candidates(
    records_by_split: dict[str, list[dict[str, Any]]],
    analyses: dict[str, dict[str, Any]],
    targets: dict[str, int],
    seed: int,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    selected_by_split: dict[str, list[dict[str, Any]]] = {split: [] for split in SPLITS}
    selected_ids: set[str] = set()
    used_duplicate_groups: set[str] = set()
    bundle_threads: set[tuple[str, str]] = set()

    def can_add(record: dict[str, Any], split: str) -> bool:
        if record["id"] in selected_ids or len(selected_by_split[split]) >= targets[split]:
            return False
        return not (duplicate_keys(record) & used_duplicate_groups)

    def add(record: dict[str, Any], split: str, reason: str) -> bool:
        if not can_add(record, split):
            return False
        selected_ids.add(record["id"])
        used_duplicate_groups.update(duplicate_keys(record))
        record_copy = dict(record)
        analysis = analyses[record["id"]]
        record_copy["candidate_selection"] = {
            "version": SELECTION_VERSION,
            "random_seed": seed,
            "requires_human_verification": True,
            "selection_reason": reason,
            "candidate_score": analysis["score"],
            "complexity_band": analysis["complexity_band"],
            "provisional_coverage_flags": analysis["flags"],
            "selection_signals": analysis["signals"],
            "selected_as_complete_thread_bundle": False,
        }
        selected_by_split[split].append(record_copy)
        return True

    # Evaluation splits claim duplicate groups first, then train.  This avoids
    # large train pools starving dev/test while still preserving original split.
    selection_order = ("dev", "test", "train")
    for split in selection_order:
        records = records_by_split[split]
        by_thread: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            by_thread[record["thread_id"]].append(record)

        # Reserve ~15% of each target for complete, realistic multi-turn thread bundles.
        bundle_budget = max(2, round(targets[split] * 0.15))
        thread_candidates = []
        for thread_id, members in by_thread.items():
            members.sort(key=lambda item: item["turn_index"])
            if not 2 <= len(members) <= 6:
                continue
            if not any(analyses[item["id"]]["flags"]["action_update_across_thread"] for item in members):
                continue
            group_keys = [key for member in members for key in duplicate_keys(member)]
            if len(group_keys) != len(set(group_keys)) or set(group_keys) & used_duplicate_groups:
                continue
            thread_score = sum(analyses[item["id"]]["score"] for item in members) / len(members)
            thread_candidates.append((thread_score, seeded_key(seed, f"{split}:{thread_id}"), thread_id, members))
        thread_candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        bundled_count = 0
        for _, _, thread_id, members in thread_candidates:
            if bundled_count + len(members) > bundle_budget or len(selected_by_split[split]) + len(members) > targets[split]:
                continue
            if not all(can_add(member, split) for member in members):
                continue
            added_members = []
            for member in members:
                if add(member, split, "complete_thread_bundle"):
                    added_members.append(selected_by_split[split][-1])
            if len(added_members) == len(members):
                for selected in added_members:
                    selected["candidate_selection"]["selected_as_complete_thread_bundle"] = True
                bundled_count += len(members)
                bundle_threads.add((split, thread_id))

        ranked = sorted(
            records,
            key=lambda record: (
                -analyses[record["id"]]["score"],
                seeded_key(seed, record["id"]),
                record["id"],
            ),
        )
        category_order = (
            "possible_prerequisite",
            "negated_canceled_or_completed",
            "ambiguous_ownership_or_deadline",
            "multiple_tasks",
            "no_actionable_tasks",
            "explicit_deadline",
            "action_update_across_thread",
            "scheduled_activity",
            "commitment_or_planned_action",
            "task_ownership",
            "explicit_actionable_request",
            "temporal_expression",
        )
        for flag in category_order:
            available = sum(analyses[record["id"]]["flags"][flag] for record in records)
            quota = quota_for(flag, targets[split], available)
            current = sum(
                record["candidate_selection"]["provisional_coverage_flags"][flag]
                for record in selected_by_split[split]
            )
            for record in ranked:
                if current >= quota or len(selected_by_split[split]) >= targets[split]:
                    break
                if analyses[record["id"]]["flags"][flag] and add(record, split, f"coverage_quota:{flag}"):
                    current += 1
        for record in ranked:
            if len(selected_by_split[split]) >= targets[split]:
                break
            add(record, split, "diversity_ranked_fill")

    # Preserve original source ordering in each output for easy traceability.
    for split in SPLITS:
        selected_by_split[split].sort(key=lambda record: (record["source_filename"], record["turn_index"], record["id"]))
    return selected_by_split, {
        "bundle_thread_count": len(bundle_threads),
        "bundle_threads": sorted([{"split": split, "thread_id": thread} for split, thread in bundle_threads], key=lambda item: (item["split"], item["thread_id"])),
        "used_duplicate_group_count": len(used_duplicate_groups),
    }


def verify_no_cross_split_duplicates(selected_by_split: dict[str, list[dict[str, Any]]]) -> None:
    owners: dict[str, str] = {}
    for split in SPLITS:
        for record in selected_by_split[split]:
            for key in duplicate_keys(record):
                if key in owners and owners[key] != split:
                    raise ValueError(f"Duplicate group {key} selected in both {owners[key]} and {split}")
                owners[key] = split


def write_jsonl(records: Iterable[dict[str, Any]], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            json.dumps(record, ensure_ascii=False)
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
            count += 1
    return count


def aggregate_metrics(
    records_by_split: dict[str, list[dict[str, Any]]],
    analyses: dict[str, dict[str, Any]],
    selected_by_split: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    selected_ids = {record["id"] for records in selected_by_split.values() for record in records}
    rows: list[dict[str, Any]] = []

    def add_row(section: str, metric: str, description: str, split: str, population: int, selected: int) -> None:
        rows.append(
            {
                "section": section,
                "metric": metric,
                "description": description,
                "split": split,
                "population_count": population,
                "selected_count": selected,
                "selected_percent_of_population": round(100 * selected / population, 2) if population else 0.0,
            }
        )

    for split in SPLITS:
        population_records = records_by_split[split]
        selected_records = selected_by_split[split]
        add_row("selection", "records", "Email-turn records", split, len(population_records), len(selected_records))
        for flag, description in FLAG_DESCRIPTIONS.items():
            population = sum(analyses[record["id"]]["flags"][flag] for record in population_records)
            selected = sum(record["candidate_selection"]["provisional_coverage_flags"][flag] for record in selected_records)
            add_row("coverage_flag", flag, description, split, population, selected)
        for band in ("low", "medium", "high"):
            population = sum(analyses[record["id"]]["complexity_band"] == band for record in population_records)
            selected = sum(record["candidate_selection"]["complexity_band"] == band for record in selected_records)
            add_row("complexity", band, "Provisional candidate complexity band", split, population, selected)

        event_population: Counter[str] = Counter()
        event_selected: Counter[str] = Counter()
        for record in population_records:
            event_population.update(analyses[record["id"]]["signals"]["event_occurrences"])
            if record["id"] in selected_ids:
                event_selected.update(analyses[record["id"]]["signals"]["event_occurrences"])
        for event_type in sorted(set(event_population) | set(event_selected)):
            add_row(
                "event_frequency",
                event_type,
                "MailEx event instances (selection signal, not Text2Task gold)",
                split,
                event_population[event_type],
                event_selected[event_type],
            )

        source_population = Counter(mailbox_source(record) for record in population_records)
        source_selected = Counter(mailbox_source(record) for record in selected_records)
        for source in sorted(source_selected):
            add_row(
                "mailbox_source",
                source,
                "Source mailbox inferred from original filename",
                split,
                source_population[source],
                source_selected[source],
            )

    # Total rows for core coverage and complexity statistics.
    for flag, description in FLAG_DESCRIPTIONS.items():
        population = sum(analyses[record["id"]]["flags"][flag] for records in records_by_split.values() for record in records)
        selected = sum(record["candidate_selection"]["provisional_coverage_flags"][flag] for records in selected_by_split.values() for record in records)
        add_row("coverage_flag", flag, description, "all", population, selected)
    return rows


def write_coverage_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "section",
        "metric",
        "description",
        "split",
        "population_count",
        "selected_count",
        "selected_percent_of_population",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def table(headers: list[str], rows: list[list[Any]]) -> str:
    def clean(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    output = ["| " + " | ".join(map(clean, headers)) + " |"]
    output.append("| " + " | ".join("---" for _ in headers) + " |")
    output.extend("| " + " | ".join(map(clean, row)) + " |" for row in rows)
    return "\n".join(output)


def representative_examples(selected_by_split: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any] | None]:
    all_selected = [record for split in SPLITS for record in selected_by_split[split]]
    examples = {}
    used_ids: set[str] = set()
    for flag in FLAG_DESCRIPTIONS:
        eligible = [
            record
            for record in all_selected
            if record["candidate_selection"]["provisional_coverage_flags"][flag]
        ]

        def example_key(record: dict[str, Any]) -> tuple[Any, ...]:
            token_count = record["candidate_selection"]["selection_signals"]["token_count"]
            minimum_tokens = 15 if flag == "no_actionable_tasks" else 10
            useful_length = minimum_tokens <= token_count <= 250 and 40 <= len(record["text"]) <= 1_500
            dependency_priority = 0
            if flag == "possible_prerequisite":
                matches = record["candidate_selection"]["selection_signals"]["prerequisite_matches"]
                connectors = {item["connector"].lower() for item in matches}
                # Prefer examples that visibly express a task-to-task ordering
                # relation.  Broad "when" matches remain candidates for review,
                # but they are less explanatory as report examples.
                dependency_priority = (
                    0
                    if connectors & {"once", "upon"}
                    else 1
                    if connectors & {"before", "until", "pending approval", "pending review", "pending completion"}
                    else 2
                )
            return (
                record["id"] in used_ids,
                not useful_length,
                dependency_priority,
                -record["candidate_selection"]["candidate_score"],
                abs(token_count - 80),
                record["id"],
            )

        eligible.sort(key=example_key)
        examples[flag] = eligible[0] if eligible else None
        if eligible:
            used_ids.add(eligible[0]["id"])
    return examples


def make_report(
    records_by_split: dict[str, list[dict[str, Any]]],
    analyses: dict[str, dict[str, Any]],
    selected_by_split: dict[str, list[dict[str, Any]]],
    targets: dict[str, int],
    seed: int,
    selection_meta: dict[str, Any],
) -> str:
    selection_rows = [
        [split, len(records_by_split[split]), targets[split], len(selected_by_split[split])]
        for split in SPLITS
    ]
    coverage_rows = []
    for flag, description in FLAG_DESCRIPTIONS.items():
        population = sum(analyses[record["id"]]["flags"][flag] for records in records_by_split.values() for record in records)
        selected = sum(record["candidate_selection"]["provisional_coverage_flags"][flag] for records in selected_by_split.values() for record in records)
        coverage_rows.append([flag, population, selected, description])

    event_population: Counter[str] = Counter()
    event_selected: Counter[str] = Counter()
    for records in records_by_split.values():
        for record in records:
            event_population.update(analyses[record["id"]]["signals"]["event_occurrences"])
    for records in selected_by_split.values():
        for record in records:
            event_selected.update(record["candidate_selection"]["selection_signals"]["event_occurrences"])
    event_rows = [
        [event_type, event_population[event_type], event_selected[event_type]]
        for event_type in sorted(event_population)
    ]

    complexity_rows = []
    for band in ("low", "medium", "high"):
        population = sum(analyses[record["id"]]["complexity_band"] == band for records in records_by_split.values() for record in records)
        selected = sum(record["candidate_selection"]["complexity_band"] == band for records in selected_by_split.values() for record in records)
        complexity_rows.append([band, population, selected])

    source_selected = Counter(mailbox_source(record) for records in selected_by_split.values() for record in records)
    source_rows = [[source, count] for source, count in source_selected.most_common(20)]
    examples = representative_examples(selected_by_split)
    example_sections = []
    for flag, description in FLAG_DESCRIPTIONS.items():
        record = examples[flag]
        if record is None:
            example_sections.append(f"### `{flag}`\n\nNo selected example was available; target was subject to suitable records.")
            continue
        signals = record["candidate_selection"]["selection_signals"]
        evidence = ""
        if flag == "possible_prerequisite":
            evidence = f"\n\nDependency evidence: `{json.dumps(signals['prerequisite_matches'], ensure_ascii=False)}`"
        preview = re.sub(r"\s+", " ", record["text"]).strip()
        if len(preview) > 420:
            preview = preview[:419].rstrip() + "…"
        example_sections.append(
            f"### `{flag}`\n\n{description}\n\n"
            f"- Record: `{record['id']}`\n"
            f"- Split/thread: `{record['source_split']}` / `{record['thread_id']}` / turn {record['turn_index']}\n"
            f"- Provisional score: {record['candidate_selection']['candidate_score']}\n"
            f"- Text: “{preview}”{evidence}"
        )

    possible_prerequisite_population = sum(
        analyses[record["id"]]["flags"]["possible_prerequisite"]
        for records in records_by_split.values()
        for record in records
    )
    return f"""# Text2Task Candidate Selection and Coverage Analysis

## Result

The deterministic selector produced **{sum(len(records) for records in selected_by_split.values()):,} provisional email candidates** from cleaned MailEx. Existing MailEx annotations were used only as candidate signals; no final Text2Task gold labels were assigned. Every coverage flag has `requires_human_verification: true`.

{table(['Split', 'Cleaned population', 'Target', 'Selected'], selection_rows)}

Random seed: **{seed}**. Selection version: `{SELECTION_VERSION}`.

## Selection safeguards

- Original thread IDs, turn order, source filenames, and train/dev/test membership are preserved.
- {selection_meta['bundle_thread_count']} complete multi-turn thread bundles were selected for realistic cross-email context.
- Exact and near-duplicate group IDs from cleaning are globally constrained, so a duplicate group cannot be selected across multiple splits.
- Quotas explicitly reserve coverage for prerequisites, negation/status, ambiguity, multiple tasks, no-action emails, deadlines, updates, scheduling, ownership, and temporal language before score-based filling.
- Ambiguous/easy signals are mixed: the selector does not treat MailEx labels as final task labels.
- Text cleaning review flags and quoted context remain attached to candidate records.

## Prerequisite expressions

**{possible_prerequisite_population:,} emails in the complete cleaned corpus contain possible prerequisite/dependency expressions under the conservative rule.** The rule accepts strong dependency terms only with nearby concrete-action evidence; connectors such as “after,” “before,” and “when” require concrete action cues on both sides. The deadline idiom “as soon as possible” and obvious terms-of-service boilerplate are excluded. Therefore, “after” alone is never sufficient.

## Provisional coverage

{table(['Coverage flag', 'Population emails', 'Selected emails', 'Meaning'], coverage_rows)}

## MailEx event frequencies

These counts are event instances used as selection evidence, not Text2Task labels.

{table(['MailEx event type', 'Population occurrences', 'Selected occurrences'], event_rows)}

## Candidate complexity

{table(['Complexity band', 'Population emails', 'Selected emails'], complexity_rows)}

## Selected source distribution

Top source mailboxes inferred from original filenames:

{table(['Mailbox source', 'Selected emails'], source_rows)}

Detailed split-level coverage, event-frequency, complexity, and mailbox-source rows are in `coverage_report.csv`.

## Representative examples for every provisional category

{chr(10).join(example_sections)}

## Reproduction

```bash
python3 scripts/select_candidates.py --seed {seed}
```

The outputs are candidate-review inputs only. Human verification is required before assigning gold task, owner, deadline, dependency, or status labels.
"""


def run_selection(
    input_dir: Path,
    output_dir: Path,
    coverage_csv: Path,
    report_path: Path,
    targets: dict[str, int],
    seed: int,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    records_by_split, analyses = load_records(input_dir)
    selected_by_split, selection_meta = select_candidates(records_by_split, analyses, targets, seed)
    verify_no_cross_split_duplicates(selected_by_split)
    for split in SPLITS:
        written = write_jsonl(selected_by_split[split], output_dir / f"{split}.jsonl")
        if written != len(selected_by_split[split]):
            raise ValueError(f"Write count mismatch for {split}")
    coverage_rows = aggregate_metrics(records_by_split, analyses, selected_by_split)
    write_coverage_csv(coverage_rows, coverage_csv)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        make_report(records_by_split, analyses, selected_by_split, targets, seed, selection_meta),
        encoding="utf-8",
    )
    return selected_by_split, {"analyses": analyses, "selection_meta": selection_meta, "coverage_rows": coverage_rows}


def print_summary(selected_by_split: dict[str, list[dict[str, Any]]]) -> None:
    print("Text2Task candidate selection complete")
    for split in SPLITS:
        print(f"  {split}: {len(selected_by_split[split]):,} candidates")
    print("  Representative examples by provisional category:")
    examples = representative_examples(selected_by_split)
    for flag in FLAG_DESCRIPTIONS:
        count = sum(
            record["candidate_selection"]["provisional_coverage_flags"][flag]
            for records in selected_by_split.values()
            for record in records
        )
        record = examples[flag]
        if record:
            preview = re.sub(r"\s+", " ", record["text"]).strip()
            preview = preview[:120] + ("…" if len(preview) > 120 else "")
            print(f"    {flag}: {count:,} | {record['id']} | {preview}")
        else:
            print(f"    {flag}: 0 | no suitable selected example")


def main() -> None:
    args = parse_args()
    targets = {"train": args.train_target, "dev": args.dev_target, "test": args.test_target}
    selected_by_split, _ = run_selection(
        args.input_dir,
        args.output_dir,
        args.coverage_csv,
        args.report_path,
        targets,
        args.seed,
    )
    print_summary(selected_by_split)
    print(f"  Coverage CSV: {args.coverage_csv.resolve()}")
    print(f"  Report: {args.report_path.resolve()}")


if __name__ == "__main__":
    main()
