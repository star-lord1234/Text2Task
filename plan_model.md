# Plan: Improving the Text2Task Entity Extractor

Status: **DRAFT FOR REVIEW. Nothing in this plan has been executed.**
Items marked **[DECISION]** need your call before the work starts.

## 1. Where we are

Best provisional run (SILVER-v2 train, SILVER-v1 validation, DistilBERT, 3 epochs, sqrt class weights):

| Metric | Value |
|---|---:|
| Overall precision / recall / F1 | 0.1201 / 0.1348 / 0.1270 |
| PERSON F1 | 0.3333 |
| TEMPORAL F1 | 0.2200 |
| TASK F1 | 0.0042 |
| Predicted B labels | 327 (reference has 208) |

## 2. Diagnosis (why the numbers are low)

1. **Train and validation labels follow different definitions.** Training uses SILVER-v2 (historical and descriptive spans removed from TASK). Validation is SILVER-v1, where our own audit found 22 of 30 records with major errors. TASK F1 partly measures this mismatch.
2. **TASK is a harder problem than PERSON and TEMPORAL.** TASK depends on meaning (current request vs past event) and covers long spans. Reference TASK spans average about 8 tokens; the model predicts about 2.8. Exact-match F1 gives no credit for partly right spans.
3. **Little training data.** 449 of 3,117 MailEx training turns are used, about 84 optimizer steps in total, with no warmup.
4. **Class weighting inflated B predictions.** It raised recall by adding noisy boundary tags, not by learning better.
5. **Tiny validation set.** 60 emails is too few to tell progress from noise.

## 3. Guiding rules

- Fix labels and evaluation **before** touching the model. Otherwise we cannot tell whether a change helped.
- Change **one thing at a time**, and log every run with the same metrics so runs are comparable.
- Keep the test split untouched until the final run.
- Keep the SILVER/GOLD provenance tagging. Do not relabel anything as GOLD without independent human review.
- Every phase ends with a **gate**: a check that decides whether to continue, change course or stop.

---

## Phase 0: Decisions and baseline (small, no training)

**Goal:** Agree on what we are measuring and what "better" means.

- 0.1 **[DECISION] What is a TASK in this project?** Options:
  - (a) Only things someone is asked or committed to do (requests, commitments, prohibitions, plans), as in `docs/annotation_guidelines_v2.md`.
  - (b) Also meetings and data requests, as MailEx's own scheme does.
  - The answer decides how MailEx's human labels map to our labels in Phase 1.
- 0.2 **[DECISION] Which metrics are the headline?** Proposal:
  - Strict: exact-match entity F1 (kept for continuity).
  - Lenient: overlap-based entity F1 (a predicted span counts if it overlaps a reference span of the same type by at least 50%).
  - Token-level F1 per type.
  - Report all three per entity type, not just the overall number.
- 0.3 Record the current best run as the **baseline** under all three metrics, so later gains are measured fairly.
- 0.4 **[DECISION] Target values.** Proposal, to be revised once we see Phase 2 results: PERSON and TEMPORAL lenient F1 at least 0.70; TASK lenient F1 at least 0.50. I'd rather agree on honest targets than promise numbers now.

**Gate:** Written agreement on 0.1 to 0.4.

## Phase 1: Better labels (the biggest expected win)

**Goal:** Replace noisy LLM-built labels with human-verified ones where possible.

- 1.1 **Audit the MailEx human annotations** in `data/unified/train.jsonl` (`original_events`). Known so far: 3,117 training turns, event types such as Request_Action, Request_Meeting, Deliver_Data, Amend_*, and about 7,600 human-labeled `Action` spans.
- 1.2 **Write a deterministic mapping** from MailEx to our labels, based on decision 0.1. For example, Action spans in Request_* and Commitment-like events map to TASK. This is code, not an LLM, and it must be reproducible and logged.
- 1.3 **Check the mapping by hand** on a random sample of 40 emails: does the mapped TASK match what we mean by TASK? Write down the error rate.
- 1.4 **PERSON and TEMPORAL:** MailEx may not label these directly. Check what is available, and if not, build them from:
  - sender and recipient headers for names (we already extract them), and
  - the best existing SILVER-v2 spans or a date/time rule library.
  Keep their provenance as SILVER and say so in the metrics.
- 1.5 **Rebuild train, validation and test** so that all three use the same label definition, with no thread overlap across splits (the existing split-integrity check stays active).

**Gate:** The mapped TASK labels agree with our definition on most of the 40-email sample (proposed: at least 80% acceptable). If not, stop and revise the mapping or the definition. Do not train on labels we do not trust.

## Phase 2: Better evaluation and a retrained baseline

**Goal:** Know what the model really does, and get the cheapest possible gains.

- 2.1 Add the lenient and token-level metrics from 0.2 to the evaluation script, and check them against hand-computed examples.
- 2.2 Retrain **the same token-tagging model** on the new data (all usable turns, not 449), with:
  - 10 to 15 epochs and best-checkpoint selection by validation F1,
  - warmup ratio 0.1,
  - learning rate in {3e-5, 5e-5} (a small sweep),
  - **no class weighting at first**; add a mild version only if B labels collapse again.
- 2.3 Report all metrics per entity type against the Phase 0 baseline.

**Gate (this answers your TASK-modeling concern):**
- If TASK lenient F1 meets the target, **we do not change how TASK is modeled.** Skip Phase 3.
- If PERSON and TEMPORAL are fine but TASK is still far from the target, go to Phase 3.
- If everything is low, the problem is still data or labels. Return to Phase 1.

## Phase 3: Possible change to how TASK is modeled (only if the Phase 2 gate says so)

You asked what "change how TASK is modeled" means. Currently the model tags every token of an email as part of a TASK or not. That works well for names and dates, because they look the same everywhere. A task is different: "Please send the report" is a task, but "I sent the report" is not, and the words are almost identical. Deciding that needs the whole sentence, and exact boundaries on long spans are hard to learn from few examples.

Options, from smallest change to largest:

| Option | What changes | Pros | Cons |
|---|---|---|---|
| **A. Keep token tagging** (default) | Nothing; rely on better data and metrics from Phases 1 and 2 | No new code, one model | May plateau on TASK |
| **B. Sentence classifier + span extraction** | A first model decides which sentences contain a task; the tagger then looks for the span only inside those | Handles "request vs past event" better; fewer false spans | Two models to train and keep consistent |
| **C. Sentence-level TASK only** | TASK output becomes the whole actionable sentence, not an exact span | Removes the boundary problem; simplest to evaluate | Output is coarser; downstream code must accept sentences |
| **D. Generative extraction (LLM or seq2seq)** | Model writes out the tasks | Flexible | Costly, slow on this laptop (the earlier local LLM run took over 4 hours for 44 records), harder to evaluate |

My recommendation: **A first**, then **B** only if the gate triggers. C is the fallback if we decide exact spans are not required. D is not recommended now.

- 3.1 **[DECISION, only if Phase 3 triggers]** Do downstream consumers need exact task spans, or is the sentence enough? This decides between B and C.
- 3.2 Build sentence-level labels from the Phase 1 data (a sentence is positive if it overlaps a TASK span).
- 3.3 Train the sentence classifier, and compare against Option A using the same lenient metric.

**Gate:** Keep the new design only if TASK lenient F1 improves clearly over Phase 2 (proposed: at least +0.10). Otherwise revert to A.

## Phase 4: Model and training refinements (only after the gates above)

- 4.1 Try a cased model (`roberta-base` or `deberta-v3-base`). Email text is cased, and the uncased DistilBERT discards capitals that help with names and sentence starts. Memory on the 16 GB laptop is the limit; keep batch size 4 with accumulation.
- 4.2 If B-label spam returns, test mild class weights, a CRF layer, or span-level decoding rules.
- 4.3 Run 3 seeds for the best configuration and report mean and spread, since the validation set is small.

**Gate:** The best configuration beats the Phase 2 run on lenient F1 across seeds, not just on one lucky seed.

## Phase 5: Final evaluation

- 5.1 Freeze the configuration. Run **once** on the test split.
- 5.2 Report strict, lenient and token-level metrics per type, with the provenance of every label source.
- 5.3 Say plainly which metrics rest on human labels (MailEx-derived TASK) and which on SILVER (PERSON, TEMPORAL if not human-labeled).
- 5.4 Run the unseen-message checks and record the failures, not just the successes.

## 4. Risks

| Risk | Effect | Mitigation |
|---|---|---|
| MailEx's notion of action differs from ours | Mapped labels are wrong for our use | Phase 1.3 sample check and the Phase 1 gate |
| MailEx has no PERSON or TEMPORAL labels | Those stay SILVER | Header-based names and rules; label provenance in every report |
| Gains come from a looser metric, not a better model | Overstated results | Always report strict alongside lenient |
| Small validation set gives noisy results | False conclusions | Use more data in validation after Phase 1; 3 seeds in Phase 4 |
| Training time on the laptop | Slow iteration | Earlier runs took about 80 seconds for 3 epochs on 449 emails; expect several minutes per run on the full data |

## 5. Order of work and rough effort

| Phase | Depends on | Rough effort |
|---|---|---|
| 0. Decisions and baseline | You | Short |
| 1. Better labels | Phase 0 | Largest piece of work |
| 2. Evaluation and retrain | Phase 1 | Medium |
| 3. TASK modeling change | Phase 2 gate; may be skipped | Medium to large |
| 4. Refinements | Phase 2 or 3 | Medium |
| 5. Final evaluation | All | Short |

## 6. Open questions for you

1. What exactly counts as a TASK for your use (Phase 0.1)?
2. Are exact task spans needed downstream, or is a sentence enough (Phase 3.1)?
3. Do the proposed metrics and targets in Phase 0 look right?
4. Is there a deadline or compute limit I should plan around?
5. Do you want the GOLD evaluation unblocked by human-reviewing a sample of validation emails, and who would do that review?
