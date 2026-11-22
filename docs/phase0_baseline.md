# Phase 0: Decisions and Baseline

## Decisions (adopted as defaults; change any of them and later phases rerun)

| # | Decision | Adopted default |
|---|---|---|
| 0.1 | What is a TASK | As in `docs/annotation_guidelines_v2.md`: a current request, future commitment, prohibition, cancellation/update, or concrete plan. Not completed history, descriptions, or system states. Phase 1 tests whether MailEx human labels can be mapped to this. |
| 0.2 | Headline metrics | Strict exact-match F1 (kept for continuity), lenient F1 (same type, span IoU >= 0.5, one-to-one), token-level F1. Overlap-any F1 (same type, >= 1 shared token) is reported as a diagnostic only. |
| 0.4 | Targets (proposed) | PERSON and TEMPORAL lenient F1 >= 0.70; TASK lenient F1 >= 0.50. To be revisited after Phase 2. |

These are the defaults proposed in `plan_model.md`. They were adopted without a separate confirmation, so they are open to change.

## Metric implementation

- `src/model_training/span_metrics.py`, tests in `tests/test_span_metrics.py` (10 tests).
- The strict metric is verified equal to seqeval on the real v2 predictions (precision, recall and F1 to 9 decimal places).
- Score any run with `python scripts/score_predictions.py <validation_predictions.jsonl>`.
- All positions are WordPiece-level, as in the prediction files.

## Baseline (SILVER-v2 train, SILVER-v1 validation; all provisional)

Full JSON: `results/entity_extraction/baseline/phase0_baseline.json`.

### Best run: epoch 3, sqrt class weights

| Type | Support | Strict F1 | Lenient F1 | Overlap-any F1 | Token F1 |
|---|---:|---:|---:|---:|---:|
| TASK | 272 | 0.0042 | 0.0675 | 0.3249 | 0.1311 |
| PERSON | 63 | 0.3333 | 0.3958 | 0.4583 | 0.3918 |
| TEMPORAL | 73 | 0.2200 | 0.4400 | 0.5700 | 0.5160 |
| OVERALL | 408 | 0.1270 | 0.2263 | 0.4111 | 0.2203 |

### Other v2 runs

| Run | Strict F1 | Lenient F1 | Overlap-any F1 | Token F1 |
|---|---:|---:|---:|---:|
| epoch 3, unweighted | 0.0192 | 0.0240 | 0.0288 | 0.0109 |
| epoch 6, unweighted | 0.0463 | 0.1637 | 0.2883 | 0.1508 |
| epoch 3, sqrt weighted | 0.1270 | 0.2263 | 0.4111 | 0.2203 |

## What the new metrics show

- **TASK is mostly a boundary problem on this validation set.** Strict F1 is 0.004 but overlap-any F1 is 0.325: the model often marks a token inside a real TASK span, but not the right extent. This agrees with the earlier diagnosis (reference TASK spans average about 8 tokens, predictions about 3).
- **TEMPORAL is under-reported by exact match.** Strict 0.22 vs lenient 0.44.
- **Caveat.** Validation labels are SILVER-v1 and use a different TASK definition from training, so even the lenient numbers are not a clean measure. Phase 1 fixes that.
