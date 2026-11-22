# Text2Task Model-Ready Data Statistics

> Annotation warning: the current finalized corpus is AI-generated **SILVER**, including validation and test. These held-out splits preserve MailEx membership but are not human-gold evaluation sets.

## Model A — DistilBERT token classification

Tokenizer: `distilbert-base-uncased` using the official vocabulary SHA-256 `07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3`. Maximum length is 512 with stride 64. Special-token labels are `-100`; the first entity piece receives `B-TYPE` and every remaining entity subword receives `I-TYPE`.

Overlaps are not overwritten. Interval-coloring creates the minimum greedy set of deterministic, non-overlapping BIO layers, each traceable to the same source email.

| Split | Emails | Threads | Rows | Entities | Emails with overlap layers | Max layers | Multi-window emails |
|---|---:|---:|---:|---:|---:|---:|---:|
| train | 450 | 364 | 704 | 3216 | 224 | 8 | 0 |
| validation | 60 | 51 | 101 | 490 | 36 | 5 | 0 |
| test | 90 | 70 | 140 | 618 | 46 | 4 | 0 |

Every emitted BIO row was reconstructed from its labeled offsets and checked against the original entity spans.

## Model B — relation classification

Entity source: `annotated`. Negative sampling ratio: 1.0:1 (seed 20261030). All positive edges are retained. NONE examples are sampled only from inference-valid endpoint pairs.

| Split | Emails | Threads | Valid candidates | Kept rows | Positives | NONE | ASSIGNED | DUE | SCHEDULED | DEPENDS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| train | 450 | 364 | 14185 | 2378 | 1189 | 1189 | 620 | 33 | 532 | 4 |
| validation | 60 | 51 | 2683 | 342 | 171 | 171 | 90 | 10 | 71 | 0 |
| test | 90 | 70 | 2438 | 452 | 226 | 226 | 122 | 7 | 94 | 3 |

Each row stores the untouched email text, typed `[E1_*]`/`[E2_*]` marked text, exact entity offsets, source record/thread IDs, and relation evidence for positive labels. The CLI also accepts per-split predicted-entity files; gold relations are then transferred only through exact type-and-span matches.

## Split integrity

The builders read `train.jsonl`, `validation.jsonl`, and `test.jsonl` separately and assert their original MailEx source splits (`train`, `dev`, `test`). Entity pairs are created only within one email, so no pair or example can cross a split or thread boundary.
