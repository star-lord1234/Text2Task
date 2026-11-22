# Live-mode test inputs

Run `scripts/run_app.sh`, switch to **Live**, and try these. "Expected" is what the **hybrid** pipeline did in my runs with the real models.
Nothing is applied until you accept it (review mode). To compare, change the header **Pipeline** selector to `neural only` and send the same text again.

## Setup
- Set the **Simulated message time** to `11/11/2026 09:30 AM` (a Wednesday) so "Friday", "tomorrow" etc. resolve as listed below. Workspace timezone: America/Chicago.
- Use **Workspace reset** between groups. Groups marked *chain* need the earlier messages sent and **accepted** first (accept the task suggestions; owner may need Edit).
- Open the **AI Inspector** (info icon on a message) to see raw neural spans vs refined spans, rule relations and the pipeline configuration.

Format: *Sender → recipients*: message → expected.

## A. Single tasks (should create a suggestion)
| Sender → to | Message | Expected |
|---|---|---|
| Riya → Bianca | Bianca, please prepare the report by Friday. | Task "prepare the report", owner Bianca, due 13 Nov |
| Riya → Anushree | Anushree, can you clean the dataset by Thursday? | "clean the dataset", Anushree, due 12 Nov |
| Anushree → Riya | I'll send the invoice tomorrow. | "send the invoice", Anushree (due may show as scheduled, 12 Nov) |
| Riya → Anushree, Bianca | Please review the slides. | "review the slides", no owner (ambiguous) |
| Riya → Anushree, Bianca | Can someone review the slides? | "review the slides", unassigned |
| Riya → Bianca | Bianca, send me the model report by Thursday and the invoice by Friday. | Two tasks for Bianca: model report (12 Nov), invoice (13 Nov) |
| Riya → Anushree | Anushree, could you update the budget spreadsheet by Friday? | "update the budget spreadsheet", Anushree, 13 Nov |
| Riya → Bianca | Bianca, I need you to draft the release notes by Monday. | "draft the release notes", Bianca, 16 Nov |
| Bianca → Riya | I will review the pull request tomorrow. | "review the pull request", Bianca |
| Anushree → Riya | Let me fix the login bug by Friday. | "fix the login bug", Anushree, 13 Nov |
| Riya → Bianca | Could you send the agenda to the team? | "send the agenda", Bianca |
| Riya → Anushree, Bianca | Someone should back up the database before Friday. | "back up the database", unassigned |
| Riya → Bianca | Bianca, please rewrite the onboarding guide by Friday. | "rewrite the onboarding guide", Bianca, 13 Nov |
| Riya → Anushree | Anushree, I need you to renew the license by Friday. | "renew the license", Anushree, 13 Nov |
| Anushree → Riya | Let me test the payment flow by Thursday. | "test the payment flow", Anushree, 12 Nov |

## B. Messages that should create nothing
- The server went down yesterday.
- Thanks, sounds good.
- Great job on the launch, everyone!
- The meeting went well and we agreed on the plan.
- I was out sick on Monday.
- Lunch is at noon in the kitchen.
- Did you see the report?
- We shipped the release yesterday.
- Thanks for sending the invoice.
- Congratulations on the promotion!
- The printer is out of paper again.
- Is the report ready?
- Happy Friday, everyone.
- I reviewed the contract last week.

## C. Dependencies in one message (expect 2 tasks + 1 dependency suggestion; accept both tasks first, then the dependency)
- Riya → Anushree, Bianca: **After you clean the dataset, write a report.** (report depends on dataset; neural-only creates nothing)
- Riya → Anushree, Bianca: Anushree, after you clean the dataset, please write a report.
- Riya → Anushree, Bianca: Before we send the report, someone needs to proofread it. (send depends on proofread)
- Riya → Bianca: Bianca, please train the model, then Anushree should evaluate it. (evaluate depends on train; owners Bianca / Anushree)
- Riya → Anushree, Bianca: First export the data, then clean it, and then train the model. (chain of 3)
- Riya → Anushree, Bianca: After you review the draft, send it to the client.
- Riya → Anushree, Bianca: Please finalize the budget before sending it to finance. (known weak: the "send" task may be missing)

## D. Dependencies across two messages (*chain*: send #1, accept, then send #2)
1. Riya → Anushree: Anushree, please clean the dataset by Thursday.  
   Riya → Bianca: **Bianca, please train the model once Anushree finishes the dataset.** → new task depends on the existing dataset task
2. Same #1, then Riya → Bianca: Bianca, train the model after the dataset is cleaned.
3. Riya → Bianca: Bianca, please write the report by Friday.  
   (with #1 accepted) Riya → Bianca: The report is waiting on the dataset.
4. Riya → Anushree: Anushree, please collect the survey responses by Monday.  
   Riya → Bianca: Bianca, analyse the results after Anushree has collected the responses.
5. Riya → Bianca: Bianca, please draft the proposal by Thursday.  
   Anushree → Riya: Riya, review the proposal once Bianca finishes the draft.
6. Riya → Anushree: Anushree, please export the customer list by Thursday.  
   Riya → Bianca: Bianca, merge the duplicates once Anushree finishes the export.
7. Riya → Anushree: Anushree, review the design by Thursday.  
   Riya → Bianca: Bianca, write the tests after the review.

## E. Should NOT create a dependency (send, accept, expect no edge)
- Riya → Anushree: Anushree, please clean the dataset by Thursday. then Riya → Bianca: Bianca, please write the report by Friday. (two independent tasks)
- Riya → Anushree: Anushree, please send the report to Bianca after lunch.
- Riya → Bianca: Bianca, update the wiki when you get a chance.
- Riya → Bianca: Bianca, water the plants when you can.
- Riya → Anushree: Anushree, send the summary after the standup.
- Riya → Bianca: Bianca, call me after the meeting. (known false positive: may keep a stray "the meeting" task and link it)

## F. Lifecycle (first send and accept: `Anushree, please clean the dataset by Thursday.` from Riya)
| Sender | Message | Expected suggestion |
|---|---|---|
| Anushree | The dataset is cleaned. | Mark done (works even though no task phrase is found) |
| Anushree | Done with the dataset. | Mark done |
| Anushree | I'm working on the dataset now. | Mark in progress |
| Anushree | Sure, I'll take care of it. | "No change · owner acknowledges" |
| Anushree | Could we move the deadline to Friday? | Proposed due-date change to 13 Nov (needs confirmation) |
| Riya | Actually, cancel the dataset task. | Mark cancelled |
| Anushree | I compiled the expense report. | Nothing (different object) |

With `Bianca, please prepare the quarterly report by Friday.` accepted first:
- Bianca: The quarterly report is done. / I finished the quarterly report. / The quarterly report has been completed. → done
- Bianca: I'm starting on the quarterly report now. → in progress
- Bianca: Can we push the quarterly report to Monday? → proposed date change
- Riya: Never mind, we don't need the quarterly report anymore. → cancel (known: may not trigger)
- Riya: Thanks Bianca! → nothing
- Bianca: I finished the budget review. → must NOT complete the report

## G. Things worth poking at (known weak spots)
- Would Monday work instead of Thursday? → wrongly read as a reassignment.
- Deployment can't start until the test server is set up. (needs existing "deploy" and "set up the test server" tasks) → edge often missed.
- Before we publish the article, someone must fact-check it. → "fact-check" is not in the verb lexicon.
- Bianca, finish the slides and email them to Riya by Thursday. → compound; check both tasks.
- Any verb that is unusual or not in the lexicon, and long, formal email-style text.

## H. Compare configurations
Send the same message under each Pipeline option: `neural only`, `refined`, `hybrid`, `rule only`.
Good ones to compare: sections C (1st item), A (Bianca report), and F (The dataset is cleaned.). In the Inspector, toggle **Raw neural / Refined** and open the Provenance tab to see which stages were on.
