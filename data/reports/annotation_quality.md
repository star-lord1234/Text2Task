# Text2Task annotation quality report

Generated: 2026-10-30T11:42:49.254566Z

## Review status

- Prepared review records: 150
- Human-completed reviews: 0
- Pending reviews: 150
- train: 0 completed / 0 prepared (0 pending)
- dev: 0 completed / 60 prepared (60 pending)
- test: 0 completed / 90 prepared (90 pending)

## Human decisions

No records have been human-verified yet. Automated validation never assigns GOLD.

## Frequent corrections

No eligible human correction statistics are available yet.

## Reviewer workflow

1. List pending items with `python3 scripts/review_annotations.py list --split dev`.
2. Inspect one record with `python3 scripts/review_annotations.py show REVIEW_FILE`. Dev/test predictions remain hidden during independent annotation.
3. Add or correct spans, types, task attributes, and relations using the `add-*`, `set-*`, and `delete-*` subcommands. Every tool-driven change is appended to `correction_events`.
4. Run `python3 scripts/review_annotations.py validate REVIEW_FILE`. Resolve errors; explicitly inspect every dependency warning. Ambiguity may remain encoded through `ambiguous`, `UNKNOWN`, and `unresolved_fields`.
5. After actual inspection, use `mark --tier GOLD|SILVER|REJECTED --reviewer REVIEWER_ID --confirm-human`. GOLD warnings require `--acknowledge-warnings`.
6. Run `python3 scripts/review_annotations.py finalize` to export decisions and refresh quality statistics.

## Test-set isolation

Test reviews are always marked `prompt_feedback_eligible=false`. Their corrections are retained for final quality assessment but must not be used to modify prompts, choose models, or select training configurations.

## Quality-control policy

- Dev and test records default to blind independent annotation; predictions remain hidden until explicit reveal or completion.
- GOLD and SILVER require an explicit human confirmation flag and reviewer identity.
- Invalid offsets, schema failures, unsupported evidence, dependency cycles, and operation/status conflicts are surfaced by validation.
- Every DEPENDS_ON edge receives a semantic-review warning even when structurally valid.
- Original LLM predictions and their hashes remain stored separately from reviewer corrections.

Detailed machine-readable counts are in `data/reports/correction_statistics.csv`.
