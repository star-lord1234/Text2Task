# Entity Extraction Execution Status

## Outcome

**Provisional SILVER training completed successfully. GOLD evaluation remains blocked.**

The explicit `provisional_silver` mode trained DistilBERT using valid SILVER annotations and used SILVER validation only for debugging and provisional checkpoint selection. Every metric produced by this mode is tagged `silver_provisional`, carries `is_final_research_metric: false`, and is not a human-grounded research result.

The separate `gold_evaluation` mode retains the strict provenance gate. It was executed and correctly stopped because 0/60 validation emails are independently human-reviewed GOLD. No SILVER annotation or provenance field was changed to GOLD.

## Environment and execution

- Hardware: Apple M5 MacBook Air, 16 GB memory
- Acceleration: Apple Silicon MPS built, available, and used by the completed run
- Virtual environment: `.venv` with Python 3.12.13
- PyTorch 2.15.0; Transformers 5.22.1; Accelerate 1.15.0; Datasets 4.8.5; seqeval 1.2.2
- Model: `distilbert/distilbert-base-uncased`
- Seed/data seed: 20261101
- Learning rate: 2e-5
- Epochs: 3
- Per-device batch size: 4
- Gradient accumulation: 4
- Weight decay: 0.01
- Windowing: 512 WordPieces with stride 64, keeping complete entity spans where possible
- Overlaps: deterministic annotation layers retained with `[unusedN]` layer markers
- Optimizer steps: 132
- Training runtime: 78.62 seconds on MPS
- Training loss: 3.7660
- Selected checkpoint: `checkpoint-132`

Input hashes recorded before and after execution are identical (`annotation_inputs_unchanged: true`). Existing cross-split thread, BIO, span reconstruction, tokenizer alignment, and overlap-layer checks all remained active.

## Provisional SILVER validation

These figures are development signals only:

| Metric | SILVER/provisional value |
|---|---:|
| Entity precision | 0.080000 |
| Entity recall | 0.004082 |
| Entity F1 | 0.007767 |
| Token accuracy | 0.731795 |

Per-entity results:

| Entity | Precision | Recall | F1 | SILVER support |
|---|---:|---:|---:|---:|
| ARTIFACT | 0 | 0 | 0 | 59 |
| GROUP | 0 | 0 | 0 | 11 |
| PERSON | 0 | 0 | 0 | 63 |
| TASK | 0 | 0 | 0 | 283 |
| TEMPORAL | 0.20 | 0.027027 | 0.047619 | 74 |
| EVENT | n/a | n/a | n/a | 0 |

The high token accuracy is dominated by the `O` class and must not be interpreted as useful extraction accuracy. The entity F1 and qualitative predictions show that this first provisional model is not yet reliable.

## Five unseen-message checks

- `unseen-001`: predicted TASK spans `the` and `report to`, plus TEMPORAL `3 PM`; it missed the person, artifact, and other temporal evidence.
- `unseen-002`: predicted partial TASK spans `schedule the` and `meeting`; it missed the person, artifact, temporal span, and prerequisite evidence.
- `unseen-003`: predicted no entities.
- `unseen-004`: predicted no entities.
- `unseen-005`: predicted TASK `investigation`, an incorrect boundary/type for the example.

Across these examples the model predicted five TASK spans and one TEMPORAL span, and no PERSON, GROUP, EVENT, or ARTIFACT spans. These outputs were inspected as model-development diagnostics, not evaluation results.

## Provenance boundary

- Provisional model weights, checkpoints, logs, predictions, and metrics are under `models/text2task-distilbert/provisional_silver/` and `results/entity_extraction/provisional_silver/`.
- The GOLD evaluation block record is under `results/entity_extraction/gold_evaluation/`.
- Final research metrics remain unavailable until independently human-verified GOLD validation/test records exist.
- No relation-classifier work was started.

## SILVER-v2 repair and three-class retraining (2026-11-02)

The versioned repair/retraining workflow completed. A local full-corpus LLM run
was attempted but stopped after more than four hours at 44 valid outputs and 19
unique failures; the complete 450-record v2 corpus therefore uses explicit
audit/validated-LLM/conservative-filter provenance. The new independent
30-record SILVER inspection improved from 22 to 10 major errors, but remains
insufficient for research-quality claims.

Three actual MPS runs were saved under
`models/text2task-distilbert/entity_v2_three_class/` and
`results/entity_extraction/entity_v2_three_class/`:

- unweighted epoch 3: SILVER/provisional F1 `0.019185`, zero B predictions;
- unweighted epoch 6: SILVER/provisional F1 `0.046263`, 9 B predictions;
- square-root weighted epoch 3: SILVER/provisional F1 `0.127021`, 327 B
  predictions, but TASK F1 only `0.004219`.

The weighted model is the strongest pipeline diagnostic for PERSON/TEMPORAL,
not a reliable TASK model. GROUP/ARTIFACT/EVENT expansion was deferred because
v2 coverage is absent or insufficient. GOLD evaluation remains blocked and no
relation classifier was started.
