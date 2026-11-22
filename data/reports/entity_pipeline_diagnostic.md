# Text2Task entity-pipeline diagnostic

This is a pre-retraining diagnostic. All reviewed corrections remain SILVER and are stored separately; no original or finalized annotation was modified or promoted to GOLD.

## Structural evidence

- Training rows: 704; validation rows: 101.
- 478 rows in 224 groups share the same base text/window across BIO layers.
- After inserting `[unusedN]`, every multilayer input is distinguishable: **True**.
- Marker IDs are [1, 2, 3, 4, 5, 6, 7, 8] and all round-trip to their corresponding `[unusedN]` token.
- Stored label mapping and model `label2id` agree: **True**.
- Export: 101 rows, 12524 positions, 3358 reference non-O, 34 predicted non-O.
- Predicted BIO prefixes: B=0, I=34. The absence of B predictions makes the decoded entity sequences structurally invalid/near-empty.

The marker position is assigned label `-100`, so it is intentionally absent from prediction/reference exports. Training and unseen inference both insert it immediately after `[CLS]`.

## Manual 30-record SILVER audit

Severity counts: {'acceptable': 2, 'major': 22, 'minor': 6}. Original TASK spans: 107; conservative corrected diagnostic TASK spans: 60.

| # | Source record | Severity | Finding |
|---:|---|---|---|
| 1 | `mailex:train:haedicke-m_inbox_58:turn_0000` | major | Historical filing was mislabeled TASK; pronoun-only `We` was a TASK; actionable service/request spans need cleaner boundaries. |
| 2 | `mailex:train:mclaughlin-e_inbox455:turn_0001` | major | Historical call, dispute, and agreement were TASK; current imperatives were missed. |
| 3 | `mailex:train:keiser-k_inbox148:turn_0000` | major | Nested duplicates and an ARTIFACT labeled TASK; passive deadline wording has a poor TASK boundary. |
| 4 | `mailex:train:blair-l_inbox_187:turn_0002` | major | Historical sending and status update were TASK; future contingent work is the actionable content. |
| 5 | `mailex:train:corman-s_inbox_archives445:turn_0000` | major | Past ticket receipt/discovery were TASK; planned attendance/request should be retained. |
| 6 | `mailex:train:mccarty-d_inbox_alaska_gas_103:turn_0002` | minor | Submission and edit requests are actionable, but the second edit is one excessively broad TASK span. |
| 7 | `mailex:train:wolfe-j_inbox260:turn_0000` | major | Automated historical card delivery was TASK while explicit user instructions were omitted. |
| 8 | `mailex:train:lavorato-j_inbox196:turn_0001` | major | `Top` was PERSON and attached-list question had overlapping/broad labels. |
| 9 | `mailex:train:mims-thurston-p_inbox39:turn_0001` | major | Duplicate nested TASK spans for one request; temporal expression omitted. |
| 10 | `mailex:train:hernandez-j_inbox72:turn_0001` | major | Job-search states, speech, and pronoun `I` were TASK; direct imperatives are cleaner targets. |
| 11 | `mailex:train:whitt-m_inbox810:turn_0000` | major | Reported market states and directives were TASK; social planning is ambiguous and direct invitation was missed. |
| 12 | `mailex:train:reitmeyer-j_inbox365:turn_0000` | major | Past referral/deal/information events were TASK; the concrete setup request was missed. |
| 13 | `mailex:train:derrick-j_inbox226:turn_0001` | major | Past negated review and bare `approve it` were TASK; mandatory future re-review is valid. |
| 14 | `mailex:train:nemec-g_inbox856:turn_0000` | major | Completed date change and document-description fragments were TASK/ARTIFACT; future commitments are usable. |
| 15 | `mailex:train:blair-l_inbox_180:turn_0000` | major | System states and past disruption were TASK; investigation/request to proceed are actionable. |
| 16 | `mailex:train:steffes-j_inbox127:turn_0003` | acceptable | No actionable task was present; original empty annotation is semantically reasonable for TASK. |
| 17 | `mailex:train:derrick-j_inbox151:turn_0000` | major | Predicted corporate state and malformed question fragment were TASK; support/discussion requests are valid. |
| 18 | `mailex:train:nemec-g_inbox113:turn_0003` | minor | Negative recommendation is actionable but requires negation-aware treatment. |
| 19 | `mailex:train:martin-t_inbox211:turn_0002` | minor | Core scheduled work is sound; request to report inability/questions was under-annotated. |
| 20 | `mailex:train:ybarbo-p_inbox53:turn_0000` | major | `Friday` was TASK and `on` TEMPORAL; scheduling request itself is valid. |
| 21 | `mailex:train:whitt-m_inbox372:turn_0000` | minor | Core requests are valid; first TASK improperly absorbs its temporal phrase. |
| 22 | `mailex:train:steffes-j_inbox101:turn_0001` | major | Presentational `here is the list` is not an actionable TASK. |
| 23 | `mailex:train:parks-j_inbox572:turn_0002` | minor | No task is appropriate, but the explicit date was omitted as TEMPORAL. |
| 24 | `mailex:train:parks-j_inbox153:turn_0000` | major | Historical `called` and vague `I'm in` were TASK; proposed attendance is the planned action. |
| 25 | `mailex:train:nemec-g_inbox1129:turn_0000` | major | Completed signing/change and `attached docs` were TASK; current send/receipt actions remain. |
| 26 | `mailex:train:germany-c_inbox43:turn_0001` | major | Phone-number statement was TASK; questions may be requests but overlap policy needs explicit handling. |
| 27 | `mailex:train:lay-k_inbox843:turn_0000` | major | Facility states were labeled TASK and an organization was PERSON; these are events/states, not assigned work. |
| 28 | `mailex:train:cash-m_inbox154:turn_0001` | major | Historical rejection and descriptive list changes were TASK; direct request to advise is actionable. |
| 29 | `mailex:train:white-s_inbox331:turn_0002` | minor | Planned deployments are useful TASKs; attached-curves statement should not be a TASK. |
| 30 | `mailex:train:mann-k_inbox32:turn_0000` | acceptable | Boilerplate advertisement contains no actionable email task. |

## Clean diagnostic set

The single-layer diagnostic contains 20 source emails and 20 tokenizer windows. It uses TASK, PERSON and TEMPORAL only (plus `O` and BIO prefixes). Entity counts: {'PERSON': 32, 'TASK': 50, 'TEMPORAL': 24}.

This is a same-example memorization test, not a held-out evaluation. Its purpose is to verify that labels, inputs, gradients, and decoding can support learning before any full retraining.

Memorization results are written by `scripts/run_entity_memorization_test.py` to `results/entity_extraction/memorization_20/`.

## Runtime and optimization evidence

- All 805 train/validation model-ready rows round-trip through the configured DistilBERT tokenizer with no token-ID mismatch.
- Every stored string label maps to the expected integer ID; the data label map, saved model `label2id`, and inverse `id2label` agree.
- The eight layer markers are vocabulary IDs 1–8 and round-trip as `[unused0]` through `[unused7]`.
- Marker embeddings changed from the base checkpoint (delta norms 0.00325–0.01663), so the marker signal was not frozen.
- A backward pass produced nonzero gradient norms in the classifier (1.6247), first encoder query projection (0.0714), and `[unused0]` embedding (0.01537).
- The original run performed 132 optimizer steps. Logged loss fell from 8.3521 at step 10 to approximately 3.05–3.46 late in training; validation loss fell only from 0.9089 to 0.8512.
- Checkpoint 132 was selected because provisional SILVER entity F1 rose from 0 to 0.007767. This is a numerically correct selection but not evidence of useful extraction.
- Training positions are 76.82% `O`; only 3.52% are B-label positions. Layer 1 is 91.10% `O` and layer 2 is 95.37% `O`. `B-EVENT` occurs only four times in training.

The complete reproducible measurements are in `data/diagnostics/entity_pipeline/runtime_evidence.json`.

## Controlled 20-example memorization result

The diagnostic ran for 60 epochs (300 optimizer steps) on MPS with learning rate 1e-4 and batch size 4. It passed the predeclared entity-F1 threshold of 0.95:

- entity precision: 1.0
- entity recall: 1.0
- entity F1: 1.0
- token accuracy: 1.0
- final loss: 0.000459
- all B labels were recovered: 50 TASK, 32 PERSON, and 24 TEMPORAL
- first reached F1 1.0 at epoch 15
- classifier weight delta norm: 0.1571
- first encoder query-weight delta norm: 0.8392

This is deliberate same-example memorization. It is **not held-out accuracy**, **not a GOLD metric**, and says nothing about generalization. It establishes that the tokenizer alignment, labels, optimizer, model head, and decoding path can learn a clean single-layer subset.

## Identified causes and retraining decision

1. The layer mechanism is not silently collapsing inputs: `[unusedN]` makes duplicated layer rows mechanically distinguishable in both training and unseen inference.
2. Layering still worsens optimization: repeated text creates many extra `O` targets, higher layers are sparse, and rare marker embeddings receive far fewer updates.
3. The original three-epoch run underfit B labels. Independent token argmax has no BIO transition constraint, so it can emit `I-*` without a preceding `B-*`; that is exactly what happened for all 34 non-O predictions.
4. The largest issue is semantic label noise. In the deterministic audit, 22/30 records had major problems and 6/30 had minor problems. Historical events, completed actions, system states, descriptive artifacts, and malformed fragments were repeatedly labeled TASK.
5. The diagnostic proves learnability, so the mechanical gate for retraining is open. However, a full six-class retrain on the unchanged corpus was **not launched** because the semantic audit failed. Repeating full training would optimize known incorrect targets. Full retraining should use a versioned, reviewed correction set rather than silently changing or promoting the current SILVER data.

The original dataset remains unchanged. The separate corrections are still SILVER and are stored in `data/diagnostics/entity_pipeline/audit30_corrected_silver_v2.jsonl`.
