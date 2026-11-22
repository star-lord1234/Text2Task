import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..") + os.sep
from wf import *
s = SVG(1440, 900, "Text2Task - Task details, edit-before-accept, ambiguous referent")
header(s, "Workspace", ("Anushree", ANU, "A"), "SCRIPTED"); banner(s, "SCRIPTED")
OK_, WARN_, INFO_ = ("#e6f4ea", "#a9d6b8", GREEN), ("#fff4d6", "#e8cf85", "#7a5c00"), ("#e8f0fb", "#b8cdee", BLUE)

# ---- left: task details drawer
x0, w0 = 16, 690
s.r(x0, 100, w0, 724, fill=WHITE)
s.t(x0 + 20, 132, "Task details", size=16, weight=700); s.t(x0 + w0 - 24, 132, "✕", size=15, anchor="end", fill=MUTED)
s.l(x0, 146, x0 + w0, 146)
s.t(x0 + 20, 174, "Title", size=11, fill=MUTED); s.r(x0 + 20, 180, w0 - 40, 34, fill=WHITE, stroke=INK, rx=6); s.t(x0 + 32, 203, "Prepare cleaned dataset", size=14, weight=700); s.t(x0 + w0 - 36, 203, "✎", size=13, anchor="end", fill=MUTED)
s.t(x0 + 20, 240, "Owner", size=11, fill=MUTED); s.r(x0 + 20, 246, 200, 32, fill=WHITE, stroke=LINE); s.avatar(x0 + 38, 262, ANU, "A", r=10); s.t(x0 + 56, 267, "Anushree  ▾", size=12.5)
s.t(x0 + 240, 240, "Status", size=11, fill=MUTED); s.r(x0 + 240, 246, 190, 32, fill=WHITE, stroke=LINE); s.t(x0 + 252, 267, "☐ To do  ▾", size=12.5)
s.t(x0 + 450, 240, "Version", size=11, fill=MUTED); s.chip(x0 + 450, 250, "v3", fill=PANEL, stroke=LINE, ink=INK); s.t(x0 + 500, 264, "edits are version-checked", size=11, fill=MUTED, italic=True)
s.t(x0 + 20, 306, "Due", size=11, fill=MUTED); s.r(x0 + 20, 312, 260, 32, fill=WHITE, stroke=LINE); s.t(x0 + 32, 333, "Thu 12 Nov 2026", size=12.5)
x = x0 + 292; x += s.chip(x, 318, "RESOLVED", fill=OK_[0], stroke=OK_[1], ink=OK_[2]) + 6; s.chip(x, 318, "rule: weekday_bare · assumes message time", fill=PANEL, stroke=LINE, ink=MUTED, size=10.5)
s.r(x0 + 20, 352, w0 - 40, 46, fill="#fff8db", stroke="#e0c867", rx=6)
s.t(x0 + 32, 372, "Unresolved example: “after approval” is stored as raw text with a reason and a question,", size=11.5, fill="#7a5c00"); s.t(x0 + 32, 389, "never a guessed date.  Missing timestamp → “Date needs a reference timestamp”.", size=11.5, fill="#7a5c00")
s.t(x0 + 20, 424, "Source", size=11, fill=MUTED); s.r(x0 + 20, 430, w0 - 40, 44, fill=PANEL, stroke=PANEL, rx=6)
s.t(x0 + 32, 449, "“Anushree, please prepare the cleaned dataset by Thursday.”", size=12, italic=True, fill=MUTED); s.t(x0 + 32, 466, "Riya · m1 · 09:30   ↗ show in chat   ·   ⓘ open in Inspector", size=11, fill=BLUE)
s.t(x0 + 20, 502, "Dependencies", size=11, fill=MUTED); s.t(x0 + 20, 522, "Blocks:  Train entity model (Bianca)  — edge accepted from m3", size=12)
s.t(x0 + 20, 560, "History (immutable)", size=13, weight=700)
hist = [("09:30", "CREATE_TASK", "Riya", "rule · scripted", "→ owner Anushree, due Thu 12 Nov"),
        ("09:32", "NO_ACTION", "Anushree", "rule", "restates this task; no duplicate (matched T-1)"),
        ("09:35", "ADD_DEPENDENCY", "Riya", "rule", "this task now blocks T-2"),
        ("09:50", "MANUAL_EDIT", "Anushree", "human", "title: “Prepare dataset” → “Prepare cleaned dataset”")]
y = 576
for i, (t_, op, who, src, txt) in enumerate(hist):
    s.c(x0 + 30, y + 10, 5, fill=INK if i == 3 else WHITE, stroke=INK)
    if i < 3: s.l(x0 + 30, y + 15, x0 + 30, y + 46, stroke=LINE, sw=2)
    s.t(x0 + 46, y + 14, t_, size=11.5, fill=MUTED); s.t(x0 + 92, y + 14, op, size=12, weight=700); s.t(x0 + 220, y + 14, f"by {who}", size=11.5)
    s.chip(x0 + 320, y + 1, src, fill=("#efe9ff" if src == "human" else PANEL), stroke=("#b8a8f0" if src == "human" else LINE), ink=("#4b3bb0" if src == "human" else INK), size=10.5, h=18)
    s.t(x0 + 92, y + 32, txt, size=11.5, fill=MUTED); y += 48
s.t(x0 + 20, 786, "Manual corrections are recorded as human edits, never as model predictions.", size=11, fill=MUTED, italic=True)
s.r(x0 + w0 - 190, 782, 170, 30, fill=WHITE, stroke=INK, rx=15); s.t(x0 + w0 - 105, 802, "Mark done", size=12.5, anchor="middle", weight=600)

# ---- right top: edit-before-accept dialog
x1, w1 = 722, 702
s.r(x1, 100, w1, 340, fill=WHITE)
s.t(x1 + 20, 130, "Edit suggestion before accepting", size=15, weight=700); s.chip(x1 + 372, 114, "Create task", fill=PANEL, stroke=LINE, ink=INK)
s.l(x1, 144, x1 + w1, 144)
s.t(x1 + 20, 170, "Assignee", size=11, fill=MUTED)
s.r(x1 + 20, 176, 300, 34, fill=WHITE, stroke=RED, rx=6, sw=2); s.t(x1 + 32, 198, "Choose…  ▾", size=12.5, fill=MUTED)
s.chip(x1 + 332, 183, "⚠ Assignee unresolved", fill="#fde8e8", stroke="#f0b3b3", ink=RED); 
s.t(x1 + 20, 232, "Candidates from the message: “you” matches 2 people (Anushree, Bianca) — we do not guess.", size=11.5, fill=MUTED)
s.t(x1 + 20, 262, "Due", size=11, fill=MUTED); s.r(x1 + 20, 268, 300, 34, fill=WHITE, stroke=LINE); s.t(x1 + 32, 290, "next Friday", size=12.5)
s.chip(x1 + 332, 275, "needs a reference timestamp", fill=WARN_[0], stroke=WARN_[1], ink=WARN_[2])
s.t(x1 + 20, 326, "Title", size=11, fill=MUTED); s.r(x1 + 20, 332, 660, 34, fill=WHITE, stroke=LINE); s.t(x1 + 32, 354, "Train entity model", size=12.5)
bx = x1 + 20
for lab, fill, ink, w in (("Accept with edits", INK, WHITE, 150), ("Cancel", WHITE, INK, 90)):
    s.r(bx, 386, w, 32, fill=fill, stroke=INK, rx=16); s.t(bx + w / 2, 407, lab, size=12.5, anchor="middle", fill=ink, weight=600); bx += w + 10
s.t(x1 + 20, 432, "Accept is disabled until required fields are resolved or explicitly left blank.", size=11, fill=MUTED, italic=True)

# ---- right bottom: ambiguous referent
s.r(x1, 456, w1, 368, fill="#fffdf6", stroke="#e8cf85")
s.t(x1 + 20, 486, "Which task does this refer to?", size=15, weight=700); s.chip(x1 + 270, 470, "ambiguous referent", fill=WARN_[0], stroke=WARN_[1], ink=WARN_[2])
s.r(x1 + 20, 498, w1 - 40, 44, fill=WHITE, stroke=LINE, rx=6)
s.t(x1 + 32, 517, "Bianca: “I've finished the report.”", size=12.5, weight=700); s.t(x1 + 32, 534, "No task was changed. Two open tasks mention “report”.", size=11.5, fill=MUTED)
def opt(y, sel, title, who, col, ch_, why):
    s.r(x1 + 20, y, w1 - 40, 66, fill=WHITE, stroke=BLUE if sel else LINE, rx=8, sw=2 if sel else 1)
    s.c(x1 + 40, y + 24, 8, fill=BLUE if sel else WHITE, stroke=BLUE if sel else MUTED)
    s.t(x1 + 60, y + 28, title, size=13, weight=700); s.avatar(x1 + 70, y + 46, col, ch_, r=9); s.t(x1 + 86, y + 50, who, size=11.5, fill=MUTED)
    s.t(x1 + 340, y + 50, why, size=11, fill=MUTED, italic=True)
opt(556, True, "T-1  Prepare the report", "Bianca (owner = speaker)", BIA, "B", "score 52 · owner matches speaker")
opt(630, False, "T-2  Review the report", "Anushree", ANU, "A", "score 40 · same object word")
s.t(x1 + 20, 724, "Candidates are shown with their score and the signals that produced it (explicit rule trace).", size=11.5, fill=MUTED)
bx = x1 + 20
for lab, fill, ink, w in (("Choose & accept", INK, WHITE, 150), ("Dismiss", WHITE, MUTED, 90), ("None of these", WHITE, INK, 120)):
    s.r(bx, 744, w, 32, fill=fill, stroke=INK if lab != "Dismiss" else LINE, rx=16); s.t(bx + w / 2, 765, lab, size=12.5, anchor="middle", fill=ink, weight=600); bx += w + 10
s.t(x1 + 20, 800, "Nothing changes until you choose: never silently overwrites an unrelated task.", size=11, fill=MUTED, italic=True)
# footer
s.r(0, 836, 1440, 64, fill=WHITE, stroke=LINE, rx=0); s.t(20, 862, "Scenario A — Simple assignment", size=13, weight=700); s.t(20, 882, "Step 3 of 5", size=11.5, fill=MUTED)
s.callout(16, 100, 1); s.callout(x0 + w0 - 24, 306, 2); s.callout(x0 + w0 - 24, 560, 3); s.callout(x1, 100, 4); s.callout(x1, 456, 5)
s.save(OUT + "04_task_details_edit_ambiguity.svg"); print("ok")
