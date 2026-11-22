import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..") + os.sep
from wf import *

s = SVG(1440, 900, "Text2Task - Workspace (desktop)")
header(s, "Workspace", ("Anushree", ANU, "A"), "SCRIPTED")
banner(s, "SCRIPTED")

# ---------------- column 1: chat
cx, cy, cw, ch = 16, 100, 440, 724
s.r(cx, cy, cw, ch, fill=WHITE)
s.t(cx + 16, cy + 26, "Team chat", size=15, weight=700); s.t(cx + 100, cy + 26, "# ml-project  ·  shared by all personas", size=12, fill=MUTED)
s.l(cx, cy + 40, cx + cw, cy + 40)
def msg(y, who, col, ch_, time, text, chips, h=86):
    s.avatar(cx + 28, y + 16, col, ch_)
    s.t(cx + 50, y + 14, who, size=13, weight=700); s.t(cx + 50 + len(who) * 8 + 10, y + 14, time, size=11, fill=MUTED)
    s.r(cx + 50, y + 22, 360, h - 36, fill=PANEL)
    for i, ln in enumerate(text):
        s.t(cx + 62, y + 42 + i * 17, ln, size=12.5)
    x = cx + 50
    for c_ in chips:
        x += s.chip(x, y + h - 8, c_[0], fill=c_[1], stroke=c_[2], ink=c_[3]) + 6
    s.t(cx + 398, y + 14, "ⓘ", size=14, fill=MUTED)
msg(cy + 52, "Riya", RIYA, "R", "09:30", ["Anushree, please prepare the cleaned", "dataset by Thursday."], [("2 changes suggested", "#fff4d6", "#e8cf85", "#7a5c00"), ("1 accepted", "#e6f4ea", "#a9d6b8", GREEN)])
msg(cy + 160, "Anushree", ANU, "A", "09:32", ["Sure, I'll take care of the dataset."], [("No change · matches T-1", PANEL, LINE, MUTED)], h=70)
msg(cy + 250, "Riya", RIYA, "R", "09:35", ["Bianca, please train the entity model", "once Anushree finishes the dataset."], [("2 changes suggested", "#fff4d6", "#e8cf85", "#7a5c00")])
# processing + failure states
s.avatar(cx + 28, cy + 366, ANU, "A"); s.t(cx + 50, cy + 364, "Anushree", size=13, weight=700); s.t(cx + 126, cy + 364, "09:41", size=11, fill=MUTED)
s.r(cx + 50, cy + 372, 360, 40, fill=PANEL); s.t(cx + 62, cy + 396, "The cleaned dataset is ready.", size=12.5)
s.chip(cx + 50, cy + 420, "⟳ Analysing…", fill=PANEL, stroke=LINE, ink=MUTED)
s.avatar(cx + 28, cy + 470, BIA, "B"); s.t(cx + 50, cy + 468, "Bianca", size=13, weight=700); s.t(cx + 100, cy + 468, "09:44", size=11, fill=MUTED)
s.r(cx + 50, cy + 476, 360, 40, fill=PANEL); s.t(cx + 62, cy + 500, "I'll begin training now.", size=12.5)
x = cx + 50; x += s.chip(x, cy + 524, "⚠ Analysis failed — model unavailable", fill="#fde8e8", stroke="#f0b3b3", ink=RED) + 6
s.chip(x, cy + 524, "↻ Retry", fill=WHITE, stroke=INK, ink=INK)
s.t(cx + 50, cy + 566, "Failures are shown, never replaced by scripted output.", size=11, fill=MUTED, italic=True)
# composer
s.l(cx, cy + 600, cx + cw, cy + 600)
s.t(cx + 16, cy + 622, "Send as", size=11, fill=MUTED); s.avatar(cx + 78, cy + 618, ANU, "A", r=10); s.t(cx + 94, cy + 622, "Anushree  ·  To:", size=12)
x = cx + 196
for nm, col in (("Riya", RIYA), ("Bianca", BIA)):
    s.r(x, cy + 608, 70, 22, fill=WHITE, stroke=col, rx=11); s.t(x + 12, cy + 623, "☑ " + nm, size=11); x += 78
s.r(cx + 16, cy + 640, 340, 44, fill=WHITE, stroke=INK); s.t(cx + 28, cy + 667, "Message as Anushree…", size=12.5, fill=MUTED)
s.r(cx + 366, cy + 640, 58, 44, fill=INK, stroke=INK); s.t(cx + 395, cy + 667, "Send", size=13, fill=WHITE, anchor="middle", weight=600)
s.t(cx + 16, cy + 704, "Simulated time: Wed 11 Nov 2026, 09:44 (Chicago)  ✎ edit", size=11, fill=MUTED)

# ---------------- column 2: tasks
tx, ty, tw = 472, 100, 440
s.r(tx, ty, tw, ch, fill=WHITE)
s.t(tx + 16, ty + 26, "My tasks", size=15, weight=700); s.t(tx + 88, ty + 26, "Anushree", size=13, fill=ANU, weight=700)
s.r(tx + 250, ty + 10, 172, 28, fill=PANEL, rx=14); s.r(tx + 252, ty + 12, 80, 24, fill=INK, stroke=INK, rx=12)
s.t(tx + 292, ty + 28, "Mine", size=12, fill=WHITE, anchor="middle", weight=600); s.t(tx + 378, ty + 28, "All users", size=12, fill=MUTED, anchor="middle")
s.l(tx, ty + 46, tx + tw, ty + 46)
def card(y, title, who, col, ch_, due, status, sflag, extra, dashed=False, h=96):
    s.r(tx + 12, y, tw - 24, h, fill=WHITE, stroke=MUTED if dashed else LINE, dash="5,4" if dashed else None, rx=8)
    s.r(tx + 24, y + 14, 16, 16, fill=WHITE, stroke=INK, rx=3)
    s.t(tx + 50, y + 28, title, size=14, weight=700)
    s.avatar(tx + 30, y + 54, col, ch_, r=10); s.t(tx + 46, y + 58, f"{who}  ·  {due}", size=12, fill=MUTED)
    x = tx + 24; x += s.chip(x, y + 70, status, fill=sflag[0], stroke=sflag[1], ink=sflag[2]) + 6
    for e in extra:
        x += s.chip(x, y + 70, e, fill=PANEL, stroke=LINE, ink=MUTED) + 6
    s.t(tx + tw - 36, y + 28, "↗ m1", size=11, fill=BLUE, anchor="end")
card(ty + 60, "Prepare cleaned dataset", "Anushree", ANU, "A", "Due Thu 12 Nov", "☐ To do", ("#e8f0fb", "#b8cdee", BLUE), ["Blocks 1 task", "from Riya · m1"])
card(ty + 168, "Review the model report", "Anushree", ANU, "A", "No confirmed due date", "◔ In progress", ("#fff4d6", "#e8cf85", "#7a5c00"), ["Date needs a reference time"])
# review queue
s.r(tx + 12, ty + 280, tw - 24, 440, fill="#fffdf6", stroke="#e8cf85", rx=8)
s.t(tx + 28, ty + 306, "Review queue", size=14, weight=700); s.chip(tx + 128, ty + 292, "2 pending", fill="#fff4d6", stroke="#e8cf85", ink="#7a5c00")
s.t(tx + 28, ty + 326, "Review mode: nothing applies until you accept it.", size=11, fill=MUTED)
def sug(y, kind, title, ev, flags):
    s.r(tx + 24, y, tw - 48, 166, fill=WHITE, stroke=LINE, rx=8)
    s.chip(tx + 36, y + 12, kind, fill=PANEL, stroke=LINE, ink=INK)
    s.t(tx + 36, y + 52, title, size=13.5, weight=700)
    s.r(tx + 36, y + 62, tw - 72, 36, fill=PANEL, rx=4, stroke=PANEL)
    s.t(tx + 44, y + 78, ev[0], size=11.5, italic=True, fill=MUTED); s.t(tx + 44, y + 92, ev[1], size=11.5, italic=True, fill=MUTED)
    x = tx + 36
    for f in flags:
        x += s.chip(x, y + 104, f, fill="#fff4d6", stroke="#e8cf85", ink="#7a5c00", size=10.5) + 5
    bx = tx + 36
    for lab, fill, ink in (("Accept", INK, WHITE), ("Edit", WHITE, INK), ("Dismiss", WHITE, MUTED)):
        w = 74
        s.r(bx, y + 134, w, 26, fill=fill, stroke=INK if lab != "Dismiss" else LINE, rx=13); s.t(bx + w / 2, y + 151, lab, size=12, fill=ink, anchor="middle", weight=600); bx += w + 8
    s.t(tx + tw - 44, y + 151, "Why? ›", size=11.5, fill=BLUE, anchor="end")
sug(ty + 342, "Create task", "Train entity model — Bianca", ["“…train the entity model once Anushree", "finishes the dataset.”  — Riya, m3"], ["Due: none confirmed", "model: scripted"])
sug(ty + 516, "Add dependency", "Prepare cleaned dataset → Train entity model", ["“…once Anushree finishes the dataset.”", "prerequisite → dependent  — rule, m3"], ["Needs both tasks accepted first"])
s.t(tx + 28, ty + 704, "Other users' tasks stay out of this list unless “All users” is selected.", size=11, fill=MUTED, italic=True)

# ---------------- column 3: graph preview
gx, gy, gw = 928, 100, 496
s.r(gx, gy, gw, ch, fill=WHITE)
s.t(gx + 16, gy + 26, "Dependencies", size=15, weight=700); s.t(gx + 130, gy + 26, "preview", size=12, fill=MUTED)
s.l(gx, gy + 46, gx + gw, gy + 46)
def node(x, y, title, who, col, status, w=190, h=70, dashed=False):
    s.r(x, y, w, h, fill=WHITE, stroke=col, rx=8, sw=2.5, dash="5,4" if dashed else None)
    s.t(x + 12, y + 24, title, size=12.5, weight=700); s.t(x + 12, y + 42, who, size=11, fill=MUTED)
    s.chip(x + 10, y + 46, status, fill=PANEL, stroke=LINE, ink=INK, size=10.5, h=18)
node(gx + 150, gy + 84, "Prepare cleaned dataset", "Anushree · Thu 12 Nov", ANU, "☐ To do")
node(gx + 150, gy + 244, "Train entity model", "Bianca · no due date", BIA, "🔒 Blocked", dashed=True)
s.path(f"M {gx+245} {gy+154} L {gx+245} {gy+244}", stroke=MUTED, dash="6,5", arrow="ahg")
s.t(gx + 256, gy + 205, "suggested · awaiting accept", size=11, fill=MUTED, italic=True)
s.r(gx + 16, gy + 360, gw - 32, 150, fill=PANEL, stroke=PANEL)
s.t(gx + 28, gy + 384, "Legend", size=12, weight=700)
s.l(gx + 30, gy + 406, gx + 80, gy + 406, stroke=INK, sw=2, arrow="ah"); s.t(gx + 90, gy + 410, "accepted prerequisite → dependent", size=11.5)
s.l(gx + 30, gy + 430, gx + 80, gy + 430, stroke=MUTED, sw=2, dash="6,5", arrow="ahg"); s.t(gx + 90, gy + 434, "suggested, not yet accepted", size=11.5)
s.l(gx + 30, gy + 454, gx + 80, gy + 454, stroke=RED, sw=2, dash="2,4", arrow="ahr"); s.t(gx + 90, gy + 458, "held for review (e.g. would create a cycle)", size=11.5)
s.t(gx + 30, gy + 484, "Border colour = owner.  Status is always a label + icon, never colour alone.", size=11, fill=MUTED)
s.r(gx + 16, gy + 530, gw - 32, 40, fill=WHITE, stroke=INK, rx=20); s.t(gx + gw / 2, gy + 555, "Open full explorer  →", size=13, weight=600, anchor="middle")
s.t(gx + 16, gy + 596, "Select a node or edge to see its source message and evidence.", size=11.5, fill=MUTED, italic=True)

# ---------------- footer: scenario controls
s.r(0, 836, 1440, 64, fill=WHITE, stroke=LINE, rx=0)
s.t(20, 862, "Scenario A — Simple assignment", size=13, weight=700); s.t(20, 882, "Step 3 of 5  ·  deterministic replay", size=11.5, fill=MUTED)
bx = 330
for lab in ("◀ Previous", "Next ▶", "Play all"):
    s.r(bx, 848, 96, 34, fill=WHITE, stroke=INK, rx=17); s.t(bx + 48, 870, lab, size=12.5, anchor="middle", weight=600); bx += 108
for i in range(5):
    s.c(700 + i * 26, 865, 6, fill=INK if i < 3 else WHITE, stroke=INK)
s.t(840, 870, "3 / 5", size=12, fill=MUTED)
s.r(900, 848, 130, 34, fill=WHITE, stroke=LINE, rx=17); s.t(965, 870, "Reset scenario", size=12.5, anchor="middle")
s.r(1040, 848, 140, 34, fill=WHITE, stroke=LINE, rx=17); s.t(1110, 870, "Reset workspace", size=12.5, anchor="middle")
s.r(1190, 848, 110, 34, fill=WHITE, stroke=LINE, rx=17); s.t(1245, 870, "Activity  ▴", size=12.5, anchor="middle")
s.t(1424, 870, "Review mode", size=11.5, fill=MUTED, anchor="end")

# callouts (numbers are explained in the plan)
s.callout(16, 70, 1); s.callout(1050 + 150 - 6, 12, 2); s.callout(1204 + 216 - 4, 12, 3); s.callout(cx - 4, cy - 4, 4); s.callout(tx - 4, ty - 4, 5); s.callout(gx - 4, gy - 4, 6)
s.callout(tx + 12, ty + 282, 7); s.callout(316, 856, 8); s.callout(cx - 4, cy + 606, 9)
s.save(OUT + "01_workspace_desktop.svg"); print("ok")
print("ok")
