# Text2Task Candidate Selection and Coverage Analysis

## Result

The deterministic selector produced **600 provisional email candidates** from cleaned MailEx. Existing MailEx annotations were used only as candidate signals; no final Text2Task gold labels were assigned. Every coverage flag has `requires_human_verification: true`.

| Split | Cleaned population | Target | Selected |
| --- | --- | --- | --- |
| train | 3117 | 450 | 450 |
| dev | 414 | 60 | 60 |
| test | 405 | 90 | 90 |

Random seed: **20261030**. Selection version: `1.0.0`.

## Selection safeguards

- Original thread IDs, turn order, source filenames, and train/dev/test membership are preserved.
- 43 complete multi-turn thread bundles were selected for realistic cross-email context.
- Exact and near-duplicate group IDs from cleaning are globally constrained, so a duplicate group cannot be selected across multiple splits.
- Quotas explicitly reserve coverage for prerequisites, negation/status, ambiguity, multiple tasks, no-action emails, deadlines, updates, scheduling, ownership, and temporal language before score-based filling.
- Ambiguous/easy signals are mixed: the selector does not treat MailEx labels as final task labels.
- Text cleaning review flags and quoted context remain attached to candidate records.

## Prerequisite expressions

**138 emails in the complete cleaned corpus contain possible prerequisite/dependency expressions under the conservative rule.** The rule accepts strong dependency terms only with nearby concrete-action evidence; connectors such as “after,” “before,” and “when” require concrete action cues on both sides. The deadline idiom “as soon as possible” and obvious terms-of-service boilerplate are excluded. Therefore, “after” alone is never sufficient.

## Provisional coverage

| Coverage flag | Population emails | Selected emails | Meaning |
| --- | --- | --- | --- |
| explicit_actionable_request | 2163 | 455 | Request-like MailEx event or explicit request language. |
| commitment_or_planned_action | 1906 | 468 | Future commitment/planning language or planned-action event. |
| multiple_tasks | 1822 | 507 | At least two potential task event instances or multiple distinct request/action cues. |
| task_ownership | 2321 | 488 | MailEx member/owner argument evidence or explicit ownership language. |
| explicit_deadline | 1055 | 395 | Date/time event argument or deterministic deadline expression. |
| scheduled_activity | 838 | 303 | Meeting/schedule event or explicit scheduling language. |
| temporal_expression | 1730 | 475 | Deterministic date, time, relative-time, or ordering expression. |
| possible_prerequisite | 138 | 111 | Action-conditioned dependency expression; connector alone is insufficient. |
| action_update_across_thread | 2880 | 566 | Multi-turn thread with repeated action/update evidence. |
| negated_canceled_or_completed | 612 | 250 | Negated, canceled, completed, or status-update action language. |
| ambiguous_ownership_or_deadline | 293 | 73 | Action candidate with missing or vague owner/deadline evidence. |
| no_actionable_tasks | 845 | 91 | No relevant MailEx event and no deterministic action/request cue. |
| multi_email_scenario | 2880 | 566 | Record belongs to a multi-turn thread with repeated action or update evidence. |

## MailEx event frequencies

These counts are event instances used as selection evidence, not Text2Task labels.

| MailEx event type | Population occurrences | Selected occurrences |
| --- | --- | --- |
| Amend_Action_Data | 3 | 2 |
| Amend_Data | 193 | 66 |
| Amend_Meeting_Data | 55 | 17 |
| Deliver_Action_Data | 3195 | 972 |
| Deliver_Data | 1820 | 350 |
| Deliver_Meeting_Data | 487 | 226 |
| O | 776 | 66 |
| Request_Action | 1376 | 411 |
| Request_Action_Data | 233 | 44 |
| Request_Data | 721 | 142 |
| Request_Meeting | 259 | 115 |
| Request_Meeting_Data | 50 | 18 |

## Candidate complexity

| Complexity band | Population emails | Selected emails |
| --- | --- | --- |
| low | 666 | 0 |
| medium | 1013 | 91 |
| high | 2257 | 509 |

## Selected source distribution

Top source mailboxes inferred from original filenames:

| Mailbox source | Selected emails |
| --- | --- |
| blair-l | 26 |
| steffes-j | 26 |
| cash-m | 24 |
| heard-m | 24 |
| donoho-l | 23 |
| buy-r | 21 |
| nemec-g | 21 |
| watson-k | 21 |
| mccarty-d | 20 |
| mims-thurston-p | 20 |
| mclaughlin-e | 19 |
| wolfe-j | 19 |
| martin-t | 18 |
| lay-k | 16 |
| ybarbo-p | 14 |
| schoolcraft-d | 13 |
| derrick-j | 12 |
| lavorato-j | 12 |
| skilling-j | 12 |
| kaminski-v | 11 |

Detailed split-level coverage, event-frequency, complexity, and mailbox-source rows are in `coverage_report.csv`.

## Representative examples for every provisional category

### `explicit_actionable_request`

Request-like MailEx event or explicit request language.

- Record: `mailex:test:rapp-b_inbox_199:turn_0000`
- Split/thread: `test` / `rapp-b_inbox_199` / turn 0
- Provisional score: 25.0
- Text: “Attached for your review and comments is a draft of TW's response to the FERC data request in the USGT negotiated rate proceeding. Please note that our response to Data Request No. 1, contemplates that we will provide to FERC copies of the other bids that were received on this capacity. We could attempt to summarize this other bids, but I think the better approach is to just provide copies. A schedule of actual volu…”
### `commitment_or_planned_action`

Future commitment/planning language or planned-action event.

- Record: `mailex:train:shackleton-s_inbox298:turn_0002`
- Split/thread: `train` / `shackleton-s_inbox298` / turn 2
- Provisional score: 24.0
- Text: “Sara and Donna, Gary has agreed that the Convertible Arbitrage Book should be transferred back to ECT Investments Inc. The Convertible Arbitrage Book was moved from ECT Investments, Inc. to Enron North America Corp., effective 1QTR2001. We will need to get this done before year-end. The Convertible Book will need to be reported at year-end for SEC 13F reporting. We want it included in ECT Investments ' 13f rather th…”
### `multiple_tasks`

At least two potential task event instances or multiple distinct request/action cues.

- Record: `mailex:train:blair-l_inbox_255:turn_0001`
- Split/thread: `train` / `blair-l_inbox_255` / turn 1
- Provisional score: 24.0
- Text: “Mike, I spoke with Steve Sweeney at Cogentrix today regarding this spreadsheet, and he would like to see our data for every day from June 1, 2001 through September 30, 2001 as you calculated for the few random days throughout the summer. The spreadsheet seems to indicate that we did not allocate Cogentrix on some of the days in question. This information is contrary to the information Steve provided and must be expl…”
### `task_ownership`

MailEx member/owner argument evidence or explicit ownership language.

- Record: `mailex:dev:lay-k_inbox187:turn_0000`
- Split/thread: `dev` / `lay-k_inbox187` / turn 0
- Provisional score: 24.0
- Text: “Hello Everyone, Just a friendly reminder that the Family dinner is planned for the 12th at the Grotto restaurant in their private room at 5:30. Good food and good fun! Please RSVP by Friday. David and Courtney I know that you are not coming but I wanted to include you in the reminder incase your plans changed. For those recieving osmars food. To make thing run smoothly in his department it is very important that you…”
### `explicit_deadline`

Date/time event argument or deterministic deadline expression.

- Record: `mailex:test:cash-m_inbox243:turn_0000`
- Split/thread: `test` / `cash-m_inbox243` / turn 0
- Provisional score: 24.0
- Text: “Just got off conference call with Wachovia to review trust arrangement particularly to ensure that this is effective in not triggering tax until time of payment rather than triggering tax at funding of trust. We think this arrangement does that as long as the following is true: Funds put in trust should not be paid out until 2002 to provide for `` service period/vesting '' requirement Must be irrevocable i.e. funds…”
### `scheduled_activity`

Meeting/schedule event or explicit scheduling language.

- Record: `mailex:dev:sager-e_inbox819:turn_0003`
- Split/thread: `dev` / `sager-e_inbox819` / turn 3
- Provisional score: 23.5
- Text: “Not completely, it means that we are not going to sign any agreements until we get the nod from appropriate management folks. We should continue low key development of the agreements as usual, but not execute new docs. Let's talk about it at our upcoming legal-credit luncheon. -- -- cgy”
### `temporal_expression`

Deterministic date, time, relative-time, or ordering expression.

- Record: `mailex:train:lavorato-j_inbox99:turn_0001`
- Split/thread: `train` / `lavorato-j_inbox99` / turn 1
- Provisional score: 22.5
- Text: “At 4pm on Wednesday Liza arrived with the DASH. It had not been circulated prior to that and there was no-one available to discuss the deal as Eva was not in the office. Please have someone ready to discuss this deal and circulate the DASH in advance of when you want it signing. 4pm on Wednesday with no briefing on the deal didn't give enough time to complete a DASH. Louise”
### `possible_prerequisite`

Action-conditioned dependency expression; connector alone is insufficient.

- Record: `mailex:train:nemec-g_inbox1036:turn_0001`
- Split/thread: `train` / `nemec-g_inbox1036` / turn 1
- Provisional score: 22.5
- Text: “OK folks, here's an update on Holcomb Oil and Gas Inc./Key Gas Holding, LLC. The only active contract we have in place with Holcomb is an Enfolio II Spot and the interest assignment letter sent by Holcomb does not cover an agreement so broad. I spoke with Susan Herrera at Holcomb [(505) 326-0550] and asked her to send an assignment letter. She didn't seem to really understand what I needed to I also gave her Gerald'…”

Dependency evidence: `[{"pattern": "action_conditioned_temporal_connector", "connector": "Once", "span": [438, 442], "context": "d an assignment letter. She didn't seem to really understand what I needed to I also gave her Gerald's number in Legal. Once we receive a good assignment, I will request that the Global Counterparty group set up the CP. Sharon will process the ", "confidence": "provisional_medium"}, {"pattern": "strong_dependency_term", "connector": "depend on", "span": [653, 662], "context": "ssignment at that point. Depending on whether we want to split deal 901255 or repath will depend on how long this process takes. I will keep everyone informed in the meantime. Please let me", "confidence": "provisional_high"}]`
### `action_update_across_thread`

Multi-turn thread with repeated action/update evidence.

- Record: `mailex:train:nemec-g_inbox257:turn_0000`
- Split/thread: `train` / `nemec-g_inbox257` / turn 0
- Provisional score: 22.5
- Text: “Kyle, Attached are the final versions of the Servitude Agreement and the Filing Form. We made some changes to the form for consistency. Please review. Roger and Rakhi, Please verify the legal description provided by Enterprise. I also have a plat which I will forward to you for review. After everyone has reviewed and approved we should be ready to go. < < File: LRCI IncAgreement 9-26-0111.doc > > < < File: ServAgrFi…”
### `negated_canceled_or_completed`

Negated, canceled, completed, or status-update action language.

- Record: `mailex:train:mclaughlin-e_inbox163:turn_0000`
- Split/thread: `train` / `mclaughlin-e_inbox163` / turn 0
- Provisional score: 22.5
- Text: “Bernice - please set up the attached book request and notify when complete. Francis/Cecilia - I will be out of the office Thursday and Friday (Dec 20 and 21). Please handle the Erms side once Bernice sends out the notification. I have already set up these books in RisktRAC. Due to the Outlook problems, I was unable to handle this request in a timely fashion. Sorry for any delays this may have caused. Thanks everyone…”
### `ambiguous_ownership_or_deadline`

Action candidate with missing or vague owner/deadline evidence.

- Record: `mailex:test:tycholiz-b_inbox246:turn_0002`
- Split/thread: `test` / `tycholiz-b_inbox246` / turn 2
- Provisional score: 20.0
- Text: “Dan, I am interested. I know that Sue Mara spoke with Ron on this subject also, although I was not on the call. The matter was not discussed on our Western Wholesale call this morning either, since I did not become aware of it till later. I would therefore like to receive input from Sue and others on our team about this, getting final sign off to proceed from Linda Robertson and Jim Steffes. If we elect to proceed,…”
### `no_actionable_tasks`

No relevant MailEx event and no deterministic action/request cue.

- Record: `mailex:train:giron-d_inbox33:turn_0000`
- Split/thread: `train` / `giron-d_inbox33` / turn 0
- Provisional score: 3.0
- Text: “P & L Responsibility Midcontinent Region Andy Lewis - Basis and Gas Daily PEPL, ANR-ok, NNG-Demarc, NNG-Vent, NGPL-midcon Jason Williams - Cash trading and index PEPL, ANR-ok, NNG-Demarc, NNG-Vent, NGPL-midcon Market Area Hunter Shively - Basis and Gas Daily Chicago Geof Storey - Basis and Gas Daily Michcon and Dawn Vladi Pimenov - Cash trading and Index (no VAR) Chicago Souad Mahmassani - Cash trading and Index (no…”
### `multi_email_scenario`

Record belongs to a multi-turn thread with repeated action or update evidence.

- Record: `mailex:dev:heard-m_inbox85:turn_0000`
- Split/thread: `dev` / `heard-m_inbox85` / turn 0
- Provisional score: 22.5
- Text: “Marie, I am working this noon time on your orders. I received pricing from Schumacher and Kravet and it is half of what you were quoted. Both are in stock. The purchase price will be a little more because of freight. Also, my husband may want me to add taxes - because I am using his tax resale certificate. I am checking with him and will let you know. Do you want me to go ahead and place the orders? I have filled ou…”

## Reproduction

```bash
python3 scripts/select_candidates.py --seed 20261030
```

The outputs are candidate-review inputs only. Human verification is required before assigning gold task, owner, deadline, dependency, or status labels.
