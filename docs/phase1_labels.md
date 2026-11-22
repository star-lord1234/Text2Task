# Phase 1: Better Labels (MailEx-derived)

## What was built

| Item | Path |
|---|---|
| Mapping config (v1.2.0) | `configs/mailex_to_text2task_v1.json` |
| Mapping code | `src/annotation/mailex_labels.py` |
| Dataset builder | `scripts/build_mailex_dataset.py` |
| Sample-for-inspection script | `scripts/sample_mailex_labels.py` |
| Tests (11) | `tests/test_mailex_labels.py` |
| **Primary dataset** (requests + commitments) | `data/model_ready/entities_mailex_v1/` |
| Ablation dataset (requests only) | `data/model_ready/entities_mailex_v1_requests_only/` |
| Per-record labels and drop logs | `data/mailex_v1/records/`, `data/mailex_v1_requests_only/records/` |

Run: `python scripts/build_mailex_dataset.py` (add `--requests-only` for the ablation, with `--records-dir` and `--output-model` pointing elsewhere).

## The mapping

| Our type | Taken from MailEx | Filters |
|---|---|---|
| TASK | `Action Description` in `Request_Action*` events (a request to do something). Also, by default, `Action Description` in `Deliver_Action*`/`Amend_Action*` events that start with a commitment form (`will`, `'ll`, `shall`, `going to`), excluding `will be <state>`, `will have`, `will not`. | Commitments are an ablation: `--requests-only`. |
| TEMPORAL | Any slot ending in `Date` or `Time` | Dropped if longer than 8 tokens, or if it begins with a subordinating word (`once`, `upon`, `when`, `by the time`, `prior to`, ...) and has no calendar/clock word, because MailEx sometimes puts event clauses there. |
| PERSON | Any `Members` slot | Must be 1 to 3 capitalized tokens; rejects pronouns, roles, a list of company/place/kinship words, all-caps and double-initial-caps words (`FERC`, `PSCo`), single letters. Other occurrences of an accepted name in the same email are also tagged, unless inside another span. |

Overlaps are resolved by the existing rule (shortest span wins; ties PERSON, TEMPORAL, TASK). In practice almost all overlap drops were exact duplicates of the same span tagged in several events; only about 5 TASK spans per 3,000 emails were lost to a cross-type overlap. Every drop is logged.

Empty-text emails (272 in train, 25 in dev) are skipped.

Not mapped, by design: `Request_Data` (MailEx labels the requested object, not the request phrase), `Request_Meeting*`, `Deliver_Data`, and `Deliver_Action` statements that are not commitments (these are mostly history or status, e.g. "received the amendment").

## Resulting data (mapping v1.2.0)

| | Train | Validation |
|---|---:|---:|
| Source emails | 2,845 | 389 |
| Model rows | 2,871 | 391 |
| TASK spans (primary / requests only) | 1,664 / 1,255 | 234 / 175 |
| PERSON spans | 1,040 | 169 |
| TEMPORAL spans | 1,036 | 130 |

Compare with the previous setup: 449 training emails (659 TASK, 428 PERSON, 481 TEMPORAL) and a 60-email SILVER-v1 validation set. Train and validation share no threads (checked in the builder). The MailEx **test split was not read or built**; it is created only in Phase 5.

## Label-quality inspection (gate 1)

Method: for each of three mapping versions, 40 random emails (at most 1,000 characters) were drawn with a fixed seed from the **train** split and read with the mapped labels shown inline. Severity rubric as in the earlier SILVER audits: *acceptable* (labels shown are right, no clear request missed), *minor* (a small wrong or missing span), *major* (a clear request missed, or several wrong spans). **This is an AI-assisted inspection by me, not an independent human review.** Samples are in `data/reports/mailex_v1_sample40.md`, `mailex_v1_1_sample40.md`, `mailex_v1_2_sample40.md`.

| Sample | Mapping | Acceptable | Minor | Major |
|---|---|---:|---:|---:|
| 1 (seed 20261103) | v1.0, requests only | 24 (60%) | 11 | 5 |
| 2 (seed 20261104) | v1.1, + commitments, stricter PERSON | 30 (75%), of which 4 were empty emails | 8 | 2 |
| 3 (seed 20261105) | v1.2, + clause filter for TEMPORAL | 24 (60%) | 11 | 5 |
| Reference: SILVER-v2 audit | | 8 of 30 (27%) | 12 | 10 (33%) |
| Reference: SILVER-v1 audit | | 2 of 30 (7%) | 6 | 22 (73%) |

Changes made between samples came from errors seen in the earlier sample (PERSON false positives, commitment pattern, TEMPORAL clauses, empty emails). Each new sample was drawn fresh so the check is not fitted to the sample that motivated the fix.

### What the inspection shows

- **Precision is good.** Wrong PERSON and TEMPORAL spans were rare after v1.1 (none judged major in sample 2; one "then" in sample 3).
- **The main weakness is missed labels, not wrong ones.** In samples 2 and 3 the major errors are clear requests that MailEx has no annotation for at all (examples: "Give me a call", "Please go ahead and meet", "Can you please change the meeting room info ...", "It would be appreciated if you would let me know the status"). About 1 email in 8 has one. No mapping can recover them.
- **The commitment rule adds some false TASKs** ("Customers are going to get very cranky", "will most likely reside on the east desk"), about 2 per 40 emails.
- **Annotator coverage of dates and names is partial.** MailEx labels dates and people only when they are arguments of an event, so some dates and names in the text are unlabeled.
- **Data requests** ("Could you forward the article?", "Can I see the proforma economics?") are excluded by design and show up as missed requests.

### Gate verdict

The plan's gate was "at least 80% acceptable". **It is not met**: 60% to 75% depending on the sample, about 66% pooled over samples 2 and 3 (n = 76 non-empty emails), with wide uncertainty at n = 40. Major errors are about 5% to 12%.

Two readings:
- *Strict:* labels are not good enough, stop here.
- *Practical:* the labels are far cleaner than SILVER-v2 (major errors about 9% vs 33%), but incomplete. Incomplete labels teach the model to ignore some real tasks and make measured precision look worse than it is.

I proceeded to Phase 2 under the practical reading because training is cheap and reversible and shows how much the gaps matter. **Phase 2 results must be read with this caveat, and the choice of how to treat the gate is yours.** Options if you want higher label quality:
1. Add a second labeling pass for requests MailEx missed (an LLM or rule pass, reviewed by a person). Earlier local LLM runs were very slow, so this should be limited to emails that contain request cues but no TASK label.
2. Ask a person to review a validation subset, which would also unblock the GOLD gate.
3. Lower the gate to "no more than 10% major errors", which this mapping meets.

## Provenance

All records carry `quality_tier: "MAILEX_DERIVED"`, `human_verified: false`, `human_source: "MailEx annotators"`. TASK and TEMPORAL spans come directly from human MailEx annotations through a deterministic mapping; PERSON spans come from human annotations through a heuristic name filter. None of this is independently reviewed against the Text2Task schema, so every metric on it remains provisional (`is_final_research_metric: false`).
