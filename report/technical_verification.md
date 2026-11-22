# Technical verification

This document records the evidence behind the report's major claims, how each was checked, and what remains unverified.
Report builds: `main.tex` → `Text2Task_Final_Report.pdf` (concise, 30 pages) and `main_full.tex` → `Text2Task_Full_Report.pdf` (full, 94 pages), compiled with Tectonic (XeTeX) on 2026-11-17. The concise edition is condensed from the full one and quotes the same numbers; `verify_numbers.py` checks the full chapters, and the concise text was cross-checked for the same headline values.

## 1. How numbers were verified

| Mechanism | What it covers |
|---|---|
| `scripts/extract_stats.py` | Reads only saved artefacts (datasets, training logs, evaluation JSON) into `data/stats.json`. Dataset counts are **recomputed** from the JSONL files rather than copied from statistics files. |
| `scripts/verify_numbers.py` | Recomputes 47 headline numbers from `stats.json`, formats them as printed, and asserts each string occurs in the named chapter. **Result: 47/47 passed.** |
| `scripts/make_charts.py` | Every chart is drawn from `stats.json`; no value is typed in by hand except the error-anatomy chart (see §4). No smoothing or interpolation. |
| Re-execution | Facts re-run against the code during writing: temporal normaliser outputs (Figure 10.1), the live worked example (`data/live_example_analysis.json`), Scenario F (API test), the full test suites. |

Consistency checks that passed:
- Recomputed MailEx split sizes (3,117 / 414 / 405 emails; 1,200 / 150 / 150 threads; 636 / 70 / 70 non-event emails) equal the figures published by Srivastava et al. (2023).
- Recomputed MailEx-derived entity counts equal `statistics.json` (TASK 1,664, PERSON 1,040, TEMPORAL 1,036 train).
- Relation class weights stored in the checkpoint (0.707, 0.994, 4.163, 1.037) equal `sqrt(N / (K·n_c))` on the training label counts (§8.5 of the report).
- Entity class weights stored for the SILVER-v2 run equal `sqrt(N_O / N_c)` (O weight 1.0).

## 2. Claims and their sources

| Claim (chapter) | Value | Source |
|---|---|---|
| Best entity model, deduplicated dev (Ch. 11, 14) | lenient 0.555, strict 0.390; TASK 0.482, PERSON 0.594, TEMPORAL 0.645 | `results/entity_extraction/phase2/dedup_rescore.json` |
| Before deduplication (Ch. 14) | lenient 0.575, strict 0.420 | same file, `full` |
| Rule baseline (Ch. 14) | lenient 0.401, strict 0.260 (clean) | same file |
| Leakage (Ch. 5) | 34 exact + 26 near copies = 39 distinct; 8 repeated in dev; 349 clean emails | `docs/results_report.md` §5 (E1), produced by `scripts/audit_leakage.py` |
| Bootstrap ablations (Ch. 14) | e.g. Run1−Run2 +0.019 [−0.006, +0.045] | `results/entity_extraction/phase2/comparison.json` |
| Deployed entity checkpoint (Ch. 11, 14) | strict 0.127, lenient 0.226, TASK strict 0.004 | `results/entity_extraction/baseline/phase0_baseline.json`; checkpoint path in `src/api/config.py` |
| Six-class SILVER model (Ch. 11) | F1 0.0078, token accuracy 0.732 | `models/text2task-distilbert/STATUS.json`, `results/entity_extraction/EXECUTION_STATUS.md` |
| Relation model (Ch. 14) | micro 0.764 [0.70, 0.84], macro 0.719, rule 0.527; confusion matrix | `results/relation_extraction/evaluation/validation_markers_sqrt.json` |
| Mode B relation scores (Ch. 14) | 0.000 / 0.024 / 0.195 | `results/relation_extraction/RESULTS.md` |
| Relation threshold table (Ch. 14) | 0.9 → precision 0.945, recall 0.650 | `results/phase4/REPORT.md` |
| Temporal coverage (Ch. 10) | 1.3 % resolved without anchor; 102/102 fixtures | `results/phase4/report.json` |
| Reconciliation (Ch. 10, 14) | 91/91 scenarios; 12,000 fuzz steps, 0 violations | `results/phase5/REPORT.md`, `results/phase7_5/REPORT.md` |
| Graph (Ch. 10, 14) | 12,000 decisions, 72,120 state checks, 0 disagreements | `results/phase6/REPORT.md` |
| Hybrid vs neural (Ch. 11, 14) | holdout strict pass 23/30 vs 7/30; rule-only 22/30 | `results/phase7_5/summary.json`, `COMPARISON.md` |
| Refinement on emails (Ch. 14) | lenient F1 0.203 → 0.232 → 0.255; TASK 0.114 | `results/phase7_5/silver_validation.json` |
| Review load (Ch. 14) | 143 creations (2.42/email) vs 96 + 3 (1.68/email) | `results/phase7_5/email_review_load.json`, `METRICS.md` |
| Training configurations (Ch. 8) | learning rates, steps, durations | each run's `metrics.json`; `models/text2task-relations/ACTIVE/relation_config.json` |
| Training curves (Ch. 8) | per-epoch loss and F1 | `training_log.json` (Phase 2), `runs/markers_sqrt/training_summary.json` |
| Test counts (Ch. 6, 12) | 362 backend, 97 frontend, 20 Playwright (13 scripted + 7 real models) | suites re-run on 2026-11-17 |
| Worked example (Ch. 7) | raw/refined spans, SCHEDULED_ON 0.969, named_addressee, due 2026-11-13 | `data/live_example_analysis.json`, captured from the real checkpoints |

## 3. Architectural claims

Every component named in the architecture chapters was checked against the code: `src/api/app.py` (routes, `_check_reviewer`), `src/api/views.py` (`reviewers`), `src/api/services/pipeline.py`, `src/refine/config.py` (stage names, presets, default `hybrid`), `src/reconciliation/cues.py` (intent priority order, 28-character negation window), `src/reconciliation/reconciler.py`, `src/pipeline/identity_resolution.py` (including `named_addressee`), `src/temporal/normalize.py`, `src/model_training/relation_classifier.py` (marker pooling), `src/model_training/span_metrics.py` (greedy one-to-one IoU matching), `src/model_training/entity_inference.py` (confidence = mean of per-piece maxima), `scripts/train_entity_model.py` and `scripts/train_distilbert_v2.py` (sqrt weights).

Diagrams were drawn from these sources. Where the implementation differs from the original plan, the diagrams follow the implementation: DEPENDS_ON is shown as rule-only; GROUP/EVENT/ARTIFACT appear only in the SILVER-v1 data; the app's entity checkpoint is the SILVER-v2 model.

## 4. Items not independently re-verified

- **Error-anatomy chart (Figure 15.1)** uses the counts tabulated in `docs/results_report.md` §2.3 (Run 1, original dev set). They were produced by earlier analysis code and were not recomputed for this report.
- **Label-quality audit rates** (73 %, 33 %, about 9 % major errors) come from AI-assisted inspections recorded in `docs/phase1_labels.md` and `data/reports/`; they are small samples, not human annotation.
- **Phase 4–7.5 functional results** were taken from the saved reports; the batteries were not re-run for this report (the full test suites were).
- **Literature numbers.** MailEx (authors, venue, dataset statistics, Table 2 F1 values), Smart To-Do (BLEU 0.23, ROUGE 0.63) and Zhong & Chen (1.7–2.8 F1 gains, typed markers) were checked against the papers online during writing. The CoNLL-2003 figures for Lample et al. (90.94) and BERT ("around 92") and the DistilBERT size/speed claims are standard results quoted from memory of the original papers and were not re-fetched.
- **Bibliography.** All entries are real publications; page numbers and DOIs for entries other than MailEx, Smart To-Do and Zhong & Chen were not re-checked online.

## 5. Screenshots and logs

- All ten screenshots were captured on 2026-11-17 by `scripts/capture_screenshots.mjs` from the running application with the real checkpoints, on a separate scratch database. Messages are controlled examples (fictional team members of this project). No mock-ups were used; images were only cropped.
- `figures/screenshots/terminal_server_log.txt` and `terminal_capabilities.json` are verbatim excerpts of that session (ports removed).
- No credentials, API keys, e-mail addresses or private data appear in screenshots, logs or code excerpts. The MailEx examples quoted are from the public Enron-derived corpus.

## 6. Unresolved limitations (also stated in the report)

1. No human-verified GOLD labels exist; every score is agreement with provisional labels or developer fixtures.
2. Models were trained and selected with the 39 leaked development emails present; only scoring is deduplicated.
3. Single seed per configuration; checkpoint selection on the reported set; no test-set result.
4. The application loads the SILVER-v2 entity checkpoint, not the stronger Phase 2 Run 1 checkpoint.
5. (Resolved) The cover now names the faculty guide, Prof. S. C. Shrawne; no placeholders remain.
