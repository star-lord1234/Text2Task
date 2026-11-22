import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..") + os.sep
from wf import *
s = SVG(1260, 900, "Text2Task - narrow screen (Chat / Tasks / Graph tabs)")
OK_, WARN_, INFO_ = ("#e6f4ea", "#a9d6b8", GREEN), ("#fff4d6", "#e8cf85", "#7a5c00"), ("#e8f0fb", "#b8cdee", BLUE)
def phone(px, active, caption):
    py, pw, ph = 40, 372, 800
    s.r(px, py, pw, ph, fill=WHITE, stroke=INK, rx=28, sw=2)
    # app bar
    s.t(px + 18, py + 38, "☰", size=18); s.t(px + 48, py + 38, "Text2Task", size=15, weight=700)
    s.r(px + 150, py + 20, 92, 26, fill=INK, stroke=INK, rx=13); s.t(px + 196, py + 38, "Scripted", size=11.5, fill=WHITE, anchor="middle", weight=600)
    s.r(px + 250, py + 16, 108, 32, fill=WHITE, stroke=INK, rx=16); s.avatar(px + 268, py + 32, ANU, "A", r=10); s.t(px + 284, py + 37, "Anushree ▾", size=11.5, weight=600)
    s.r(px + 1, py + 58, pw - 2, 24, fill="#fff4d6", stroke="#e8cf85", rx=0); s.t(px + 12, py + 74, "SCRIPTED DEMO — extraction pre-written", size=11, weight=600, fill="#7a5c00")
    # segmented tabs
    s.r(px + 14, py + 92, pw - 28, 36, fill=PANEL, stroke=LINE, rx=18)
    for i, lab in enumerate(("Chat", "Tasks", "Graph")):
        w = (pw - 36) / 3
        if lab == active:
            s.r(px + 16 + i * w, py + 94, w, 32, fill=INK, stroke=INK, rx=16)
        s.t(px + 16 + i * w + w / 2, py + 115, lab, size=13, anchor="middle", weight=600, fill=WHITE if lab == active else MUTED)
    # bottom scenario bar
    s.r(px + 1, py + ph - 56, pw - 2, 55, fill=WHITE, stroke=LINE, rx=0)
    s.r(px + 14, py + ph - 46, 70, 34, fill=WHITE, stroke=INK, rx=17); s.t(px + 49, py + ph - 24, "◀ Prev", size=12, anchor="middle", weight=600)
    s.t(px + pw / 2, py + ph - 24, "Step 3 / 5", size=12.5, anchor="middle", weight=600)
    s.r(px + pw - 84, py + ph - 46, 70, 34, fill=INK, stroke=INK, rx=17); s.t(px + pw - 49, py + ph - 24, "Next ▶", size=12, anchor="middle", fill=WHITE, weight=600)
    s.t(px + pw / 2, py + ph + 24, caption, size=12.5, anchor="middle", fill=MUTED)
    return py + 140
def bubble(px, y, who, col, ch_, text, chip=None, h=64):
    s.avatar(px + 28, y + 12, col, ch_, r=11); s.t(px + 46, y + 10, who, size=12, weight=700)
    s.r(px + 46, y + 16, 300, h - 28, fill=PANEL, stroke=PANEL, rx=8); s.t(px + 56, y + 38, text, size=12)
    if chip: s.chip(px + 46, y + h - 10, chip[0], fill=chip[1], stroke=chip[2], ink=chip[3], size=10.5, h=18)

# --- phone 1: chat
px = 24; y = phone(px, "Chat", "Chat: persona switch, composer, per-message status")
bubble(px, y + 4, "Riya", RIYA, "R", "Anushree, please prepare the dataset…", ("2 changes suggested", "#fff4d6", "#e8cf85", "#7a5c00"), h=76)
bubble(px, y + 92, "Anushree", ANU, "A", "Sure, I'll take care of the dataset.", ("No change · matches T-1", PANEL, LINE, MUTED), h=76)
bubble(px, y + 180, "Riya", RIYA, "R", "Bianca, train once the data is ready.", ("⟳ Analysing…", PANEL, LINE, MUTED), h=76)
bubble(px, y + 268, "Bianca", BIA, "B", "I'll begin training now.", ("⚠ Analysis failed", "#fde8e8", "#f0b3b3", RED), h=76)
s.chip(px + 168, y + 336, "↻ Retry", fill=WHITE, stroke=INK, ink=INK, size=10.5, h=18)
s.r(px + 14, y + 506, 344, 40, fill=WHITE, stroke=INK, rx=20); s.t(px + 30, y + 531, "Message as Anushree…", size=12, fill=MUTED)
s.r(px + 296, y + 512, 54, 28, fill=INK, stroke=INK, rx=14); s.t(px + 323, y + 531, "Send", size=11.5, anchor="middle", fill=WHITE, weight=600)
s.t(px + 18, y + 566, "To: ☑ Riya  ☑ Bianca      ✎ simulated time 09:44", size=11, fill=MUTED)

# --- phone 2: tasks
px = 24 + 396; y = phone(px, "Tasks", "Tasks: Mine | All users, review queue first")
s.r(px + 200, y - 4, 156, 28, fill=PANEL, stroke=LINE, rx=14); s.r(px + 202, y - 2, 74, 24, fill=INK, stroke=INK, rx=12); s.t(px + 239, y + 15, "Mine", size=12, anchor="middle", fill=WHITE, weight=600); s.t(px + 316, y + 15, "All", size=12, anchor="middle", fill=MUTED)
s.t(px + 16, y + 14, "My tasks", size=14, weight=700)
s.r(px + 14, y + 34, 344, 36, fill="#fff4d6", stroke="#e8cf85", rx=8); s.t(px + 26, y + 57, "Review queue · 2 pending  ›", size=12.5, weight=700, fill="#7a5c00")
def tcard(y_, title, who, col, ch_, due, st, sf, dashed=False):
    s.r(px + 14, y_, 344, 92, fill=WHITE, stroke=MUTED if dashed else LINE, rx=10, dash="5,4" if dashed else None)
    s.r(px + 26, y_ + 14, 15, 15, fill=WHITE, stroke=INK, rx=3); s.t(px + 50, y_ + 27, title, size=13, weight=700)
    s.avatar(px + 32, y_ + 50, col, ch_, r=9); s.t(px + 46, y_ + 54, f"{who} · {due}", size=11.5, fill=MUTED)
    s.chip(px + 26, y_ + 64, st, fill=sf[0], stroke=sf[1], ink=sf[2], size=10.5, h=18); s.t(px + 340, y_ + 27, "↗ m1", size=10.5, anchor="end", fill=BLUE)
tcard(y + 82, "Prepare cleaned dataset", "Anushree", ANU, "A", "Thu 12 Nov", "☐ To do · blocks 1", INFO_)
tcard(y + 184, "Review the model report", "Anushree", ANU, "A", "no confirmed due", "◔ In progress", WARN_)
tcard(y + 286, "Train entity model", "Bianca", BIA, "B", "no confirmed due", "Proposed · needs review", ("#fff4d6", "#e8cf85", "#7a5c00"), dashed=True)
s.t(px + 18, y + 410, "Other users' tasks appear only under “All”.", size=11, fill=MUTED, italic=True)
s.r(px + 14, y + 430, 344, 150, fill="#fffdf6", stroke="#e8cf85", rx=10)
s.t(px + 26, y + 454, "Create task: Train entity model — Bianca", size=12, weight=700); s.t(px + 26, y + 474, "“…train once Anushree finishes the dataset.”", size=11, italic=True, fill=MUTED)
for i, (lab, f_, i_) in enumerate((("Accept", INK, WHITE), ("Edit", WHITE, INK), ("Dismiss", WHITE, MUTED))):
    s.r(px + 26 + i * 86, y + 492, 78, 28, fill=f_, stroke=INK if i < 2 else LINE, rx=14); s.t(px + 65 + i * 86, y + 511, lab, size=11.5, anchor="middle", fill=i_, weight=600)
s.t(px + 26, y + 548, "Tap a task for details, history, source message.", size=11, fill=MUTED, italic=True)

# --- phone 3: graph
px = 24 + 792; y = phone(px, "Graph", "Graph: pan / zoom, tap node or edge for details")
s.r(px + 14, y - 4, 344, 38, fill=PANEL, stroke=LINE, rx=8)
for i, (nm, col, ch_) in enumerate((("R", RIYA, "R"), ("A", ANU, "A"), ("B", BIA, "B"))):
    s.avatar(px + 36 + i * 36, y + 15, col, ch_, r=11)
s.t(px + 150, y + 20, "State ▾", size=11.5); s.t(px + 214, y + 20, "☑ accepted ☑ suggested", size=10.5, fill=MUTED)
s.r(px + 14, y + 42, 344, 440, fill=WHITE, stroke=LINE, rx=8)
def pn(x_, y_, t_, col, st):
    s.r(x_, y_, 150, 58, fill=WHITE, stroke=col, rx=8, sw=2.5); s.t(x_ + 10, y_ + 22, t_, size=11.5, weight=700); s.chip(x_ + 8, y_ + 32, st, fill=PANEL, stroke=LINE, ink=INK, size=10, h=18)
pn(px + 28, y + 80, "Prepare dataset", ANU, "✓ Done")
pn(px + 190, y + 190, "Train entity model", BIA, "◔ In progress")
pn(px + 28, y + 310, "Evaluate model", RIYA, "🔒 Blocked")
s.path(f"M {px+103} {y+138} C {px+103} {y+190}, {px+150} {y+219}, {px+190} {y+219}", stroke=INK, sw=2, arrow="ah")
s.path(f"M {px+265} {y+248} C {px+265} {y+290}, {px+150} {y+330}, {px+178} {y+338}", stroke=MUTED, sw=2, dash="6,5", arrow="ahg")
s.r(px + 14, y + 496, 344, 84, fill=WHITE, stroke=BLUE, rx=10)
s.t(px + 26, y + 520, "Prepare dataset → Train entity model", size=12, weight=700); s.chip(px + 26, y + 530, "accepted", fill=OK_[0], stroke=OK_[1], ink=OK_[2], size=10.5, h=18); s.chip(px + 100, y + 530, "rule · scripted", fill=PANEL, stroke=LINE, ink=INK, size=10.5, h=18)
s.t(px + 26, y + 568, "“…once Anushree finishes the dataset.” ↗", size=11, italic=True, fill=MUTED)
s.save(OUT + "05_narrow_screen.svg"); print("ok")
