# Text2Task final dataset statistics

Generated: 2026-10-30T12:09:33.442930Z

**Dataset status: READY_SILVER_ONLY**

## Quality warning

- Validation and test annotations are AI-generated SILVER, not human-verified GOLD; reported metrics measure agreement with silver labels only.

## Final split totals

### train

- Threads: 364
- Emails: 450
- Tasks: 1770
- Entity spans: 3216
- Relation instances: 1189
- Dependency links: 4
- Messages with multiple tasks: 380
- GOLD records: 0
- SILVER records: 450

Entity labels: `{"ARTIFACT": 412, "EVENT": 4, "GROUP": 35, "PERSON": 463, "TASK": 1770, "TEMPORAL": 532}`

Relation labels: `{"ASSIGNED_TO": 620, "DEPENDS_ON": 4, "DUE_ON": 33, "SCHEDULED_ON": 532}`

Task operations: `{"CANCEL": 9, "COMPLETE": 89, "CREATE": 533, "UNKNOWN": 1073, "UPDATE": 66}`

Task statuses: `{"CANCELED": 9, "COMPLETED": 89, "PENDING": 599, "UNKNOWN": 1073}`

### validation

- Threads: 51
- Emails: 60
- Tasks: 283
- Entity spans: 490
- Relation instances: 171
- Dependency links: 0
- Messages with multiple tasks: 51
- GOLD records: 0
- SILVER records: 60

Entity labels: `{"ARTIFACT": 59, "GROUP": 11, "PERSON": 63, "TASK": 283, "TEMPORAL": 74}`

Relation labels: `{"ASSIGNED_TO": 90, "DUE_ON": 10, "SCHEDULED_ON": 71}`

Task operations: `{"CANCEL": 1, "COMPLETE": 12, "CREATE": 93, "UNKNOWN": 167, "UPDATE": 10}`

Task statuses: `{"CANCELED": 1, "COMPLETED": 12, "PENDING": 103, "UNKNOWN": 167}`

### test

- Threads: 70
- Emails: 90
- Tasks: 340
- Entity spans: 618
- Relation instances: 226
- Dependency links: 3
- Messages with multiple tasks: 77
- GOLD records: 0
- SILVER records: 90

Entity labels: `{"ARTIFACT": 75, "EVENT": 3, "GROUP": 3, "PERSON": 102, "TASK": 340, "TEMPORAL": 95}`

Relation labels: `{"ASSIGNED_TO": 122, "DEPENDS_ON": 3, "DUE_ON": 7, "SCHEDULED_ON": 94}`

Task operations: `{"COMPLETE": 20, "CREATE": 112, "UNKNOWN": 197, "UPDATE": 11}`

Task statuses: `{"COMPLETED": 20, "PENDING": 123, "UNKNOWN": 197}`

## Split integrity

- Full-data records included: 0
- Cross-split source thread conflicts: 0
- Cleaned-source exact cross-split duplicate groups: 58
- Cleaned-source high-confidence near-duplicate pairs: 2
- Final exact cross-split duplicate groups: 0
- Final near-duplicate cross-split pairs: 0
- Human-verified validation examples: 0
- Human-verified test examples: 0
- Quarantined annotations: 0

## Test classes too small for meaningful evaluation

- entity `EVENT`: 3 instance(s); minimum reporting threshold is 5
- entity `GROUP`: 3 instance(s); minimum reporting threshold is 5
- relation `DEPENDS_ON`: 3 instance(s); minimum reporting threshold is 5

## Provenance policy

Each final record keeps `original_events` from MailEx, `source_provenance` for cleaned-source history, `text2task_annotations` for experiment labels, and `annotation_provenance` identifying GOLD versus SILVER. Test outcomes are isolated from prompt and training-configuration decisions.

Complete duplicate findings, quarantines, validation state, and machine-readable counts are in `data/reports/split_integrity.json`.
