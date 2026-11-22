"""Prepare type-valid, marked entity pairs for relation classification."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.model_data.token_classification import SOURCE_SPLITS, atomic_json, atomic_jsonl, read_jsonl


RELATION_LABELS = ["NONE", "ASSIGNED_TO", "DUE_ON", "SCHEDULED_ON", "DEPENDS_ON"]
LABEL_TO_ID = {label: index for index, label in enumerate(RELATION_LABELS)}
VALID_PAIR_LABELS = {
    ("TASK", "PERSON"): ("ASSIGNED_TO",),
    ("TASK", "GROUP"): ("ASSIGNED_TO",),
    ("TASK", "TEMPORAL"): ("DUE_ON", "SCHEDULED_ON"),
    ("TASK", "TASK"): ("DEPENDS_ON",),
    ("TASK", "EVENT"): ("DEPENDS_ON",),
}


def _validate_entities(text: str, entities: Sequence[Mapping[str, Any]], record_id: str) -> None:
    ids: set[str] = set()
    for entity in entities:
        entity_id = str(entity.get("id"))
        start, end = entity.get("start"), entity.get("end")
        if entity_id in ids:
            raise ValueError(f"{record_id}: duplicate entity ID {entity_id}")
        ids.add(entity_id)
        if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(text)):
            raise ValueError(f"{record_id}/{entity_id}: invalid entity offsets")
        if text[start:end] != entity.get("text"):
            raise ValueError(f"{record_id}/{entity_id}: entity text does not match offsets")


def _marker_events(entity: Mapping[str, Any], number: int) -> tuple[tuple[int, int, int, str], tuple[int, int, int, str]]:
    start, end = int(entity["start"]), int(entity["end"])
    entity_type = str(entity["type"])
    # At one boundary, close inner spans first, then open outer spans first.
    opening = (start, 1, -end, f"[E{number}_{entity_type}]")
    closing = (end, 0, -start, f"[/E{number}_{entity_type}]")
    return opening, closing


def marked_text(text: str, source: Mapping[str, Any], target: Mapping[str, Any]) -> str:
    """Insert typed entity markers without changing the preserved raw context."""

    if (source["start"], source["end"]) == (target["start"], target["end"]):
        start, end = int(source["start"]), int(source["end"])
        return (
            text[:start]
            + f"[E1_{source['type']}][E2_{target['type']}]"
            + text[start:end]
            + f"[/E2_{target['type']}][/E1_{source['type']}]"
            + text[end:]
        )
    events = [*_marker_events(source, 1), *_marker_events(target, 2)]
    by_position: dict[int, list[tuple[int, int, int, str]]] = {}
    for event in events:
        by_position.setdefault(event[0], []).append(event)
    output = []
    cursor = 0
    for position in sorted(by_position):
        output.append(text[cursor:position])
        for _position, kind, ordering, marker in sorted(by_position[position], key=lambda item: (item[1], item[2], item[3])):
            output.append(marker)
        cursor = position
    output.append(text[cursor:])
    return "".join(output)


def _prediction_entities(row: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    if isinstance(row.get("entities"), list):
        return row["entities"]
    annotations = row.get("text2task_annotations")
    if isinstance(annotations, Mapping) and isinstance(annotations.get("entities"), list):
        return annotations["entities"]
    raise ValueError(f"Predicted-entity row {row.get('id')} has no entities list")


def load_predicted_entities(path: Path) -> dict[str, Sequence[Mapping[str, Any]]]:
    result = {}
    for row in read_jsonl(path):
        record_id = str(row.get("source_record_id") or row.get("id"))
        if record_id in result:
            raise ValueError(f"Duplicate predicted-entity record {record_id}")
        result[record_id] = _prediction_entities(row)
    return result


def _annotation_relations(
    record: Mapping[str, Any],
    entities: Sequence[Mapping[str, Any]],
    *,
    entity_source: str,
) -> tuple[dict[tuple[str, str], Mapping[str, Any]], int, set[str]]:
    annotations = record["text2task_annotations"]
    original_entities = {str(entity["id"]): entity for entity in annotations.get("entities") or []}
    selected_entities = {str(entity["id"]): entity for entity in entities}
    skipped = 0
    ambiguous_predicted_ids: set[str] = set()
    if entity_source == "predicted":
        exact = {(entity["type"], int(entity["start"]), int(entity["end"])): str(entity["id"]) for entity in entities}
        id_map = {
            entity_id: exact.get((entity["type"], int(entity["start"]), int(entity["end"])))
            for entity_id, entity in original_entities.items()
        }
        for predicted in entities:
            for original in original_entities.values():
                if predicted["type"] == original["type"] and int(predicted["start"]) < int(original["end"]) and int(original["start"]) < int(predicted["end"]):
                    if (predicted["start"], predicted["end"]) != (original["start"], original["end"]):
                        ambiguous_predicted_ids.add(str(predicted["id"]))
    else:
        id_map = {entity_id: entity_id for entity_id in original_entities}

    positives: dict[tuple[str, str], Mapping[str, Any]] = {}
    for relation in annotations.get("relations") or []:
        relation_type = str(relation.get("type"))
        if relation_type not in RELATION_LABELS[1:]:
            continue
        source_id = id_map.get(str(relation.get("source_entity_id")))
        target_id = id_map.get(str(relation.get("target_entity_id")))
        if not source_id or not target_id:
            skipped += 1
            continue
        source, target = selected_entities[source_id], selected_entities[target_id]
        allowed = VALID_PAIR_LABELS.get((str(source["type"]), str(target["type"])), ())
        if relation_type not in allowed:
            raise ValueError(f"{record['id']}/{relation.get('id')}: invalid endpoint types for {relation_type}")
        key = (source_id, target_id)
        if key in positives and positives[key].get("type") != relation_type:
            raise ValueError(f"{record['id']}: pair {key} has multiple relation labels")
        positives[key] = relation
    return positives, skipped, ambiguous_predicted_ids


def candidate_rows_for_record(
    record: Mapping[str, Any],
    *,
    final_split: str,
    entity_source: str = "annotated",
    predicted_entities: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    if record.get("source_split") != SOURCE_SPLITS[final_split]:
        raise ValueError(f"{record.get('id')}: source/final split mismatch")
    text = str(record.get("text", ""))
    annotations = record.get("text2task_annotations")
    if not isinstance(annotations, Mapping):
        raise ValueError(f"{record.get('id')}: missing annotations")
    if entity_source == "predicted":
        if predicted_entities is None:
            raise ValueError(f"{record.get('id')}: no predicted entities supplied")
        entities = [dict(entity) for entity in predicted_entities]
    else:
        entities = [dict(entity) for entity in annotations.get("entities") or []]
    _validate_entities(text, entities, str(record.get("id")))
    positives, skipped_relations, ambiguous_ids = _annotation_relations(record, entities, entity_source=entity_source)
    output = []
    ambiguous_pairs_skipped = 0
    for source in entities:
        for target in entities:
            source_id, target_id = str(source["id"]), str(target["id"])
            if source_id == target_id:
                continue
            permitted = VALID_PAIR_LABELS.get((str(source["type"]), str(target["type"])))
            if not permitted:
                continue
            relation = positives.get((source_id, target_id))
            if relation is None and (source_id in ambiguous_ids or target_id in ambiguous_ids):
                ambiguous_pairs_skipped += 1
                continue
            label = str(relation["type"]) if relation else "NONE"
            digest = hashlib.sha256(f"{record['id']}\0{source_id}\0{target_id}".encode("utf-8")).hexdigest()[:16]
            evidence = relation.get("relation_evidence") if relation else None
            output.append({
                "id": f"{record['id']}::relation_pair_{digest}",
                "source_record_id": record["id"],
                "source": record.get("source"),
                "final_split": final_split,
                "source_split": record["source_split"],
                "thread_id": record.get("thread_id"),
                "turn_index": record.get("turn_index"),
                "annotation_tier": (record.get("annotation_provenance") or {}).get("quality_tier"),
                "entity_source": entity_source,
                "text": text,
                "marked_text": marked_text(text, source, target),
                "source_entity": {key: source.get(key) for key in ("id", "type", "start", "end", "text")},
                "target_entity": {key: target.get(key) for key in ("id", "type", "start", "end", "text")},
                "candidate_relation_types": list(permitted),
                "label": label,
                "label_id": LABEL_TO_ID[label],
                "original_relation_id": relation.get("id") if relation else None,
                "relation_evidence": evidence,
                "explicit_vs_inferred": relation.get("explicit_vs_inferred") if relation else None,
                "ambiguous": relation.get("ambiguous") if relation else False,
            })
    positive_keys = {(row["source_entity"]["id"], row["target_entity"]["id"]) for row in output if row["label"] != "NONE"}
    if positive_keys != set(positives):
        raise ValueError(f"{record.get('id')}: positive relation lost during candidate generation")
    return output, skipped_relations, ambiguous_pairs_skipped


def _rank(seed: int, row: Mapping[str, Any]) -> str:
    return hashlib.sha256(f"{seed}\0{row['id']}".encode("utf-8")).hexdigest()


def sample_negatives(rows: Sequence[Mapping[str, Any]], *, ratio: float, seed: int) -> list[dict[str, Any]]:
    """Keep all positives and a deterministic, bounded set of valid NONE rows."""

    if ratio < 0:
        raise ValueError("negative ratio cannot be negative")
    positives = [dict(row) for row in rows if row["label"] != "NONE"]
    negatives = [dict(row) for row in rows if row["label"] == "NONE"]
    by_record: dict[str, list[dict[str, Any]]] = {}
    positive_records = {str(row["source_record_id"]) for row in positives}
    for row in negatives:
        by_record.setdefault(str(row["source_record_id"]), []).append(row)
    protected = [min(values, key=lambda row: _rank(seed, row)) for record_id, values in by_record.items() if record_id not in positive_records]
    target = max(math.ceil(len(positives) * ratio), len(protected)) if negatives else 0
    target = min(target, len(negatives))
    selected_ids = {row["id"] for row in protected[:target]}
    remaining = sorted((row for row in negatives if row["id"] not in selected_ids), key=lambda row: _rank(seed, row))
    selected = protected[:target] + remaining[: max(0, target - len(selected_ids))]
    return sorted(positives + selected, key=lambda row: (str(row["source_record_id"]), str(row["id"])))


def prepare_split(
    input_path: Path,
    output_path: Path,
    *,
    final_split: str,
    negative_ratio: float = 1.0,
    seed: int = 20261030,
    entity_source: str = "annotated",
    predicted_by_record: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    records = read_jsonl(input_path)
    all_rows: list[dict[str, Any]] = []
    skipped_relations = 0
    ambiguous_pairs = 0
    for record in records:
        predicted = predicted_by_record.get(str(record["id"])) if predicted_by_record is not None else None
        rows, skipped, ambiguous = candidate_rows_for_record(
            record,
            final_split=final_split,
            entity_source=entity_source,
            predicted_entities=predicted,
        )
        all_rows.extend(rows)
        skipped_relations += skipped
        ambiguous_pairs += ambiguous
    sampled = sample_negatives(all_rows, ratio=negative_ratio, seed=seed)
    atomic_jsonl(output_path, sampled)
    counts = Counter(row["label"] for row in sampled)
    return {
        "source_records": len(records),
        "threads": len({record.get("thread_id") for record in records}),
        "all_type_valid_candidates": len(all_rows),
        "model_rows": len(sampled),
        "positive_rows": sum(value for key, value in counts.items() if key != "NONE"),
        "negative_rows": counts["NONE"],
        "label_counts": dict(sorted(counts.items())),
        "records_represented": len({row["source_record_id"] for row in sampled}),
        "unmatched_positive_relations_for_predicted_entities": skipped_relations,
        "ambiguous_predicted_pairs_skipped": ambiguous_pairs,
    }


def prepare_all_splits(
    input_dir: Path,
    output_dir: Path,
    *,
    negative_ratio: float = 1.0,
    seed: int = 20261030,
    entity_source: str = "annotated",
    predicted_entity_files: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    if entity_source not in {"annotated", "gold", "predicted"}:
        raise ValueError("entity_source must be annotated, gold, or predicted")
    normalized_source = "annotated" if entity_source == "gold" else entity_source
    split_stats = {}
    for split in ("train", "validation", "test"):
        predicted = None
        if normalized_source == "predicted":
            if not predicted_entity_files or split not in predicted_entity_files:
                raise ValueError(f"Missing predicted-entity file for {split}")
            predicted = load_predicted_entities(predicted_entity_files[split])
        split_stats[split] = prepare_split(
            input_dir / f"{split}.jsonl",
            output_dir / f"{split}.jsonl",
            final_split=split,
            negative_ratio=negative_ratio,
            seed=seed,
            entity_source=normalized_source,
            predicted_by_record=predicted,
        )
    stats = {
        "task": "relation_classification",
        "entity_source": normalized_source,
        "negative_ratio": negative_ratio,
        "seed": seed,
        "valid_pair_labels": {f"{source}->{target}": list(labels) for (source, target), labels in VALID_PAIR_LABELS.items()},
        "splits": split_stats,
    }
    atomic_json(output_dir / "label_map.json", {"labels": RELATION_LABELS, "label_to_id": LABEL_TO_ID})
    atomic_json(output_dir / "statistics.json", stats)
    return stats
