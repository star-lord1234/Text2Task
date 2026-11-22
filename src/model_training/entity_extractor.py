"""Shared preflight, metrics, and dataset helpers for entity extraction."""

from __future__ import annotations

import inspect
import hashlib
import json
import os
import random
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SPLITS = ("train", "validation", "test")
EXPECTED_SOURCE_SPLIT = {"train": "train", "validation": "dev", "test": "test"}
EXPERIMENT_MODES = {"provisional_silver", "gold_evaluation"}


def load_config(path: Path) -> dict[str, Any]:
    """Load the JSON-compatible YAML config without making PyYAML mandatory."""

    text = path.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as error:
            raise RuntimeError("Non-JSON YAML requires PyYAML") from error
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError(f"Training config must be an object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    values = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            values.append(value)
    return values


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    def default(item: Any) -> Any:
        if hasattr(item, "item"):
            return item.item()
        if isinstance(item, Path):
            return str(item)
        if isinstance(item, set):
            return sorted(item)
        raise TypeError(f"Object of type {item.__class__.__name__} is not JSON serializable")

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=default) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def human_gold(record: Mapping[str, Any]) -> bool:
    provenance = record.get("annotation_provenance") or {}
    review = provenance.get("human_review") or record.get("human_review") or {}
    reviewer = review.get("reviewer") or {}
    return (
        provenance.get("quality_tier") == "GOLD"
        and review.get("review_status") == "COMPLETED"
        and review.get("quality_tier") == "GOLD"
        and isinstance(reviewer.get("reviewer_id"), str)
        and bool(reviewer.get("reviewer_id"))
        and bool(reviewer.get("completed_at"))
    )


def schema_labels(schema_path: Path) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return list(schema["x-text2task-label-policy"]["entity_labels"])


def metric_context(config: Mapping[str, Any], mode: str) -> dict[str, str | bool]:
    if mode not in EXPERIMENT_MODES:
        raise ValueError(f"unknown experiment mode {mode!r}")
    evaluation = config["evaluation"]
    if mode == "provisional_silver":
        return {
            "mode": mode,
            "annotation_tier": "SILVER",
            "metric_prefix": str(evaluation["provisional_metric_prefix"]),
            "is_final_research_metric": False,
            "disclaimer": str(evaluation["disclaimer"]),
        }
    return {
        "mode": mode,
        "annotation_tier": "GOLD",
        "metric_prefix": str(evaluation["gold_metric_prefix"]),
        "is_final_research_metric": True,
        "disclaimer": "Metrics use independently human-reviewed GOLD annotations.",
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def data_fingerprints(config: Mapping[str, Any]) -> dict[str, str]:
    paths = config["paths"]
    values = {}
    for directory_key, directory in (("model_ready", paths["entity_data"]), ("final", paths["final_data"])):
        for split in SPLITS:
            path = Path(directory) / f"{split}.jsonl"
            values[f"{directory_key}/{split}.jsonl"] = file_sha256(path)
    values["schema"] = file_sha256(Path(paths["schema"]))
    return values


def preflight(
    config: Mapping[str, Any],
    *,
    mode: str | None = None,
    require_gold_validation: bool | None = None,
) -> dict[str, Any]:
    if require_gold_validation is not None:
        compatibility_mode = "gold_evaluation" if require_gold_validation else "provisional_silver"
        if mode is not None and mode != compatibility_mode:
            raise ValueError("mode conflicts with require_gold_validation")
        mode = compatibility_mode
    mode = mode or str(config["evaluation"]["mode"])
    context = metric_context(config, mode)
    paths = config["paths"]
    entity_dir = Path(paths["entity_data"])
    final_dir = Path(paths["final_data"])
    schema_path = Path(paths["schema"])
    vocab_path = Path(paths["vocab"])
    label_map_path = entity_dir / "label_map.json"
    errors: list[str] = []
    blockers: list[str] = []
    if not schema_path.is_file() or not label_map_path.is_file():
        return {
            "passed": False,
            "errors": ["schema or label map is missing"],
            "blockers": ["missing_inputs"],
            "splits": {},
        }
    from src.model_data.entity_readiness import audit_entity_data

    structural_audit = audit_entity_data(entity_dir, final_dir, schema_path, vocab_path=vocab_path)
    if structural_audit["structural_errors"]:
        errors.extend(f"entity readiness: {value}" for value in structural_audit["structural_errors"])
    entity_types = schema_labels(schema_path)
    label_map = json.loads(label_map_path.read_text(encoding="utf-8"))
    expected_bio = {"O"} | {f"{prefix}-{label}" for prefix in ("B", "I") for label in entity_types}
    if set(label_map.get("labels") or []) != expected_bio:
        errors.append("BIO label map does not match the finalized schema entity vocabulary")
    if config.get("model", {}).get("name") != "distilbert/distilbert-base-uncased":
        errors.append("model.name must be distilbert/distilbert-base-uncased")

    reports: dict[str, Any] = {}
    threads: dict[str, set[str]] = {}
    for split in SPLITS:
        model_path = entity_dir / f"{split}.jsonl"
        final_path = final_dir / f"{split}.jsonl"
        if not model_path.is_file() or not final_path.is_file():
            errors.append(f"missing {split} data")
            continue
        rows = read_jsonl(model_path)
        records = read_jsonl(final_path)
        by_id = {str(record["id"]): record for record in records}
        tier_counts = Counter(str((record.get("annotation_provenance") or {}).get("quality_tier")) for record in records)
        gold_count = sum(human_gold(record) for record in records)
        row_tiers = Counter(str(row.get("annotation_tier")) for row in rows)
        expected_source = EXPECTED_SOURCE_SPLIT[split]
        for row in rows:
            source_id = str(row.get("source_record_id"))
            source = by_id.get(source_id)
            if source is None:
                errors.append(f"{split}/{row.get('id')}: source record missing")
                continue
            if row.get("source_split") != expected_source or row.get("final_split") != split:
                errors.append(f"{split}/{row.get('id')}: split mismatch")
            if row.get("thread_id") != source.get("thread_id"):
                errors.append(f"{split}/{row.get('id')}: thread mismatch")
            source_tier = (source.get("annotation_provenance") or {}).get("quality_tier")
            if row.get("annotation_tier") != source_tier:
                errors.append(f"{split}/{row.get('id')}: model-row provenance is stale; regenerate model-ready data")
            sequences = [row.get(key) for key in ("input_ids", "attention_mask", "label_ids", "tokens", "labels")]
            if any(not isinstance(value, list) for value in sequences) or len({len(value) for value in sequences}) != 1:
                errors.append(f"{split}/{row.get('id')}: inconsistent token sequence fields")
            elif len(row["input_ids"]) + 1 > int(config["data"]["max_length"]):
                errors.append(f"{split}/{row.get('id')}: layer marker would exceed context limit")
        reports[split] = {
            "emails": len(records),
            "model_rows": len(rows),
            "threads": len({str(record.get("thread_id")) for record in records}),
            "email_tiers": dict(sorted(tier_counts.items())),
            "row_tiers": dict(sorted(row_tiers.items())),
            "human_reviewed_gold_emails": gold_count,
        }
        threads[split] = {str(record.get("thread_id")) for record in records}

    overlaps = []
    for left_index, left in enumerate(SPLITS):
        for right in SPLITS[left_index + 1:]:
            shared = sorted(threads.get(left, set()) & threads.get(right, set()))
            if shared:
                overlaps.append({"splits": [left, right], "thread_ids": shared})
    if overlaps:
        errors.append("source threads overlap across splits")
    train_tiers = set(reports.get("train", {}).get("email_tiers", {}))
    if train_tiers - {"GOLD", "SILVER"}:
        blockers.append("training_contains_unapproved_annotation_tier")
    validation = reports.get("validation", {})
    validation_tiers = set(validation.get("email_tiers", {}))
    if mode == "gold_evaluation":
        if validation.get("human_reviewed_gold_emails") != validation.get("emails"):
            blockers.append("validation_is_not_fully_human_reviewed_gold")
        if validation_tiers != {"GOLD"}:
            blockers.append("gold_evaluation_validation_contains_non_gold_tiers")
    elif validation_tiers - {"SILVER", "GOLD"}:
        blockers.append("provisional_validation_contains_unapproved_annotation_tier")
    return {
        "passed": not errors and not blockers,
        "errors": errors,
        "blockers": blockers,
        "splits": reports,
        "cross_split_thread_overlaps": overlaps,
        "schema_entity_labels": entity_types,
        "bio_labels": label_map.get("labels"),
        "label_to_id": label_map.get("label_to_id"),
        "ignore_index": label_map.get("ignore_index"),
        "model_name": config.get("model", {}).get("name"),
        "full_structural_audit_passed": structural_audit["structurally_valid_for_silver_experiments"],
        "experiment_mode": mode,
        "metric_context": context,
        "data_fingerprints": data_fingerprints(config),
    }


def seed_everything(seed: int) -> None:
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass
    try:
        import torch
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass


def detect_device(torch_module: Any) -> str:
    if hasattr(torch_module.backends, "mps") and torch_module.backends.mps.is_available():
        return "mps"
    if torch_module.cuda.is_available():
        return "cuda"
    return "cpu"


def validate_tokenizer_alignment(rows: Sequence[Mapping[str, Any]], tokenizer: Any) -> None:
    for row in rows:
        converted = tokenizer.convert_ids_to_tokens(row["input_ids"])
        if converted != row["tokens"]:
            raise ValueError(f"{row['id']}: stored WordPieces/IDs differ from the configured pretrained tokenizer")


def layer_marker_token(layer_index: int) -> str:
    if not 0 <= layer_index < 100:
        raise ValueError(f"unsupported overlap layer {layer_index}")
    return f"[unused{layer_index}]"


def model_features(row: Mapping[str, Any], tokenizer: Any, max_length: int) -> dict[str, list[int]]:
    """Inject a deterministic layer ID so overlapping targets are learnable."""

    marker = layer_marker_token(int(row["layer_index"]))
    marker_id = tokenizer.convert_tokens_to_ids(marker)
    if marker_id == tokenizer.unk_token_id:
        raise ValueError(f"Tokenizer lacks overlap marker {marker}")
    input_ids = list(row["input_ids"][:1]) + [marker_id] + list(row["input_ids"][1:])
    attention_mask = list(row["attention_mask"][:1]) + [1] + list(row["attention_mask"][1:])
    labels = list(row["label_ids"][:1]) + [-100] + list(row["label_ids"][1:])
    if len(input_ids) > max_length:
        raise ValueError(f"{row['id']}: layer-aware input exceeds {max_length} tokens")
    return {"input_ids": input_ids, "attention_mask": attention_mask, "labels": labels}


def make_dataset_class(torch_module: Any):
    class TokenRows(torch_module.utils.data.Dataset):
        def __init__(self, rows: Sequence[Mapping[str, Any]], tokenizer: Any, max_length: int):
            self.rows = list(rows)
            self.features = [model_features(row, tokenizer, max_length) for row in self.rows]

        def __len__(self) -> int:
            return len(self.features)

        def __getitem__(self, index: int) -> dict[str, list[int]]:
            return self.features[index]

    return TokenRows


def seqeval_metrics(predictions: Any, references: Any, id_to_label: Mapping[int, str]) -> tuple[dict[str, float], dict[str, Any], list[list[str]], list[list[str]]]:
    import numpy as np
    from seqeval.metrics import accuracy_score, classification_report, f1_score, precision_score, recall_score

    logits = predictions[0] if isinstance(predictions, tuple) else predictions
    predicted_ids = np.argmax(logits, axis=-1)
    true_predictions: list[list[str]] = []
    true_references: list[list[str]] = []
    for predicted_row, reference_row in zip(predicted_ids, references):
        predicted_labels = []
        reference_labels = []
        for predicted_id, reference_id in zip(predicted_row, reference_row):
            if int(reference_id) == -100:
                continue
            predicted_labels.append(id_to_label[int(predicted_id)])
            reference_labels.append(id_to_label[int(reference_id)])
        true_predictions.append(predicted_labels)
        true_references.append(reference_labels)
    metrics = {
        "precision": float(precision_score(true_references, true_predictions, zero_division=0)),
        "recall": float(recall_score(true_references, true_predictions, zero_division=0)),
        "f1": float(f1_score(true_references, true_predictions, zero_division=0)),
        "accuracy": float(accuracy_score(true_references, true_predictions)),
    }
    report = classification_report(true_references, true_predictions, output_dict=True, zero_division=0)
    return metrics, report, true_predictions, true_references


def trainer_compute_metrics(id_to_label: Mapping[int, str], metric_prefix: str):
    def compute(eval_prediction: Any) -> dict[str, float]:
        metrics, _report, _predictions, _references = seqeval_metrics(
            eval_prediction.predictions, eval_prediction.label_ids, id_to_label
        )
        return {f"{metric_prefix}_{key}": value for key, value in metrics.items()}

    return compute


def training_arguments_kwargs(training_arguments_class: Any, values: Mapping[str, Any]) -> dict[str, Any]:
    """Translate/filter TrainingArguments across supported Transformers APIs."""

    parameters = inspect.signature(training_arguments_class.__init__).parameters
    kwargs = dict(values)
    evaluation_value = kwargs.pop("evaluation_strategy")
    kwargs["eval_strategy" if "eval_strategy" in parameters else "evaluation_strategy"] = evaluation_value
    if "warmup_ratio" in kwargs and "warmup_ratio" not in parameters:
        if float(kwargs["warmup_ratio"]) != 0.0:
            raise ValueError("installed Transformers requires explicit warmup_steps for a nonzero warmup ratio")
        kwargs.pop("warmup_ratio")
    return {key: value for key, value in kwargs.items() if key in parameters}


def trainer_tokenizer_kwarg(trainer_class: Any, tokenizer: Any) -> dict[str, Any]:
    parameters = inspect.signature(trainer_class.__init__).parameters
    return {"processing_class": tokenizer} if "processing_class" in parameters else {"tokenizer": tokenizer}


def prediction_records(
    rows: Sequence[Mapping[str, Any]],
    predicted_labels: Sequence[Sequence[str]],
    reference_labels: Sequence[Sequence[str]],
) -> list[dict[str, Any]]:
    output = []
    for row, predictions, references in zip(rows, predicted_labels, reference_labels):
        active = [
            (token, offset, entity_id)
            for token, offset, label, entity_id in zip(row["tokens"], row["offset_mapping"], row["labels"], row["entity_ids"])
            if label is not None
        ]
        if len(active) != len(predictions):
            raise ValueError(f"{row['id']}: prediction length does not match active tokens")
        output.append({
            "id": row["id"],
            "source_record_id": row["source_record_id"],
            "thread_id": row["thread_id"],
            "layer_index": row["layer_index"],
            "window_index": row["window_index"],
            "tokens": [item[0] for item in active],
            "offset_mapping": [item[1] for item in active],
            "entity_ids": [item[2] for item in active],
            "predictions": list(predictions),
            "references": list(references),
        })
    return output
