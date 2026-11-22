# Phase 4 — Temporal normalisation, identity resolution, uncertainty (PROVISIONAL)

Functional checks on SILVER/MailEx-derived data: train+validation only, **test split never read**, no human-reviewed labels.
Nothing below is accuracy against human judgement. Raw numbers: `report.json`. Relation model: `relations-markers_sqrt` (Phase 3, uncalibrated softmax scores).

## 1. Temporal normaliser
- **Fixtures:** 102 / 102 hand-authored cases pass (`tests/fixtures/temporal_cases.json`). These are functional regression tests I wrote, **not an independent benchmark**; they cover relative dates, timezones/DST, missing anchor/year, same-weekday ambiguity, EOD convention, ranges, event conditions and vague terms.
- **Real corpus spans** (606 TEMPORAL spans, 459 distinct, train+validation):

| status | no timestamp (corpus reality) | illustrative anchor 2001-11-15 |
|---|---|---|
| RESOLVED | 1.3% | 40.1% |
| UNRESOLVED_NO_ANCHOR | 32.5% | – |
| PARTIAL (time-only, year/date missing) | 19.5% | 10.2% |
| UNRESOLVED_EVENT_CONDITION | 17.7% | 17.7% |
| AMBIGUOUS (lists, same-weekday) | – | 3.6% |
| VAGUE | 1.2% | 1.2% |
| UNPARSEABLE | 27.9% | 27.2% |

  **No record in the corpus has a message timestamp**, so only 1.3% of spans resolve on real data. The anchored column uses a made-up date purely to exercise the relative-date paths. 52% of spans need an anchor or a year.
- **Unparseable (27%)** is mostly annotation noise ("the", "process", "proposals"), durations ("1 hr", "all day"), past-relative phrases ("a few weeks ago"), holidays ("Thanksgiving") and idioms. They are deliberately left unresolved. The top 40 are in `report.json` for grammar review.

## 2. Identity resolution and candidates (validation, 249 task candidates, low-trust MailEx registry)
Assignee: UNASSIGNED 141 (no evidence 119, "we" 17, several recipients 5), RESOLVED 25, UNKNOWN_PERSON 25, RESOLVED_SENDER 22 (first-person commitment), AMBIGUOUS 19 (all `multiple_assignees`), RESOLVED_RECIPIENT 17 (single addressee). Only 3 matched by unique name token.
The registry is parsed from noisy MailEx headers, so UNKNOWN_PERSON is inflated by it. In the app, Phase 7 supplies clean participants.

## 3. Flags and review
- **Review rate: 90%** of candidates carry at least one non-info flag. This is high because the SILVER task spans include many non-actionable ones (NO_ASSIGNEE on 136) and the two linkers disagree on 35% of tasks (MODEL_DISAGREEMENT 88). It reflects the current extraction quality, not a tuned threshold.
- Other flags (no-anchor run): WEAK_RELATION_SCORE 52, DATE_UNRESOLVED_NO_ANCHOR 25, UNKNOWN_PERSON 25, MULTIPLE_ASSIGNEES 19, DATE_UNPARSEABLE 19, DATE_EVENT_CONDITION 11, **DATE_RELATION_CONFLICT 9**, COMPETING_DATES 8, DATE_PARTIAL 7.
- **Deadline/scheduled conflict:** 9 links the model called SCHEDULED_ON carried a deadline cue ("by", "before"...). They were proposed as `due`, flagged, and the model label was kept in `provenance.label_reinterpretations`; nothing was overwritten silently.
- With a (made-up) timestamp but no timezone, 31 values also get an info-level TZ_ASSUMED.

## 4. Relation-score threshold (validation, SILVER, thread-bootstrap CIs in `report.json`)
| min score | links kept | precision | recall |
|---|---|---|---|
| none | 100% | 0.759 | 0.769 |
| 0.7 | 82% | 0.842 | 0.700 |
| 0.8 | 77% | 0.872 | 0.681 |
| **0.9** | **68%** | **0.945** | **0.650** |
| 0.95 | 66% | 0.944 | 0.631 |
| 0.99 | 41% | 0.955 | 0.400 |

Default `min_relation_score = 0.9` (provisional, chosen on validation only; `configs/phase4.json`). It only **flags** weak links for review; no link is dropped. Scores are uncalibrated.

## Limitations
- Corpus has no timestamps; resolved-date behaviour is verified only by fixtures and the illustrative run.
- Grammar is rule-based: unparseable spans stay unparseable (listed), and conventions (ISO weeks, business-hours am/pm, EOD = 17:00, US m/d/y) are assumptions that are recorded per value and flagged at info level.
- MailEx-derived registry is low-trust. Group assignees and multiple assignees are not supported and always go to review.
- DEPENDS_ON stays a rule-only, proposed path (unit-tested, not evaluated).
- No human-reviewed GOLD data was used; all rates are agreement/behaviour on SILVER, not accuracy.
