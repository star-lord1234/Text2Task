"""Tiny SVG wireframe toolkit (grayscale + 3 persona accents; status always has an icon/label, never colour alone)."""
from xml.sax.saxutils import escape

INK, MUTED, LINE, PANEL, BG, WHITE = "#1f2933", "#6b7785", "#cdd3da", "#f4f6f8", "#e9edf1", "#ffffff"
RIYA, ANU, BIA = "#6c5ce7", "#00a38c", "#e17055"          # persona accents (avatars / node borders)
AMBER, GREEN, BLUE, RED = "#b7791f", "#2f855a", "#2b6cb0", "#c53030"

class SVG:
    def __init__(self, w, h, title):
        self.w, self.h, self.parts = w, h, []
        self.title = title
    def r(self, x, y, w, h, fill=WHITE, stroke=LINE, rx=6, dash=None, sw=1, op=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        o = f' opacity="{op}"' if op else ""
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}{o}/>')
    def t(self, x, y, s, size=13, fill=INK, weight=400, anchor="start", italic=False):
        st = ' font-style="italic"' if italic else ""
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}" text-anchor="{anchor}"{st}>{escape(s)}</text>')
    def l(self, x1, y1, x2, y2, stroke=LINE, sw=1, dash=None, arrow=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        m = f' marker-end="url(#{arrow})"' if arrow else ""
        self.parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{sw}"{d}{m}/>')
    def path(self, d, stroke=LINE, sw=1.5, dash=None, arrow=None, fill="none"):
        dd = f' stroke-dasharray="{dash}"' if dash else ""
        m = f' marker-end="url(#{arrow})"' if arrow else ""
        self.parts.append(f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{dd}{m}/>')
    def c(self, x, y, r, fill=WHITE, stroke=LINE, sw=1):
        self.parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
    def chip(self, x, y, s, fill=PANEL, stroke=LINE, ink=INK, size=11, pad=8, h=20, weight=500):
        w = int(len(s) * size * 0.58) + pad * 2
        self.r(x, y, w, h, fill=fill, stroke=stroke, rx=h // 2)
        self.t(x + pad, y + h * 0.7, s, size=size, fill=ink, weight=weight)
        return w
    def avatar(self, x, y, col, ch, r=13):
        self.c(x, y, r, fill=col, stroke=col)
        self.t(x, y + 4, ch, size=12, fill=WHITE, weight=700, anchor="middle")
    def note(self, x, y, s, w=200):
        self.r(x, y, w, 24, fill="#fff8db", stroke="#e0c867", rx=3)
        self.t(x + 8, y + 16, s, size=11, fill="#7a5c00")
    def callout(self, x, y, n):
        self.c(x, y, 11, fill=INK, stroke=INK)
        self.t(x, y + 4, str(n), size=11, fill=WHITE, weight=700, anchor="middle")
    def save(self, path):
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" '
                f'font-family="-apple-system, Helvetica, Arial, sans-serif"><title>{escape(self.title)}</title>'
                f'<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{INK}"/></marker>'
                f'<marker id="ahr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{RED}"/></marker>'
                f'<marker id="ahg" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{MUTED}"/></marker></defs>'
                f'<rect width="{self.w}" height="{self.h}" fill="{BG}"/>')
        open(path, "w").write(head + "".join(self.parts) + "</svg>")

def header(s, active="Workspace", user=("Riya", RIYA, "R"), mode="SCRIPTED", w=1440):
    s.r(0, 0, w, 56, fill=WHITE, stroke=LINE, rx=0)
    s.t(20, 35, "Text2Task", size=18, weight=700)
    x = 140
    for tab in ("Workspace", "Dependencies"):
        s.t(x, 35, tab, size=14, weight=600 if tab == active else 400, fill=INK if tab == active else MUTED)
        if tab == active:
            s.l(x - 2, 50, x + len(tab) * 8 + 2, 50, stroke=INK, sw=3)
        x += len(tab) * 8 + 36
    s.t(400, 35, "Team: ML Project", size=13, fill=MUTED)
    sx = w - 800
    s.r(sx, 14, 236, 28, fill=PANEL); s.t(sx + 10, 33, "Scenario A — Simple assignment  ▾" if mode == "SCRIPTED" else "Live chat (no scenario)  ▾", size=12)
    mx = sx + 252
    s.r(mx, 14, 150, 28, fill=PANEL, stroke=LINE, rx=14)
    on_s = mode == "SCRIPTED"
    s.r(mx + 2, 16, 72, 24, fill=INK if on_s else PANEL, stroke=INK if on_s else PANEL, rx=12)
    s.t(mx + 38, 32, "Scripted", size=12, fill=WHITE if on_s else MUTED, anchor="middle", weight=600)
    s.r(mx + 76, 16, 72, 24, fill=INK if not on_s else PANEL, stroke=INK if not on_s else PANEL, rx=12)
    s.t(mx + 112, 32, "Live", size=12, fill=WHITE if not on_s else MUTED, anchor="middle", weight=600)
    ux = w - 236
    s.t(ux - 74, 33, "Active user", size=11, fill=MUTED)
    s.r(ux, 12, 216, 32, fill=WHITE, stroke=INK, rx=16)
    s.avatar(ux + 18, 28, user[1], user[2], r=12); s.t(ux + 38, 33, user[0], size=13, weight=600)
    s.t(ux + 38 + len(user[0]) * 8 + 10, 33, "Project Lead  ▾" if user[0] == "Riya" else ("Data Engineer  ▾" if user[0] == "Anushree" else "ML Engineer  ▾"), size=11, fill=MUTED)

def banner(s, kind="SCRIPTED", w=1440, y=56):
    if kind == "SCRIPTED":
        s.r(0, y, w, 28, fill="#fff4d6", stroke="#e8cf85", rx=0)
        s.t(36, y + 19, "SCRIPTED DEMO", size=12, weight=700, fill="#7a5c00")
        s.t(156, y + 19, "Entity/relation extraction is pre-written for this scenario. Reconciliation, review, history and the graph are the real code paths.", size=12, fill="#7a5c00")
    else:
        s.r(0, y, w, 28, fill="#e6f4ea", stroke="#a9d6b8", rx=0)
        s.t(36, y + 19, "LIVE", size=12, weight=700, fill=GREEN)
        s.t(86, y + 19, "Real models: entity v2 (3-class, provisional SILVER) · relations markers_sqrt (provisional) · rule linker OFF (opt-in)", size=12, fill=GREEN)
        s.t(w - 20, y + 19, "Review mode — nothing is applied without Accept", size=12, fill=GREEN, anchor="end")
