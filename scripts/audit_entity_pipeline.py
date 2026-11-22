#!/usr/bin/env python3
"""Audit the entity pipeline and build a versioned three-entity diagnostic set.

This script never mutates the finalized or original annotation files.  Its
manual review manifest is intentionally explicit and produces a separate
SILVER-v2 diagnostic artifact.
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model_data.token_classification import DistilBertWordPieceTokenizer, prepare_record  # noqa: E402
from src.model_training.entity_extractor import layer_marker_token, model_features  # noqa: E402


SEED = 20261101
SOURCE = Path("data/final/train.jsonl")
MODEL_READY = Path("data/model_ready/entities")
PREDICTIONS = Path("results/entity_extraction/provisional_silver/silver_provisional_validation_predictions.jsonl")
OUTPUT_DIR = Path("data/diagnostics/entity_pipeline")
REPORT = Path("data/reports/entity_pipeline_diagnostic.md")
VOCAB = Path("configs/tokenizers/distilbert-base-uncased-vocab.txt")


AUDIT_IDS = [
    "mailex:train:haedicke-m_inbox_58:turn_0000",
    "mailex:train:mclaughlin-e_inbox455:turn_0001",
    "mailex:train:keiser-k_inbox148:turn_0000",
    "mailex:train:blair-l_inbox_187:turn_0002",
    "mailex:train:corman-s_inbox_archives445:turn_0000",
    "mailex:train:mccarty-d_inbox_alaska_gas_103:turn_0002",
    "mailex:train:wolfe-j_inbox260:turn_0000",
    "mailex:train:lavorato-j_inbox196:turn_0001",
    "mailex:train:mims-thurston-p_inbox39:turn_0001",
    "mailex:train:hernandez-j_inbox72:turn_0001",
    "mailex:train:whitt-m_inbox810:turn_0000",
    "mailex:train:reitmeyer-j_inbox365:turn_0000",
    "mailex:train:derrick-j_inbox226:turn_0001",
    "mailex:train:nemec-g_inbox856:turn_0000",
    "mailex:train:blair-l_inbox_180:turn_0000",
    "mailex:train:steffes-j_inbox127:turn_0003",
    "mailex:train:derrick-j_inbox151:turn_0000",
    "mailex:train:nemec-g_inbox113:turn_0003",
    "mailex:train:martin-t_inbox211:turn_0002",
    "mailex:train:ybarbo-p_inbox53:turn_0000",
    "mailex:train:whitt-m_inbox372:turn_0000",
    "mailex:train:steffes-j_inbox101:turn_0001",
    "mailex:train:parks-j_inbox572:turn_0002",
    "mailex:train:parks-j_inbox153:turn_0000",
    "mailex:train:nemec-g_inbox1129:turn_0000",
    "mailex:train:germany-c_inbox43:turn_0001",
    "mailex:train:lay-k_inbox843:turn_0000",
    "mailex:train:cash-m_inbox154:turn_0001",
    "mailex:train:white-s_inbox331:turn_0002",
    "mailex:train:mann-k_inbox32:turn_0000",
]


DIAGNOSTIC_IDS = {
    AUDIT_IDS[index - 1] for index in (1, 2, 3, 5, 6, 8, 9, 10, 12, 13, 14, 15, 16, 17, 19, 20, 21, 24, 25, 29)
}


# The reviewed entities are deliberately limited to TASK, PERSON and TEMPORAL.
# tuple format: (type, exact substring, zero-based occurrence when repeated)
CURATED: dict[str, list[tuple[str, str, int]]] = {
    AUDIT_IDS[0]: [
        ("TASK", "get citation issued", 0),
        ("TASK", "serve the papers on MSN's registered agent in Austin", 0),
        ("TASK", "do not mention the lawsuit to MSN", 0),
        ("TASK", "let me know if any commercial reason arises such that you believe service should be delayed", 0),
        ("TASK", "keep you updated", 0),
        ("TEMPORAL", "by the end of the day", 0),
        ("PERSON", "Andy", 0),
    ],
    AUDIT_IDS[1]: [
        ("TASK", "talk w/ Chris Chang in settlements", 0),
        ("TASK", "call me at 713-870-8211", 0),
        ("TEMPORAL", "last week", 0),
    ],
    AUDIT_IDS[2]: [
        ("TASK", "use the attached spreadsheet to populate", 0),
        ("TASK", "return via email", 0),
        ("TASK", "set up a new export process the streamline reporting", 0),
        ("TASK", "include only the information related to active deals that we anticipate fulfilling", 0),
        ("TASK", "note that as a caveat at the bottom of the spreadsheet", 0),
        ("TEMPORAL", "priro to noon each Wednesday and Monday", 0),
        ("PERSON", "Chris Abel", 0),
    ],
    AUDIT_IDS[3]: [
        ("TASK", "help me find it", 0),
        ("TASK", "get it to Jean Blair to get the writeoff forms written up", 0),
        ("TEMPORAL", "After I find that entry", 0),
        ("PERSON", "Lynn", 0), ("PERSON", "Rick", 0), ("PERSON", "Frank", 0),
        ("PERSON", "Alice", 0), ("PERSON", "Jean Blair", 0), ("PERSON", "Raetta", 0),
    ],
    AUDIT_IDS[4]: [
        ("TASK", "are all going to the Aeros game", 0),
        ("TASK", "Let me know if you would like to use the tickets", 0),
        ("TEMPORAL", "Friday night after practice", 0),
        ("PERSON", "Terrell", 0), ("PERSON", "Gina", 0), ("PERSON", "Kim R. Erb", 0),
    ],
    AUDIT_IDS[5]: [
        ("TASK", "should be submitted to the other teams", 0),
        ("TASK", "the sub heading should be `` Receipt/Delivery Points ''", 0),
        ("TASK", "`` Toll '' read `` Illustrative Toll ''", 0),
        ("PERSON", "Bob Hill", 0),
    ],
    AUDIT_IDS[6]: [
        ("TASK", "click on this pickup window link", 0),
        ("TASK", "copy and paste it in your browser address window", 0),
        ("TASK", "visit our Help pages", 0),
    ],
    AUDIT_IDS[7]: [
        ("TASK", "have started ranking and will be finished", 0),
        ("TASK", "What is Beck's list", 0),
        ("TEMPORAL", "today", 0),
    ],
    AUDIT_IDS[8]: [
        ("TASK", "send me your address and fax number", 0),
        ("TASK", "get some contracts sent our", 0),
        ("PERSON", "Jimbo", 0),
        ("TEMPORAL", "sometime real soon", 0),
    ],
    AUDIT_IDS[9]: [
        ("TASK", "Check it out", 0), ("TASK", "pass it around for him", 0),
        ("PERSON", "Larry", 0), ("PERSON", "Joe Davis", 0), ("PERSON", "Dana", 0),
        ("PERSON", "Warrick", 0), ("TEMPORAL", "ASAP", 0),
    ],
    AUDIT_IDS[10]: [
        ("TASK", "meet us for a drink", 0),
        ("TEMPORAL", "in december", 0), ("TEMPORAL", "tonight", 0), ("TEMPORAL", "after work", 0),
    ],
    AUDIT_IDS[11]: [
        ("TASK", "a rate server handle set up for the Gas Daily Published point `` PSCo citygate ''", 0),
        ("TASK", "Please help", 0),
        ("PERSON", "Kelly", 0), ("PERSON", "Carole Frank", 0), ("PERSON", "Russ", 0),
    ],
    AUDIT_IDS[12]: [
        ("TASK", "the draft Budget with the new amendemends must be reviewed once again as a whole", 0),
        ("TEMPORAL", "at the next Sup.Board meeting", 0),
    ],
    AUDIT_IDS[13]: [
        ("TASK", "is sending us a T & D only contract", 0),
        ("TASK", "will try to send it", 0),
        ("TASK", "he'll check on it", 0),
        ("TASK", "will be sent to us", 0),
        ("TASK", "will notify us", 0),
        ("TASK", "will get back to us on the portion of the power cost that taxes should be applied to", 0),
        ("PERSON", "Ricki", 0), ("PERSON", "G. Thomas Allison", 0), ("PERSON", "John", 0),
        ("TEMPORAL", "first thing tomorrow morning", 0), ("TEMPORAL", "before 9 AM", 0),
        ("TEMPORAL", "6/27", 0),
    ],
    AUDIT_IDS[14]: [
        ("TASK", "investigate the ability to keep outbound TMS messages and Critical Notices flowing during these periods of virus infiltration", 0),
        ("TASK", "let me know how we should proceed", 0),
        ("TEMPORAL", "yesterday's", 0),
    ],
    AUDIT_IDS[15]: [("PERSON", "Jim", 0)],
    AUDIT_IDS[16]: [
        ("TASK", "continue to request support", 0),
        ("TASK", "discuss our ability to compete with a company with which we've been in discussions", 0),
        ("PERSON", "James", 0), ("PERSON", "Whalley", 0), ("PERSON", "Mark Haedicke", 0),
        ("PERSON", "Heath Schiesser", 0), ("TEMPORAL", "the latter part of the week", 0),
    ],
    AUDIT_IDS[17]: [
        ("TASK", "would not advise inserting the usual `` final, non-appealable order ''", 0),
        ("TEMPORAL", "before the end of the year", 0),
    ],
    AUDIT_IDS[18]: [
        ("TASK", "will be scheduling interviews for the Trading Track", 0),
        ("TASK", "will be interviewing approximately 12 - 16 candidates", 0),
        ("TASK", "reserve this time in your calander", 0),
        ("TASK", "let me know", 0),
        ("TEMPORAL", "Wednesday, May 30th", 0),
        ("TEMPORAL", "from 1.00 pm to approximately 4.00 pm", 0),
        ("PERSON", "Karen", 0),
    ],
    AUDIT_IDS[19]: [
        ("TASK", "meet for lunch", 0), ("TASK", "Let me know", 0),
        ("TEMPORAL", "today", 0), ("TEMPORAL", "Wed and Thurs", 0),
        ("TEMPORAL", "Friday", 0), ("TEMPORAL", "next week", 0),
        ("PERSON", "Ramona Rodriguez", 0),
    ],
    AUDIT_IDS[20]: [
        ("TASK", "coordinate a vacation schedule planner for me for all of the staff", 0),
        ("TASK", "include Denver BT", 0),
        ("TEMPORAL", "from now until the end of the year (including Jan)", 0),
    ],
    AUDIT_IDS[21]: [],
    AUDIT_IDS[22]: [("TEMPORAL", "10/1", 0)],
    AUDIT_IDS[23]: [
        ("TASK", "attend the CCA crawfish boil function", 0),
        ("PERSON", "Zander", 0), ("PERSON", "Todd C. Feder", 0),
        ("TEMPORAL", "Thurday May 2, 2002", 0),
    ],
    AUDIT_IDS[24]: [
        ("TASK", "will be receiving the original for your signature in the mail", 0),
        ("TASK", "send a copy of the original to me", 0),
        ("TEMPORAL", "once you have signed", 0),
        ("PERSON", "Brian", 0), ("PERSON", "Jean", 0), ("PERSON", "Jack", 0),
        ("PERSON", "Randy", 0), ("PERSON", "Robyn", 0),
    ],
    AUDIT_IDS[25]: [
        ("TASK", "How's Baby Trogg?", 0), ("TASK", "How is Mamma Trogg?", 0),
        ("PERSON", "Trogg", 0), ("PERSON", "Don Germany", 0), ("TEMPORAL", "soon", 0),
    ],
    AUDIT_IDS[26]: [
        ("TEMPORAL", "today (December 6, 2001)", 0), ("TEMPORAL", "7:30 p.m.", 0),
        ("TEMPORAL", "from Friday, December 7 through Friday, December 14", 0),
        ("TEMPORAL", "during the hours of 8:00 a.m. - 5:00 p.m.", 0),
    ],
    AUDIT_IDS[27]: [
        ("TASK", "let me know how to proceed", 0),
        ("TEMPORAL", "each day", 0), ("TEMPORAL", "today", 0),
        ("PERSON", "Eric Shaw", 0), ("PERSON", "Naomi Connell", 0),
        ("PERSON", "Mary Nell Browning", 0), ("PERSON", "Melissa Allen", 0),
    ],
    AUDIT_IDS[28]: [
        ("TASK", "go live with the Southeast Region", 0),
        ("TASK", "go live with the remaining region of Ercot", 0),
        ("TASK", "let me know if anyone has any questions", 0),
        ("TEMPORAL", "tomorrow", 0), ("TEMPORAL", "Monday, November 5", 0),
        ("PERSON", "Casey", 0),
    ],
    AUDIT_IDS[29]: [],
}


AUDIT_NOTES = {
    1: ("major", "Historical filing was mislabeled TASK; pronoun-only `We` was a TASK; actionable service/request spans need cleaner boundaries."),
    2: ("major", "Historical call, dispute, and agreement were TASK; current imperatives were missed."),
    3: ("major", "Nested duplicates and an ARTIFACT labeled TASK; passive deadline wording has a poor TASK boundary."),
    4: ("major", "Historical sending and status update were TASK; future contingent work is the actionable content."),
    5: ("major", "Past ticket receipt/discovery were TASK; planned attendance/request should be retained."),
    6: ("minor", "Submission and edit requests are actionable, but the second edit is one excessively broad TASK span."),
    7: ("major", "Automated historical card delivery was TASK while explicit user instructions were omitted."),
    8: ("major", "`Top` was PERSON and attached-list question had overlapping/broad labels."),
    9: ("major", "Duplicate nested TASK spans for one request; temporal expression omitted."),
    10: ("major", "Job-search states, speech, and pronoun `I` were TASK; direct imperatives are cleaner targets."),
    11: ("major", "Reported market states and directives were TASK; social planning is ambiguous and direct invitation was missed."),
    12: ("major", "Past referral/deal/information events were TASK; the concrete setup request was missed."),
    13: ("major", "Past negated review and bare `approve it` were TASK; mandatory future re-review is valid."),
    14: ("major", "Completed date change and document-description fragments were TASK/ARTIFACT; future commitments are usable."),
    15: ("major", "System states and past disruption were TASK; investigation/request to proceed are actionable."),
    16: ("acceptable", "No actionable task was present; original empty annotation is semantically reasonable for TASK."),
    17: ("major", "Predicted corporate state and malformed question fragment were TASK; support/discussion requests are valid."),
    18: ("minor", "Negative recommendation is actionable but requires negation-aware treatment."),
    19: ("minor", "Core scheduled work is sound; request to report inability/questions was under-annotated."),
    20: ("major", "`Friday` was TASK and `on` TEMPORAL; scheduling request itself is valid."),
    21: ("minor", "Core requests are valid; first TASK improperly absorbs its temporal phrase."),
    22: ("major", "Presentational `here is the list` is not an actionable TASK."),
    23: ("minor", "No task is appropriate, but the explicit date was omitted as TEMPORAL."),
    24: ("major", "Historical `called` and vague `I'm in` were TASK; proposed attendance is the planned action."),
    25: ("major", "Completed signing/change and `attached docs` were TASK; current send/receipt actions remain."),
    26: ("major", "Phone-number statement was TASK; questions may be requests but overlap policy needs explicit handling."),
    27: ("major", "Facility states were labeled TASK and an organization was PERSON; these are events/states, not assigned work."),
    28: ("major", "Historical rejection and descriptive list changes were TASK; direct request to advise is actionable."),
    29: ("minor", "Planned deployments are useful TASKs; attached-curves statement should not be a TASK."),
    30: ("acceptable", "Boilerplate advertisement contains no actionable email task."),
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def locate(text: str, needle: str, occurrence: int) -> tuple[int, int]:
    starts = [match.start() for match in re.finditer(re.escape(needle), text)]
    if occurrence >= len(starts):
        raise ValueError(f"cannot find occurrence {occurrence} of {needle!r}")
    start = starts[occurrence]
    return start, start + len(needle)


def curated_entities(record: dict[str, Any]) -> list[dict[str, Any]]:
    entities = []
    for index, (entity_type, needle, occurrence) in enumerate(CURATED[record["id"]], 1):
        start, end = locate(record["text"], needle, occurrence)
        entities.append({"id": f"v2-e{index}", "type": entity_type, "start": start, "end": end, "text": needle})
    entities.sort(key=lambda item: (item["start"], item["end"], item["type"]))
    if record["id"] in DIAGNOSTIC_IDS:
        for left, right in zip(entities, entities[1:]):
            if left["end"] > right["start"]:
                raise ValueError(f"{record['id']}: diagnostic spans overlap: {left} / {right}")
    return entities


def select_audit(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {record["id"]: record for record in records}
    missing = set(AUDIT_IDS) - set(by_id)
    if missing:
        raise ValueError(f"missing audit records: {sorted(missing)}")
    # Assert the manifest still corresponds to the documented deterministic
    # sample: 15 records enriched for suspicious historical TASK wording and
    # 15 seeded records from the remainder.
    historical = re.compile(r"\b(was|were|had|did|sent|completed|finished|approved|received|discussed|met|made|told|said|requested|asked|provided|submitted|updated|cancelled|canceled)\b", re.I)
    scored = []
    for record in records:
        tasks = [e for e in (record.get("text2task_annotations") or {}).get("entities", []) if e.get("type") == "TASK"]
        score = sum(bool(historical.search(str(e.get("text", "")))) for e in tasks)
        score += 0.1 * bool(historical.search(record["text"]))
        scored.append((score, record))
    rng = random.Random(SEED)
    high = [record for score, record in scored if score >= 1]
    rest = [record for score, record in scored if score < 1]
    rng.shuffle(high)
    rng.shuffle(rest)
    expected = [record["id"] for record in high[:15] + rest[:15]]
    if expected != AUDIT_IDS:
        raise ValueError("audit sampling drifted; refusing to substitute different records silently")
    return [by_id[record_id] for record_id in AUDIT_IDS]


def pipeline_evidence(tokenizer: Any) -> dict[str, Any]:
    train_rows = read_jsonl(MODEL_READY / "train.jsonl")
    validation_rows = read_jsonl(MODEL_READY / "validation.jsonl")
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in train_rows:
        groups[(row["source_record_id"], row["window_index"], tuple(row["input_ids"]))].append(row)
    multilayer = [group for group in groups.values() if len(group) > 1]
    distinct = all(
        len({tuple(model_features(row, tokenizer, 512)["input_ids"]) for row in group}) == len(group)
        for group in multilayer
    )
    markers = []
    for index in range(max(row["layer_count"] for row in train_rows + validation_rows)):
        token = layer_marker_token(index)
        token_id = tokenizer.convert_tokens_to_ids(token)
        markers.append({"layer": index, "token": token, "id": token_id, "round_trip": tokenizer.convert_ids_to_tokens(token_id)})
    predictions, references = Counter(), Counter()
    positions = 0
    prediction_rows = read_jsonl(PREDICTIONS)
    for row in prediction_rows:
        predictions.update(row["predictions"])
        references.update(row["references"])
        positions += len(row["predictions"])
    label_map = json.loads((MODEL_READY / "label_map.json").read_text(encoding="utf-8"))
    model_config = json.loads(Path("models/text2task-distilbert/provisional_silver/config.json").read_text(encoding="utf-8"))
    return {
        "train_rows": len(train_rows),
        "validation_rows": len(validation_rows),
        "train_layer_distribution": dict(sorted(Counter(row["layer_index"] for row in train_rows).items())),
        "identical_base_input_groups": len(multilayer),
        "identical_base_input_rows": sum(len(group) for group in multilayer),
        "inputs_distinct_after_marker": distinct,
        "markers": markers,
        "export_rows": len(prediction_rows),
        "evaluated_positions": positions,
        "prediction_labels": dict(sorted(predictions.items())),
        "reference_labels": dict(sorted(references.items())),
        "predicted_non_o": sum(value for key, value in predictions.items() if key != "O"),
        "reference_non_o": sum(value for key, value in references.items() if key != "O"),
        "predicted_b": sum(value for key, value in predictions.items() if key.startswith("B-")),
        "predicted_i": sum(value for key, value in predictions.items() if key.startswith("I-")),
        "mapping_matches_model": label_map["label_to_id"] == model_config["label2id"],
        "label_to_id": label_map["label_to_id"],
    }


def main() -> None:
    from transformers import AutoTokenizer

    records = read_jsonl(SOURCE)
    audited = select_audit(records)
    output = []
    clean_records = []
    severity_counts = Counter()
    original_task_count = 0
    corrected_task_count = 0
    for number, record in enumerate(audited, 1):
        severity, notes = AUDIT_NOTES[number]
        severity_counts[severity] += 1
        entities = curated_entities(record)
        original_entities = (record.get("text2task_annotations") or {}).get("entities", [])
        original_task_count += sum(e.get("type") == "TASK" for e in original_entities)
        corrected_task_count += sum(e["type"] == "TASK" for e in entities)
        corrected = {
            "schema_version": "text2task-diagnostic-3class-v1",
            "annotation_tier": "SILVER",
            "human_verified": False,
            "entity_types": ["TASK", "PERSON", "TEMPORAL"],
            "entities": entities,
            "relations": [],
            "review_notes": notes,
        }
        output.append({
            "id": record["id"],
            "source_split": record["source_split"],
            "thread_id": record["thread_id"],
            "turn_index": record["turn_index"],
            "text": record["text"],
            "audit_sample_index": number,
            "audit_severity": severity,
            "original_silver_annotations": deepcopy(record.get("text2task_annotations")),
            "corrected_silver_v2_diagnostic": corrected,
            "provenance": {
                "source_record_id": record["id"],
                "source_annotation_tier": "SILVER",
                "correction_method": "manual semantic diagnostic review",
                "original_modified": False,
                "seed": SEED,
            },
        })
        if record["id"] in DIAGNOSTIC_IDS:
            diagnostic = {
                key: deepcopy(value) for key, value in record.items()
                if key not in {"text2task_annotations", "annotation_provenance"}
            }
            diagnostic["text2task_annotations"] = {"entities": entities, "relations": [], "unresolved": []}
            diagnostic["annotation_provenance"] = {
                "quality_tier": "SILVER",
                "human_verified": False,
                "version": "diagnostic-3class-v1",
                "source_record_id": record["id"],
            }
            clean_records.append(diagnostic)

    if len(output) != 30 or len(clean_records) != 20:
        raise ValueError("diagnostic cardinality mismatch")
    tokenizer = DistilBertWordPieceTokenizer(VOCAB)
    model_rows = []
    for record in clean_records:
        rows, info = prepare_record(record, tokenizer, final_split="train", max_length=512, stride=64)
        if info["layers"] != 1:
            raise ValueError(f"{record['id']}: clean diagnostic record unexpectedly needs {info['layers']} BIO layers")
        model_rows.extend(rows)
    write_jsonl(OUTPUT_DIR / "audit30_corrected_silver_v2.jsonl", output)
    write_jsonl(OUTPUT_DIR / "three_class_20_annotations.jsonl", clean_records)
    write_jsonl(OUTPUT_DIR / "three_class_20_model_ready.jsonl", model_rows)

    hf_tokenizer = AutoTokenizer.from_pretrained("models/text2task-distilbert/provisional_silver", use_fast=True)
    evidence = pipeline_evidence(hf_tokenizer)
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "seed": SEED,
        "audit_records": 30,
        "diagnostic_records": 20,
        "diagnostic_rows": len(model_rows),
        "diagnostic_entity_counts": dict(sorted(Counter(e["type"] for r in clean_records for e in r["text2task_annotations"]["entities"]).items())),
        "audit_severity": dict(sorted(severity_counts.items())),
        "original_task_spans_in_audit": original_task_count,
        "corrected_task_spans_in_audit": corrected_task_count,
        "pipeline_evidence": evidence,
        "original_files_modified": False,
    }
    (OUTPUT_DIR / "audit_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Text2Task entity-pipeline diagnostic",
        "",
        "This is a pre-retraining diagnostic. All reviewed corrections remain SILVER and are stored separately; no original or finalized annotation was modified or promoted to GOLD.",
        "",
        "## Structural evidence",
        "",
        f"- Training rows: {evidence['train_rows']}; validation rows: {evidence['validation_rows']}.",
        f"- {evidence['identical_base_input_rows']} rows in {evidence['identical_base_input_groups']} groups share the same base text/window across BIO layers.",
        f"- After inserting `[unusedN]`, every multilayer input is distinguishable: **{evidence['inputs_distinct_after_marker']}**.",
        f"- Marker IDs are {[item['id'] for item in evidence['markers']]} and all round-trip to their corresponding `[unusedN]` token.",
        f"- Stored label mapping and model `label2id` agree: **{evidence['mapping_matches_model']}**.",
        f"- Export: {evidence['export_rows']} rows, {evidence['evaluated_positions']} positions, {evidence['reference_non_o']} reference non-O, {evidence['predicted_non_o']} predicted non-O.",
        f"- Predicted BIO prefixes: B={evidence['predicted_b']}, I={evidence['predicted_i']}. The absence of B predictions makes the decoded entity sequences structurally invalid/near-empty.",
        "",
        "The marker position is assigned label `-100`, so it is intentionally absent from prediction/reference exports. Training and unseen inference both insert it immediately after `[CLS]`.",
        "",
        "## Manual 30-record SILVER audit",
        "",
        f"Severity counts: {dict(sorted(severity_counts.items()))}. Original TASK spans: {original_task_count}; conservative corrected diagnostic TASK spans: {corrected_task_count}.",
        "",
        "| # | Source record | Severity | Finding |",
        "|---:|---|---|---|",
    ]
    for number, record in enumerate(audited, 1):
        severity, notes = AUDIT_NOTES[number]
        lines.append(f"| {number} | `{record['id']}` | {severity} | {notes.replace('|', '/')} |")
    lines.extend([
        "",
        "## Clean diagnostic set",
        "",
        f"The single-layer diagnostic contains 20 source emails and {len(model_rows)} tokenizer windows. It uses TASK, PERSON and TEMPORAL only (plus `O` and BIO prefixes). Entity counts: {summary['diagnostic_entity_counts']}.",
        "",
        "This is a same-example memorization test, not a held-out evaluation. Its purpose is to verify that labels, inputs, gradients, and decoding can support learning before any full retraining.",
        "",
        "Memorization results are written by `scripts/run_entity_memorization_test.py` to `results/entity_extraction/memorization_20/`.",
    ])
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
