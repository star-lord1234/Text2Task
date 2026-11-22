# Text2Task entity extraction: how the results were achieved, what is still wrong, and what could be better

Status date: 2026-11-03. Everything below is **provisional**: labels are derived from MailEx annotations through a deterministic mapping and were not independently reviewed against the Text2Task schema. The MailEx test split has not been built or read.

---

## 1. Summary

| | Before | After (Run 1) | After, leakage-corrected |
|---|---:|---:|---:|
| Overall lenient F1 | 0.226 | 0.575 | **0.555** |
| Overall strict F1 | 0.127 | 0.420 | **0.390** |
| TASK lenient / strict | 0.068 / 0.004 | 0.508 / 0.286 | **0.482** / not recomputed |
| PERSON lenient | 0.396 | 0.612 | **0.594** |
| TEMPORAL lenient | 0.440 | 0.656 | **0.645** |

- The improvement is real and large, but **the two columns "Before" and "After" are not a controlled comparison**: training data, dev set and label definition all changed together. The earlier numbers were scored against noisy SILVER-v1 labels (73% of audited records had major errors).
- **A data-leakage problem was found while writing this report** (section 5, error E1): 39 of 389 dev emails are copies of training emails. Removing them lowers neural scores by about 0.02 to 0.03. The last column uses the deduplicated dev set (349 emails). **Use the corrected column in anything you present.**
- After correction, TASK lenient F1 (0.482) is **below** the 0.50 target, and PERSON and TEMPORAL are below 0.70 too. This changes the Gate-2 recommendation I gave earlier (section 6).

## 2. How the results were achieved

### 2.1 The pipeline, in order

1. **Source:** MailEx, 1,500 email threads with human-annotated *events* (who asks whom to do what, with typed argument slots such as `Action Description`, `Action Members`, `Meeting Date`).
2. **Label mapping** (`configs/mailex_to_text2task_v1.json`, `src/annotation/mailex_labels.py`): a deterministic translation from MailEx slots to our three entity types.
   - TASK: `Action Description` in `Request_Action*` events (a request), plus commitments (`Deliver_Action*` descriptions that start with `will`, `'ll`, `going to`; not `will be <state>`).
   - TEMPORAL: any `Date` or `Time` slot, minus event clauses ("Upon her approval") and spans over 8 tokens.
   - PERSON: any `Members` slot that passes a name filter (capitalized, 1 to 3 words, not a pronoun/company/role), plus other occurrences of the same name in the same email.
3. **Dataset build** (`scripts/build_mailex_dataset.py`): WordPiece tokenization, BIO tags on one layer, windows of 512 tokens, empty emails dropped, thread-disjoint train/dev. Result: 2,845 train emails and 389 dev emails.
4. **Model** (`scripts/train_entity_model.py`): DistilBERT (uncased) with a token-classification head; 10 epochs, learning rate 5e-5, 10% warmup, batch 4 with gradient accumulation 4, seed 20261101, no class weighting, best epoch chosen by dev lenient F1.
5. **Evaluation** (`src/model_training/span_metrics.py`): strict F1 (exact boundaries and type), lenient F1 (same type and span overlap IoU of at least 0.5, one-to-one), overlap-any F1 and token-level F1. Strict reproduces the earlier seqeval numbers exactly (verified to 9 decimals).

### 2.2 Why the score went up (what drove it, and how sure we are)

| Factor | Evidence | Confidence |
|---|---|---|
| **Cleaner labels.** Audited major-error rate: SILVER-v1 73%, SILVER-v2 33%, MailEx-derived about 9% (pooled over two samples). | AI-assisted inspection of 30 to 40 emails per sample (`docs/phase1_labels.md`). | Medium. Small samples, not independent human review. |
| **Much more training data.** 449 emails (659 TASK) became 2,845 emails (1,664 TASK). | Counts from the build statistics. | High that it helps; the size of the effect is **not isolated**. |
| **Validation labels now follow the training definition.** The old dev set used a different TASK definition from training. | Shown by the earlier audits. | High. Part of the "gain" is just a fairer measurement. |
| **A proper training recipe.** 10 epochs, warmup, no class weights. The old runs had 3 epochs, no warmup, and weights that made the model spam B-tags (327 predicted against 208 real). | The old runs' B-label counts; epoch curves of Run 1. | Medium. |

What we **cannot** say: how much of the gain comes from each factor. No experiment changed only one of them. Say "the combination of better labels, more data and a better recipe", not "the labels caused it".

### 2.3 Why the model is where it is (error anatomy, Run 1, dev set)

| Type | Predicted | Reference | Exact | Near (IoU ≥ 0.5) | Partial / none | Reference spans missed entirely |
|---|---:|---:|---:|---:|---:|---:|
| TASK | 298 | 234 | 76 | 60 | 51 partial, 111 no overlap | 72 (31%) |
| PERSON | 161 | 169 | 98 | 3 | 3 partial, 57 no overlap | 66 (39%) |
| TEMPORAL | 169 | 130 | 70 | 31 | 7 partial, 61 no overlap | 25 (19%) |

How to read it:
- **TASK** is mainly a *boundary* problem: only 76 of 234 are exact, but 162 reference spans overlap some prediction. Where predicted spans nearly match, they more often start too late (28) than too early (13), and end too early (18) than too late (7). MailEx itself is inconsistent about whether "Please" belongs in the span, which caps strict F1.
- **PERSON** boundaries are almost perfect (98 of 104 overlapping predictions are exact). The weakness is *finding* names: 39% of reference names are missed entirely.
- **TEMPORAL** is the most reliable type, with mostly boundary noise (prepositions like "by" or "on").
- **"False positives" are of two kinds.** From a random sample of 12 per type: many are real entities the labels never marked ("check this out", "advise me regarding your availability", the names "david", "john", "bill rapp", the dates "today", "afternoon", "a couple of weeks"), because MailEx labels names and dates only when they are arguments of an event. But a quarter or more are junk fragments ("the", "'", "chance to", "at", "9", "g", "o . k ."). The first kind is label incompleteness; the second is a real, fixable model weakness.
- **Some reference "misses" are label noise** too: "director", "girl", "playboy" are labeled PERSON because the name filter is only a heuristic.

### 2.4 Ablations and baseline

| Comparison | Result | Meaning |
|---|---|---|
| Learning rate 5e-5 vs 3e-5 | Run 1 ahead by 0.019 lenient F1; 95% interval [-0.006, +0.045] | Not distinguishable (single seed). |
| With vs without commitment TASKs (each on its own labels) | Difference -0.003 overall; TASK -0.013; all intervals include 0 | The commitment rule neither helped nor hurt. Kept because the guidelines count commitments as tasks. |
| Rule-based baseline (E1 spans) | Lenient 0.402 / strict 0.259 on the full dev set | Neural wins on every type; the biggest gap is PERSON (0.29 vs 0.61). The baseline is not affected by the leakage (0.401 on the clean dev set). |

All bootstrap intervals come from resampling dev rows; they do not capture seed-to-seed variation.

## 3. Final comparison table (leakage-corrected dev set: 349 emails, 351 rows)

| Model | Lenient F1 | Strict F1 | TASK lenient | PERSON lenient | TEMPORAL lenient |
|---|---:|---:|---:|---:|---:|
| Run 1: lr 5e-5, +commitments | **0.555** | **0.390** | **0.482** | **0.594** | **0.645** |
| Run 2: lr 3e-5, +commitments | 0.534 | 0.383 | 0.479 | 0.566 | 0.605 |
| Run 3: lr 5e-5, requests only (own labels) | 0.544 | 0.357 | 0.456 | 0.558 | 0.639 |
| Rule-based baseline | 0.401 | 0.260 | 0.399 | 0.300 | 0.474 |

On the 45 reference spans inside the leaked dev emails alone, Run 1 scores 0.82 lenient F1. That is the memorization signal.

## 4. What was verified as correct

- Tokenizer alignment: 0 mismatches across all 3,262 train and dev rows (checked in this report; the new training script itself only checks the first row).
- Train and dev share no threads (checked at build time).
- Strict F1 equals seqeval's F1 on real predictions (unit test). 113 tests pass.
- The test split was never read or built. Runs 1 and 2 were left untouched by the Run 3 interruption.

## 5. Errors and risks still in the system (ranked)

| # | Problem | Status | Impact | Fix |
|---|---|---|---|---|
| E1 | **Train/dev leakage.** 34 dev emails are exact copies of training emails and 26 more are near-copies (39 distinct after merging), plus 8 repeated inside dev. The MailEx build used all unified records and skipped the deduplication the older pipeline had. | **Verified** (`scripts/audit_leakage.py`) | Neural scores overstated by 0.02 to 0.03 lenient and 0.03 to 0.04 strict; Run 3 strict by 0.04. Also affects training (duplicates in train). | Deduplicate across and within splits before splitting (group by text hash plus near-duplicate clusters), rebuild, retrain (about 30 minutes per run). **Not yet done.** |
| E2 | **Dev labels are incomplete.** MailEx labels names and dates only as event arguments; about 1 in 8 clear requests has no annotation at all. | Verified by inspection | Precision is understated; recall of real tasks cannot be trusted; models learn to ignore real entities. | Human-verified dev subset; optional second labeling pass for missed requests. |
| E3 | **Heuristic label noise.** PERSON filter lets through "director", "girl", "playboy"; commitment rule creates false TASKs ("are going to get very cranky"); TEMPORAL still contains odd spans. | Verified by inspection | Limits both training and measurement. | Tighten filters after a human review of a PERSON/TASK sample. |
| E4 | **Model selection on the same dev set it is reported on.** Best epoch picked by dev lenient F1. | Verified by design | Small optimism (Run 1: best epoch 8 = 0.575, final epoch 10 = 0.568). | Use a separate selection split or report final-epoch scores. |
| E5 | **Single seed per setting.** | Verified | Differences under about 0.03 are noise. | 3 seeds for the chosen configuration. |
| E6 | **Window handling.** Entities are assigned to one window only; the overlapping part of the next window is labeled `O`. 52 train rows and 4 dev rows are multi-window. | Verified by counts | Small label noise on long emails. | Label overlapping windows consistently, or merge window predictions per email. |
| E7 | **Stale and conflicting status files.** `models/text2task-distilbert/ACTIVE_PROVISIONAL_MODEL.json` still points to the old model (F1 0.0078); `results/entity_extraction/EXECUTION_STATUS.md` ends at 0.127. Two data lineages exist (`data/final` cleaned text, SILVER; `data/unified` raw MailEx), and the old 90-email SILVER test set is in the first one. | Verified | Someone could load the wrong model or test on the wrong set. | Point the active-model file at Run 1 (after the E1 retrain), and decide which lineage the final test uses. |
| E8 | **No resume support** in `train_entity_model.py`, and no test for the training script. | Verified | A real crash costs the whole run. | Add `--resume-from-checkpoint`. |
| E9 | **Junk fragments in predictions** ("the", "'", single characters). | Verified by sample | Lowers precision across all types. | Post-filter spans made only of stop words, punctuation or one character (untested; see section 6). |

## 6. Gate-2 recommendation, corrected

Earlier I recommended skipping the TASK-modeling redesign because TASK lenient F1 was 0.508 against a 0.50 target. That margin was 0.008 and was inflated by leakage. On the clean dev set TASK is 0.482 (below target), PERSON is 0.594 and TEMPORAL is 0.645 (both below 0.70). By the plan's gate, "everything low" means going back to data and labels rather than redesigning TASK modeling. **Do not skip or start Phase 3 until E1 is fixed and the models are retrained on deduplicated data.**

## 7. Scope for better results (hypotheses, not promises)

Ordered by what I expect to matter most. None of these has been tested.

1. **Fix E1 and retrain.** Not an improvement, but it gives honest numbers and removes duplicate-driven overfitting. Do this first.
2. **Better evaluation labels (E2).** A human-verified dev subset of 100 to 150 emails would show the true level, which is probably higher than shown. This is also needed for any final claim and is required by the master plan (§6).
3. **Recover missing labels for training.** A reviewed second pass for requests that MailEx missed would raise TASK recall (72 of 234 TASK references are currently missed entirely, and some real tasks are in the "false positives").
4. **PERSON recall.** 39% of names are missed. Ideas: add sender and recipient names from headers; try a cased encoder (`roberta-base`, `deberta-v3-base`), since capitalization is the strongest cue for names. Note all 169 dev names start with a capital, so a cased model has a clear signal to use.
5. **Cheap post-processing (E9).** Drop junk fragments; optionally adjust TASK boundaries to a consistent convention (for example always starting at the verb). Likely to help strict F1 and precision a little.
6. **Seeds and checkpoint choice.** Three seeds, report mean and spread; consider averaging weights from the last epochs. Validation loss rose after epoch 3 while F1 kept rising, which suggests over-confidence and matters for the calibration extension (§11 of the master plan).
7. **Larger structural options** from `plan_model.md` (sentence classifier plus span tagger, Option B) only if TASK stays low after 1 to 3.

Realistic expectation: the labels and the evaluation set are probably the main ceiling now. Model changes alone are unlikely to give another jump like the last one.

## 8. How to explain this to a reviewer

Say:
- "We replaced noisy LLM-built labels with labels derived from MailEx's human annotations, enlarged the training set about 6 times, and fixed the training recipe. Lenient F1 went from 0.23 to about 0.56 on a deduplicated dev set."
- "We report exact-match and overlap-based scores because the main error is span boundaries, not detection."
- "We found and quantified a train/dev duplication problem and report scores on the corrected dev set."
- "The remaining ceiling is mostly the labels: MailEx leaves many real names, dates and requests unmarked."

Do not say:
- That accuracy is 0.56. The reference is incomplete and partly heuristic.
- That any one change caused the improvement.
- That these are final results. There is no human-verified evaluation set and no test run yet.

## 9. Reproduce

```
python scripts/build_mailex_dataset.py                                   # data (mapping v1.2.0)
python scripts/train_entity_model.py --run-name mailex_v1_lr5e-5 --learning-rate 5e-5 --epochs 10
python scripts/score_predictions.py results/entity_extraction/phase2/mailex_v1_lr5e-5/validation_predictions.jsonl
python scripts/compare_runs.py                                           # cross-label comparison + bootstrap
python scripts/audit_leakage.py                                          # leakage audit + deduplicated rescoring
python scripts/evaluate_rule_baseline.py --split validation              # rule-based baseline
python -m unittest discover -s tests                                     # 113 tests
```

Related documents: `docs/phase0_baseline.md`, `docs/phase1_labels.md`, `docs/phase2_results.md`, `docs/baseline_rule_based.md`, `plan_model.md`.
