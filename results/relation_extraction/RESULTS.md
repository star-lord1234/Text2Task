# Phase 3 — Relation extraction results (PROVISIONAL, SILVER)

All numbers are agreement with MailEx-derived SILVER labels on the **validation** split. They are not human-grounded.
The test split was built but never read or scored. Single seed (20261102). Checkpoint: `models/text2task-relations/ACTIVE` -> `provisional_silver/markers_sqrt` (epoch 3).

## Scope
Neural labels: NONE, ASSIGNED_TO, DUE_ON, SCHEDULED_ON over TASK->PERSON and TASK->TEMPORAL pairs.
**DEPENDS_ON is not neural**: the only 4 train / 3 test positives are TASK->EVENT (0 in validation); it exists only as an explicit-cue rule path (unit-tested, never evaluated).
Dropped from scope: ASSIGNED_TO->GROUP (41 train / 11 val / 3 test positives), TASK->TASK pairs.

## Mode A — reference spans, full validation candidate set (922 pairs: 160 positive, 762 NONE)
| | Neural | Rule |
|---|---|---|
| micro F1 (positives) | **0.764** (95% CI 0.70-0.84) | 0.527 (0.45-0.60) |
| macro F1 (3 positive labels) | **0.719** (0.62-0.82) | 0.517 (0.39-0.60) |
| ASSIGNED_TO P/R/F1 (n=79) | 0.65 / 0.75 / 0.69 | 0.92 / 0.15 / 0.26 |
| DUE_ON P/R/F1 (n=10) | 0.71 / 0.50 / 0.59 | 0.45 / 0.90 / 0.60 |
| SCHEDULED_ON P/R/F1 (n=71) | 0.92 / 0.83 / 0.87 | 0.72 / 0.66 / 0.69 |
| NONE false-positive rate | 4.6% | - |

CIs are thread-level bootstrap (1000 resamples). Paired neural-minus-rule delta: micro +0.16 to +0.32, macro +0.09 to +0.35.
Neural errors: 32 NONE->ASSIGNED_TO (likely partly unannotated true links), 20 ASSIGNED_TO->NONE, 3 DUE_ON->SCHEDULED_ON. Per-row errors: `evaluation/validation_markers_sqrt_errors.jsonl`.

## Mode B — predicted spans (three-class entity checkpoint `epoch3_sqrt_weighted`)
| Matching | Neural micro F1 | Rule micro F1 | Candidate recall |
|---|---|---|---|
| strict | 0.000 | 0.000 | 0.000 |
| lenient (IoU>=0.5) | 0.024 | 0.009 | 0.025 |
| any overlap | 0.195 | 0.103 | 0.263 |

**These are not a measure of relation quality.** The relation references use the older v1 entity spans, which the SILVER-v2 entity model does not reproduce (on 25 validation records only 3 of 139 reference TASK spans match at IoU>=0.5). End-to-end relation F1 cannot be measured reliably until references and entity spans share one span definition (a reviewed GOLD subset).

## Training
Pooling `markers` ([CLS] + both entity-start markers), sqrt class weights, lr 3e-5, batch 8 x accum 2, validation macro-F1 (epoch 1-4): 0.35, 0.49, **0.72**, 0.68. The run was stopped in epoch 5 (loss ~0.001, overfitting). The selection metric rests on only 10 DUE_ON validation examples, so it is noisy.

## Limitations
- `[CLS]`-pooling and unweighted ablations were **not run** (wall-clock cost); pooling choice is untested against alternatives.
- DUE_ON is weak and unstable (33 train / 10 val). Example: "Riya, please submit the report by Friday" is predicted SCHEDULED_ON (0.97) — v1 labels blur deadline vs scheduling (60% of train SCHEDULED_ON positives are flagged ambiguous).
- NONE means "no annotated link", not a verified negative; softmax scores are uncalibrated; no abstention threshold was tuned.
- Reference spans are noisy v1 SILVER spans, so Mode A also reflects those spans.
