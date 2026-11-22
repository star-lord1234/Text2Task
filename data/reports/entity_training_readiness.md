# Text2Task Entity Training-Readiness Audit

**Status: NOT_READY**

The files are structurally valid for controlled SILVER experiments.
The dataset is **not approved for training with gold validation/test evaluation** because held-out records are not human-reviewed GOLD.

## Schema and file format

Schema entities: TASK, PERSON, GROUP, TEMPORAL, EVENT, ARTIFACT.
BIO vocabulary: O, B-ARTIFACT, I-ARTIFACT, B-EVENT, I-EVENT, B-GROUP, I-GROUP, B-PERSON, I-PERSON, B-TASK, I-TASK, B-TEMPORAL, I-TEMPORAL. Special tokens use ignore index `-100`.
Each JSONL row is a pretokenized DistilBERT window/layer, not a generic raw-text Hugging Face example. It contains input IDs, masks, WordPiece strings, character offsets, BIO labels/IDs, source provenance, and exact row entities.

## Split audit

| Split | Emails | Threads | Model rows | Human GOLD | SILVER emails | Max tokens | >512 | Overlap emails | Max layers |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| train | 450 | 364 | 704 | 0 | 450 | 475 | 0 | 224 | 8 |
| validation | 60 | 51 | 101 | 0 | 60 | 368 | 0 | 36 | 5 |
| test | 90 | 70 | 140 | 0 | 90 | 434 | 0 | 46 | 4 |

Validation and test both have `human_review = null`; their provenance explicitly says `requires_human_review_for_gold: true`. No provenance was upgraded or rewritten by this audit.

## Original-email token lengths (including `[CLS]` and `[SEP]`)

| Split | Min | Median | P90 | P95 | P99 | Max |
|---|---:|---:|---:|---:|---:|---:|
| train | 3 | 96.5 | 251.0 | 311.1 | 432.5 | 475 |
| validation | 2 | 104.5 | 237.0 | 263.8 | 329.6 | 368 |
| test | 6 | 87.0 | 262.2 | 293.9 | 379.7 | 434 |

No email exceeds DistilBERT's 512-token context limit in the current build; no truncation repair is needed.

## Entity-span distribution

Counts below are unique annotated character spans, not subword-token counts or duplicated overlap layers.

| Label | Train | Validation | Test |
|---|---:|---:|---:|
| TASK | 1770 | 283 | 340 |
| PERSON | 463 | 63 | 102 |
| GROUP | 35 | 11 | 3 |
| TEMPORAL | 532 | 74 | 95 |
| EVENT | 4 | 0 | 3 |
| ARTIFACT | 412 | 59 | 75 |

## Insufficient-support flags

Screening rule: flag fewer than 20 training spans or fewer than 5 spans in either evaluation split. These are pragmatic warnings, not guarantees of statistical adequacy.

- `GROUP` in test: 3 spans (threshold 5).
- `EVENT` in train: 4 spans (threshold 20).
- `EVENT` in validation: 0 spans (threshold 5).
- `EVENT` in test: 3 spans (threshold 5).

## Structural verification

- BIO/token/offset/ID validation errors: 0.
- Cross-split thread overlaps: 0.
- Cross-split record-ID overlaps: 0.
- Every entity was found exactly once across its deterministic overlap layers.
- Every BIO sequence reconstructed the exact source character spans.
- No semantic annotations were changed.

## Decision

Do **not** begin the requested gold-evaluated fine-tuning yet. Human-review and GOLD promotion of every validation and test email is the blocking gate. The current files may only be used if the experiment is explicitly described as SILVER-only and its metrics are not presented as human-gold evaluation.
