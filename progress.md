# Text2Task ML Project Progress

Status reviewed: **2026-11-15**

## Current state

The project has an implemented and tested pipeline for converting MailEx email data into Text2Task-style entity datasets, training DistilBERT entity extractors, and evaluating them with strict and overlap-based metrics. The strongest current model is still **provisional**: it is evaluated on MailEx-derived labels rather than an independently human-reviewed GOLD set.

The latest leakage-corrected development result for the best Phase-2 run is:

- Overall lenient F1: **0.555**
- Overall strict F1: **0.390**
- TASK lenient F1: **0.482**
- PERSON lenient F1: **0.594**
- TEMPORAL lenient F1: **0.645**
- Evaluation set after duplicate removal: **349 emails / 351 model rows**

These values are development signals, not final accuracy claims, because the reference labels are incomplete and have not been independently verified against the Text2Task schema.

## Implemented

### 1. MailEx ingestion and conversion

- MailEx source records can be converted into a unified JSONL representation.
- Train, development, and test membership, thread IDs, turn order, original tokens, event annotations, and character offsets are preserved.
- Conversion and auditing entry points are available in `scripts/convert_mailex.py`, `scripts/inspect-mailex.py`, and `scripts/audit_mailex.py`.
- Unified datasets exist under `data/unified/`.

### 2. Conservative email cleaning

- Deterministic, token-aware cleaning is implemented in `src/preprocessing/clean_emails.py` and exposed through `scripts/clean_mailex.py`.
- The cleaner handles legal disclaimers, quoted or forwarded blocks, signatures, encoding normalization, alignment validation, and safe fallback to raw text.
- Tokens belonging to MailEx labels or triggers are protected from silent removal.
- Exact and conservative near-duplicate detection is implemented.
- All **3,936** unified records were processed with reliable alignment and no raw-text fallbacks:
  - Train: 3,117
  - Development: 414
  - Test: 405
- Cleaning reports and hashes are stored in `data/reports/cleaning_report.md`.

### 3. Candidate selection

- Deterministic candidate selection is implemented in `scripts/select_candidates.py`.
- The selector preserves complete thread context and split membership while preventing duplicate groups from being selected across splits.
- Coverage signals include requests, commitments, multiple tasks, ownership, deadlines, scheduling, prerequisites, status/negation, ambiguity, and no-action examples.
- **600** provisional candidates were selected:
  - Train: 450
  - Development: 60
  - Test: 90
- Candidate datasets are stored under `data/candidates/`, with the selection report in `data/reports/candidate_selection.md`.

### 4. Annotation schema, validation, and review workflow

- The Text2Task schema and versioned prompts are defined under `configs/`.
- Entity types supported by the full schema are TASK, PERSON, GROUP, TEMPORAL, EVENT, and ARTIFACT.
- Relation types supported by the schema are ASSIGNED_TO, DUE_ON, SCHEDULED_ON, and DEPENDS_ON.
- Structural and semantic record validation is implemented in `src/annotation/validators.py` and `src/annotation/semantic_quality.py`.
- LLM annotation infrastructure supports Ollama and OpenAI Responses providers, structured output, redaction/restoration, retries, checkpointing, and review routing.
- Deterministic auto-SILVER annotation is implemented in `src/annotation/auto_silver.py`.
- Human review document creation, editing, QC, audit trails, tier assignment, and finalization are implemented in `src/annotation/review_workflow.py`.
- Dataset assembly, provenance checks, duplicate auditing, split integrity, and statistics generation are implemented in `src/annotation/finalize_dataset.py`.
- Finalized SILVER data exists under `data/final/` for train, validation, and test.

### 5. SILVER-v2 repair workflow

- Versioned TASK guidelines and three-class entity prompts were added.
- A local LLM annotation attempt was executed but stopped as operationally impractical after more than four hours; partial successes and failures were retained with explicit provenance.
- A reproducible hybrid repair pipeline was implemented in `scripts/build_silver_v2_hybrid.py`.
- The hybrid training corpus contains 450 emails using corrected audit records, eligible validated LLM outputs, and conservative SILVER-v1 filtering.
- A fresh 30-record audit improved major errors from 22/30 in SILVER-v1 to 10/30 in SILVER-v2, but this is still below research-quality requirements.
- A single-layer TASK/PERSON/TEMPORAL dataset builder is implemented in `scripts/build_entity_dataset_v2.py`.

### 6. MailEx-derived labels for improved training

- A deterministic MailEx-to-Text2Task mapping is implemented in `src/annotation/mailex_labels.py` with configuration in `configs/mailex_to_text2task_v1.json`.
- The mapping derives:
  - TASK from request-action spans and selected future commitments.
  - TEMPORAL from date/time slots with clause and length filters.
  - PERSON from member slots using a conservative name filter.
- Both the default requests-plus-commitments dataset and a requests-only ablation dataset are generated by `scripts/build_mailex_dataset.py`.
- Primary model-ready data contains:
  - 2,845 training emails and 2,871 training rows.
  - 389 development emails and 391 development rows before duplicate correction.
  - 1,664 TASK, 1,040 PERSON, and 1,036 TEMPORAL training spans.
- The test split has deliberately not been built for this Phase-2 workflow.
- The quality gate of 80% fully acceptable labels was not met; sampled acceptability was 60% to 75%. The data is cleaner than the earlier SILVER sets but remains incomplete.

### 7. Model-ready dataset preparation

- DistilBERT token-classification preparation is implemented in `src/model_data/token_classification.py` and `scripts/prepare_token_classification.py`.
- It supports WordPiece alignment, BIO labels, long-document windows, overlap layers, exact span reconstruction checks, and traceability back to source emails.
- Relation-classification data preparation is implemented in `src/model_data/relation_classification.py` and `scripts/prepare_relation_classification.py`.
- It supports typed entity markers, inference-valid entity pairs, negative sampling, positive-edge retention, and split-safe traceability.
- Model-ready entity and relation datasets exist under `data/model_ready/`.
- Data readiness and provenance gates are implemented in `src/model_data/entity_readiness.py` and `scripts/audit_entity_training_readiness.py`.

### 8. Baselines and diagnostics

- A rule-based entity baseline is implemented in `src/baselines/rule_based.py` and `scripts/evaluate_rule_baseline.py`.
- On the leakage-corrected development set, its overall lenient F1 is approximately **0.401**, below the best neural run at **0.555**.
- Structural pipeline diagnostics verify tokenizer alignment, label mappings, layer markers, gradients, and decoding behavior.
- A controlled 20-example memorization test reached entity F1 **1.0**, confirming that the training and decoding path can learn a clean subset. This is a mechanical diagnostic, not a generalization result.

### 9. Entity model training and inference

- DistilBERT token-classification training is implemented in `src/model_training/entity_extractor.py` and the training scripts under `scripts/`.
- Training supports Apple Silicon MPS, gradient accumulation, warmup, configurable learning rates and epochs, optional class weighting, best-checkpoint selection, provenance-aware experiment modes, and saved predictions/metrics.
- Prediction entry points exist for saved entity models and unseen messages.
- Multiple trained checkpoints are present under `models/text2task-distilbert/`, including:
  - Initial six-class provisional SILVER model.
  - Three SILVER-v2 three-class diagnostic runs.
  - Three Phase-2 MailEx-derived runs.
  - A memorization diagnostic model.
- The Phase-2 experiments completed with DistilBERT, 10 epochs, 10% warmup, batch size 4 with gradient accumulation 4, and no class weighting:
  - Requests + commitments, learning rate 5e-5: best raw dev lenient F1 0.575.
  - Requests + commitments, learning rate 3e-5: raw dev lenient F1 0.556.
  - Requests only, learning rate 5e-5: raw dev lenient F1 0.572 on its own labels.
- Learning-rate and commitment-ablation differences were not statistically distinguishable with the current single-seed experiments.

### 10. Evaluation and reporting

- Span evaluation is implemented in `src/model_training/span_metrics.py`.
- Metrics include strict exact-match F1, lenient IoU-based F1, overlap-any F1, and token-level F1, reported overall and per entity type.
- Strict scoring was verified against seqeval on real predictions.
- Comparison and scoring scripts are available in `scripts/score_predictions.py` and `scripts/compare_runs.py`.
- Leakage auditing is implemented in `scripts/audit_leakage.py`.
- The audit found 39 copied development emails among the original 389; corrected results exclude those records.
- Detailed experiment reports, predictions, logs, and metrics are stored under `docs/`, `data/reports/`, and `results/entity_extraction/`.

### 11. Automated tests

- Test coverage exists for cleaning, schemas, auto-SILVER generation, MailEx mapping, LLM annotation helpers, review workflow, finalization, candidate selection, semantic quality, model-data preparation, entity diagnostics/training, v2 dataset construction, the rule baseline, conversion, and span metrics.
- Latest verification on 2026-11-15: **113 tests passed** using:

```bash
./.venv/bin/python -m unittest discover -s tests
```

## Current limitations and blockers

- **No independent GOLD evaluation set:** 0 validation emails are independently human-reviewed as GOLD. The strict GOLD training/evaluation mode correctly blocks.
- **Labels remain incomplete:** MailEx does not annotate every real request, name, or temporal expression, and the PERSON mapping is heuristic.
- **Duplicate leakage was discovered:** the corrected scores are available, but the underlying train/development datasets have not yet been rebuilt to remove the duplicates before training and checkpoint selection.
- **Targets are not fully met after leakage correction:** TASK is 0.482 versus the proposed 0.50 lenient-F1 target; PERSON and TEMPORAL are below their proposed 0.70 targets.
- **Only single-seed Phase-2 runs exist:** small differences between configurations are not conclusive.
- **The test split remains untouched for the improved MailEx-derived workflow:** there is no final held-out test result.
- **No relation classifier has been trained:** relation dataset preparation exists, but relation-model training and evaluation have not started.
- **GROUP, ARTIFACT, and EVENT are not part of the improved three-class model:** coverage was insufficient to justify expansion.
- **No final production model has been designated:** all saved models are provisional or diagnostic.

## Recommended next work

1. Rebuild train/development data with cross-split exact and near-duplicate removal, then retrain so duplicate records cannot influence checkpoint selection.
2. Create an independently human-reviewed validation subset following `docs/annotation_guidelines_v2.md`; keep SILVER and GOLD provenance separate.
3. Add a targeted second-pass annotation workflow for request-like emails that currently have no TASK span, plus deterministic PERSON/header and temporal helpers.
4. Retrain the same three-class architecture on the corrected labels before changing TASK model architecture.
5. Test a cased encoder and run multiple seeds only after the label and leakage issues are addressed.
6. Freeze one configuration, build the untouched MailEx test split, and perform one final evaluation.
7. Train and evaluate the relation classifier only after entity quality and GOLD evaluation are sufficient.

## Key references

- `docs/results_report.md` — latest consolidated result and leakage analysis.
- `docs/phase0_baseline.md` — baseline decisions and metrics.
- `docs/phase1_labels.md` — MailEx mapping, dataset counts, and quality-gate outcome.
- `docs/phase2_results.md` — completed Phase-2 runs and ablations.
- `data/reports/cleaning_report.md` — cleaning and alignment results.
- `data/reports/final_dataset_statistics.md` — finalized SILVER dataset statistics.
- `data/reports/model_data_statistics.md` — entity and relation model-data statistics.
- `data/reports/entity_v2_retraining.md` — SILVER-v2 repair and retraining history.
- `results/entity_extraction/phase2/dedup_rescore.json` — leakage-corrected metrics.
- `results/entity_extraction/EXECUTION_STATUS.md` — provisional/GOLD execution boundary.

