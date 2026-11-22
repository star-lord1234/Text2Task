# Text2Task: final metrics

Every quality number below is agreement with **provisional SILVER labels** (MailEx-derived) or the outcome of **developer-written functional checks**.
None is human-verified accuracy: no GOLD evaluation exists, so none of these are final research results.
Sources: `results/entity_extraction/`, `results/relation_extraction/`, `results/phase4`–`phase6/report.json`, `results/phase7_5/` (all saved files; nothing recomputed here).

## 1. Entity model (the checkpoint the app uses)
DistilBERT, three classes (TASK, PERSON, TEMPORAL), `entity_v2_three_class/epoch3_sqrt_weighted`.
Entity-level seqeval on SILVER-v2 validation:

| type | precision | recall | F1 | support |
|---|---|---|---|---|
| all (micro) | 0.120 | 0.135 | **0.127** | 408 |
| PERSON | 0.248 | 0.508 | 0.333 | 63 |
| TASK | 0.005 | 0.004 | **0.004** | 272 |
| TEMPORAL | 0.173 | 0.301 | 0.220 | 73 |

Earlier runs, scored as lenient span matching (IoU ≥ 0.5) on a different label set, so **not directly comparable**:

| run | strict F1 | lenient F1 |
|---|---|---|
| lr 5e-5 (full labels) | 0.420 | 0.575 |
| lr 3e-5 | 0.409 | 0.556 |
| requests-only labels | 0.398 | 0.572 |
| rule baseline (E1) | 0.259 | 0.402 |

The model is clearly weak on TASK spans.

## 2. Relation model (`relations-markers_sqrt`, validation, reference spans)

| label | precision | recall | F1 | support |
|---|---|---|---|---|
| ASSIGNED_TO | 0.65 | 0.75 | 0.69 | 79 |
| DUE_ON | 0.71 | 0.50 | 0.59 | 10 |
| SCHEDULED_ON | 0.92 | 0.83 | 0.87 | 71 |

- Micro F1 **0.764** (95% CI 0.70–0.84); macro F1 **0.719** (0.62–0.82). Rule baseline: 0.527 micro, 0.517 macro.
- False-link rate on unlinked pairs: 4.6%.
- With predicted spans instead of reference spans: F1 0.000 strict, 0.024 lenient. This mostly reflects mismatched span definitions between references and the entity model, not relation quality.
- The DUE_ON figure rests on 10 examples and is noisy. There is no neural DEPENDS_ON class.

## 3. Rule-based stages (functional checks; no accuracy labels exist)

| stage | result |
|---|---|
| Temporal and owner resolution (Phase 4) | 102/102 hand-written fixtures. On the real corpus only 1.3% of date spans resolve (no message timestamps exist); 27% are unparseable. |
| Reconciliation (Phase 5) | 43/43 original scenarios, now 91/91 with the later fixtures; 12,000 fuzz steps, 0 invariant violations. |
| Dependency graph (Phase 6) | 15/15 graph and 3/3 chat scenarios; 12,000 oracle edit checks, 0 violations. |

## 4. Whole system, live (Phase 7.5)
Short chat messages written by the developer. A simulated reviewer accepted every actionable proposal. "Strict pass" means every expected task, owner, due day, status and edge is present and nothing extra.

| strict pass | neural only | **hybrid (default)** | rule only |
|---|---|---|---|
| Original battery (24) | 2 | **23** | 20 |
| New scenarios (34) | 7 | **28** | 28 |
| Holdout (30) | 7 | **23** | 22 |

| hybrid vs neural only | original | new | holdout |
|---|---|---|---|
| task recall | 0.26 → 1.00 | 0.17 → 0.97 | 0.09 → 0.91 |
| false tasks | 29 → 0 | 40 → 1 | 27 → 3 |
| dependency edges recovered | 0/7 → 7/7 | 0/7 → 5/7 | 0/6 → 2/6 |
| false edges | 0 → 0 | 0 → 1 | 0 → 0 |

- Dependencies overall: 14 of 20 expected edges (hybrid) vs 0 of 20 (neural only); 1 false edge.
- Due-date accuracy (of found tasks that expected one): 0.00 → 0.83 and 0.00 → 0.80 on the first two sets; 1.00 on the holdout for both configurations.
- Lifecycle status accuracy (hybrid): 1.00 / 0.88 / 0.86.
- No case that passes with neural only fails with hybrid.

**Real email text** (60 SILVER validation emails; lenient entity agreement, F1):

| span type | neural | refined | hybrid |
|---|---|---|---|
| overall | 0.203 | 0.232 | 0.255 |
| TASK | 0.055 | 0.061 | 0.114 |
| PERSON | 0.385 | 0.415 | 0.415 |
| TEMPORAL | 0.380 | 0.404 | 0.404 |

**Review load on those emails** (proposals only, no labels): neural only 143 creations (2.42 per email); refined 81; hybrid 96 creations + 3 dependencies (1.68 per email).

## 5. Tests
Backend 352 passed, frontend 88, Playwright 20 (including real-model runs).

## Caveats
- Everything above is SILVER or developer-written; not one number is human-verified accuracy.
- **Hybrid ≈ rule only** on chat. The rules and verb lexicon do most of the work, so hybrid's score is not evidence that the neural entity model is good.
- Fixtures use the author's own phrasing, so chat figures are optimistic for real conversation.
- The new scenarios were used to find bugs; only the holdout set was unseen when first run.
- Known misses and false positives are listed in `results/phase7_5/REPORT.md`. Full tables are in `results/phase7_5/COMPARISON.md`.
