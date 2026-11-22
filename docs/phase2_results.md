# Phase 2 results: retraining the token tagger on MailEx-derived labels

All metrics are on the MailEx-derived dev split (389 emails, 391 rows) and are provisional (see `docs/phase1_labels.md`). Scripts: `scripts/train_entity_model.py`, `scripts/compare_runs.py`. Raw outputs: `results/entity_extraction/phase2/`.

## Runs (DistilBERT uncased, 10 epochs, warmup 10%, batch 4 x accumulation 4, seed 20261101, no class weights, best checkpoint by dev lenient F1)

| Run | LR | Training labels | Best epoch | Dev lenient F1 | Dev strict F1 |
|---|---|---|---:|---:|---:|
| 1 | 5e-5 | requests + commitments | 8 | **0.575** | **0.420** |
| 2 | 3e-5 | requests + commitments | 10 | 0.556 | 0.409 |
| 3 | 5e-5 | requests only | 10 | 0.572 (on its own dev labels) | 0.398 |
| Previous best (SILVER-v2, sqrt weights) | 2e-5 | 449 SILVER emails | 3 | 0.226 | 0.127 |

The jump from 0.226 to 0.575 is real but is **not a controlled comparison**: the training data, dev set and label definition all changed together.

## Per-type results, Run 1 (best), lenient / strict F1

| Type | Lenient | Strict | Phase 0 target (lenient) |
|---|---:|---:|---|
| TASK | 0.508 | 0.286 | >= 0.50 (met, by 0.008) |
| PERSON | 0.612 | 0.594 | >= 0.70 (not met) |
| TEMPORAL | 0.656 | 0.468 | >= 0.70 (not met) |

## Learning rate (Run 1 vs Run 2)
Run 1 is ahead by 0.019 lenient F1 overall; the paired bootstrap 95% interval over dev rows is [-0.006, +0.045], so **the two learning rates are not statistically distinguishable** (single seed each). Run 1 was kept as the reference.

## Commitment ablation (Run 3 vs Run 1)
The dev labels differ between the two definitions (TASK 175 vs 234 spans; PERSON 170 vs 169 because overlap resolution changes slightly), so every model was scored against **both** label sets (same rows, same tokens, verified identical):

| Model \ scored on | Full labels (+commitments) | Requests-only labels |
|---|---:|---:|
| Run 1 (+commitments) | **0.575** (TASK 0.508) | 0.533 (TASK 0.402) |
| Run 2 (+commitments) | 0.556 (TASK 0.502) | 0.509 (TASK 0.390) |
| Run 3 (requests only) | 0.539 (TASK 0.426) | **0.572** (TASK 0.493) |

Each model wins on the definition it was trained for; that is expected and says nothing about which definition is better. The fair question is whether a model does as well on its *own* definition. Paired bootstrap, lenient F1, Run 3 minus Run 1, each on its own labels:

| | Median | 95% interval |
|---|---:|---:|
| TASK | -0.013 | [-0.063, +0.039] |
| PERSON | -0.030 | [-0.067, +0.005] |
| TEMPORAL | +0.005 | [-0.035, +0.054] |
| Overall | -0.003 | [-0.030, +0.026] |

**Conclusion: no measurable difference.** The commitment rule neither helped nor hurt overall accuracy. Run 1 predicts more TASK spans (215 B-TASK vs 140), which shows it did learn to tag commitments. Because the scores are equal and the v2 guidelines count future commitments as TASK, the commitment version stays the default. Its cost is the extra label noise measured in Phase 1 (about 2 false commitments per 40 emails). PERSON and TEMPORAL are almost the same task in both runs, so their small differences are a measure of run-to-run noise (PERSON -0.03 is borderline, not significant).

## Run 3 interruption and recovery
Run 3 stalled for about 2 hours 20 minutes (checkpoint 1260 written 13:46, checkpoint 1440 at 16:07) while the machine was apparently asleep or hung. The process was never killed (`uptime` showed 88 days; the process was alive and its log kept updating), so **no resume or restart was needed**, nothing was lost, no results were overwritten, and no duplicate run was created. Wall-clock time recorded in its metrics (11,060 s) includes the stall; actual compute was about 25 minutes. Because the same process continued, Run 3 is fully comparable with Runs 1 and 2 (identical settings, data order and seed). The Run 3 checkpoints at steps 1260 and 1440 were verified complete (weights, optimizer, scheduler, RNG and trainer state) and would have supported a resume; the training script has no `--resume` option yet.

## Gate 2 (from `plan_model.md`)
- TASK lenient F1 meets the target (0.508 vs 0.50), but only just, and the dev labels miss about 1 in 8 real requests. PERSON and TEMPORAL are below target (0.61, 0.66 vs 0.70).
- This is neither "TASK low, others fine" nor "everything low". **Recommendation: skip Phase 3 (changing how TASK is modeled) for now.**
- The remaining gap is in PERSON and TEMPORAL. Likely causes: MailEx labels names and dates only when they are event arguments; the PERSON filter drops lowercase names; and the uncased encoder cannot use capitalization. Phase 4 items (a cased encoder; optional header-name and date-rule helpers) address these directly.

## Caveats
- Single seed per setting; dev set of 391 rows; differences under about 0.03 lenient F1 should be treated as noise.
- Dev labels are incomplete (missed requests, partial date and name coverage), so absolute scores are likely understated and cannot be quoted as accuracy.
- No test-split data was read in any Phase 2 run.
