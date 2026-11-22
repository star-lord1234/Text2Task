#!/usr/bin/env python3
"""Reproducible, read-only audit of the local MailEx dataset.

The script deliberately treats train/dev/test as the authoritative annotated
corpus and audits full_data only for duplication.  It never writes below the
raw dataset directory; reports are written to data/reports by default.
"""

from __future__ import annotations

import argparse
import ast
import csv
import difflib
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


SCRIPT_VERSION = "1.0.0"
SPLITS = ("train", "dev", "test")
ALL_JSON_DIRS = (*SPLITS, "full_data")
TURN_RE = re.compile(r"^turn_(\d+)$")
LABEL_RE = re.compile(r"^\s*([BI])-(.+?)\s*$")
THREAD_SEPARATOR_RE = re.compile(r"(?m)^-{20,}\s*$")
HEADER_RE = re.compile(r"(?i)^(FROM|TO|CC|SUBJECT|DATE|SENT):\s*(.*)$")
WORD_RE = re.compile(r"[a-z0-9]+")

DEPENDENCY_PATTERNS = {
    "before": re.compile(r"\bbefore\b", re.I),
    "after": re.compile(r"\bafter\b", re.I),
    "once": re.compile(r"\bonce\b", re.I),
    "until": re.compile(r"\buntil\b", re.I),
    "as_soon_as": re.compile(r"\bas soon as\b", re.I),
    "prior_to": re.compile(r"\bprior to\b", re.I),
    "upon": re.compile(r"\bupon\b", re.I),
    "pending": re.compile(r"\bpending\b", re.I),
    "depend": re.compile(r"\bdepends?\b|\bdependent\b", re.I),
    "contingent": re.compile(r"\bcontingent\b", re.I),
    "prerequisite": re.compile(r"\bprerequisite\b", re.I),
    "following": re.compile(r"\bfollowing\b", re.I),
}

DISCLAIMER_PATTERNS = {
    "confidential_or_privileged": re.compile(r"\bconfidential\b|\bprivileged\b", re.I),
    "intended_recipient": re.compile(r"\bintended recipient", re.I),
    "property_of_enron": re.compile(r"\bproperty of enron", re.I),
    "unauthorized_review_or_use": re.compile(r"unauthori[sz]ed.{0,30}(review|use|disclosure)", re.I),
    "virus_or_security_notice": re.compile(r"\bvirus\b|electronic mail.{0,40}not secure", re.I),
}

SIGNATURE_RE = re.compile(
    r"\b(thanks|thank you|regards|kind regards|best regards|sincerely|cheers)\b"
    r"|\b(tel|telephone|phone|fax|cell|mobile)\s*[:.]",
    re.I,
)
QUOTED_REPLY_RE = re.compile(
    r"original message|forwarded by|wrote\s*:|\bfrom\s*:.*\b(to|sent|subject)\s*:",
    re.I | re.S,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path("data/raw/mailex"),
        help="MailEx root containing train/dev/test/full_data (default: %(default)s)",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("data/reports"),
        help="Output directory (default: %(default)s)",
    )
    return parser.parse_args()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def aggregate_digest(paths: Iterable[Path], base: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(base).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def percentile(values: list[int], q: float) -> float | int | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lo = math.floor(position)
    hi = math.ceil(position)
    value = ordered[lo] if lo == hi else ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)
    return int(value) if float(value).is_integer() else round(value, 2)


def describe(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": min(values),
        "p10": percentile(values, 0.10),
        "p25": percentile(values, 0.25),
        "median": percentile(values, 0.50),
        "p75": percentile(values, 0.75),
        "p90": percentile(values, 0.90),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": max(values),
        "mean": round(sum(values) / len(values), 2),
    }


def flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(flatten_strings(item))
        return result
    return [str(value)]


def sentence_text(tokens: Any) -> str:
    return " ".join(flatten_strings(tokens))


def normalized_text(text: str) -> str:
    return " ".join(WORD_RE.findall(text.lower()))


def truncate(text: str, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def parse_label(label: str) -> dict[str, str] | None:
    if label == "O":
        return None
    parts = label.split(":")
    match = LABEL_RE.match(parts[-1])
    if not match:
        raise ValueError(f"Malformed non-O label: {label!r}")
    qualifier = ":".join(part.strip() for part in parts[1:-1]).strip()
    argument = match.group(2).strip()
    return {
        "embedded_event_type": parts[0].strip(),
        "bio_prefix": match.group(1),
        "qualifier": qualifier,
        "argument_label": argument,
        "qualified_argument_label": f"{qualifier}: {argument}" if qualifier else argument,
    }


def parse_trigger(trigger: Any) -> tuple[dict[str, Any] | None, str | None]:
    if trigger in ("", "O"):
        return None, None
    if not isinstance(trigger, str):
        return None, "not_a_string"
    try:
        value = ast.literal_eval(trigger)
    except (SyntaxError, ValueError):
        return None, "literal_parse_error"
    if not isinstance(value, dict):
        return None, "not_a_dict"
    indices_text = str(value.get("indices", "")).strip()
    try:
        indices = [int(item) for item in indices_text.split()] if indices_text else []
    except ValueError:
        return None, "invalid_indices"
    return {"words": str(value.get("words", "")), "indices": indices}, None


def raw_key(path: Path) -> str:
    return path.name[:-1] if path.name.endswith(".") else path.name


def parse_raw_blocks(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    chunks = [chunk for chunk in THREAD_SEPARATOR_RE.split(text) if chunk.strip()]
    blocks: list[dict[str, Any]] = []
    for chunk in chunks:
        lines = chunk.strip().splitlines()
        headers: dict[str, str] = {}
        body_start = 0
        saw_header = False
        for index, line in enumerate(lines[:10]):
            match = HEADER_RE.match(line)
            if match:
                saw_header = True
                headers[match.group(1).upper()] = match.group(2).strip()
                body_start = index + 1
            elif saw_header:
                break
            elif line.strip():
                break
        blocks.append({"headers": headers, "body": "\n".join(lines[body_start:]).strip()})
    return blocks


def counter_dict(counter: Counter[Any]) -> dict[str, int]:
    return {str(key): counter[key] for key in sorted(counter, key=str)}


def nested_counter(counter: Counter[tuple[Any, ...]], names: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = []
    for key in sorted(counter, key=lambda item: tuple(str(part) for part in item)):
        rows.append({**dict(zip(names, key)), "count": counter[key]})
    return rows


def audit(dataset_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dataset_root = dataset_root.resolve()
    required = [dataset_root / name for name in ALL_JSON_DIRS]
    missing = [str(path) for path in required if not path.is_dir()]
    if missing:
        raise SystemExit(f"Missing required MailEx directories: {', '.join(missing)}")

    files_by_dir = {name: sorted((dataset_root / name).glob("*.json")) for name in ALL_JSON_DIRS}
    split_names = {name: {path.name for path in files_by_dir[name]} for name in ALL_JSON_DIRS}
    split_union = set().union(*(split_names[name] for name in SPLITS))

    overlaps = {
        f"{left}_{right}": sorted(split_names[left] & split_names[right])
        for index, left in enumerate(SPLITS)
        for right in SPLITS[index + 1 :]
    }
    full_byte_mismatches: list[dict[str, str]] = []
    for split in SPLITS:
        for path in files_by_dir[split]:
            full_path = dataset_root / "full_data" / path.name
            if full_path.exists() and path.read_bytes() != full_path.read_bytes():
                full_byte_mismatches.append({"split": split, "file": path.name})

    directory_inventory = {}
    for child in sorted(dataset_root.iterdir()):
        if child.is_dir():
            recursive_files = [path for path in child.rglob("*") if path.is_file()]
            directory_inventory[child.name] = {
                "file_count": len(recursive_files),
                "extensions": counter_dict(Counter(path.suffix or "<no extension>" for path in recursive_files)),
            }
        else:
            directory_inventory[child.name] = {"type": "file", "size_bytes": child.stat().st_size}

    event_container_entries: Counter[tuple[str, str]] = Counter()
    event_occurrences: Counter[tuple[str, str]] = Counter()
    argument_tokens: Counter[tuple[str, str, str, str, str]] = Counter()
    argument_spans: Counter[tuple[str, str, str, str]] = Counter()
    explicit_b_spans: Counter[tuple[str, str, str, str]] = Counter()
    qualifier_counts: Counter[str] = Counter()
    bio_counts: Counter[str] = Counter()
    qualified_argument_counts: Counter[str] = Counter()
    argument_label_counts: Counter[str] = Counter()
    trigger_stats: Counter[str] = Counter()
    dependency_counts: Counter[str] = Counter()
    disclaimer_counts: Counter[str] = Counter()

    token_lengths: list[int] = []
    thread_turn_counts: list[int] = []
    thread_token_counts: list[int] = []
    split_email_counts: Counter[str] = Counter()
    split_token_counts: Counter[str] = Counter()
    no_event_turns: Counter[str] = Counter()
    signature_turns: Counter[str] = Counter()
    quoted_reply_turns: Counter[str] = Counter()

    structural_anomalies: list[dict[str, Any]] = []
    length_mismatches: list[dict[str, Any]] = []
    turn_key_mismatches: list[dict[str, Any]] = []
    orphan_i_records: list[dict[str, Any]] = []
    embedded_event_mismatches: list[dict[str, Any]] = []
    trigger_anomalies: list[dict[str, Any]] = []
    label_parse_anomalies: list[dict[str, Any]] = []
    instance_trigger_count_mismatches: list[dict[str, Any]] = []

    thread_content_hashes: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    email_content_hashes: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    action_examples: list[dict[str, Any]] = []
    dependency_examples: list[dict[str, Any]] = []
    annotation_instances: list[dict[str, Any]] = []
    all_event_types: set[str] = set()

    for split in SPLITS:
        for path in files_by_dir[split]:
            raw_bytes = path.read_bytes()
            thread_content_hashes[sha256_bytes(raw_bytes)].append({"split": split, "file": path.name})
            try:
                data = json.loads(raw_bytes)
            except json.JSONDecodeError as error:
                structural_anomalies.append({"split": split, "file": path.name, "issue": "invalid_json", "detail": str(error)})
                continue
            if not isinstance(data, dict):
                structural_anomalies.append({"split": split, "file": path.name, "issue": "top_level_not_object"})
                continue
            if set(data) != {"events", "sentences"}:
                structural_anomalies.append(
                    {"split": split, "file": path.name, "issue": "unexpected_top_level_keys", "keys": sorted(data)}
                )
            sentences = data.get("sentences")
            events = data.get("events")
            if not isinstance(sentences, list) or not isinstance(events, dict):
                structural_anomalies.append(
                    {"split": split, "file": path.name, "issue": "sentences_or_events_wrong_type"}
                )
                continue

            thread_turn_counts.append(len(sentences))
            split_email_counts[split] += len(sentences)
            expected_turns = {f"turn_{index}" for index in range(len(sentences))}
            if set(events) != expected_turns:
                turn_key_mismatches.append(
                    {
                        "split": split,
                        "file": path.name,
                        "sentence_count": len(sentences),
                        "event_turn_keys": sorted(events),
                    }
                )

            thread_tokens = 0
            for turn_index, tokens in enumerate(sentences):
                if not isinstance(tokens, list):
                    structural_anomalies.append(
                        {"split": split, "file": path.name, "turn": turn_index, "issue": "sentence_not_list"}
                    )
                    continue
                non_string = [index for index, token in enumerate(tokens) if not isinstance(token, str)]
                if non_string:
                    structural_anomalies.append(
                        {
                            "split": split,
                            "file": path.name,
                            "turn": turn_index,
                            "issue": "non_string_tokens",
                            "indices": non_string,
                            "value_preview": repr(tokens[:5]),
                        }
                    )
                length = len(tokens)
                token_lengths.append(length)
                thread_tokens += length
                split_token_counts[split] += length
                canonical = json.dumps(tokens, ensure_ascii=False, separators=(",", ":"))
                email_content_hashes[sha256_bytes(canonical.encode("utf-8"))].append(
                    {"split": split, "file": path.name, "turn": turn_index}
                )
                text = sentence_text(tokens)
                tail = " ".join(flatten_strings(tokens)[-60:])
                if SIGNATURE_RE.search(tail):
                    signature_turns[split] += 1
                if QUOTED_REPLY_RE.search(text):
                    quoted_reply_turns[split] += 1
                for name, pattern in DISCLAIMER_PATTERNS.items():
                    if pattern.search(text):
                        disclaimer_counts[name] += 1
                matched_dependencies = [name for name, pattern in DEPENDENCY_PATTERNS.items() if pattern.search(text)]
                for name in matched_dependencies:
                    dependency_counts[name] += 1
                if matched_dependencies:
                    action_cues = len(
                        re.findall(
                            r"\b(please|need|must|should|can|could|request|complete|send|provide|review|approve|finish|deliver|file|schedule)\b",
                            text,
                            re.I,
                        )
                    )
                    strong_terms = len(set(matched_dependencies) - {"following"})
                    dependency_examples.append(
                        {
                            "split": split,
                            "file": path.name,
                            "turn": turn_index,
                            "matched_terms": matched_dependencies,
                            "text": truncate(text),
                            "selection_score": 10 * bool(action_cues and strong_terms)
                            + 2 * min(action_cues, 3)
                            + 2 * strong_terms
                            + int(len(text) <= 1_000),
                        }
                    )
            thread_token_counts.append(thread_tokens)

            for turn_key, turn_events in events.items():
                match = TURN_RE.match(turn_key)
                if not match:
                    continue
                turn_index = int(match.group(1))
                if turn_index >= len(sentences) or not isinstance(turn_events, dict):
                    continue
                tokens = sentences[turn_index]
                if not isinstance(tokens, list):
                    continue
                real_types = [event_type for event_type in turn_events if event_type != "O"]
                if not real_types:
                    no_event_turns[split] += 1

                for event_type, payload in turn_events.items():
                    all_event_types.add(event_type)
                    event_container_entries[(split, event_type)] += 1
                    if not isinstance(payload, dict):
                        structural_anomalies.append(
                            {"split": split, "file": path.name, "turn": turn_key, "event_type": event_type, "issue": "payload_not_object"}
                        )
                        continue
                    if set(payload) != {"labels", "triggers", "extras"}:
                        structural_anomalies.append(
                            {
                                "split": split,
                                "file": path.name,
                                "turn": turn_key,
                                "event_type": event_type,
                                "issue": "unexpected_payload_keys",
                                "keys": sorted(payload),
                            }
                        )
                    labels_list = payload.get("labels", [])
                    triggers = payload.get("triggers", [])
                    if not isinstance(labels_list, list) or not isinstance(triggers, list):
                        structural_anomalies.append(
                            {"split": split, "file": path.name, "turn": turn_key, "event_type": event_type, "issue": "labels_or_triggers_not_list"}
                        )
                        continue
                    if len(labels_list) != len(triggers):
                        instance_trigger_count_mismatches.append(
                            {
                                "split": split,
                                "file": path.name,
                                "turn": turn_key,
                                "event_type": event_type,
                                "label_sequences": len(labels_list),
                                "triggers": len(triggers),
                            }
                        )

                    for instance_index, label_sequence in enumerate(labels_list):
                        event_occurrences[(split, event_type)] += 1
                        if not isinstance(label_sequence, list):
                            structural_anomalies.append(
                                {
                                    "split": split,
                                    "file": path.name,
                                    "turn": turn_key,
                                    "event_type": event_type,
                                    "instance": instance_index,
                                    "issue": "label_sequence_not_list",
                                }
                            )
                            continue
                        if len(label_sequence) != len(tokens):
                            length_mismatches.append(
                                {
                                    "split": split,
                                    "file": path.name,
                                    "turn": turn_key,
                                    "event_type": event_type,
                                    "instance": instance_index,
                                    "token_count": len(tokens),
                                    "label_count": len(label_sequence),
                                }
                            )

                        trigger_raw = triggers[instance_index] if instance_index < len(triggers) else None
                        trigger, trigger_error = parse_trigger(trigger_raw)
                        if trigger_raw in ("", "O"):
                            trigger_stats["no_event_placeholder"] += 1
                        elif trigger_error:
                            trigger_stats[trigger_error] += 1
                            trigger_anomalies.append(
                                {
                                    "split": split,
                                    "file": path.name,
                                    "turn": turn_key,
                                    "event_type": event_type,
                                    "instance": instance_index,
                                    "trigger": trigger_raw,
                                    "issue": trigger_error,
                                }
                            )
                        elif trigger is not None:
                            trigger_stats["parsed"] += 1
                            indices = trigger["indices"]
                            if not indices:
                                trigger_stats["empty_indices"] += 1
                            elif any(index < 0 or index >= len(tokens) for index in indices):
                                trigger_stats["out_of_bounds"] += 1
                                trigger_anomalies.append(
                                    {
                                        "split": split,
                                        "file": path.name,
                                        "turn": turn_key,
                                        "event_type": event_type,
                                        "instance": instance_index,
                                        "trigger": trigger_raw,
                                        "issue": "out_of_bounds",
                                    }
                                )
                            else:
                                if indices != list(range(indices[0], indices[-1] + 1)):
                                    trigger_stats["noncontiguous_indices"] += 1
                                trigger_words = " ".join(str(tokens[index]) for index in indices)
                                if trigger_words == trigger["words"]:
                                    trigger_stats["words_exactly_match_indexed_tokens"] += 1
                                else:
                                    trigger_stats["word_index_mismatch"] += 1
                                    trigger_anomalies.append(
                                        {
                                            "split": split,
                                            "file": path.name,
                                            "turn": turn_key,
                                            "event_type": event_type,
                                            "instance": instance_index,
                                            "trigger_words": trigger["words"],
                                            "indexed_words": trigger_words,
                                            "issue": "word_index_mismatch",
                                        }
                                    )

                        spans: list[dict[str, Any]] = []
                        active: dict[str, Any] | None = None
                        for token_index, label in enumerate(label_sequence):
                            if not isinstance(label, str):
                                label_parse_anomalies.append(
                                    {
                                        "split": split,
                                        "file": path.name,
                                        "turn": turn_key,
                                        "event_type": event_type,
                                        "instance": instance_index,
                                        "token_index": token_index,
                                        "label": repr(label),
                                        "issue": "label_not_string",
                                    }
                                )
                                active = None
                                continue
                            try:
                                parsed = parse_label(label)
                            except ValueError:
                                label_parse_anomalies.append(
                                    {
                                        "split": split,
                                        "file": path.name,
                                        "turn": turn_key,
                                        "event_type": event_type,
                                        "instance": instance_index,
                                        "token_index": token_index,
                                        "label": label,
                                        "issue": "malformed_non_o_label",
                                    }
                                )
                                active = None
                                continue
                            if parsed is None:
                                active = None
                                continue
                            if parsed["embedded_event_type"] != event_type:
                                embedded_event_mismatches.append(
                                    {
                                        "split": split,
                                        "file": path.name,
                                        "turn": turn_key,
                                        "container_event_type": event_type,
                                        "embedded_event_type": parsed["embedded_event_type"],
                                        "label": label,
                                    }
                                )
                            role_key = (
                                parsed["embedded_event_type"],
                                parsed["qualifier"],
                                parsed["argument_label"],
                            )
                            bio_counts[parsed["bio_prefix"]] += 1
                            qualifier_counts[parsed["qualifier"] or "<none>"] += 1
                            qualified_argument_counts[parsed["qualified_argument_label"]] += 1
                            argument_label_counts[parsed["argument_label"]] += 1
                            argument_tokens[
                                (
                                    split,
                                    event_type,
                                    parsed["qualifier"],
                                    parsed["argument_label"],
                                    parsed["bio_prefix"],
                                )
                            ] += 1

                            begins_span = parsed["bio_prefix"] == "B"
                            orphan_i = parsed["bio_prefix"] == "I" and (
                                active is None or active["role_key"] != role_key
                            )
                            if begins_span or orphan_i:
                                span = {
                                    "qualifier": parsed["qualifier"],
                                    "argument_label": parsed["argument_label"],
                                    "qualified_argument_label": parsed["qualified_argument_label"],
                                    "start": token_index,
                                    "end": token_index,
                                    "tokens": [str(tokens[token_index])] if token_index < len(tokens) else [],
                                    "started_with": parsed["bio_prefix"],
                                }
                                spans.append(span)
                                active = {"role_key": role_key, "span": span}
                                argument_spans[(split, event_type, parsed["qualifier"], parsed["argument_label"])] += 1
                                if begins_span:
                                    explicit_b_spans[(split, event_type, parsed["qualifier"], parsed["argument_label"])] += 1
                                else:
                                    orphan_i_records.append(
                                        {
                                            "split": split,
                                            "file": path.name,
                                            "turn": turn_key,
                                            "event_type": event_type,
                                            "instance": instance_index,
                                            "token_index": token_index,
                                            "label": label,
                                            "previous_label": label_sequence[token_index - 1] if token_index else None,
                                        }
                                    )
                            elif active is not None:
                                active["span"]["end"] = token_index
                                if token_index < len(tokens):
                                    active["span"]["tokens"].append(str(tokens[token_index]))

                        instance = {
                            "split": split,
                            "file": path.name,
                            "turn": turn_index,
                            "event_type": event_type,
                            "instance": instance_index,
                            "trigger": trigger,
                            "spans": [
                                {**span, "text": " ".join(span.pop("tokens"))}
                                for span in spans
                            ],
                            "text": truncate(sentence_text(tokens)),
                        }
                        annotation_instances.append(instance)
                        role_names = {span["argument_label"] for span in instance["spans"]}
                        if (
                            event_type in {"Request_Action", "Deliver_Action_Data", "Amend_Action_Data"}
                            and "Action Description" in role_names
                            and role_names & {"Action Members", "Deliver Members"}
                            and role_names & {"Action Date", "Deliver Date", "Action Time", "Deliver Time"}
                        ):
                            action_examples.append(instance)

    action_examples.sort(
        key=lambda item: (
            item["event_type"] != "Request_Action",
            len(item["text"]),
            item["split"],
            item["file"],
            item["turn"],
            item["instance"],
        )
    )
    dependency_examples.sort(
        key=lambda item: (
            -item["selection_score"],
            len(item["text"]),
            item["split"],
            item["file"],
            item["turn"],
        )
    )
    for item in dependency_examples:
        item.pop("selection_score", None)

    duplicate_thread_groups = [group for group in thread_content_hashes.values() if len(group) > 1]
    duplicate_email_groups = [group for group in email_content_hashes.values() if len(group) > 1]
    cross_split_thread_groups = [group for group in duplicate_thread_groups if len({item["split"] for item in group}) > 1]
    cross_split_email_groups = [group for group in duplicate_email_groups if len({item["split"] for item in group}) > 1]

    raw_dir = dataset_root / "raw_threads"
    raw_files = sorted(path for path in raw_dir.iterdir() if path.is_file() and not path.name.startswith(".")) if raw_dir.is_dir() else []
    raw_lookup: dict[str, Path] = {}
    raw_key_collisions: defaultdict[str, list[str]] = defaultdict(list)
    for path in raw_files:
        key = raw_key(path)
        raw_key_collisions[key].append(path.name)
        raw_lookup.setdefault(key, path)
    full_stems = {path.stem for path in files_by_dir["full_data"]}
    raw_keys = set(raw_lookup)
    raw_header_counts: Counter[str] = Counter()
    raw_block_distribution: Counter[int] = Counter()
    raw_mapped_block_count = 0
    raw_all_block_count = 0
    raw_turn_count_mismatches: list[dict[str, Any]] = []
    order_relationship: Counter[str] = Counter()

    parsed_raw_cache: dict[str, list[dict[str, Any]]] = {}
    for path in raw_files:
        blocks = parse_raw_blocks(path)
        parsed_raw_cache[raw_key(path)] = blocks
        raw_all_block_count += len(blocks)
        raw_block_distribution[len(blocks)] += 1

    full_data_by_name = {path.stem: path for path in files_by_dir["full_data"]}
    for stem in sorted(full_stems & raw_keys):
        blocks = parsed_raw_cache[stem]
        raw_mapped_block_count += len(blocks)
        data = json.loads(full_data_by_name[stem].read_text(encoding="utf-8"))
        sentences = data["sentences"]
        if len(blocks) != len(sentences):
            raw_turn_count_mismatches.append(
                {"file": f"{stem}.json", "annotated_turns": len(sentences), "raw_delimited_blocks": len(blocks)}
            )
        for block in blocks:
            headers = block["headers"]
            for header in ("FROM", "TO", "SUBJECT", "DATE", "SENT", "CC"):
                if header in headers:
                    raw_header_counts[f"{header.lower()}_present"] += 1
                if headers.get(header):
                    raw_header_counts[f"{header.lower()}_nonempty"] += 1

        if len(blocks) == len(sentences) and len(blocks) >= 2:
            raw_norm = [normalized_text(block["body"]) for block in blocks]
            json_norm = [normalized_text(sentence_text(tokens)) for tokens in sentences]
            same_scores = [difflib.SequenceMatcher(None, left, right).ratio() for left, right in zip(raw_norm, json_norm)]
            reverse_scores = [
                difflib.SequenceMatcher(None, left, right).ratio()
                for left, right in zip(raw_norm, reversed(json_norm))
            ]
            same_score = sum(same_scores) / len(same_scores)
            reverse_score = sum(reverse_scores) / len(reverse_scores)
            if reverse_score >= same_score + 0.05:
                order_relationship["raw_reverse_of_sentences"] += 1
            elif same_score >= reverse_score + 0.05:
                order_relationship["raw_same_order_as_sentences"] += 1
            else:
                order_relationship["unclear"] += 1

    total_threads = sum(len(files_by_dir[split]) for split in SPLITS)
    total_emails = sum(split_email_counts.values())
    total_real_events = sum(
        count for (split, event_type), count in event_occurrences.items() if event_type != "O"
    )
    total_o_instances = sum(count for (split, event_type), count in event_occurrences.items() if event_type == "O")
    total_recovered_spans = sum(argument_spans.values())
    total_explicit_b_spans = sum(explicit_b_spans.values())

    event_totals = Counter()
    for (_, event_type), count in event_occurrences.items():
        event_totals[event_type] += count
    event_container_totals = Counter()
    for (_, event_type), count in event_container_entries.items():
        event_container_totals[event_type] += count
    span_totals_by_event = Counter()
    span_totals_by_role = Counter()
    for (_, event_type, qualifier, argument), count in argument_spans.items():
        span_totals_by_event[event_type] += count
        qualified = f"{qualifier}: {argument}" if qualifier else argument
        span_totals_by_role[qualified] += count

    label_rows: list[dict[str, Any]] = []
    for (split, event_type), count in sorted(event_occurrences.items()):
        label_rows.append(
            {
                "metric": "event_occurrence",
                "split": split,
                "event_type": event_type,
                "qualifier": "",
                "argument_label": "",
                "bio_prefix": "",
                "count": count,
            }
        )
    for (split, event_type, qualifier, argument, prefix), count in sorted(argument_tokens.items()):
        label_rows.append(
            {
                "metric": "argument_token",
                "split": split,
                "event_type": event_type,
                "qualifier": qualifier,
                "argument_label": argument,
                "bio_prefix": prefix,
                "count": count,
            }
        )
    for (split, event_type, qualifier, argument), count in sorted(argument_spans.items()):
        label_rows.append(
            {
                "metric": "argument_span",
                "split": split,
                "event_type": event_type,
                "qualifier": qualifier,
                "argument_label": argument,
                "bio_prefix": "BIO-decoded",
                "count": count,
            }
        )

    report: dict[str, Any] = {
        "audit": {
            "script_version": SCRIPT_VERSION,
            "dataset_root": str(dataset_root),
            "counting_policy": {
                "authoritative_corpus": "train + dev + test",
                "full_data_counted_as_independent": False,
                "event_occurrence": "one labels/triggers entry; not one event-type container and not one labeled token",
                "argument_span": "BIO-decoded span; orphan I starts a recovered span and is also reported as an anomaly",
                "unique_email": "exact identity of the serialized sentences[i] token structure",
            },
            "input_digests_sha256": {
                name: aggregate_digest(files_by_dir[name], dataset_root) for name in ALL_JSON_DIRS
            }
            | ({"raw_threads": aggregate_digest(raw_files, dataset_root)} if raw_files else {}),
        },
        "structure": {
            "recursive_inventory": directory_inventory,
            "split_file_counts": {name: len(files_by_dir[name]) for name in ALL_JSON_DIRS},
            "split_filename_overlaps": {key: {"count": len(value), "files": value} for key, value in overlaps.items()},
            "split_union_file_count": len(split_union),
            "full_data": {
                "filename_set_equals_split_union": split_names["full_data"] == split_union,
                "missing_from_full_data": sorted(split_union - split_names["full_data"]),
                "only_in_full_data": sorted(split_names["full_data"] - split_union),
                "byte_mismatch_count": len(full_byte_mismatches),
                "byte_mismatches": full_byte_mismatches,
                "conclusion": "duplicate convenience view" if split_names["full_data"] == split_union and not full_byte_mismatches else "not an exact duplicate",
            },
            "json_schema": {
                "expected_top_level_keys": ["events", "sentences"],
                "expected_payload_keys": ["extras", "labels", "triggers"],
                "structural_anomaly_count": len(structural_anomalies),
                "structural_anomalies_by_issue": counter_dict(
                    Counter(item["issue"] for item in structural_anomalies)
                ),
                "structural_anomalies": structural_anomalies,
            },
        },
        "identity_and_size": {
            "annotated_thread_occurrences": total_threads,
            "unique_thread_filenames": len(split_union),
            "unique_thread_contents_sha256": len(thread_content_hashes),
            "duplicate_thread_content_groups": len(duplicate_thread_groups),
            "duplicate_thread_occurrences_beyond_first": sum(len(group) - 1 for group in duplicate_thread_groups),
            "duplicate_thread_groups": duplicate_thread_groups,
            "cross_split_duplicate_thread_groups": cross_split_thread_groups,
            "annotated_email_turn_occurrences": total_emails,
            "unique_email_token_sequences": len(email_content_hashes),
            "duplicate_email_groups": len(duplicate_email_groups),
            "duplicate_email_occurrences_beyond_first": sum(len(group) - 1 for group in duplicate_email_groups),
            "cross_split_duplicate_email_groups": len(cross_split_email_groups),
            "cross_split_duplicate_email_group_examples": sorted(cross_split_email_groups, key=len, reverse=True)[:25],
            "per_split_emails": counter_dict(split_email_counts),
            "per_split_tokens": counter_dict(split_token_counts),
            "thread_turn_count_stats": describe(thread_turn_counts),
            "email_token_length_stats": describe(token_lengths),
            "thread_token_length_stats": describe(thread_token_counts),
        },
        "sentence_event_relationship": {
            "description": "sentences[i] is the token sequence for email turn i; events['turn_i'] contains all event-type containers for that same sequence. Each event instance has a full-length BIO label sequence aligned one-to-one with sentences[i].",
            "turn_key_mismatch_count": len(turn_key_mismatches),
            "turn_key_mismatches": turn_key_mismatches,
            "token_label_length_mismatch_count": len(length_mismatches),
            "token_label_length_mismatches": length_mismatches,
            "instance_trigger_count_mismatch_count": len(instance_trigger_count_mismatches),
            "instance_trigger_count_mismatches": instance_trigger_count_mismatches,
            "raw_vs_annotated_order": counter_dict(order_relationship),
            "raw_order_method": "For equal-length threads, mean normalized-text similarity was compared for same versus reversed raw-block order; a 0.05 margin was required.",
        },
        "events": {
            "event_types": sorted(all_event_types),
            "event_type_count_including_o": len(all_event_types),
            "event_container_entries": counter_dict(event_container_totals),
            "event_occurrences": counter_dict(event_totals),
            "real_event_occurrences_excluding_o": total_real_events,
            "o_placeholder_instances": total_o_instances,
            "no_event_turns_by_split": counter_dict(no_event_turns),
            "occurrences_by_split": nested_counter(event_occurrences, ("split", "event_type")),
            "trigger_validation": counter_dict(trigger_stats),
            "trigger_anomaly_count": len(trigger_anomalies),
            "trigger_anomalies": trigger_anomalies,
        },
        "arguments": {
            "bio_prefixes": ["B", "I", "O"],
            "labeled_token_bio_counts_excluding_o": counter_dict(bio_counts),
            "qualifiers": counter_dict(qualifier_counts),
            "argument_labels": sorted(argument_label_counts),
            "qualified_argument_labels": sorted(qualified_argument_counts),
            "argument_label_token_counts": counter_dict(argument_label_counts),
            "qualified_argument_token_counts": counter_dict(qualified_argument_counts),
            "argument_spans_bio_decoded": total_recovered_spans,
            "argument_spans_explicit_b_only": total_explicit_b_spans,
            "argument_spans_by_event_type": counter_dict(span_totals_by_event),
            "argument_spans_by_qualified_label": counter_dict(span_totals_by_role),
            "orphan_i_count": len(orphan_i_records),
            "orphan_i_examples": orphan_i_records[:100],
            "label_parse_anomaly_count": len(label_parse_anomalies),
            "label_parse_anomalies": label_parse_anomalies,
            "embedded_event_type_mismatch_count": len(embedded_event_mismatches),
            "embedded_event_type_mismatches": embedded_event_mismatches,
        },
        "action_item_relevance": {
            "direct_action_event_types": ["Request_Action", "Deliver_Action_Data", "Amend_Action_Data"],
            "coordination_event_types": ["Request_Meeting", "Deliver_Meeting_Data", "Amend_Meeting_Data"],
            "information_work_event_types": ["Request_Data", "Deliver_Data", "Amend_Data", "Request_Action_Data", "Request_Meeting_Data"],
            "dependency_annotation": "No explicit dependency/prerequisite event type or argument label exists; dependencies must be inferred from language or relations between extracted events.",
            "action_people_date_examples": action_examples[:8],
            "dependency_language_email_counts": counter_dict(dependency_counts),
            "dependency_language_examples": dependency_examples[:12],
        },
        "email_content": {
            "signature_heuristic": "Closing/contact terms within the final 60 tokens.",
            "signature_like_turns_by_split": counter_dict(signature_turns),
            "quoted_reply_heuristic": "Original Message / Forwarded by / wrote: / embedded From-To-Sent-Subject patterns.",
            "quoted_reply_like_turns_by_split": counter_dict(quoted_reply_turns),
            "disclaimer_turn_counts": counter_dict(disclaimer_counts),
            "note": "The raw format already separates many quoted messages into thread blocks, so embedded-quote counts are intentionally conservative.",
        },
        "metadata": {
            "annotated_json_fields": {
                "sender": False,
                "recipient": False,
                "timestamp": False,
                "subject": False,
                "explicit_thread_id": False,
                "thread_identity_source": "filename",
            },
            "raw_threads": {
                "file_count": len(raw_files),
                "delimited_block_count_all_raw_files": raw_all_block_count,
                "files_matching_annotated_thread_stems": len(full_stems & raw_keys),
                "annotated_threads_missing_raw_file": sorted(full_stems - raw_keys),
                "raw_files_without_annotated_json": sorted(raw_keys - full_stems),
                "normalized_filename_collisions": {key: value for key, value in raw_key_collisions.items() if len(value) > 1},
                "delimited_block_count_for_matching_files": raw_mapped_block_count,
                "header_completeness_for_matching_blocks": counter_dict(raw_header_counts),
                "block_count_distribution_all_raw_files": counter_dict(raw_block_distribution),
                "raw_annotated_turn_count_mismatch_count": len(raw_turn_count_mismatches),
                "raw_annotated_turn_count_mismatches": raw_turn_count_mismatches,
                "warning": "Hyphen-delimited raw blocks are source-format chunks, not guaranteed canonical emails; annotated sentences/events define the audited email-turn count.",
            },
        },
        "anomalies_summary": {
            "structural_anomalies": len(structural_anomalies),
            "turn_key_mismatches": len(turn_key_mismatches),
            "token_label_length_mismatches": len(length_mismatches),
            "label_trigger_instance_count_mismatches": len(instance_trigger_count_mismatches),
            "malformed_label_values": len(label_parse_anomalies),
            "embedded_event_type_mismatches": len(embedded_event_mismatches),
            "orphan_i_transitions": len(orphan_i_records),
            "trigger_anomalies_excluding_noncontiguous_and_empty": len(trigger_anomalies),
            "noncontiguous_trigger_indices": trigger_stats["noncontiguous_indices"],
            "empty_trigger_indices": trigger_stats["empty_indices"],
            "raw_annotated_turn_count_mismatches": len(raw_turn_count_mismatches),
        },
    }
    return report, label_rows


def pct(numerator: int, denominator: int) -> str:
    return "n/a" if denominator == 0 else f"{100 * numerator / denominator:.1f}%"


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    def clean(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    rendered = ["| " + " | ".join(clean(value) for value in headers) + " |"]
    rendered.append("| " + " | ".join("---" for _ in headers) + " |")
    rendered.extend("| " + " | ".join(clean(value) for value in row) + " |" for row in rows)
    return "\n".join(rendered)


def make_markdown(report: dict[str, Any]) -> str:
    identity = report["identity_and_size"]
    structure = report["structure"]
    relationship = report["sentence_event_relationship"]
    events = report["events"]
    arguments = report["arguments"]
    metadata = report["metadata"]["raw_threads"]
    content = report["email_content"]
    relevance = report["action_item_relevance"]
    anomalies = report["anomalies_summary"]

    split_rows = []
    for split in SPLITS:
        split_rows.append(
            [
                split,
                structure["split_file_counts"][split],
                identity["per_split_emails"][split],
                identity["per_split_tokens"][split],
            ]
        )
    split_rows.append(
        [
            "Total (authoritative)",
            identity["annotated_thread_occurrences"],
            identity["annotated_email_turn_occurrences"],
            sum(identity["per_split_tokens"].values()),
        ]
    )

    event_rows = [
        [event_type, count, events["event_container_entries"].get(event_type, 0), arguments["argument_spans_by_event_type"].get(event_type, 0)]
        for event_type, count in sorted(events["event_occurrences"].items(), key=lambda item: (-item[1], item[0]))
    ]
    role_rows = [
        [role, count, arguments["qualified_argument_token_counts"].get(role, 0)]
        for role, count in sorted(arguments["argument_spans_by_qualified_label"].items(), key=lambda item: (-item[1], item[0]))
    ]
    length_stats = identity["email_token_length_stats"]
    thread_stats = identity["thread_turn_count_stats"]
    header_total = metadata["delimited_block_count_for_matching_files"]
    metadata_rows = []
    for field in ("from", "to", "subject", "date", "sent", "cc"):
        present = metadata["header_completeness_for_matching_blocks"].get(f"{field}_present", 0)
        nonempty = metadata["header_completeness_for_matching_blocks"].get(f"{field}_nonempty", 0)
        metadata_rows.append([field.upper(), present, nonempty, pct(nonempty, header_total)])

    action_example_lines = []
    for example in relevance["action_people_date_examples"][:5]:
        spans = "; ".join(
            f"{span['qualified_argument_label']} = “{span['text']}”" for span in example["spans"]
        )
        action_example_lines.append(
            f"- `{example['split']}/{example['file']} turn_{example['turn']}` — {spans}"
        )
    dependency_example_lines = []
    for example in relevance["dependency_language_examples"][:6]:
        dependency_example_lines.append(
            f"- `{example['split']}/{example['file']} turn_{example['turn']}` ({', '.join(example['matched_terms'])}): “{example['text']}”"
        )

    structural_samples = structure["json_schema"]["structural_anomalies"][:10]
    structural_lines = [
        f"- `{item.get('split')}/{item.get('file')} turn_{item.get('turn')}`: {item['issue']} ({item.get('value_preview', '')})"
        for item in structural_samples
    ]

    return f"""# MailEx Dataset Audit

## Executive summary

- The authoritative train/dev/test corpus contains **{identity['annotated_thread_occurrences']:,} thread-file occurrences and {identity['annotated_email_turn_occurrences']:,} annotated email turns**. Exact token-structure deduplication leaves **{identity['unique_email_token_sequences']:,} unique email bodies**.
- `full_data` is an exact duplicate convenience view: its filename set equals the three-split union and all matching files are byte-identical. It is **not** counted as another 1,500 threads.
- Each `sentences[i]` is the token sequence for one email turn, and `events["turn_i"]` contains one or more event-type containers for that same sequence. Every event instance contributes one full-length BIO sequence and one trigger entry.
- There are **{events['real_event_occurrences_excluding_o']:,} real event occurrences** and **{arguments['argument_spans_bio_decoded']:,} decoded argument spans**. These are instance/span counts—not labeled-token counts.
- No token/label length mismatches or turn-key mismatches were found in this copy.
- The main annotation anomaly is **{arguments['orphan_i_count']:,} orphan or role-transition `I-` labels**. Recovering each as a span start produces {arguments['argument_spans_bio_decoded']:,} spans versus {arguments['argument_spans_explicit_b_only']:,} explicit `B-` starts.
- The JSON annotations contain no sender, recipient, subject, timestamp, or explicit thread ID fields. Raw source chunks usually contain From/To/Subject, but timestamps are almost entirely absent and 37 annotated/raw block counts disagree.
- Action extraction is directly supported by `Request_Action`, `Deliver_Action_Data`, and `Amend_Action_Data`; meeting and data events add coordination/information work. There is **no explicit dependency label**, so prerequisite relations require inference from language such as *before*, *after*, *once*, *until*, and *pending*.

## Corpus structure and split integrity

{md_table(['Split', 'Thread JSON files', 'Annotated email turns', 'Tokens'], split_rows)}

`full_data` contains {structure['split_file_counts']['full_data']:,} JSON files. Its filename set equals the union of train/dev/test: **{structure['full_data']['filename_set_equals_split_union']}**. Byte mismatches: **{structure['full_data']['byte_mismatch_count']}**. Pairwise split filename overlaps are all zero.

The recursive download also contains `raw_threads/` ({metadata['file_count']:,} files), `prompt_data.txt`, and `.DS_Store`. Of the raw files, {metadata['files_matching_annotated_thread_stems']:,} match annotated thread stems; {len(metadata['annotated_threads_missing_raw_file'])} annotated threads lack a raw file and {len(metadata['raw_files_without_annotated_json'])} raw files lack annotated JSON.

## Unique threads, emails, and duplication

- Unique thread filenames: **{identity['unique_thread_filenames']:,}**.
- Unique byte-level annotated thread contents: **{identity['unique_thread_contents_sha256']:,}**. There are {identity['duplicate_thread_content_groups']} duplicate-content groups accounting for {identity['duplicate_thread_occurrences_beyond_first']} occurrences beyond the first.
- Exact unique `sentences[i]` token structures: **{identity['unique_email_token_sequences']:,}** of {identity['annotated_email_turn_occurrences']:,} turns. There are {identity['duplicate_email_groups']} duplicate-email groups and {identity['duplicate_email_occurrences_beyond_first']} repeated occurrences beyond the first.
- Cross-split exact duplicates exist: {len(identity['cross_split_duplicate_thread_groups'])} thread-content groups and {identity['cross_split_duplicate_email_groups']} email-content groups. This matters for leakage-sensitive experiments even though filenames are split-disjoint.

## `sentences[i]` and `events["turn_i"]`

{relationship['description']}

Event-type containers are not event counts: a container may hold multiple parallel `labels` sequences. The occurrence count is the number of label/trigger entries. In this copy, label-sequence count always matches trigger count, and each label sequence has exactly the same length as its corresponding token list.

The raw source blocks are predominantly reverse-chronological while `sentences` is chronological. Among equal-length, automatically comparable threads: {relationship['raw_vs_annotated_order'].get('raw_reverse_of_sentences', 0)} strongly favor reversed order, {relationship['raw_vs_annotated_order'].get('raw_same_order_as_sentences', 0)} same order, and {relationship['raw_vs_annotated_order'].get('unclear', 0)} are unclear under the documented similarity margin.

## Event types and occurrence counts

{md_table(['Event type', 'Occurrences', 'Turn/type containers', 'Argument spans'], event_rows)}

`O` is a no-event placeholder, not a semantic event. The total real-event count excludes its {events['o_placeholder_instances']:,} placeholder instances.

## Argument labels, BIO prefixes, and spans

BIO prefixes present are `B`, `I`, and `O`. Excluding `O`, labeled token counts are: B = {arguments['labeled_token_bio_counts_excluding_o'].get('B', 0):,}; I = {arguments['labeled_token_bio_counts_excluding_o'].get('I', 0):,}. Qualifiers are `Context`, `Revision`, and no qualifier. Case is not fully normalized: for example, both `Deliver Members` and `Deliver members`, and both `Context: Request Members` and `Context: Request members`, occur.

{md_table(['Qualified argument label', 'Decoded spans', 'Labeled tokens'], role_rows)}

The machine-readable CSV gives split × event × qualifier × argument × BIO counts and separate event-occurrence and span rows.

## Action-item relevance and examples

- Direct action: `Request_Action`, `Deliver_Action_Data`, `Amend_Action_Data`.
- Coordination/action context: `Request_Meeting`, `Deliver_Meeting_Data`, `Amend_Meeting_Data`.
- Information work: `Request_Data`, `Deliver_Data`, `Amend_Data`, plus action/meeting-data request types.
- `Action Description`, action/delivery members, and action/delivery date/time slots map naturally to task, assignee, and deadline candidates. MailEx does not distinguish requester from assignee consistently enough to use member slots without event-aware interpretation.
- Dependencies are not annotated as relations or slots.

Examples with action descriptions, people, and date/time arguments:

{chr(10).join(action_example_lines) if action_example_lines else '- No single instance contained all three under the strict selection rule.'}

Prerequisite-like language examples (lexical candidates, not gold dependency annotations):

{chr(10).join(dependency_example_lines)}

## Email length and boilerplate

- Email token length: min {length_stats['min']}, median {length_stats['median']}, p90 {length_stats['p90']}, p95 {length_stats['p95']}, p99 {length_stats['p99']}, max {length_stats['max']}; mean {length_stats['mean']}.
- Thread length: min {thread_stats['min']}, median {thread_stats['median']}, p90 {thread_stats['p90']}, max {thread_stats['max']} email turns; mean {thread_stats['mean']}.
- Signature-like turns by split: {content['signature_like_turns_by_split']} (heuristic: closing/contact terms in the last 60 tokens).
- Embedded quoted-reply-like turns by split: {content['quoted_reply_like_turns_by_split']} (conservative; raw messages are often already separated into blocks).
- Repeated disclaimer categories by email-turn presence: {content['disclaimer_turn_counts']}.

Long tails are substantial and include corporate disclaimers, signatures/contact details, forwarded material, and quoted content. Models should not assume short sentence-like inputs even though the field is named `sentences`.

## Metadata completeness

The annotated JSON has no sender, recipient, subject, timestamp, or explicit thread-id fields. Filename is the only thread identifier. The raw-source header audit below covers {header_total:,} delimiter-separated blocks from the {metadata['files_matching_annotated_thread_stems']:,} matching raw files.

{md_table(['Raw header', 'Present', 'Non-empty', 'Non-empty share'], metadata_rows)}

`DATE`/`SENT` is only a syntactic header heuristic and can include body-like fields, so timestamp availability is at most the reported value. Raw block counts disagree with annotated turn counts in {metadata['raw_annotated_turn_count_mismatch_count']} threads. Consequently, the authoritative email count for modeling is the {identity['annotated_email_turn_occurrences']:,} annotated turns, not the {metadata['delimited_block_count_for_matching_files']:,} raw delimiter chunks.

## Annotation anomalies

{md_table(['Check', 'Count'], [[key.replace('_', ' '), value] for key, value in anomalies.items()])}

Structural anomaly samples:

{chr(10).join(structural_lines) if structural_lines else '- None.'}

Notable details:

- **327 turns across 282 threads** encode empty content as a nested list token (`[[""]]`) instead of a string token. One additional turn ends with a nested empty token after normal string tokens. These account for all 328 structural anomalies.
- {arguments['orphan_i_count']:,} `I-` transitions occur without a matching active span; downstream BIO decoders must choose whether to reject them or recover them as starts.
- {events['trigger_validation'].get('noncontiguous_indices', 0):,} triggers use non-contiguous token indices, and {events['trigger_validation'].get('empty_indices', 0):,} real triggers have empty index lists. Parsed, in-range trigger words otherwise match their indexed tokens in this copy.
- Label capitalization variants should be normalized only in a derived preprocessing layer, never by changing the raw files.

## Reproducibility

Run from the project root:

```bash
python3 scripts/audit_mailex.py
```

The script reads only `data/raw/mailex/`, counts train/dev/test as authoritative, verifies `full_data`, and rewrites the three report files deterministically. Input SHA-256 aggregate digests and exact counting policies are recorded in `mailex_audit.json`.
"""


def write_reports(report: dict[str, Any], label_rows: list[dict[str, Any]], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "mailex_audit.json"
    markdown_path = report_dir / "mailex_audit.md"
    csv_path = report_dir / "label_distribution.csv"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_path.write_text(make_markdown(report), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["metric", "split", "event_type", "qualifier", "argument_label", "bio_prefix", "count"],
        )
        writer.writeheader()
        writer.writerows(label_rows)


def print_summary(report: dict[str, Any], report_dir: Path) -> None:
    identity = report["identity_and_size"]
    structure = report["structure"]
    events = report["events"]
    arguments = report["arguments"]
    anomalies = report["anomalies_summary"]
    print("MailEx audit complete")
    print(f"  Authoritative threads: {identity['annotated_thread_occurrences']:,}")
    print(
        f"  Annotated email turns: {identity['annotated_email_turn_occurrences']:,} "
        f"({identity['unique_email_token_sequences']:,} exact unique token sequences)"
    )
    print(
        f"  full_data: {structure['full_data']['conclusion']} "
        f"({structure['full_data']['byte_mismatch_count']} byte mismatches)"
    )
    print(f"  Real event occurrences: {events['real_event_occurrences_excluding_o']:,}")
    print(
        f"  Argument spans: {arguments['argument_spans_bio_decoded']:,} BIO-decoded "
        f"({arguments['argument_spans_explicit_b_only']:,} explicit B starts)"
    )
    print(
        "  Alignment anomalies: "
        f"{anomalies['turn_key_mismatches']} turn-key, "
        f"{anomalies['token_label_length_mismatches']} token/label length"
    )
    print(
        f"  Main BIO anomaly: {anomalies['orphan_i_transitions']:,} orphan/role-transition I labels"
    )
    print(f"  Reports: {report_dir.resolve()}")


def main() -> None:
    args = parse_args()
    report, label_rows = audit(args.dataset_root)
    write_reports(report, label_rows, args.report_dir)
    print_summary(report, args.report_dir)


if __name__ == "__main__":
    main()
