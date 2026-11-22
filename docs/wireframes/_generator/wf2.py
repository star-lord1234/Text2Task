import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..") + os.sep
from wf import *
s = SVG(1440, 900, "Text2Task - Dependency Explorer")
header(s, "Dependencies", ("Riya", RIYA, "R"), "SCRIPTED"); banner(s, "SCRIPTED")

# toolbar
s.r(16, 96, 1408, 48, fill=WHITE)
s.t(30, 125, "Owner", size=11.5, fill=MUTED)
x = 78
for nm, col, ch_ in (("Riya", RIYA, "R"), ("Anushree", ANU, "A"), ("Bianca", BIA, "B")):
    w = 30 + len(nm) * 8 + 14
    s.r(x, 106, w, 28, fill=WHITE, stroke=col, rx=14, sw=2); s.avatar(x + 15, 120, col, ch_, r=9); s.t(x + 30, 125, nm, size=12, weight=600); x += w + 8
s.l(x + 6, 106, x + 6, 134); x += 22
s.t(x, 125, "Status", size=11.5, fill=MUTED); s.r(x + 46, 106, 110, 28, fill=PANEL); s.t(x + 56, 125, "All states  ▾", size=12); x += 176
s.t(x, 125, "Show edges", size=11.5, fill=MUTED); x += 76
for lab, dash, col in (("accepted", None, INK), ("suggested", "6,5", MUTED), ("held", "2,4", RED)):
    s.t(x, 125, "☑", size=13); s.l(x + 18, 120, x + 46, 120, stroke=col, sw=2, dash=dash); s.t(x + 52, 125, lab, size=12); x += 52 + len(lab) * 7 + 22
s.l(x, 106, x, 134); x += 16
s.t(x, 125, "Layout", size=11.5, fill=MUTED); s.r(x + 48, 106, 130, 28, fill=PANEL); s.t(x + 58, 125, "Left → Right  ▾", size=12); x += 200
for i, lab in enumerate(("Fit", "＋", "－")):
    s.r(1424 - 40 - i * 50 - 0, 106, 40, 28, fill=WHITE, stroke=INK, rx=14); s.t(1424 - 20 - i * 50, 125, lab, size=12, anchor="middle", weight=600)

# canvas
s.r(16, 156, 1076, 668, fill=WHITE)
for gx_ in range(40, 1092, 28):
    for gy_ in range(180, 824, 28):
        s.c(gx_, gy_, 1, fill="#dfe4ea", stroke="#dfe4ea")
def node(x, y, title, who, col, status, sflag, sel=False, w=212, h=84, dashed=False):
    if sel:
        s.r(x - 6, y - 6, w + 12, h + 12, fill="none", stroke=BLUE, rx=12, sw=2, dash="4,3")
    s.r(x, y, w, h, fill=WHITE, stroke=col, rx=10, sw=3, dash="6,4" if dashed else None)
    s.t(x + 14, y + 26, title, size=13.5, weight=700); s.t(x + 14, y + 46, who, size=11.5, fill=MUTED)
    s.chip(x + 12, y + 56, status, fill=sflag[0], stroke=sflag[1], ink=sflag[2], size=11, h=20)
OK_, WARN_, INFO_, GR_ = ("#e6f4ea", "#a9d6b8", GREEN), ("#fff4d6", "#e8cf85", "#7a5c00"), ("#e8f0fb", "#b8cdee", BLUE), (PANEL, LINE, INK)
node(60, 380, "Prepare cleaned dataset", "Anushree · Thu 12 Nov", ANU, "✓ Done", OK_)
node(380, 300, "Train entity model", "Bianca · no confirmed due", BIA, "◔ In progress", WARN_)
node(700, 230, "Evaluate model", "Riya · Mon 16 Nov", RIYA, "🔒 Blocked by 1", GR_)
node(700, 420, "Write results section", "Riya · no confirmed due", RIYA, "☐ To do", INFO_, dashed=True)
node(380, 560, "Review the slides", "Bianca · no confirmed due", BIA, "☐ To do", INFO_)
# edges
s.path("M 272 422 C 330 422, 320 342, 380 342", stroke=BLUE, sw=7)         # selection halo
s.path("M 272 422 C 330 422, 320 342, 380 342", stroke=INK, sw=2, arrow="ah")
s.path("M 592 330 C 650 330, 650 272, 700 272", stroke=INK, sw=2, arrow="ah")
s.path("M 592 350 C 650 350, 650 462, 700 462", stroke=MUTED, sw=2, dash="6,5", arrow="ahg")
s.t(640, 452, "suggested", size=11, fill=MUTED, italic=True)
s.path("M 700 252 C 560 190, 190 200, 160 378", stroke=RED, sw=2, dash="2,4", arrow="ahr")
s.r(300, 196, 214, 22, fill="#fde8e8", stroke="#f0b3b3", rx=4); s.t(407, 211, "held: would close a cycle", size=11, fill=RED, anchor="middle", weight=600)
s.t(250, 700, "No edge between “Review the slides” and the rest: message order alone never creates a dependency.", size=11.5, fill=MUTED, italic=True)
# legend
s.r(32, 736, 330, 74, fill=PANEL, stroke=LINE)
s.t(44, 756, "Legend", size=12, weight=700)
s.l(44, 774, 84, 774, stroke=INK, sw=2, arrow="ah"); s.t(92, 778, "accepted (prerequisite → dependent)", size=11.5)
s.l(44, 794, 84, 794, stroke=MUTED, sw=2, dash="6,5", arrow="ahg"); s.t(92, 798, "suggested", size=11.5); s.l(190, 794, 230, 794, stroke=RED, sw=2, dash="2,4", arrow="ahr"); s.t(238, 798, "held", size=11.5)
# minimap
s.r(930, 700, 150, 110, fill=WHITE, stroke=LINE); s.t(938, 716, "Minimap", size=10.5, fill=MUTED)
for (mx, my, c_) in ((945, 740, ANU), (975, 732, BIA), (1010, 722, RIYA), (1010, 748, RIYA), (975, 770, BIA)):
    s.r(mx, my, 24, 12, fill=WHITE, stroke=c_, rx=2, sw=2)
s.r(940, 722, 120, 72, fill="none", stroke=BLUE, rx=2, dash="3,2")

# right panel: edge details
px = 1106
s.r(px, 156, 318, 668, fill=WHITE)
s.t(px + 16, 184, "Edge details", size=15, weight=700); s.t(px + 16, 202, "Selected: prerequisite → dependent", size=11.5, fill=MUTED)
s.l(px, 214, px + 318, 214)
s.t(px + 16, 240, "Prepare cleaned dataset", size=13, weight=700); s.t(px + 16, 260, "→  blocks  Train entity model", size=13, weight=700, fill=BIA)
x = px + 16; x += s.chip(x, 274, "accepted", fill=OK_[0], stroke=OK_[1], ink=OK_[2]) + 6; x += s.chip(x, 274, "origin: rule", fill=PANEL, stroke=LINE, ink=INK) + 6; s.chip(x, 274, "scripted", fill="#fff4d6", stroke="#e8cf85", ink="#7a5c00")
s.t(px + 16, 322, "Evidence", size=12, weight=700)
s.r(px + 16, 332, 286, 70, fill=PANEL, stroke=PANEL, rx=6)
s.t(px + 26, 354, "“…train the entity model once", size=12, italic=True, fill=MUTED); s.t(px + 26, 372, "Anushree finishes the dataset.”", size=12, italic=True, fill=MUTED); s.t(px + 26, 392, "Riya · m3 · 09:35   ↗ show in chat", size=11, fill=BLUE)
s.t(px + 16, 428, "Checks", size=12, weight=700)
for i, (ok, txt) in enumerate(((True, "No cycle (accepted graph is acyclic)"), (True, "Both endpoints exist"), (True, "No date used to infer this edge"), (False, "Warning: none"))):
    s.t(px + 20, 450 + i * 20, ("✓ " if ok else "○ ") + txt, size=11.5, fill=GREEN if ok else MUTED)
s.t(px + 16, 548, "Derived state", size=12, weight=700); s.t(px + 16, 568, "“Train entity model” is not blocked:", size=11.5, fill=MUTED); s.t(px + 16, 584, "its prerequisite is done.", size=11.5, fill=MUTED)
for i, lab in enumerate(("Open in Inspector", "Remove edge", "Reconsider held edges")):
    s.r(px + 16, 590 + i * 44, 286, 34, fill=WHITE, stroke=INK if i == 0 else LINE, rx=17); s.t(px + 159, 612 + i * 44, lab, size=12.5, anchor="middle", weight=600 if i == 0 else 400, fill=INK if i < 2 else MUTED)
s.t(px + 16, 742, "Removing keeps the edge as “held”, with who/why,", size=11, fill=MUTED, italic=True); s.t(px + 16, 758, "so evidence is never lost.", size=11, fill=MUTED, italic=True)
# footer
s.r(0, 836, 1440, 64, fill=WHITE, stroke=LINE, rx=0)
s.t(20, 862, "Scenario A — Simple assignment", size=13, weight=700); s.t(20, 882, "Step 3 of 5  ·  graph shows the state at this step", size=11.5, fill=MUTED)
bx = 330
for lab in ("◀ Previous", "Next ▶", "Play all"):
    s.r(bx, 848, 96, 34, fill=WHITE, stroke=INK, rx=17); s.t(bx + 48, 870, lab, size=12.5, anchor="middle", weight=600); bx += 108
s.t(700, 870, "Step", size=11.5, fill=MUTED); s.l(736, 865, 880, 865, stroke=LINE, sw=3); s.l(736, 865, 816, 865, stroke=INK, sw=3); s.c(816, 865, 7, fill=INK, stroke=INK); s.t(894, 870, "3 / 5", size=12, fill=MUTED)
s.t(1424, 870, "Empty graph shows “No confirmed dependencies yet”", size=11.5, fill=MUTED, anchor="end")
s.callout(16, 70, 1); s.callout(24, 100, 2); s.callout(1096, 156, 3); s.callout(60, 380, 4); s.callout(32, 736, 5); s.callout(930, 700, 6); s.callout(300, 196, 7)
s.save(OUT + "02_dependency_explorer.svg"); print("ok")
