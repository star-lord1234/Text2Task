"""DistilBERT WordPiece preparation with exact character-offset alignment.

The project deliberately keeps this implementation dependency-free.  It uses
the official ``distilbert-base-uncased`` vocabulary and mirrors the relevant
BasicTokenizer + greedy WordPiece behavior while retaining offsets into the
original email.  That makes the alignment auditable without requiring a
particular version of ``transformers`` at data-build time.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ENTITY_TYPES = ("ARTIFACT", "EVENT", "GROUP", "PERSON", "TASK", "TEMPORAL")
LABELS = ["O"] + [label for entity_type in ENTITY_TYPES for label in (f"B-{entity_type}", f"I-{entity_type}")]
LABEL_TO_ID = {label: index for index, label in enumerate(LABELS)}
SOURCE_SPLITS = {"train": "train", "validation": "dev", "test": "test"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def atomic_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _is_whitespace(char: str) -> bool:
    return char in " \t\n\r" or unicodedata.category(char) == "Zs"


def _is_control(char: str) -> bool:
    return char not in "\t\n\r" and unicodedata.category(char) in {"Cc", "Cf"}


def _is_punctuation(char: str) -> bool:
    code = ord(char)
    return (33 <= code <= 47) or (58 <= code <= 64) or (91 <= code <= 96) or (123 <= code <= 126) or unicodedata.category(char).startswith("P")


def _is_chinese(char: str) -> bool:
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x20000 <= code <= 0x2A6DF
        or 0x2A700 <= code <= 0x2B73F
        or 0x2B740 <= code <= 0x2B81F
        or 0x2B820 <= code <= 0x2CEAF
        or 0xF900 <= code <= 0xFAFF
        or 0x2F800 <= code <= 0x2FA1F
    )


class DistilBertWordPieceTokenizer:
    """Minimal offset-aware tokenizer for the official uncased vocabulary."""

    def __init__(self, vocab_path: Path | str, max_input_chars_per_word: int = 100):
        self.vocab_path = Path(vocab_path)
        tokens = self.vocab_path.read_text(encoding="utf-8").splitlines()
        if len(tokens) < 100 or len(tokens) != len(set(tokens)):
            raise ValueError(f"Invalid WordPiece vocabulary: {self.vocab_path}")
        self.vocab = {token: index for index, token in enumerate(tokens)}
        for required in ("[PAD]", "[UNK]", "[CLS]", "[SEP]"):
            if required not in self.vocab:
                raise ValueError(f"Vocabulary lacks {required}")
        self.max_input_chars_per_word = max_input_chars_per_word

    def _basic_tokens(self, text: str) -> list[tuple[str, list[int]]]:
        raw_units: list[tuple[str, list[int]]] = []
        index = 0
        while index < len(text):
            char = text[index]
            if _is_whitespace(char) or _is_control(char):
                index += 1
                continue
            if _is_punctuation(char) or _is_chinese(char):
                raw_units.append((char, [index]))
                index += 1
                continue
            start = index
            while index < len(text):
                current = text[index]
                if _is_whitespace(current) or _is_control(current) or _is_punctuation(current) or _is_chinese(current):
                    break
                index += 1
            raw_units.append((text[start:index], list(range(start, index))))

        normalized: list[tuple[str, list[int]]] = []
        for unit, positions in raw_units:
            chars: list[str] = []
            mapping: list[int] = []
            for char, original_position in zip(unit, positions):
                for decomposed in unicodedata.normalize("NFD", char.lower()):
                    if unicodedata.category(decomposed) != "Mn":
                        chars.append(decomposed)
                        mapping.append(original_position)
            if chars:
                normalized.append(("".join(chars), mapping))
        return normalized

    def tokenize_with_offsets(self, text: str) -> list[dict[str, Any]]:
        pieces: list[dict[str, Any]] = []
        for token, mapping in self._basic_tokens(text):
            if len(token) > self.max_input_chars_per_word:
                pieces.append({"token": "[UNK]", "id": self.vocab["[UNK]"], "start": mapping[0], "end": mapping[-1] + 1})
                continue
            start = 0
            current: list[tuple[str, int, int]] = []
            failed = False
            while start < len(token):
                end = len(token)
                matched: tuple[str, int, int] | None = None
                while start < end:
                    candidate = token[start:end]
                    vocabulary_form = candidate if start == 0 else "##" + candidate
                    if vocabulary_form in self.vocab:
                        matched = (vocabulary_form, start, end)
                        break
                    end -= 1
                if matched is None:
                    failed = True
                    break
                current.append(matched)
                start = matched[2]
            if failed:
                pieces.append({"token": "[UNK]", "id": self.vocab["[UNK]"], "start": mapping[0], "end": mapping[-1] + 1})
                continue
            for vocabulary_form, piece_start, piece_end in current:
                pieces.append({
                    "token": vocabulary_form,
                    "id": self.vocab[vocabulary_form],
                    "start": mapping[piece_start],
                    "end": mapping[piece_end - 1] + 1,
                })
        return pieces


def spans_overlap(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return int(left["start"]) < int(right["end"]) and int(right["start"]) < int(left["end"])


def assign_overlap_layers(entities: Sequence[Mapping[str, Any]]) -> list[list[dict[str, Any]]]:
    """Greedily color interval spans; no layer contains an overlap."""

    layers: list[list[dict[str, Any]]] = []
    ordered = sorted((dict(entity) for entity in entities), key=lambda item: (int(item["start"]), int(item["end"]), str(item["type"]), str(item["id"])))
    for entity in ordered:
        for layer in layers:
            if all(not spans_overlap(entity, existing) for existing in layer):
                layer.append(entity)
                break
        else:
            layers.append([entity])
    return layers or [[]]


def _piece_indices_for_entity(text: str, entity: Mapping[str, Any], pieces: Sequence[Mapping[str, Any]]) -> list[int]:
    start, end = int(entity["start"]), int(entity["end"])
    if not (0 <= start < end <= len(text)) or text[start:end] != entity.get("text"):
        raise ValueError(f"{entity.get('id')}: entity text/offset mismatch")
    indices = [index for index, piece in enumerate(pieces) if int(piece["start"]) < end and int(piece["end"]) > start]
    if not indices:
        raise ValueError(f"{entity.get('id')}: entity has no WordPiece tokens")
    first, last = pieces[indices[0]], pieces[indices[-1]]
    if int(first["start"]) != start or int(last["end"]) != end:
        raise ValueError(
            f"{entity.get('id')}: span [{start},{end}) is not on WordPiece boundaries "
            f"([{first['start']},{last['end']}) reconstructed)"
        )
    if any(int(pieces[index]["start"]) < start or int(pieces[index]["end"]) > end for index in indices):
        raise ValueError(f"{entity.get('id')}: partial WordPiece overlap")
    return indices


def _windows(piece_count: int, max_length: int, stride: int) -> list[tuple[int, int]]:
    capacity = max_length - 2
    if capacity < 1 or stride < 0 or stride >= capacity:
        raise ValueError("max_length must exceed 2 and stride must be in [0, max_length-2)")
    if piece_count == 0:
        return [(0, 0)]
    result = []
    start = 0
    while start < piece_count:
        end = min(piece_count, start + capacity)
        result.append((start, end))
        if end == piece_count:
            break
        start = end - stride
    return result


def _verify_bio_reconstruction(text: str, row: Mapping[str, Any]) -> None:
    labels = row["labels"]
    offsets = row["offset_mapping"]
    expected = {entity["id"]: entity for entity in row["entities"]}
    recovered: list[tuple[str, int, int]] = []
    index = 0
    while index < len(labels):
        label = labels[index]
        if not isinstance(label, str) or not label.startswith("B-"):
            index += 1
            continue
        entity_type = label[2:]
        start = offsets[index][0]
        end = offsets[index][1]
        index += 1
        while index < len(labels) and labels[index] == f"I-{entity_type}":
            end = offsets[index][1]
            index += 1
        recovered.append((entity_type, start, end))
    expected_spans = sorted((entity["type"], int(entity["start"]), int(entity["end"])) for entity in expected.values())
    if sorted(recovered) != expected_spans:
        raise ValueError(f"BIO reconstruction mismatch: expected {expected_spans}, recovered {sorted(recovered)}")
    for entity_type, start, end in recovered:
        if not text[start:end]:
            raise ValueError(f"Empty recovered {entity_type} span")


def prepare_record(
    record: Mapping[str, Any],
    tokenizer: DistilBertWordPieceTokenizer,
    *,
    final_split: str,
    max_length: int = 512,
    stride: int = 64,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    expected_source = SOURCE_SPLITS[final_split]
    if record.get("source_split") != expected_source:
        raise ValueError(f"{record.get('id')}: {final_split} must retain source split {expected_source}")
    text = record.get("text")
    annotations = record.get("text2task_annotations")
    if not isinstance(text, str) or not isinstance(annotations, Mapping):
        raise ValueError(f"{record.get('id')}: missing text or annotations")
    entities = annotations.get("entities") or []
    pieces = tokenizer.tokenize_with_offsets(text)
    entity_piece_indices = {str(entity["id"]): _piece_indices_for_entity(text, entity, pieces) for entity in entities}
    windows = _windows(len(pieces), max_length, stride)
    layers = assign_overlap_layers(entities)
    output: list[dict[str, Any]] = []
    assigned_ids: set[str] = set()

    for layer_index, layer in enumerate(layers):
        assignment: dict[str, int] = {}
        for entity in layer:
            indices = entity_piece_indices[str(entity["id"])]
            candidates = [window_index for window_index, (start, end) in enumerate(windows) if start <= indices[0] and indices[-1] < end]
            if not candidates:
                raise ValueError(f"{record.get('id')}/{entity['id']}: entity crosses every tokenizer window")
            assignment[str(entity["id"])] = candidates[0]
            assigned_ids.add(str(entity["id"]))

        for window_index, (piece_start, piece_end) in enumerate(windows):
            content = pieces[piece_start:piece_end]
            tokens = ["[CLS]"] + [piece["token"] for piece in content] + ["[SEP]"]
            input_ids = [tokenizer.vocab["[CLS]"]] + [int(piece["id"]) for piece in content] + [tokenizer.vocab["[SEP]"]]
            offsets = [[0, 0]] + [[int(piece["start"]), int(piece["end"])] for piece in content] + [[0, 0]]
            labels: list[str | None] = [None] + ["O"] * len(content) + [None]
            entity_ids: list[str | None] = [None] * len(tokens)
            row_entities = []
            for entity in layer:
                entity_id = str(entity["id"])
                if assignment[entity_id] != window_index:
                    continue
                indices = entity_piece_indices[entity_id]
                local_indices = [global_index - piece_start + 1 for global_index in indices]
                for offset, local_index in enumerate(local_indices):
                    labels[local_index] = ("B-" if offset == 0 else "I-") + str(entity["type"])
                    entity_ids[local_index] = entity_id
                row_entities.append({
                    "id": entity_id,
                    "type": entity["type"],
                    "start": entity["start"],
                    "end": entity["end"],
                    "text": entity["text"],
                })
            label_ids = [-100 if label is None else LABEL_TO_ID[label] for label in labels]
            row_id = f"{record['id']}::bio_layer_{layer_index:02d}::window_{window_index:03d}"
            row = {
                "id": row_id,
                "source_record_id": record["id"],
                "source": record.get("source"),
                "final_split": final_split,
                "source_split": record["source_split"],
                "thread_id": record.get("thread_id"),
                "turn_index": record.get("turn_index"),
                "annotation_tier": (record.get("annotation_provenance") or {}).get("quality_tier"),
                "text": text,
                "layer_index": layer_index,
                "layer_count": len(layers),
                "window_index": window_index,
                "window_count": len(windows),
                "wordpiece_range": [piece_start, piece_end],
                "tokens": tokens,
                "input_ids": input_ids,
                "attention_mask": [1] * len(tokens),
                "special_tokens_mask": [1] + [0] * len(content) + [1],
                "offset_mapping": offsets,
                "labels": labels,
                "label_ids": label_ids,
                "entity_ids": entity_ids,
                "entities": row_entities,
                "overlap_policy": "deterministic_interval_layers",
                "subword_policy": "first_piece_B_remaining_pieces_I_special_tokens_-100",
                "tokenizer": "distilbert-base-uncased",
            }
            _verify_bio_reconstruction(text, row)
            output.append(row)
    expected_ids = {str(entity["id"]) for entity in entities}
    if assigned_ids != expected_ids:
        raise ValueError(f"{record.get('id')}: lost entities during layering: {expected_ids - assigned_ids}")
    return output, {"layers": len(layers), "windows": len(windows), "wordpieces": len(pieces)}


def prepare_split(
    input_path: Path,
    output_path: Path,
    tokenizer: DistilBertWordPieceTokenizer,
    *,
    final_split: str,
    max_length: int = 512,
    stride: int = 64,
) -> dict[str, Any]:
    records = read_jsonl(input_path)
    output: list[dict[str, Any]] = []
    layer_counts = Counter()
    window_counts = Counter()
    label_counts = Counter()
    source_ids: set[str] = set()
    for record in records:
        rows, info = prepare_record(record, tokenizer, final_split=final_split, max_length=max_length, stride=stride)
        output.extend(rows)
        source_ids.add(str(record["id"]))
        layer_counts[info["layers"]] += 1
        window_counts[info["windows"]] += 1
        for row in rows:
            label_counts.update(label for label in row["labels"] if label is not None)
    atomic_jsonl(output_path, output)
    return {
        "source_records": len(records),
        "source_record_ids": len(source_ids),
        "model_rows": len(output),
        "threads": len({record.get("thread_id") for record in records}),
        "entities": sum(len((record.get("text2task_annotations") or {}).get("entities") or []) for record in records),
        "records_requiring_overlap_layers": sum(count for layers, count in layer_counts.items() if layers > 1),
        "maximum_layers": max(layer_counts, default=0),
        "records_requiring_multiple_windows": sum(count for windows, count in window_counts.items() if windows > 1),
        "label_counts": dict(sorted(label_counts.items())),
    }


def prepare_all_splits(
    input_dir: Path,
    output_dir: Path,
    vocab_path: Path,
    *,
    max_length: int = 512,
    stride: int = 64,
) -> dict[str, Any]:
    tokenizer = DistilBertWordPieceTokenizer(vocab_path)
    split_stats = {}
    for split in ("train", "validation", "test"):
        split_stats[split] = prepare_split(
            input_dir / f"{split}.jsonl",
            output_dir / f"{split}.jsonl",
            tokenizer,
            final_split=split,
            max_length=max_length,
            stride=stride,
        )
    vocabulary_sha = hashlib.sha256(vocab_path.read_bytes()).hexdigest()
    stats = {
        "task": "token_classification",
        "tokenizer": "distilbert-base-uncased",
        "vocabulary_path": str(vocab_path),
        "vocabulary_sha256": vocabulary_sha,
        "max_length": max_length,
        "stride": stride,
        "overlap_policy": "deterministic_interval_layers",
        "subword_policy": "first_piece_B_remaining_pieces_I_special_tokens_-100",
        "splits": split_stats,
    }
    atomic_json(output_dir / "label_map.json", {"labels": LABELS, "label_to_id": LABEL_TO_ID, "ignore_index": -100})
    atomic_json(output_dir / "statistics.json", stats)
    return stats

