# Demo walkthrough: Scenario F, "launch the sentiment model"

A 17-message story that shows everything Text2Task does in one sitting:

- turning chat into tasks
- only the right person approving
- every kind of dependency the system recognises
- date changes, progress, completion and cancellation
- what the AI ignores

Plan for 10–12 minutes. If you only have 2, use [the fast path](#fast-path-2-minutes).

---

## Before you start

1. Run the app with `scripts/run_app.sh` (or `T2T_NO_MODELS=1 scripts/run_app.sh` if you only need the demo), then open http://127.0.0.1:8000.
2. **Settings** (bottom of the sidebar) → **Reset workspace…** so the board is empty.
3. Load the story: on the empty chat, click the **Full demo: launch the sentiment model** chip. You can also pick it under **Settings → Demo story**.
4. Bottom-left, check you're **viewing as Riya**.

**The cast**

| Person | Role | In the story |
|---|---|---|
| **Riya** | Project Lead | Hands out the work |
| **Anushree** | Data Engineer | Collects and cleans the data, volunteers for the server |
| **Bianca** | ML Engineer | Trains the model, builds the dashboard, writes the evaluation |

**How every step works.** Press **Next** to send the next message. The player at the bottom always shows who speaks next and what they'll say. Then accept the suggestions it creates **before pressing Next again**: later messages refer to earlier tasks, so they need to exist first.

**The rule worth saying out loud early.** A suggestion is approved by the person it lands on, not by whoever is watching:

- **New task:** the assignee approves it.
- **Status change, or "has to wait for another task":** the owner of the affected task approves it.
- **Date change:** the person whose agreement it needs confirms it.

As Riya you'll see those cards under **Waiting on teammates** with a **Switch to …** button. Use it to jump to the right person.

---

## The story, step by step

> **Legend:** **Viewing as** is who should be selected bottom-left. A card title in quotes is what you'll see on the card in the **Tasks** panel.

### Act 1 — Work gets handed out

| # | Message | Viewing as → click | What to point at |
|---|---|---|---|
| 1 | **Riya:** "Anushree, please collect the customer reviews by Monday." | Riya sees it under *Waiting on teammates* → **Switch to Anushree** → **Accept** | The AI found the task, the person and the date ("Due Mon 16 Nov"). **Riya cannot accept it; Anushree can.** The lead doesn't approve other people's work. |
| 2 | **Anushree:** "Sure, I'll collect the customer reviews." | Nothing to accept | Chip under the message: *No change · restates "collect the customer reviews"*. An acknowledgement is **not** a duplicate task. |
| 3 | **Riya:** "Anushree, please clean the review dataset by Tuesday **once** you collect the customer reviews." | Anushree → **Accept** the new task, then **Accept** "Has to wait for another task" | Two suggestions from one sentence: a task **plus a dependency**. The dependency card stays disabled until its task exists ("Waiting for another suggestion to be accepted first"). |
| 4 | **Riya:** "Bianca, please train the sentiment model by November 18 **once** the review dataset is cleaned." | **Switch to Bianca** → Accept both | A dependency **across people**: Bianca's work waits on Anushree's. Chain: collect → clean → train. |
| 5 | **Riya:** "Bianca, please write the evaluation script by Thursday." | Bianca → **Accept** | An independent task with a deadline (Thu 12 Nov). |

### Act 2 — Open calls and volunteers

| # | Message | Viewing as → click | What to point at |
|---|---|---|---|
| 6 | **Riya:** "Can someone set up the demo server?" | Anyone → **Leave open** | No one was named, so the AI **does not guess** an owner: *"New task · no one assigned yet"*. Anyone can decide. **I'll take it** would assign it to you; choose **Leave open** so the next message can claim it. |
| 7 | **Anushree:** "I can set up the demo server." | **Switch to Anushree** → **Accept** ("Hand over to you") | A volunteer claims the **existing** open task. No second task is created. |

### Act 3 — The dependency web

| # | Message | Viewing as → click | What to point at |
|---|---|---|---|
| 8 | **Riya:** "Bianca, please build the demo dashboard by November 20 **after** you train the sentiment model." | Bianca → Accept both | A different cue word, "after": chain step 3 (train → dashboard). |
| 9 | **Riya:** "The demo dashboard **is waiting on** the demo server. The demo dashboard **is blocked by** the evaluation script." | Bianca → Accept both | Two more phrasings, this time between tasks that **already exist**. The dashboard now waits on **three** tasks (*fan-in*). Bianca accepts because it's her task that waits. |
| 10 | **Riya:** "Bianca, please share the results report after you write the evaluation script." | Bianca → Accept both | The evaluation script now blocks **two** tasks (*fan-out*). |
| 11 | **Anushree:** "The office wifi went down yesterday." | Nothing | Chip: *No change · historical statement*. Talking about the past is not a to-do. |

👉 **Good moment to open Dependencies** in the sidebar (see [the tour](#tour-after-the-story)), then come back to **team-chat**.

### Act 4 — Plans change

| # | Message | Viewing as → click | What to point at |
|---|---|---|---|
| 12 | **Bianca:** "Could we move the evaluation script deadline to Friday?" | Bianca → **Accept** ("Date change requested by you") | A **request**, not a change: the task row now says *"New date Fri 13 Nov awaiting OK"* and the due date **stays Thursday**. |
| 13 | **Riya:** "Friday is fine." | **Switch to Riya** → **Accept** ("Confirm the new date") | The short reply is understood as a confirmation **of that request**. Only now does the due date become **Fri 13 Nov**. Open the task to show both steps under **Activity**. |
| 14 | **Anushree:** "I've finished collecting the customer reviews." | **Switch to Anushree** → **Accept** ("Mark as done") | Completion **unblocks** the next task: "Clean the review dataset" loses its lock. |
| 15 | **Anushree:** "I'm working on the review dataset now." | Anushree → **Accept** ("Mark as in progress") | Progress updates move the status; no new task. |

### Act 5 — Guard rails

| # | Message | Viewing as → click | What to point at |
|---|---|---|---|
| 16 | **Riya:** "The sentiment model is waiting on the demo dashboard." | **Switch to Bianca** → **Accept** | This would make a loop (the dashboard already waits on training). The graph **refuses** it: it shows as a **red dotted "held: cycle"** edge, kept for review instead of silently dropped, and the graph stays valid. |
| 17 | **Riya:** "We no longer need the evaluation script." | Bianca (or Riya, who created it) → **Accept** ("Cancel this task") | **Cancelled is not done.** "Share the results report" waited only on the script, so it becomes **Needs review**. Someone must decide whether it still makes sense. The dashboard stays **Blocked**: it still waits on training. |

---

## Tour after the story

### Dependencies (sidebar)
The final graph, left to right:

```
Collect reviews ──▶ Clean dataset ──▶ Train model ──▶ Build dashboard ◀── Set up demo server
   (Done)          (In progress)      (Blocked)        (Blocked by 2)
                                          ▲ ┄┄┄held: cycle┄┄┄┘   ▲
                                                                  │
                                       Write evaluation script ───┤
                                             (Canceled) ──────────▶ Share results report
                                                                        (Needs review)
```

Things to click:

- **The highlight switch** (All · Ready · Blocked · Review · Done) to answer "what can start right now?"
- **An arrow** to see its evidence sentence, checks ("not inferred from message order") and **Open the source message**.
- **The red dotted edge** to see why it's held. **Reconsider** only succeeds once the loop is gone.
- **A task, then "What if…"**: e.g. *Clean the review dataset → …it were completed* shows **Train the sentiment model** becoming ready. Nothing is changed; it's a preview.
- **The Step slider** replays how the graph grew message by message.
- **Graph as table** gives a keyboard- and screen-reader-friendly version of the same graph.

### Timeline (sidebar)
One row per person, one column per day. *Due* chips are deadlines (🏳); *Planned* chips are times something is meant to happen ("tomorrow", "on Thursday"). Tasks without a confirmed date sit in **No date yet**, never guessed onto a day. A 🔒 *waiting* marker means the task is blocked.

### How the AI read a message
Hover any message → **How AI read this**. Try message 3:

- **Highlights** shows the exact words picked out (Task · Person · Date).
- **Links** shows which person and date belong to which task.
- **People & dates** shows "Tuesday" resolved to a real date, and how.
- **Decision** shows why it became "new task + dependency".
- **Sources** says honestly which steps were pre-written for the demo and which are the real code.

### Model results (sidebar)
The saved evaluation numbers, with the caveat that they are measured against provisional SILVER labels, not a human-verified gold set.

---

## Fast path (2 minutes)
Load the story and press **Play all**. Every message is sent and every suggestion is accepted by a clearly labelled *simulated reviewer*. Then go straight to **Dependencies** and **Timeline**.

## If something looks off
- **"Differs from the scripted expectation" on a message**: an earlier suggestion wasn't accepted before pressing **Next** (e.g. the acknowledgement in step 2 needs the task from step 1). Use **◀** to step back, or **↺** to restart the story.
- **No Accept button on a card**: you're viewing as someone else. Use **Switch to …** on the card.
- **Step 7 proposes a second "set up the demo server" task, flagged as a possible duplicate**: in step 6 someone chose **I'll take it** instead of **Leave open**, so there was no open task to claim. Dismiss it, or restart the story.

## Live mode bonus
**Settings → Live AI** lets you type your own messages; the trained models read them. Names work even when the message goes to everyone: "Bianca please prepare the report by Friday", with or without a comma, is assigned to Bianca. A request that names nobody ("Please prepare the report") stays open, and the card offers **I'll take it** / **Leave open**.
