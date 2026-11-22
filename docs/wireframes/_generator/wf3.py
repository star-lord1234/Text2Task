import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..") + os.sep
from wf import *
s = SVG(1440, 900, "Text2Task - Model Inspector drawer")
header(s, "Workspace", ("Riya", RIYA, "R"), "LIVE"); banner(s, "LIVE")
# dimmed workspace underneath
for (x, w) in ((16, 440), (472, 440)):
    s.r(x, 100, w, 724, fill=WHITE, op=0.55)
s.r(16, 100, 440, 40, fill=WHITE, op=0.0)
s.t(32, 128, "Team chat", size=15, weight=700, fill=MUTED)
s.r(66, 346, 380, 44, fill=PANEL, stroke=BLUE, rx=6, sw=2); s.t(78, 372, "Bianca, please train the entity model once Anushree…", size=12.5, fill=MUTED)
s.t(66, 336, "Riya  09:35   ← selected message", size=12, fill=BLUE, weight=600)
s.r(0, 56, 860, 844, fill="#1f2933", stroke="#1f2933", rx=0, op=0.18)
# drawer
dx, dw = 860, 580
s.r(dx, 56, dw, 844, fill=WHITE, stroke=LINE, rx=0)
s.t(dx + 20, 92, "Model Inspector", size=17, weight=700); s.t(dx + 168, 92, "message m3 · Riya · 09:35", size=12.5, fill=MUTED)
s.t(dx + dw - 28, 92, "✕", size=16, anchor="end", fill=MUTED)
s.l(dx, 108, dx + dw, 108)
# message with highlighted spans
s.r(dx + 20, 122, dw - 40, 108, fill=PANEL, stroke=PANEL)
s.t(dx + 34, 146, "Exact message text (spans are character offsets into this string)", size=11, fill=MUTED)
def span(x, y, w, col, label):
    s.r(x, y, w, 24, fill=col[0], stroke=col[1], rx=4); s.t(x + 4, y + 17, label, size=13, weight=600, fill=col[2])
PER, TSK, TMP = ("#efe9ff", "#b8a8f0", "#4b3bb0"), ("#e0f0ff", "#9cc4ee", "#1f5fa8"), ("#fff4d6", "#e8cf85", "#7a5c00")
x0, y0 = dx + 34, 156
span(x0, y0, 54, PER, "Bianca"); s.t(x0 + 56, y0 + 17, ", please", size=13)
span(x0 + 118, y0, 168, TSK, "train the entity model"); s.t(x0 + 290, y0 + 17, "once", size=13)
span(x0 + 326, y0, 190, TSK, "Anushree finishes the")
s.t(x0, y0 + 46, "dataset", size=13, fill=TSK[2], weight=600); s.t(x0 + 52, y0 + 46, ".", size=13)
x = dx + 34
for lab, c_ in (("PERSON", PER), ("TASK", TSK), ("TEMPORAL", TMP)):
    x += s.chip(x, 206, lab, fill=c_[0], stroke=c_[1], ink=c_[2], size=10.5, h=18) + 6
s.t(x + 8, 220, "none found for TEMPORAL — shown as such, not invented", size=11, fill=MUTED, italic=True)
# tabs
tabs = ("Entities", "Relations", "Resolution", "Reconciliation", "Provenance")
x = dx + 20
for t_ in tabs:
    w = len(t_) * 8 + 28
    act = t_ == "Relations"
    s.t(x + 14, 262, t_, size=13, weight=700 if act else 400, fill=INK if act else MUTED)
    if act:
        s.l(x + 10, 272, x + w - 10, 272, stroke=INK, sw=3)
    x += w
s.l(dx, 274, dx + dw, 274)
# relations content
s.t(dx + 20, 302, "Relations (typed, directed)", size=13, weight=700); s.t(dx + 230, 302, "source → target, with the text that supports it", size=11.5, fill=MUTED)
def rel(y, src, lab, tgt, prov, pc, note, ev):
    s.r(dx + 20, y, dw - 40, 92, fill=WHITE, stroke=LINE, rx=8)
    s.t(dx + 34, y + 24, src, size=12.5, weight=700, fill=TSK[2]); s.chip(dx + 34 + len(src) * 7.6 + 10, y + 8, "→ " + lab + " →", fill=PANEL, stroke=LINE, ink=INK, size=11)
    s.t(dx + 34, y + 46, tgt, size=12.5, weight=700, fill=PER[2] if lab == "ASSIGNED_TO" else TSK[2])
    s.chip(dx + dw - 40 - 96, y + 8, prov, fill=pc[0], stroke=pc[1], ink=pc[2], size=10.5, h=18)
    s.t(dx + 34, y + 68, note, size=11.5, fill=MUTED); s.t(dx + 34, y + 84, ev, size=11.5, italic=True, fill=MUTED)
rel(316, "train the entity model", "ASSIGNED_TO", "Bianca", "scripted", ("#fff4d6", "#e8cf85", "#7a5c00"), "relation score: —  (scripted fixture, no model score)", "evidence: “Bianca, please train the entity model”")
rel(418, "train the entity model", "DEPENDS_ON", "Anushree finishes the dataset", "rule", ("#e8f0fb", "#b8cdee", BLUE), "cue: “once” between two task spans (explicit prerequisite wording)", "proposed edge: Prepare cleaned dataset → Train entity model")
s.r(dx + 20, 520, dw - 40, 30, fill="#fff8db", stroke="#e0c867", rx=4); s.t(dx + 30, 540, "Model scores, when present, are uncalibrated softmax values — not probabilities.", size=11.5, fill="#7a5c00")
# collapsed accordions
def acc(y, title, line1, line2=None, h=70):
    s.r(dx + 20, y, dw - 40, h, fill=WHITE, stroke=LINE, rx=8); s.t(dx + 34, y + 24, "▸ " + title, size=13, weight=700)
    s.t(dx + 34, y + 44, line1, size=11.5, fill=MUTED)
    if line2: s.t(dx + 34, y + 60, line2, size=11.5, fill=MUTED)
acc(566, "Resolution", "“Thursday” → 2026-11-12  (anchor: message time, America/Chicago, rule weekday_bare)", "Unresolved example: “after approval” → event condition, kept as raw text", h=72)
acc(648, "Reconciliation", "CREATE_TASK “Train entity model” (owner Bianca) + ADD_DEPENDENCY on T-1", "Referent T-1 matched by overlap “dataset” (score shown) · a rule trace, not model reasoning", h=72)
# provenance
s.r(dx + 20, 730, dw - 40, 118, fill=PANEL, stroke=PANEL, rx=8)
s.t(dx + 34, 754, "Provenance", size=13, weight=700)
x = dx + 34
for lab, c_ in (("neural", ("#e6f4ea", "#a9d6b8", GREEN)), ("rule", ("#e8f0fb", "#b8cdee", BLUE)), ("scripted", ("#fff4d6", "#e8cf85", "#7a5c00")), ("human", ("#efe9ff", "#b8a8f0", "#4b3bb0"))):
    x += s.chip(x, 762, lab, fill=c_[0], stroke=c_[1], ink=c_[2], size=11) + 6
s.t(x + 6, 777, "← every result carries exactly one of these", size=11, fill=MUTED, italic=True)
s.t(dx + 34, 800, "entity: entity_v2_three_class · epoch3_sqrt_weighted · provisional SILVER · mps", size=11.5, fill=MUTED)
s.t(dx + 34, 818, "relations: relations-markers_sqrt · provisional SILVER · run r-0f3a · LIVE · rule linker OFF", size=11.5, fill=MUTED)
s.t(dx + 34, 836, "Never shown: attention weights or logits as an “explanation”.", size=11.5, fill=MUTED, italic=True)
s.callout(dx + 8, 122, 1); s.callout(dx + 8, 262, 2); s.callout(dx + 8, 316, 3); s.callout(dx + 8, 566, 4); s.callout(dx + 8, 730, 5)
s.save(OUT + "03_inspector_drawer.svg"); print("ok")
