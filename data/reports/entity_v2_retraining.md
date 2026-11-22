# Text2Task entity SILVER-v2 repair and retraining report

## Executive outcome

The versioned three-class pipeline ran end to end, but it did **not** establish a
reliable research-quality TASK extractor. The best development experiment is the
three-epoch square-root class-weighted run with SILVER/provisional entity F1
`0.1270`. It recovered BIO boundaries, but TASK F1 is only `0.0042` and a fresh
30-record inspection still found 10 major annotation errors. These values are
development diagnostics, not human-grounded accuracy.

No annotation was promoted to GOLD. The original train/dev/test JSONL hashes are
unchanged, no test record was used for prompting or filter fitting, and the strict
GOLD evaluation gate remains active.

## Phase 1: guideline correction

- `docs/annotation_guidelines_v2.md` defines TASK as a current request, future
  commitment, prohibition, cancellation/update, or concrete plan.
- It separates completed history, descriptions, system states, attachment
  presentation, temporal expressions, negation, modality, and uncertainty.
- It contains 30 difficult cases derived exclusively from the training-split
  diagnostic audit.
- `configs/annotation_prompt_v2.md` is the full-schema prompt.
- `configs/entity_annotation_prompt_v2.md` is the three-class prompt, version
  `text2task-entity-v2.0.2`, and includes all 30 audit-derived lessons.
- `src/annotation/semantic_quality.py` quarantines severe historical,
  descriptive, fragmentary, nested, and unresolved-completion cases. It never
  silently changes semantic labels.

## Phase 2: versioned SILVER v2

### Local LLM attempt

The local `llama3.1:latest` run was genuinely executed. Strict full-schema pilots
were not usable: the first pilot produced 1 valid record and 12 failures; a JSON
pilot produced no valid records before it was stopped. The simplified exact-span
run produced 44 valid records and 19 unique failed records, but required more than
four hours to reach only a small part of the 450-record corpus. It was stopped as
operationally non-viable. Partial successes and every failure remain under
`data/annotations/silver_v2_entities_v202/`; none is represented as a completed
full-corpus LLM run.

### Reproducible hybrid completion

`scripts/build_silver_v2_hybrid.py` assembled all 450 original training emails
with deterministic precedence:

1. 30 corrected diagnostic-audit records;
2. 41 validated and eligible local-LLM records not superseded by the audit;
3. 379 records repaired conservatively from SILVER-v1.

The fallback TASK filter was fitted only on 107 original TASK candidates from the
30 training audit records (47 keep, 60 reject). At threshold `0.65`, grouped
five-fold diagnostic results were keep precision `0.8125`, keep recall `0.5532`,
and keep F1 `0.6582`. This is an annotation-repair diagnostic, not held-out model
accuracy. Strong explicit action cues can override the statistical filter;
historical/descriptive rules can veto it. All rejected spans, overlap resolutions,
probabilities, and sources are stored in
`data/annotations/silver_v2_hybrid/correction_log.jsonl`.

Hybrid corpus results:

- 450 emails and 364 threads, all original `train` members;
- 446 records pass automatic single-layer semantic gates;
- 661 TASK, 430 PERSON, and 482 TEMPORAL spans before model-data audit overrides;
- 655 low-confidence TASK candidates rejected;
- 274 candidates rejected by semantic-quality rules;
- 18 overlaps resolved and logged;
- annotation tier is SILVER and `human_verified=false` for every record.

### New 30-record quality inspection

The deterministic seed-`20261102` sample excludes the 30 prompt-development
records. AI-assisted manual inspection found:

- 8 acceptable records;
- 12 records with minor errors;
- 10 records with major errors.

The original v1 diagnostic sample had 2 acceptable, 6 minor, and 22 major errors.
The major-error count therefore fell from 22 to 10, but a one-third major-error
rate remains too high for final claims. Examples of remaining failures include a
historical `has not returned my call` span retained as TASK, omitted direct
requests, missing deadlines, and incomplete PERSON/TEMPORAL coverage. Full
record-level decisions are in `data/reports/silver_v2_audit30.jsonl` and
`data/reports/silver_v2_audit30.md`.

## Phase 3: single-layer three-class data

`scripts/build_entity_dataset_v2.py` generated one BIO layer with labels `O`,
`B/I-TASK`, `B/I-PERSON`, and `B/I-TEMPORAL`. The overlap rule is: shortest exact
span wins; ties prefer PERSON, then TEMPORAL, then TASK; every drop is logged.

Model-ready data:

- training: 449 emails, 363 threads, 449 rows, 659 TASK, 428 PERSON, 481 TEMPORAL;
- validation: 60 untouched SILVER-v1 dev emails, 51 threads, 60 rows, 272 TASK,
  63 PERSON, 73 TEMPORAL;
- no train/validation thread overlap;
- maximum sequence length is 475 WordPieces, so no record required a second
  window in this selected corpus;
- all 84 project tests passed before training.

Training BIO positions were `45,425 O`, `659 B-TASK`, `5,519 I-TASK`,
`428 B-PERSON`, `338 I-PERSON`, `481 B-TEMPORAL`, and `1,477 I-TEMPORAL`.
This severe boundary imbalance explains the unweighted model's B-label collapse.

## Phase 4: actual training and provisional evaluation

All runs used `distilbert/distilbert-base-uncased`, MPS, seed `20261101`, learning
rate `2e-5`, batch size 4, gradient accumulation 4, and weight decay `0.01`.

### V2 unweighted, three epochs

- provisional precision `0.4444`, recall `0.0098`, F1 `0.0192`;
- predicted B labels: `0`;
- only TEMPORAL had nonzero entity F1 (`0.0976`).

### V2 unweighted, six epochs

The additional run was justified by decreasing validation loss and rising F1 at
epoch 3. Its best/final epoch was 6:

- provisional precision `0.0844`, recall `0.0319`, F1 `0.0463`;
- PERSON F1 `0.0909`, TASK F1 `0.0109`, TEMPORAL F1 `0.1240`;
- 9 predicted B labels: 3 PERSON and 6 TEMPORAL; no B-TASK.

### V2 square-root inverse-frequency loss, three epochs

This was saved as a separate imbalance diagnostic. Weights are recorded in the
metrics file; annotations were not changed.

- provisional precision `0.1201`, recall `0.1348`, F1 `0.1270`;
- PERSON: precision `0.2481`, recall `0.5079`, F1 `0.3333`, support 63;
- TASK: precision `0.0050`, recall `0.0037`, F1 `0.0042`, support 272;
- TEMPORAL: precision `0.1732`, recall `0.3014`, F1 `0.2200`, support 73;
- predicted B labels: 327 (`129 PERSON`, `100 TASK`, `98 TEMPORAL`).

Predicted BIO positions were `6,231 O`, `129 B-PERSON`, `100 B-TASK`,
`98 B-TEMPORAL`, `182 I-TASK`, and `227 I-TEMPORAL`; it predicted no I-PERSON.
References were `4,425 O`, `63 B-PERSON`, `272 B-TASK`, `73 B-TEMPORAL`,
`53 I-PERSON`, `1,886 I-TASK`, and `195 I-TEMPORAL`.

Compared with the six-class v1 provisional F1 `0.0078`, the best three-class
development F1 is higher by `0.1193`. This is not a controlled annotation-only
comparison: the label set, layer representation, annotations, and loss differ.
The validation data is SILVER in both cases.

### Five unseen messages

The weighted model extracted a plausible TASK and TEMPORAL from a direct sending
request and a planned meeting. It correctly avoided TASK on a completed-audit
example, but falsely labeled `The` as TASK in a historical filing example,
missed named people in two requests, split `for` from `next week`, and dropped
negation/object context from `Do not publish the release notes`. The raw outputs
are in `results/entity_extraction/entity_v2_three_class/unseen_predictions.jsonl`.

## Phase 5: class expansion decision

GROUP, ARTIFACT, and EVENT were not added. SILVER-v1 validation provides only 11
GROUP examples, 59 ARTIFACT examples, and 0 EVENT examples, while no complete
SILVER-v2 repair exists for those classes. The original six-class model scored
zero F1 for GROUP and ARTIFACT and had no EVENT support. Training another
six-class model would force unsupported labels and was therefore deferred.

## Integrity and research boundary

- Original final hashes remain: train `8c2f0710...a53`, validation
  `184bd076...2b2`, test `516cd5fa...c85b`.
- The test split was not read for prompting, filter fitting, checkpoint choice,
  or this provisional evaluation.
- Validation is SILVER-v1 and all reported metrics are provisional.
- Human-GOLD metrics remain unavailable; strict final evaluation must continue
  to block until independently reviewed GOLD validation/test records exist.
- The weighted model is useful as a pipeline diagnostic, not a reliable final
  TASK extractor.
