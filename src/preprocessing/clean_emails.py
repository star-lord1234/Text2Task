"""Conservative, annotation-safe cleaning for unified email records.

Cleaning is token-aware: MailEx argument and trigger token positions are
protected from deletion, original tokens/events are never rewritten, and the
cleaned token-offset list remains indexed by original token position.  Ambiguous
signature/quote/artifact candidates are retained and flagged for review.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SPLITS = ("train", "dev", "test")
CLEANING_VERSION = "1.0.0"

DISCLAIMER_PATTERNS = (
    re.compile(r"this e-?mail is the property of enron", re.I),
    re.compile(r"\+{3,}\s*confidentiality notice\s*\+{3,}", re.I),
    re.compile(r"\bconfidentiality notice\s*:", re.I),
    re.compile(r"the information (?:in|contained in) this (?:e-?mail|electronic mail).{0,80}(?:confidential|privileged)", re.I),
    re.compile(r"this message is confidential\s*\.?\s*it may also be privileged", re.I),
    re.compile(r"this e-?mail and any files transmitted with it.{0,100}confidential", re.I),
)
DISCLAIMER_EVIDENCE = re.compile(
    r"intended recipient|review,? use,? distribution|dissemination or copying|delete (?:all copies|this email)|privileged",
    re.I,
)
QUOTE_PATTERNS = (
    re.compile(r"(?:-{2,}\s*)?original message(?:\s*-{2,})?", re.I),
    re.compile(r"(?:-{2,}\s*)?forwarded message(?:\s*-{2,})?", re.I),
    re.compile(r"-{2,}\s*forwarded by\b", re.I),
    re.compile(r"\bfrom\s*:.{0,200}\bsent\s*:.{0,200}\b(?:to|subject)\s*:", re.I | re.S),
)
SIGNOFF_RE = re.compile(
    r"\b(kind regards|best regards|warm regards|regards|sincerely|cheers|many thanks|thanks|thank you)[,!:.]?",
    re.I,
)
CONTACT_RE = re.compile(
    r"(?:\b(?:tel|telephone|phone|fax|cell|mobile|pager|email|e-mail)\s*[:.]|"
    r"\b\d{3}[- )]\d{3}[- ]\d{4}\b|[A-Z0-9._%+-]+\s*@\s*[A-Z0-9.-]+\.[A-Z]{2,})",
    re.I,
)
TASK_OR_TEMPORAL_RE = re.compile(
    r"\b(?:before|after|today|tomorrow|tonight|next|week|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|until|when|please|must|need|should|call|send|review|approve|meet|schedule)\b",
    re.I,
)
NON_SIGNATURE_CONTENT_RE = re.compile(
    r"\$|\b(?:fee|fare|ticket|tkt|reservation|charged|amount|deadline|due|attached|attachment|question|opportunity)\b",
    re.I,
)
SIGNATURE_DELIMITER_RE = re.compile(r"(?:^|\s)(?:--\s*){1,3}(?=\S)")
ENCODING_REPLACEMENTS = {
    "â€™": "’",
    "â€˜": "‘",
    "â€œ": "“",
    "â€": "”",
    "â€“": "–",
    "â€”": "—",
    "Â ": " ",
    "\u00a0": " ",
    "\u200b": "",
}
UNCERTAIN_ARTIFACT_RE = re.compile(r"(?:\ufffd|=(?:0A|0D|09|20)|â€)", re.I)
WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Candidate:
    kind: str
    start: int
    end: int
    confidence: str
    reason: str
    automatic: bool


def token_surface(token: Any) -> str:
    if isinstance(token, str):
        return token
    if isinstance(token, list):
        return " ".join(token_surface(item) for item in token)
    return json.dumps(token, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def protected_token_indices(record: dict[str, Any]) -> set[int]:
    """Collect every token referenced by a non-O BIO label or trigger."""

    protected: set[int] = set()
    for payload in record.get("original_events", {}).values():
        if not isinstance(payload, dict):
            continue
        for sequence in payload.get("labels", []):
            if not isinstance(sequence, list):
                continue
            protected.update(index for index, label in enumerate(sequence) if label != "O")
        for trigger_raw in payload.get("triggers", []):
            if not trigger_raw or trigger_raw == "O" or not isinstance(trigger_raw, str):
                continue
            try:
                trigger = ast.literal_eval(trigger_raw)
                indices = str(trigger.get("indices", "")).split() if isinstance(trigger, dict) else []
                protected.update(int(index) for index in indices)
            except (SyntaxError, ValueError, TypeError):
                # Malformed triggers are dealt with by conservative fallback:
                # candidate deletion is disabled later if annotation parsing is unsafe.
                protected.add(-1)
    return protected


def indices_overlapping_span(offsets: list[Any], start: int, end: int) -> list[int]:
    indices = []
    for index, offset in enumerate(offsets):
        if not isinstance(offset, list) or len(offset) != 2:
            continue
        token_start, token_end = offset
        if token_start == token_end:
            if start <= token_start <= end:
                indices.append(index)
        elif token_end > start and token_start < end:
            indices.append(index)
    return indices


def _first_match(patterns: Iterable[re.Pattern[str]], text: str) -> re.Match[str] | None:
    matches = [match for pattern in patterns if (match := pattern.search(text))]
    return min(matches, key=lambda match: match.start()) if matches else None


def detect_disclaimer(text: str) -> Candidate | None:
    match = _first_match(DISCLAIMER_PATTERNS, text)
    if not match:
        return None
    start = match.start()
    # Repeated asterisk/underscore separators are part of the legal boilerplate
    # when they occur immediately before a recognized disclaimer anchor.
    separator = re.search(r"(?:(?:\s*\*){8,}|(?:\s*_){8,})\s*$", text[:start])
    if separator:
        start = separator.start()
    tail = text[start:]
    evidence = len(DISCLAIMER_EVIDENCE.findall(tail))
    near_tail = start >= max(0, len(text) // 3) or len(tail) <= 2_500
    automatic = evidence >= 2 and near_tail
    return Candidate(
        kind="legal_disclaimer",
        start=start,
        end=len(text),
        confidence="high" if automatic else "uncertain",
        reason=f"legal boilerplate anchor with {evidence} corroborating phrase(s)",
        automatic=automatic,
    )


def detect_quote(text: str) -> Candidate | None:
    match = _first_match(QUOTE_PATTERNS, text)
    if not match:
        return None
    # A whole-message forward can contain the only task evidence.  Store and
    # flag it, but automatically remove only a trailing quoted history after a
    # substantive current-message prefix.
    prefix_words = WORD_RE.findall(text[: match.start()])
    automatic = len(prefix_words) >= 3 and match.start() >= 20
    return Candidate(
        kind="quoted_or_forwarded_block",
        start=match.start(),
        end=len(text),
        confidence="high" if automatic else "uncertain",
        reason="explicit reply/forward header sequence",
        automatic=automatic,
    )


def detect_signature(text: str, upper_bound: int | None = None) -> Candidate | None:
    end = upper_bound if upper_bound is not None else len(text)
    searchable = text[:end]
    tail_start = max(0, int(len(searchable) * 0.60))
    tail = searchable[tail_start:]
    signoffs = list(SIGNOFF_RE.finditer(tail))
    delimiters = list(SIGNATURE_DELIMITER_RE.finditer(tail))
    matches = [(match.start() + tail_start, "signoff") for match in signoffs]
    matches += [(match.start() + tail_start, "delimiter") for match in delimiters]
    if not matches:
        return None
    start, marker_kind = min(matches)
    candidate_text = searchable[start:]
    has_contact = bool(CONTACT_RE.search(candidate_text))
    word_count = len(WORD_RE.findall(candidate_text))
    has_task_or_time_language = bool(TASK_OR_TEMPORAL_RE.search(candidate_text))
    has_non_signature_content = bool(NON_SIGNATURE_CONTENT_RE.search(candidate_text))
    automatic = (
        marker_kind == "signoff"
        and has_contact
        and 3 <= word_count <= 30
        and not has_task_or_time_language
        and not has_non_signature_content
    )
    return Candidate(
        kind="email_signature",
        start=start,
        end=end,
        confidence="high" if automatic else "uncertain",
        reason=(
            f"trailing {marker_kind}"
            + (" with contact evidence" if has_contact else " without contact evidence")
            + (" containing task/temporal language" if has_task_or_time_language else "")
            + (" containing non-signature content" if has_non_signature_content else "")
        ),
        automatic=automatic,
    )


def normalize_token_surface(surface: str) -> tuple[str, list[dict[str, str]], bool]:
    modified = surface
    changes: list[dict[str, str]] = []
    for source, target in ENCODING_REPLACEMENTS.items():
        if source in modified:
            modified = modified.replace(source, target)
            changes.append({"from": source, "to": target})
    uncertain = bool(UNCERTAIN_ARTIFACT_RE.search(modified))
    return modified, changes, uncertain


def _separator(raw_text: str, offsets: list[list[int]], previous: int, current: int) -> str:
    if previous + 1 == current:
        raw_separator = raw_text[offsets[previous][1] : offsets[current][0]]
        if not raw_separator:
            return ""
        return " " if raw_separator.isspace() else re.sub(r"\s+", " ", raw_separator)
    previous_surface = raw_text[offsets[previous][0] : offsets[previous][1]]
    current_surface = raw_text[offsets[current][0] : offsets[current][1]]
    if not previous_surface or not current_surface:
        return ""
    if re.match(r"^[.,!?;:%)\]}]", current_surface):
        return ""
    return " "


def render_clean_text(
    record: dict[str, Any], removed: set[int], protected: set[int]
) -> tuple[str, list[list[int] | None], list[dict[str, Any]], list[str]]:
    raw_text = record["text"]
    tokens = record["tokens"]
    raw_offsets = record["token_offsets"]
    pieces: list[str] = []
    clean_offsets: list[list[int] | None] = [None] * len(tokens)
    modifications: list[dict[str, Any]] = []
    flags: list[str] = []
    cursor = 0
    previous_kept: int | None = None

    for index, (token, offset) in enumerate(zip(tokens, raw_offsets)):
        if index in removed:
            continue
        raw_surface = raw_text[offset[0] : offset[1]]
        expected_surface = token_surface(token)
        if raw_surface != expected_surface:
            raise ValueError(f"raw token offset mismatch at token {index}")
        clean_surface, changes, uncertain = normalize_token_surface(raw_surface)
        if changes and index in protected:
            clean_surface = raw_surface
            flags.append("encoding_artifact_overlaps_annotation")
            modifications.append(
                {
                    "type": "encoding_artifact",
                    "action": "preserved_for_review",
                    "raw_token_span": [index, index + 1],
                    "raw_char_span": offset,
                    "original_text": raw_surface,
                    "replacement": None,
                    "reason": "deterministic replacement overlaps protected annotation token",
                    "confidence": "uncertain",
                }
            )
        elif changes:
            modifications.append(
                {
                    "type": "encoding_artifact",
                    "action": "modified",
                    "raw_token_span": [index, index + 1],
                    "raw_char_span": offset,
                    "original_text": raw_surface,
                    "replacement": clean_surface,
                    "reason": f"known encoding replacement(s): {changes}",
                    "confidence": "high",
                }
            )
        if uncertain:
            flags.append("uncertain_encoding_artifact")
        if previous_kept is not None:
            separator = _separator(raw_text, raw_offsets, previous_kept, index)
            normalized = re.sub(r"\s+", " ", separator)
            if normalized != separator:
                modifications.append(
                    {
                        "type": "whitespace",
                        "action": "modified",
                        "raw_token_span": [previous_kept + 1, index],
                        "raw_char_span": [raw_offsets[previous_kept][1], offset[0]],
                        "original_text": separator,
                        "replacement": normalized,
                        "reason": "collapsed excessive inter-token whitespace",
                        "confidence": "high",
                    }
                )
            pieces.append(normalized)
            cursor += len(normalized)
        start = cursor
        pieces.append(clean_surface)
        cursor += len(clean_surface)
        clean_offsets[index] = [start, cursor]
        previous_kept = index
    return "".join(pieces), clean_offsets, modifications, sorted(set(flags))


def validate_source_alignment(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    text = record.get("text")
    tokens = record.get("tokens")
    offsets = record.get("token_offsets")
    if not isinstance(text, str) or not isinstance(tokens, list) or not isinstance(offsets, list):
        return ["missing or invalid text/tokens/token_offsets"]
    if len(tokens) != len(offsets):
        return ["token/offset length mismatch"]
    for index, (token, offset) in enumerate(zip(tokens, offsets)):
        if not isinstance(offset, list) or len(offset) != 2 or not all(isinstance(value, int) for value in offset):
            errors.append(f"invalid offset at {index}")
            continue
        start, end = offset
        if not 0 <= start <= end <= len(text) or text[start:end] != token_surface(token):
            errors.append(f"unreliable source alignment at {index}")
    return errors


def validate_clean_alignment(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    text = record["text"]
    tokens = record["tokens"]
    offsets = record["token_offsets"]
    removed = set(record["cleaning"]["removed_token_indices"])
    if len(tokens) != len(offsets):
        return ["clean token/offset length mismatch"]
    for index, (token, offset) in enumerate(zip(tokens, offsets)):
        if index in removed:
            if offset is not None:
                errors.append(f"removed token {index} has an offset")
            continue
        if offset is None:
            errors.append(f"retained token {index} lacks an offset")
            continue
        start, end = offset
        expected, _, _ = normalize_token_surface(token_surface(token))
        if index in set(record["cleaning"]["protected_token_indices"]):
            # Protected encoding artifacts are intentionally left unchanged.
            raw_start, raw_end = record["token_offsets_raw"][index]
            raw_surface = record["text_raw"][raw_start:raw_end]
            if any(op["type"] == "encoding_artifact" and op["action"] == "preserved_for_review" and op["raw_token_span"][0] == index for op in record["cleaning"]["operations"]):
                expected = raw_surface
        if text[start:end] != expected:
            errors.append(f"clean token {index} does not reconstruct")
    return errors


def clean_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a cleaned record without mutating the unified input record."""

    source_errors = validate_source_alignment(record)
    raw_text = record.get("text", "")
    raw_offsets = record.get("token_offsets", [])
    protected = protected_token_indices(record)
    annotation_parse_unsafe = -1 in protected
    protected.discard(-1)
    operations: list[dict[str, Any]] = []
    quoted_context: list[dict[str, Any]] = []
    review_flags: list[str] = []
    removed: set[int] = set()

    if source_errors:
        cleaned = dict(record)
        cleaned["text_raw"] = raw_text
        cleaned["token_offsets_raw"] = raw_offsets
        cleaned["cleaning"] = {
            "version": CLEANING_VERSION,
            "alignment_status": "fallback_raw",
            "training_text_source": "text_raw",
            "protected_token_indices": sorted(protected),
            "removed_token_indices": [],
            "operations": [],
            "review_flags": ["unreliable_source_alignment", *source_errors],
        }
        cleaned["quoted_context"] = []
        cleaned["duplicate_info"] = None
        return cleaned

    disclaimer = detect_disclaimer(raw_text)
    quote = detect_quote(raw_text)
    candidates = [candidate for candidate in (quote, disclaimer) if candidate]
    earliest_high_confidence_removal = min(
        (candidate.start for candidate in candidates if candidate.automatic), default=len(raw_text)
    )
    signature = detect_signature(raw_text, earliest_high_confidence_removal)
    if signature:
        candidates.append(signature)
    candidates.sort(key=lambda candidate: (candidate.start, candidate.kind))

    for candidate in candidates:
        overlapping = indices_overlapping_span(raw_offsets, candidate.start, candidate.end)
        remaining = [index for index in overlapping if index not in removed]
        if not remaining:
            continue
        protected_overlap = sorted(set(remaining) & protected)
        automatic = candidate.automatic and not protected_overlap and not annotation_parse_unsafe
        action = "removed" if automatic else "preserved_for_review"
        exact_start = raw_offsets[remaining[0]][0]
        exact_end = raw_offsets[remaining[-1]][1]
        operation = {
            "type": candidate.kind,
            "action": action,
            "raw_char_span": [exact_start, exact_end],
            "raw_token_span": [remaining[0], remaining[-1] + 1],
            "original_text": raw_text[exact_start:exact_end],
            "replacement": "" if automatic else None,
            "reason": candidate.reason,
            "confidence": candidate.confidence,
            "protected_overlap": protected_overlap,
        }
        operations.append(operation)
        if candidate.kind == "quoted_or_forwarded_block":
            quoted_context.append(
                {
                    "kind": "quoted_or_forwarded_block",
                    "raw_char_span": [exact_start, exact_end],
                    "raw_token_span": [remaining[0], remaining[-1] + 1],
                    "text": raw_text[exact_start:exact_end],
                    "removed_from_text": automatic,
                    "protected_overlap": protected_overlap,
                }
            )
        if automatic:
            removed.update(remaining)
        else:
            review_flags.append(f"review_{candidate.kind}")
            if protected_overlap:
                review_flags.append(f"{candidate.kind}_overlaps_annotation")

    try:
        clean_text, clean_offsets, modifications, artifact_flags = render_clean_text(record, removed, protected)
    except (ValueError, IndexError, TypeError) as error:
        cleaned = dict(record)
        cleaned["text_raw"] = raw_text
        cleaned["token_offsets_raw"] = raw_offsets
        cleaned["cleaning"] = {
            "version": CLEANING_VERSION,
            "alignment_status": "fallback_raw",
            "training_text_source": "text_raw",
            "protected_token_indices": sorted(protected),
            "removed_token_indices": [],
            "operations": operations,
            "review_flags": sorted(set([*review_flags, "clean_render_failure", str(error)])),
        }
        cleaned["quoted_context"] = quoted_context
        cleaned["duplicate_info"] = None
        return cleaned

    operations.extend(modifications)
    review_flags.extend(artifact_flags)
    cleaned = dict(record)
    cleaned["text_raw"] = raw_text
    cleaned["token_offsets_raw"] = raw_offsets
    cleaned["text"] = clean_text
    cleaned["token_offsets"] = clean_offsets
    cleaned["cleaning"] = {
        "version": CLEANING_VERSION,
        "alignment_status": "reliable",
        "training_text_source": "text",
        "protected_token_indices": sorted(protected),
        "removed_token_indices": sorted(removed),
        "operations": operations,
        "review_flags": sorted(set(review_flags)),
    }
    cleaned["quoted_context"] = quoted_context
    cleaned["duplicate_info"] = None
    alignment_errors = validate_clean_alignment(cleaned)
    if alignment_errors:
        cleaned["text"] = raw_text
        cleaned["token_offsets"] = raw_offsets
        cleaned["cleaning"]["alignment_status"] = "fallback_raw"
        cleaned["cleaning"]["training_text_source"] = "text_raw"
        cleaned["cleaning"]["removed_token_indices"] = []
        cleaned["cleaning"]["review_flags"] = sorted(
            set([*cleaned["cleaning"]["review_flags"], "clean_alignment_validation_failed", *alignment_errors])
        )
    json.dumps(cleaned, ensure_ascii=False)
    return cleaned


def normalized_words(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def shingles(words: list[str], width: int = 3) -> set[str]:
    if len(words) < width:
        return set(words)
    return {" ".join(words[index : index + width]) for index in range(len(words) - width + 1)}


def simhash(values: set[str]) -> int:
    if not values:
        return 0
    weights = [0] * 64
    for value in sorted(values):
        number = int.from_bytes(hashlib.sha256(value.encode("utf-8")).digest()[:8], "big")
        for bit in range(64):
            weights[bit] += 1 if number & (1 << bit) else -1
    result = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            result |= 1 << bit
    return result


class UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def annotate_duplicates(records: list[dict[str, Any]], near_threshold: float = 0.85) -> dict[str, Any]:
    """Annotate exact-text and conservative shingle-Jaccard near duplicates."""

    exact_groups: defaultdict[str, list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        digest = hashlib.sha256(record["text_raw"].encode("utf-8")).hexdigest()
        exact_groups[digest].append(index)
    exact_multi = {digest: indices for digest, indices in exact_groups.items() if len(indices) > 1}

    word_lists = [normalized_words(record["text"]) for record in records]
    shingle_sets = [shingles(words) for words in word_lists]
    hashes = [simhash(values) for values in shingle_sets]
    buckets: defaultdict[tuple[int, int], list[int]] = defaultdict(list)
    for index, (words, signature) in enumerate(zip(word_lists, hashes)):
        if len(words) < 8:
            continue
        for band in range(4):
            buckets[(band, (signature >> (band * 16)) & 0xFFFF)].append(index)

    candidates: set[tuple[int, int]] = set()
    skipped_large_buckets = 0
    for indices in buckets.values():
        if len(indices) > 250:
            skipped_large_buckets += 1
            continue
        for position, left in enumerate(indices):
            for right in indices[position + 1 :]:
                candidates.add((min(left, right), max(left, right)))

    union = UnionFind(len(records))
    near_pairs = 0
    for left, right in sorted(candidates):
        if records[left]["text_raw"] == records[right]["text_raw"]:
            continue
        left_words, right_words = word_lists[left], word_lists[right]
        length_ratio = min(len(left_words), len(right_words)) / max(len(left_words), len(right_words))
        if length_ratio < 0.75:
            continue
        left_set, right_set = shingle_sets[left], shingle_sets[right]
        union_size = len(left_set | right_set)
        score = len(left_set & right_set) / union_size if union_size else 0.0
        if score >= near_threshold:
            union.union(left, right)
            near_pairs += 1

    near_components: defaultdict[int, list[int]] = defaultdict(list)
    for index in range(len(records)):
        near_components[union.find(index)].append(index)
    near_multi = [indices for indices in near_components.values() if len(indices) > 1]

    for digest, indices in exact_multi.items():
        canonical = min((records[index]["id"] for index in indices))
        group_id = f"exact:{digest[:16]}"
        for index in indices:
            info = records[index]["duplicate_info"] or {}
            info["exact_group_id"] = group_id
            info["exact_group_size"] = len(indices)
            info["exact_canonical_id"] = canonical
            records[index]["duplicate_info"] = info
    for indices in near_multi:
        canonical = min((records[index]["id"] for index in indices))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        group_id = f"near:{digest}"
        for index in indices:
            info = records[index]["duplicate_info"] or {}
            info["near_group_id"] = group_id
            info["near_group_size"] = len(indices)
            info["near_canonical_id"] = canonical
            info["near_threshold"] = near_threshold
            records[index]["duplicate_info"] = info

    return {
        "exact_group_count": len(exact_multi),
        "exact_record_count": sum(len(indices) for indices in exact_multi.values()),
        "near_group_count": len(near_multi),
        "near_record_count": sum(len(indices) for indices in near_multi),
        "near_verified_pair_count": near_pairs,
        "near_candidate_pair_count": len(candidates),
        "skipped_large_simhash_buckets": skipped_large_buckets,
        "near_threshold": near_threshold,
    }


def write_jsonl(records: Iterable[dict[str, Any]], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
            count += 1
    return count


def load_and_clean(input_dir: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    records_by_split: dict[str, list[dict[str, Any]]] = {}
    all_records: list[dict[str, Any]] = []
    stats_by_split: dict[str, Any] = {}
    for split in SPLITS:
        input_path = input_dir / f"{split}.jsonl"
        if not input_path.is_file():
            raise ValueError(f"Missing unified input: {input_path}")
        records: list[dict[str, Any]] = []
        stats: Counter[str] = Counter()
        for line_number, line in enumerate(input_path.read_text(encoding="utf-8").splitlines(), 1):
            source = json.loads(line)
            cleaned = clean_record(source)
            if cleaned["source_split"] != split:
                raise ValueError(f"Split mismatch in {input_path}:{line_number}")
            records.append(cleaned)
            stats["records"] += 1
            stats["tokens"] += len(cleaned["tokens"])
            stats[f"alignment_{cleaned['cleaning']['alignment_status']}"] += 1
            if cleaned["cleaning"]["operations"]:
                stats["records_with_operations"] += 1
            if cleaned["cleaning"]["review_flags"]:
                stats["records_flagged_for_review"] += 1
            if cleaned["quoted_context"]:
                stats["records_with_quoted_context"] += 1
            for operation in cleaned["cleaning"]["operations"]:
                stats[f"operation_{operation['type']}_{operation['action']}"] += 1
        records_by_split[split] = records
        all_records.extend(records)
        stats_by_split[split] = dict(sorted(stats.items()))
    duplicate_stats = annotate_duplicates(all_records)
    return records_by_split, {"by_split": stats_by_split, "duplicates": duplicate_stats}


def clean_dataset(input_dir: Path, output_dir: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    records_by_split, stats = load_and_clean(input_dir)
    for split in SPLITS:
        written = write_jsonl(records_by_split[split], output_dir / f"{split}.jsonl")
        if written != stats["by_split"][split]["records"]:
            raise ValueError(f"Output record count mismatch for {split}")
    return records_by_split, stats
