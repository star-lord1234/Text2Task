# Phase 3 Plan — Neural Relation Extraction

**Status:** Draft, awaiting approval. No code has been written or run for this plan.
**Source:** `remaining_phases.md` §4, checked against the current repo on 15 Nov 2026.
**Goal:** A real, saved relation checkpoint that links TASK spans to PERSON and TEMPORAL spans (and TASK→TASK where supervision allows). It sits next to a rule comparator, is evaluated honestly as provisional (SILVER) work, and exposes an inference API that Phase 4 and later can call.

---

## 1. What the repo audit found

| Finding | Source | Consequence |
|---|---|---|
| The relation export is built from `data/final/*` (v1 annotations, `entity_source=annotated`), not from the SILVER-v2 three-class data the current entity checkpoint was trained on. | `data/model_ready/relations/statistics.json` | Check that the relation labels and spans are compatible with the three-class entity model. Rebuild if they are not. |
| Support is very uneven. Train: ASSIGNED_TO 620, SCHEDULED_ON 532, DUE_ON 33, **DEPENDS_ON 4**. Validation: DUE_ON 10, **DEPENDS_ON 0**. Test: DUE_ON 7, DEPENDS_ON 3. | same | DEPENDS_ON cannot be learned or fairly evaluated. DUE_ON is thin. Per-class F1 on these will be noisy and must be reported with support. |
| NONE is sampled 1:1 against positives in **all** splits, including validation and test. Train has 14,185 type-valid candidates but only 2,378 rows. | `sample_negatives`, `prepare_split` | 1:1 sampling is fine for training. For evaluation it inflates precision and hides deployment false-positive rates. Evaluation needs the **full** candidate set. |
| `VALID_PAIR_LABELS` includes GROUP and EVENT endpoints. The three-class entity model only emits TASK, PERSON and TEMPORAL. | `relation_classification.py`, `entity_training_v2_three_class.json` | Filter to TASK→{PERSON, TEMPORAL, TASK} for the MVP. Report any positives dropped for unsupported endpoint types. |
| Markers are `[E1_TASK]…[/E1_TASK]` and `[E2_PERSON]…`, with E1 as the source and E2 as the target. | `marked_text()` | These are new strings, not DistilBERT vocabulary. They must be registered as special tokens, with embeddings resized and the new rows initialised. |
| `ambiguous` and `explicit_vs_inferred` exist per relation. The `NONE` label is "no annotated link", which is not a verified negative. | row schema | Keep the flags. Report NONE as weak negatives. Use them for error analysis. |
| The entity checkpoint in use is `models/text2task-distilbert/entity_v2_three_class` (provisional SILVER). The test split is untouched. | `ACTIVE_PROVISIONAL_MODEL.json`, `progress.md` | Do not touch `test.jsonl` for model selection. |

I haven't verified two things yet. One is whether a thread-disjoint check exists for the relation export. The other is how many positives survive after the GROUP/EVENT filter. Both are covered in Step 1.

---

## 2. Decisions to confirm before execution

1. **Single-label MVP policy.** `_annotation_relations` already raises an error if one pair has two different relation types. I'd document this as mutually exclusive single-label classification, with no multilabel head.
2. **DEPENDS_ON handling.** With 4 train and 0 validation positives, I'd keep the label in the label map but **not claim neural DEPENDS_ON performance**. DEPENDS_ON stays on a rule or manual path (Step 3), clearly labelled.
3. **Dev/test usage.** All selection uses `validation`. `test` is only built, never scored, until you explicitly approve a final run.
4. **Model encoder.** Use `distilbert/distilbert-base-uncased`, as in the entity work, for consistency and speed. Cased or larger models are out of scope.

---

## 3. Steps

### Step 1 — Audit the relation dataset (Gate G1)

New script: `scripts/audit_relation_dataset.py`. It writes `results/relation_extraction/audit.json` and `audit.md`.

- Per split: positives per label, NONE count, full candidate count, and rows dropped for GROUP/EVENT endpoints.
- Offset checks: entity text must equal `text[start:end]`. Evidence spans must lie in the text. Markers must round-trip, i.e. stripping them gives the original text.
- Leakage checks: thread-disjointness across train, validation and test. Exact and normalised-text duplicate groups across splits, at the record and pair level.
- Compatibility check: every relation endpoint type must be in {TASK, PERSON, TEMPORAL}. Compare relation spans against what the entity checkpoint produces on the same records, and report the exact-match rate.
- Token length: the share of rows where both entities fit in a 512-token window, and the share of unrepresentable distant pairs.
- **Gate:** if the audit finds thread overlap, endpoint mismatches or lost positives, rebuild from `data/final` before training. If it passes, proceed.

### Step 2 — Rebuild the dataset, if needed or for evaluation (Gate G1)

Extend `src/model_data/relation_classification.py` and `scripts/prepare_relation_classification.py`. Add new options and keep the current defaults so existing tests still pass.

- Add `--types-allowed TASK,PERSON,TEMPORAL` and filter endpoint types.
- Write **two views** per split:
  - `train.jsonl`: all positives plus negatives sampled at a configurable ratio (default 1:1 as now, with a 3:1 ablation if time allows).
  - `*_full.jsonl` for validation and test: **all** type-valid candidates with no sampling, so evaluation reflects the deployment mix.
- Store a manifest with input file hashes, seed, the negative ratio, label counts and filter drops. Output to `data/model_ready/relations_v2_three_class/`, leaving the original directory untouched.
- Keep the `--entity-source predicted` mode. It is used for end-to-end evaluation in Step 6.

### Step 3 — Rule comparator

New module: `src/baselines/rule_relations.py`.

- **ASSIGNED_TO:** link a task to the nearest compatible PERSON using conservative cues (an addressee form such as "Riya, please…", "ask Riya to…", "Riya will…"). Use sentence-boundary and distance limits. When two persons are equally plausible, abstain and report the case as `UNRESOLVED`.
- **DUE_ON vs SCHEDULED_ON:** deadline cues ("by", "before", "due", "no later than") map to DUE_ON. Cues such as "at", "on" and "tomorrow at 10" map to SCHEDULED_ON.
- **DEPENDS_ON:** only on explicit prerequisite cues ("after X is done", "once X", "depends on"). This is the labelled rule/manual path.
- Return the same output schema as the neural model, plus `provenance: "rule"`. Abstentions are kept, not dropped.
- Evaluate it on the same rows as the neural model. Extend the existing rule baseline in `src/baselines/rule_based.py` only if its helpers can be reused. Don't duplicate them.

### Step 4 — Training code

New: `src/model_training/relation_classifier.py`, `scripts/train_relation_classifier.py` and `configs/relation_training.yaml`, structured like the entity trainer.

- Tokenizer: add the marker tokens (`[E1_TASK]`, `[/E1_TASK]`, `[E2_PERSON]`, etc.) via `add_special_tokens`. Call `resize_token_embeddings`. Initialise the new embeddings from the mean of existing embeddings rather than random values.
- Model: `AutoModelForSequenceClassification` with 5 labels from the existing `label_map.json`. I'd test two pooling variants: the standard `[CLS]` pooling, and the concatenated hidden states at the `[E1_*]` and `[E2_*]` start markers, which is usually stronger for relation extraction. Select between them on validation.
- Windowing: truncate around the pair, with both entities required in the window. Mark and count the rows that can't fit.
- Loss: weighted cross-entropy or class weights, because DUE_ON is small. Report the unweighted run as an ablation.
- Hyperparameters (the plan's defaults): lr 2e-5 to 5e-5, batch size 8 with gradient accumulation 4, 3 to 5 epochs, a fixed seed (`20261102`), early stopping on **macro-F1 over positive relations present in validation**. This excludes NONE, and excludes DEPENDS_ON where validation support is 0.
- Type-aware masking at inference: restrict logits to the labels valid for the endpoint types (`VALID_PAIR_LABELS`) before the argmax. A TASK→PERSON pair can never be predicted DUE_ON.
- Save the checkpoint to `models/text2task-relations/provisional_silver/` with a status JSON: provisional, SILVER, not final, and the dataset hash.
- Quick checks before the full run: a 20-example memorisation test (as with the entity model) and a smoke test on CPU/MPS.

### Step 5 — Evaluation

New: `scripts/evaluate_relation_classifier.py`, writing to `results/relation_extraction/`.

- **Mode A (reference spans):** run on the full validation candidate set. Report per-relation precision, recall, F1 and support, plus micro and macro (positive classes only). Handle NONE explicitly: it counts as a prediction but is not rewarded in the positive micro-F1. Also report the confusion matrix and the false-positive rate on NONE.
- **Mode B (predicted spans):** apply the three-class entity checkpoint to validation, build candidate pairs from its spans, classify them, and score against the reference relations with strict and lenient span matching. Report candidate recall (the share of gold relations whose endpoints were both detected) alongside relation F1, so errors from entity extraction are separated from linking errors.
- **Rule vs neural:** both run on identical rows. Report the delta, with a bootstrap CI over **threads**, not rows.
- Sparse classes: always show support. For DEPENDS_ON, report only the rule/manual result and label it "insufficient supervision".
- Error analysis: write 30 sampled errors per major confusion pair to `errors.jsonl`. Include ambiguous and inferred relations, and the cases where the cause is annotation incompleteness (flagged where the evidence suggests the "false positive" is a real missing label).
- Label every table as SILVER, provisional and not human-grounded.

### Step 6 — Inference interface

New: `scripts/predict_relations.py` and a library function `predict_relations(text, entities, model) -> list[RelationPrediction]`.

- Input: text plus entities with `id`, `type`, `start`, `end`.
- Output per candidate pair: `source_id`, `target_id`, `label`, `score` (softmax, documented as **uncalibrated**), `evidence_text`, `model_version`, `provenance` (`neural`/`rule`), and an `abstained` flag.
- Keep NONE decisions and unrepresentable pairs in a `debug` field rather than discarding them.
- Load the checkpoint once. Fail loudly if it is missing. Do not silently fall back to the rules unless explicitly requested.

### Step 7 — Tests

New `tests/test_relation_classifier.py` and `tests/test_rule_relations.py`:

- Marker tokenisation: the tokens are single IDs, and the embedding matrix is resized.
- Pair construction is type-valid, and all positives survive.
- Splits are thread-disjoint, and the dataset hashes are deterministic.
- Type-aware label masking.
- The rule comparator on hand-made cases (deadline vs scheduled, multiple persons, no assignee).
- The inference output schema.
- All existing tests (113 reported) must still pass.

---

## 4. Deliverables

```
scripts/audit_relation_dataset.py
scripts/train_relation_classifier.py
scripts/evaluate_relation_classifier.py
scripts/predict_relations.py
src/model_training/relation_classifier.py
src/baselines/rule_relations.py
configs/relation_training.yaml
data/model_ready/relations_v2_three_class/        (train sampled; val/test full)
models/text2task-relations/provisional_silver/    (checkpoint + STATUS.json)
results/relation_extraction/                      (audit, metrics, errors, rule-vs-neural)
tests/test_relation_classifier.py, tests/test_rule_relations.py
```

## 5. Acceptance criteria (from `remaining_phases.md`)

- [ ] Type-valid pair construction and deterministic, thread-disjoint split checks pass.
- [ ] A real checkpoint and real predictions exist. Per-relation and micro/macro P/R/F1 are reported with NONE handled explicitly.
- [ ] Rule and neural results are compared on identical rows. End-to-end (predicted-span) results and candidate coverage are reported separately.
- [ ] Sparse relations (DEPENDS_ON, and DUE_ON if thin) are disclosed with support. Neural claims are limited accordingly.
- [ ] All outputs are labelled provisional SILVER. The test split is unused.

## 6. Risks

| Risk | Mitigation |
|---|---|
| DUE_ON (33 train, 10 validation) gives unstable metrics. | Report supports and CIs. Don't tune on it. Consider merging DUE_ON/SCHEDULED_ON as a "TEMPORAL link" ablation, reported separately. |
| Weak NONE labels penalise correct predictions. | Report NONE as weak negatives. Manually review a sample of high-confidence "false positives". |
| Entity spans in the relation export differ from the three-class model's output, so Mode B yields low candidate recall. | The Step 1 audit quantifies this early. Report candidate recall explicitly. |
| Training on 1:1 data but deploying on skewed candidate sets gives many false positives. | Evaluate on full candidate sets. If precision is poor, adjust the negative ratio or add a score threshold (tuned on validation only). |
| Small data leads to overfitting. | Early stopping, a fixed seed, and the memorisation test to confirm the pipeline works before the real run. Multi-seed runs are a stretch goal. |

## 7. Order and checkpoints

1. Step 1 (audit) → **pause and report the findings to you** if the audit finds incompatibilities.
2. Steps 2 and 3 in parallel (dataset rebuild and rule comparator).
3. Step 4 (smoke and memorisation test, then the full run).
4. Steps 5 to 7.
5. Final summary of the metrics and caveats.

Out of scope for this phase: GROUP/EVENT/ARTIFACT detection, `DEPENDS_ON` neural claims, calibration, multi-seed runs, any use of the test split, and Phases 4 to 8.
