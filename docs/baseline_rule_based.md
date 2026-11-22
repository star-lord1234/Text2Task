# Rule-based baseline (E1, span extraction)

Code: `src/baselines/rule_based.py` · Score: `python scripts/evaluate_rule_baseline.py --split validation` · Tests: `tests/test_rule_based.py` (8) · Output: `results/entity_extraction/baseline/rule_based_E1_validation.json`

## What it does
No learning and no MailEx labels. Regex and word lists only.

| Type | Rules |
|---|---|
| TEMPORAL | Weekdays, months with day numbers, numeric dates, clock times, `today/tomorrow/tonight/yesterday/EOD/COB`, `next/last/this + unit or weekday`, `end of day/week`. Bare `may`, `sat`, `sun`, `mar` are ignored unless capitalized. |
| PERSON | Capitalized name after a person cue (`ask, tell, call, contact, cc, thanks, hi, dear, meet, with, notify`) or in a salutation (`Kim,`). A stop list removes pronouns, weekdays, common words and all-caps words. |
| TASK | `please/pls/kindly + ...`; `can/could/would/will you ...`; `let me know`; clause-initial imperative verbs (about 100 verbs); `I/we will/'ll/going to/need to/must/should + verb`; bare `will/'ll + verb` (not `will be/have/not`). Span runs to the end of the sentence, capped at 14 words, and is cut before any date it contains. |

Rules were designed and tuned only on the **train** split (a few variants compared there). The dev set was scored once, after the rules were frozen.

## Results (dev set, 391 rows, same rows and metrics as the neural runs)

| Type | Support | Strict F1 | Lenient F1 | Overlap-any F1 | Token F1 |
|---|---:|---:|---:|---:|---:|
| TASK | 234 | 0.179 | 0.399 | 0.494 | 0.430 |
| PERSON | 169 | 0.289 | 0.289 | 0.289 | 0.280 |
| TEMPORAL | 130 | 0.348 | 0.487 | 0.539 | 0.512 |
| **Overall** | 533 | **0.259** | **0.402** | **0.461** | **0.433** |

Train scores are close (lenient 0.386), so the rules are not fitted to the training split.

## Comparison with the neural tagger (Phase 2, run 1: lr 5e-5, best checkpoint)

| Type | Rules: lenient | Neural: lenient | Rules: strict | Neural: strict |
|---|---:|---:|---:|---:|
| TASK | 0.399 | 0.508 | 0.179 | 0.286 |
| PERSON | 0.289 | 0.612 | 0.289 | 0.594 |
| TEMPORAL | 0.487 | 0.656 | 0.348 | 0.468 |
| **Overall** | 0.402 | **0.575** | 0.259 | **0.420** |

The neural tagger wins on every type. The gap is smallest for TASK (about 0.11 lenient) and largest for PERSON (about 0.32): names need more than a capitalization rule.

## Caveats
- **The references are incomplete**, so the rules look worse than they are on precision. Many "false positives" are real dates and requests that MailEx never labeled (for example `June 8th`, `yesterday`). The neural model has learned MailEx's labeling habits (mostly event arguments only), which gives it an advantage on this reference. Treat the gap as an upper bound on the true benefit.
- **This is only the span-extraction part of E1.** The plan's §7 also asks for assignee linking, nearest-date linking and dependency cues (`after`, `once`, `only if`). Those need the relation labels and are not implemented.
- **No failure log by category yet** (multiple dates, implicit actors, negation, quoted replies), which §7 also asks for.
- Metrics are provisional and based on MailEx-derived labels (see `docs/phase1_labels.md`).
