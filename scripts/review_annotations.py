#!/usr/bin/env python3
"""Prepare, inspect, correct, validate, and export Text2Task human reviews.

Examples:
  python scripts/review_annotations.py prepare --source data/candidates/dev.jsonl
  python scripts/review_annotations.py show data/annotations/review/dev/RECORD.review.json
  python scripts/review_annotations.py add-entity FILE --reviewer alice --id e1 --type TASK --start 7 --end 22
  python scripts/review_annotations.py mark FILE --reviewer alice --tier GOLD --confirm-human
  python scripts/review_annotations.py finalize
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.annotation.review_workflow import (  # noqa: E402
    add_entity,
    add_relation,
    build_quality_outputs,
    delete_entity,
    delete_relation,
    finalize_reviews,
    iter_review_documents,
    load_review,
    mark_review,
    prepare_review_documents,
    render_review,
    save_review,
    set_entity,
    set_relation,
    set_task_attribute,
    validate_review_document,
)


DEFAULT_REVIEW_ROOT = Path("data/annotations/review")
DEFAULT_GOLD_DIR = Path("data/annotations/gold")
DEFAULT_REVIEWED_SILVER_DIR = Path("data/annotations/silver_reviewed")
DEFAULT_REJECTED_DIR = Path("data/annotations/rejected")
DEFAULT_REPORT = Path("data/reports/annotation_quality.md")
DEFAULT_STATS = Path("data/reports/correction_statistics.csv")


def add_file_and_reviewer(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("file", type=Path)
    parser.add_argument("--reviewer", required=True, help="Stable human reviewer identifier")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Create immutable-source review documents")
    prepare.add_argument("--source", type=Path, action="append", required=True, help="Candidate/source JSONL; repeatable")
    prepare.add_argument("--predictions", type=Path, action="append", default=[], help="Validated LLM JSONL; repeatable")
    prepare.add_argument("--failures", type=Path, action="append", default=[], help="LLM failure JSONL; repeatable")
    prepare.add_argument("--output-root", type=Path, default=DEFAULT_REVIEW_ROOT)
    prepare.add_argument("--mode", choices=("AUTO", "INDEPENDENT", "VERIFY"), default="AUTO")
    prepare.add_argument("--limit", type=int)
    prepare.add_argument("--overwrite", action="store_true", help="Replace pending review documents; never use after review begins")

    show = subparsers.add_parser("show", help="Render email, spans, relations, evidence, and QC findings")
    show.add_argument("file", type=Path)
    show.add_argument("--reveal-prediction", action="store_true", help="Reveal prediction during independent review (avoid until annotation is committed)")

    list_parser = subparsers.add_parser("list", help="List review-queue items without exposing email content")
    list_parser.add_argument("--review-root", type=Path, default=DEFAULT_REVIEW_ROOT)
    list_parser.add_argument("--split", choices=("train", "dev", "test"))
    list_parser.add_argument("--status", choices=("PENDING", "COMPLETED"), default="PENDING")
    list_parser.add_argument("--limit", type=int, default=20)

    validate = subparsers.add_parser("validate", help="Validate one review file or every file under a directory")
    validate.add_argument("path", type=Path)
    validate.add_argument("--save", action="store_true", help="Refresh the stored validation snapshot")

    add_entity_parser = subparsers.add_parser("add-entity", help="Add an exact character-offset entity")
    add_file_and_reviewer(add_entity_parser)
    add_entity_parser.add_argument("--id", required=True)
    add_entity_parser.add_argument("--type", required=True)
    add_entity_parser.add_argument("--start", type=int, required=True)
    add_entity_parser.add_argument("--end", type=int, required=True)

    set_entity_parser = subparsers.add_parser("set-entity", help="Correct an entity type or exact span")
    add_file_and_reviewer(set_entity_parser)
    set_entity_parser.add_argument("--id", required=True)
    set_entity_parser.add_argument("--type")
    set_entity_parser.add_argument("--start", type=int)
    set_entity_parser.add_argument("--end", type=int)

    delete_entity_parser = subparsers.add_parser("delete-entity", help="Delete an entity, explicitly cascading linked relations if requested")
    add_file_and_reviewer(delete_entity_parser)
    delete_entity_parser.add_argument("--id", required=True)
    delete_entity_parser.add_argument("--cascade", action="store_true")

    attribute = subparsers.add_parser("set-task-attribute", help="Correct one TASK attribute using a JSON value")
    add_file_and_reviewer(attribute)
    attribute.add_argument("--id", required=True)
    attribute.add_argument("--attribute", required=True)
    attribute.add_argument("--value", required=True, help='JSON value, e.g. false, "PENDING", or ["ASSIGNEE"]')

    add_relation_parser = subparsers.add_parser("add-relation", help="Add a typed relation with exact evidence")
    add_file_and_reviewer(add_relation_parser)
    add_relation_parser.add_argument("--id", required=True)
    add_relation_parser.add_argument("--type", required=True)
    add_relation_parser.add_argument("--source-id", required=True)
    add_relation_parser.add_argument("--target-id", required=True)
    add_relation_parser.add_argument("--evidence-start", type=int, required=True)
    add_relation_parser.add_argument("--evidence-end", type=int, required=True)
    add_relation_parser.add_argument("--explicit-vs-inferred", choices=("EXPLICIT", "INFERRED"), default="EXPLICIT")
    add_relation_parser.add_argument("--ambiguous", action="store_true")

    set_relation_parser = subparsers.add_parser("set-relation", help="Correct relation type, links, evidence, or attributes")
    add_file_and_reviewer(set_relation_parser)
    set_relation_parser.add_argument("--id", required=True)
    set_relation_parser.add_argument("--type")
    set_relation_parser.add_argument("--source-id")
    set_relation_parser.add_argument("--target-id")
    set_relation_parser.add_argument("--evidence-start", type=int)
    set_relation_parser.add_argument("--evidence-end", type=int)
    set_relation_parser.add_argument("--explicit-vs-inferred", choices=("EXPLICIT", "INFERRED"))
    set_relation_parser.add_argument("--ambiguous", action=argparse.BooleanOptionalAction, default=None)

    delete_relation_parser = subparsers.add_parser("delete-relation", help="Delete a relation")
    add_file_and_reviewer(delete_relation_parser)
    delete_relation_parser.add_argument("--id", required=True)

    mark = subparsers.add_parser("mark", help="Record an actual human GOLD, SILVER, or REJECTED decision")
    add_file_and_reviewer(mark)
    mark.add_argument("--tier", choices=("GOLD", "SILVER", "REJECTED"), required=True)
    mark.add_argument("--confirm-human", action="store_true", help="Required: confirms a human actually inspected this record")
    mark.add_argument("--acknowledge-warnings", action="store_true")
    mark.add_argument("--note")

    report = subparsers.add_parser("report", help="Build correction statistics and annotation-quality report")
    report.add_argument("--review-root", type=Path, default=DEFAULT_REVIEW_ROOT)
    report.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    report.add_argument("--statistics", type=Path, default=DEFAULT_STATS)

    finalize = subparsers.add_parser("finalize", help="Export only completed human decisions without changing originals")
    finalize.add_argument("--review-root", type=Path, default=DEFAULT_REVIEW_ROOT)
    finalize.add_argument("--gold-dir", type=Path, default=DEFAULT_GOLD_DIR)
    finalize.add_argument("--silver-dir", type=Path, default=DEFAULT_REVIEWED_SILVER_DIR)
    finalize.add_argument("--rejected-dir", type=Path, default=DEFAULT_REJECTED_DIR)
    finalize.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    finalize.add_argument("--statistics", type=Path, default=DEFAULT_STATS)
    return parser.parse_args()


def _existing(paths: list[Path], label: str) -> None:
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing {label}: {', '.join(str(path) for path in missing)}")


def _mutate(path: Path, operation) -> None:
    document = load_review(path)
    if document.get("review_status") == "COMPLETED":
        raise SystemExit("Completed reviews are immutable; create an adjudication workflow instead of silently editing them")
    operation(document)
    save_review(path, document)
    validation = document["validation"]
    print(f"Updated {path}: valid={validation['valid']} errors={validation['error_count']} warnings={validation['warning_count']}")


def main() -> None:
    args = parse_args()
    try:
        if args.command == "prepare":
            if args.limit is not None and args.limit < 1:
                raise SystemExit("--limit must be positive")
            _existing(args.source, "source JSONL")
            _existing(args.predictions, "prediction JSONL")
            _existing(args.failures, "failure JSONL")
            counts = prepare_review_documents(
                args.source,
                args.predictions,
                args.failures,
                args.output_root,
                mode=args.mode,
                limit=args.limit,
                overwrite=args.overwrite,
            )
            print("Prepared Text2Task human review queue")
            for key, value in sorted(counts.items()):
                print(f"  {key}: {value}")
            return

        if args.command == "show":
            print(render_review(load_review(args.file), reveal_prediction=args.reveal_prediction))
            return

        if args.command == "list":
            shown = 0
            for path, document in iter_review_documents(args.review_root):
                if args.split and document.get("source_split") != args.split:
                    continue
                if document.get("review_status") != args.status:
                    continue
                print(
                    f"{path}  id={document.get('record_id')} split={document.get('source_split')} "
                    f"mode={document.get('review_mode')} prediction={document.get('original_prediction') is not None} "
                    f"failure={document.get('original_failure') is not None}"
                )
                shown += 1
                if shown >= args.limit:
                    break
            print(f"Shown {shown} {args.status.lower()} review item(s)")
            return

        if args.command == "validate":
            if args.path.is_file():
                documents = [(args.path, load_review(args.path))]
            else:
                documents = list(iter_review_documents(args.path))
            totals: Counter[str] = Counter()
            for path, document in documents:
                validation = validate_review_document(document)
                totals["records"] += 1
                totals["errors"] += validation["error_count"]
                totals["warnings"] += validation["warning_count"]
                totals["valid"] += int(validation["valid"])
                if args.save:
                    document["validation"] = validation
                    save_review(path, document)
                if not validation["valid"] or validation["warning_count"]:
                    print(f"{path}: errors={validation['error_count']} warnings={validation['warning_count']}")
                    for issue in validation["issues"]:
                        print(f"  [{issue['severity']}] {issue['code']}: {issue['message']}")
            print(f"Validated {totals['records']} record(s): valid={totals['valid']} errors={totals['errors']} warnings={totals['warnings']}")
            return

        if args.command == "add-entity":
            _mutate(args.file, lambda document: add_entity(document, args.reviewer, args.id, args.type, args.start, args.end))
        elif args.command == "set-entity":
            _mutate(args.file, lambda document: set_entity(document, args.reviewer, args.id, entity_type=args.type, start=args.start, end=args.end))
        elif args.command == "delete-entity":
            _mutate(args.file, lambda document: delete_entity(document, args.reviewer, args.id, cascade=args.cascade))
        elif args.command == "set-task-attribute":
            try:
                value = json.loads(args.value)
            except json.JSONDecodeError as error:
                raise SystemExit(f"--value must be valid JSON: {error}") from error
            _mutate(args.file, lambda document: set_task_attribute(document, args.reviewer, args.id, args.attribute, value))
        elif args.command == "add-relation":
            _mutate(
                args.file,
                lambda document: add_relation(
                    document,
                    args.reviewer,
                    args.id,
                    args.type,
                    args.source_id,
                    args.target_id,
                    args.evidence_start,
                    args.evidence_end,
                    explicit_vs_inferred=args.explicit_vs_inferred,
                    ambiguous=args.ambiguous,
                ),
            )
        elif args.command == "set-relation":
            _mutate(
                args.file,
                lambda document: set_relation(
                    document,
                    args.reviewer,
                    args.id,
                    relation_type=args.type,
                    source_id=args.source_id,
                    target_id=args.target_id,
                    evidence_start=args.evidence_start,
                    evidence_end=args.evidence_end,
                    explicit_vs_inferred=args.explicit_vs_inferred,
                    ambiguous=args.ambiguous,
                ),
            )
        elif args.command == "delete-relation":
            _mutate(args.file, lambda document: delete_relation(document, args.reviewer, args.id))
        elif args.command == "mark":
            document = load_review(args.file)
            mark_review(
                document,
                args.reviewer,
                args.tier,
                confirm_human=args.confirm_human,
                acknowledge_warnings=args.acknowledge_warnings,
                note=args.note,
            )
            save_review(args.file, document)
            print(f"Human review recorded: {args.file} -> {args.tier}")
        elif args.command == "report":
            stats = build_quality_outputs(args.review_root, args.report, args.statistics)
            print(json.dumps(stats, indent=2, sort_keys=True))
        elif args.command == "finalize":
            export = finalize_reviews(args.review_root, args.gold_dir, args.silver_dir, args.rejected_dir)
            quality = build_quality_outputs(args.review_root, args.report, args.statistics)
            print("Finalized completed human reviews")
            print(json.dumps({"exports": export, "quality": quality}, indent=2, sort_keys=True))
    except (ValueError, KeyError, TypeError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
