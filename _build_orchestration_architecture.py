"""
Generate a standalone, single-slide architecture diagram:

    "Order Creation & Orchestration - Architecture with Human-in-the-Loop Governance"

MULTI-AGENT view, reflecting the ACTUAL implementation (as running locally):
each process is a named specialist AI agent (as shown in the app UI), all
coordinated by an Orchestrator over a shared context.

  Agents (as named in the app):
    Intake Agent · Customer Validation Agent · Product Matching Agent ·
    Pricing & Promo Agent · Credit Agent · Inventory Agent · Shipments Agent ·
    Approvals Agent · Exception Governance Agent · Order Execution Agent

Output: demo/Order-Creation-Orchestration-Architecture.pptx
"""
import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.oxml.ns import qn

BG     = RGBColor(0x14, 0x14, 0x1E)
BG2    = RGBColor(0x0E, 0x0E, 0x16)
PANEL  = RGBColor(0x22, 0x22, 0x30)
PANEL2 = RGBColor(0x2E, 0x2E, 0x40)
YELLOW = RGBColor(0xFF, 0xE6, 0x00)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
GREY   = RGBColor(0xC2, 0xC2, 0xD0)
DGREY  = RGBColor(0x8C, 0x8C, 0x9B)
GREEN  = RGBColor(0x35, 0xC7, 0x59)
RED    = RGBColor(0xFF, 0x5A, 0x5A)
AMBER  = RGBColor(0xFF, 0xB0, 0x20)
BLUE   = RGBColor(0x4A, 0x9E, 0xFF)
TEAL   = RGBColor(0x33, 0xC9, 0xC9)
PURPLE = RGBColor(0xA9, 0x7B, 0xFF)
LINE   = RGBColor(0x3C, 0x3C, 0x4E)
FONT = "Segoe UI"
BOT = "\U0001F916"          # robot / agent icon (matches the app)
T, F = True, False

prs = Presentation()
prs.slide_width = Inches(13.333); prs.slide_height = Inches(7.5)
SW, SH = prs.slide_width, prs.slide_height
BLANK = prs.slide_layouts[6]


def _fill(shape, color, line_color=None, line_w=None):
    if color is None: shape.fill.background()
    else: shape.fill.solid(); shape.fill.fore_color.rgb = color
    if line_color is None: shape.line.fill.background()
    else: shape.line.color.rgb = line_color; shape.line.width = Pt(line_w or 1)
    shape.shadow.inherit = False


def box(s, x, y, w, h, fill=PANEL, line_color=None, line_w=None, radius=True, adj=0.06):
    shp = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
                             Inches(x), Inches(y), Inches(w), Inches(h))
    _fill(shp, fill, line_color, line_w)
    if radius:
        try: shp.adjustments[0] = adj
        except Exception: pass
    shp.text_frame.word_wrap = True
    return shp


def txt(s, x, y, w, h, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, ls=1.0, sa=0):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = True; tf.vertical_anchor = anchor
    tf.margin_left = 0; tf.margin_right = 0; tf.margin_top = 0; tf.margin_bottom = 0
    first = True
    for para in runs:
        p = tf.paragraphs[0] if first else tf.add_paragraph(); first = False
        p.alignment = align; p.space_after = Pt(sa); p.space_before = Pt(0); p.line_spacing = ls
        if isinstance(para, tuple): para = [para]
        for (t, sz, col, bold, ital) in para:
            r = p.add_run(); r.text = t
            r.font.size = Pt(sz); r.font.color.rgb = col; r.font.bold = bold; r.font.italic = ital; r.font.name = FONT
    return tb


def fill_text(shape, lines, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, ls=1.0):
    tf = shape.text_frame; tf.word_wrap = True; tf.vertical_anchor = anchor
    tf.margin_left = Inches(0.03); tf.margin_right = Inches(0.03); tf.margin_top = Inches(0.01); tf.margin_bottom = Inches(0.01)
    first = True
    for line in lines:
        p = tf.paragraphs[0] if first else tf.add_paragraph(); first = False
        p.alignment = align; p.space_after = Pt(0); p.space_before = Pt(0); p.line_spacing = ls
        if isinstance(line, tuple): line = [line]
        for (t, sz, col, bold, ital) in line:
            r = p.add_run(); r.text = t
            r.font.size = Pt(sz); r.font.color.rgb = col; r.font.bold = bold; r.font.italic = ital; r.font.name = FONT


def _lp(c, color, w, dash=None, tail=False, head=False):
    ln = c.line; ln.color.rgb = color; ln.width = Pt(w)
    el = ln._get_or_add_ln()
    if dash: el.append(el.makeelement(qn('a:prstDash'), {'val': dash}))
    if head: el.append(el.makeelement(qn('a:headEnd'), {'type': 'triangle', 'w': 'med', 'len': 'med'}))
    if tail: el.append(el.makeelement(qn('a:tailEnd'), {'type': 'triangle', 'w': 'med', 'len': 'med'}))


def conn(s, x1, y1, x2, y2, color=YELLOW, w=1.4, dash=None, tail=True, head=False):
    c = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.shadow.inherit = False; _lp(c, color, w, dash, tail, head); return c


def chev(s, x, y, w, h=0.2, color=YELLOW):
    a = s.shapes.add_shape(MSO_SHAPE.CHEVRON, Inches(x), Inches(y), Inches(w), Inches(h)); _fill(a, color); return a


def down(s, x, y, w=0.32, h=0.14, color=YELLOW):
    a = s.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, Inches(x), Inches(y), Inches(w), Inches(h)); _fill(a, color); return a


# ── slide + title ─────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
bgr = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SW, SH); _fill(bgr, BG)
bgr.text_frame.paragraphs[0].text = ""
box(s, 0, 0, 13.333, 0.10, fill=YELLOW, radius=False)
txt(s, 0.35, 0.12, 10.0, 0.22, [[("MULTI-AGENT SOLUTION ARCHITECTURE", 10, YELLOW, T, F)]])
txt(s, 0.35, 0.32, 12.6, 0.4,
    [[("Order Creation & Orchestration \u2014 Architecture ", 18, WHITE, T, F),
      ("with Human-in-the-Loop Governance", 18, YELLOW, T, F)]])

# ── geometry ──────────────────────────────────────────────────────────────────
LX, LW = 0.33, 1.28
MX = 1.72
MW = 11.28                     # main content width (full)
MCX = MX + MW / 2

L1 = (0.82, 0.80, "PO\nINTAKE", BLUE)
L3 = (1.72, 3.50, "ORCHESTRATION\n& HUMAN\nDECISIONS", YELLOW)
L5 = (5.34, 1.12, "ORDER CREATION\n& DOWNSTREAM", GREEN)


def tier(band):
    y, h, name, color = band
    b = box(s, LX, y, LW, h, fill=PANEL)
    box(s, LX, y, 0.06, h, fill=color, radius=False)
    fill_text(b, [[(w, 8.3, WHITE, T, F)] for w in name.split("\n")], ls=0.98)


for b in (L3, L5):
    tier(b)


def flowbox(x, y, w, h, title, accent, lines):
    box(s, x, y, w, h, fill=PANEL, line_color=LINE, line_w=0.6)
    box(s, x, y, w, 0.05, fill=accent, radius=False)
    txt(s, x + 0.1, y + 0.09, w - 0.2, 0.2, [[(title, 7.8, accent, T, F)]], align=PP_ALIGN.CENTER)
    txt(s, x + 0.1, y + 0.31, w - 0.2, h - 0.35, [[(ln, 6.6, GREY, F, F)] for ln in lines], ls=1.04, align=PP_ALIGN.CENTER)


# ── L1 PO INTAKE (input) — feeds the orchestration below ──────────────────────
y = L1[0]
flowbox(MX + 0.05, y + 0.16, MW - 0.1, 0.52, "CUSTOMER INTERACTION LAYER", BLUE,
        ["Received as Email PO, Excel PO etc.  \u2192  handed to the orchestration below"])

# ── L3 ORCHESTRATION — all agents contained in one orchestration box ──────────
y, h = L3[0], L3[1]
box(s, MX, y, MW, h, fill=BG2, line_color=YELLOW, line_w=0.9)
txt(s, MX + 0.14, y + 0.18, MW - 0.28, 0.26,
    [[(BOT + "  ORCHESTRATOR  ", 9.6, YELLOW, T, F),
      ("\u2014 coordinates the specialist AI agents over a shared context", 8, GREY, F, F)]],
    align=PP_ALIGN.CENTER)
down(s, MCX - 0.14, y + 0.56, 0.28, 0.12, color=YELLOW)

agents = [
    ("Intake", "Agent", "reads PO \u00b7 extracts fields"),
    ("Customer", "Validation Agent", "account \u00b7 buyer auth \u00b7 ship-to"),
    ("Product", "Matching Agent", "catalog \u00b7 compliance"),
    ("Pricing &", "Promo Agent", "contract \u00b7 promo \u00b7 margin"),
    ("Credit", "Agent", "limit \u00b7 terms \u00b7 risk"),
    ("Inventory", "Agent", "DC stock \u00b7 ATP \u00b7 alloc"),
    ("Shipments", "Agent", "carrier \u00b7 service \u00b7 SLA"),
    ("Optimization", "Agent", "plan A/B/C \u00b7 freight"),
    ("Approvals", "Agent", "budget \u00b7 matrix (last)"),
]
na = len(agents); ag = 0.08; aw = (MW - 0.28 - ag * (na - 1)) / na; ax0 = MX + 0.14; aty = y + 0.74; ah = 1.16
for i, (n1, n2, focus) in enumerate(agents):
    b = box(s, ax0 + i * (aw + ag), aty, aw, ah, fill=PANEL, line_color=YELLOW, line_w=0.8)
    box(s, ax0 + i * (aw + ag), aty, aw, 0.05, fill=YELLOW, radius=False)
    fill_text(b, [[(BOT + " ", 8.3, YELLOW, T, F), (n1, 6.8, WHITE, T, F)],
                  [(n2, 6.8, WHITE, T, F)],
                  [(focus, 5.6, GREY, F, F)]], ls=1.16)
    if i < na - 1:
        chev(s, ax0 + i * (aw + ag) + aw - 0.02, aty + 0.49, ag + 0.06, 0.18, color=YELLOW)

# ── HUMAN DECISION LAYER wired to EVERY agent (inside the orchestration box) ──
rail_y = y + 2.55; rail_h = 0.62
for i in range(na):
    cx = ax0 + i * (aw + ag) + aw / 2
    conn(s, cx, aty + ah, cx, rail_y, color=AMBER, w=1.2, dash='dash', tail=True, head=True)
rb = box(s, MX + 0.14, rail_y, MW - 0.28, rail_h, fill=PANEL, line_color=AMBER, line_w=1.3)
box(s, MX + 0.14, rail_y, MW - 0.28, 0.06, fill=AMBER, radius=False)
fill_text(rb, [[("\u26A0  HUMAN DECISION LAYER   ", 9.2, AMBER, T, F),
                ("\u2014 every agent pauses on exception for a human decision, then the pipeline resumes   (all agents pass \u21d2 straight-through)",
                 7.6, GREY, F, F)]],
          align=PP_ALIGN.CENTER)

# ── L5 ORDER CREATION & DOWNSTREAM ───────────────────────────────────────────
y, h = L5[0], L5[1]
txt(s, MX + 0.02, y + 0.04, 9.0, 0.2, [[("ORDER CREATION & DOWNSTREAM \u2014 the ", 8, YELLOW, T, F),
                                        (BOT + " Order Execution Agent", 8, WHITE, T, F)]])
oe = box(s, MX + 0.05, y + 0.34, 2.35, 0.64, fill=PANEL2, line_color=GREEN, line_w=1.1)
fill_text(oe, [[(BOT + " Order Execution", 8, WHITE, T, F)], [("Agent \u00b7 create sales order", 7, GREY, F, F)]])
chev(s, MX + 2.44, y + 0.56, 0.3, 0.2, color=GREEN)
ds = ["ERP\nsales order", "OMS\nrequest", "WMS\npick ticket", "TMS\nshipment+track", "Email\nnotification"]
dx0 = MX + 2.90; dn = len(ds); dg = 0.10; dw = (MW - 2.90 - 0.05 - dg * (dn - 1)) / dn
for i, d in enumerate(ds):
    b = box(s, dx0 + i * (dw + dg), y + 0.34, dw, 0.64, fill=PANEL2, line_color=LINE, line_w=0.7)
    fill_text(b, [[(ln, 6.8, WHITE, T, F)] for ln in d.split("\n")], ls=0.95)

# ── vertical spine ────────────────────────────────────────────────────────────
for gy in (L1[0] + L1[1], L3[0] + L3[1]):
    down(s, MCX - 0.16, gy - 0.02, 0.32, 0.12, color=YELLOW)

# ── footer legend ────────────────────────────────────────────────────────────
txt(s, 0.35, 6.66, 12.6, 0.24,
    [[(BOT + " = specialist AI agent    \u00b7    ", 8, WHITE, F, T),
      ("green = straight-through (autonomous)    \u00b7    ", 8, GREEN, F, T),
      ("amber = human-in-the-loop decision", 8, AMBER, F, T)]])

out = os.path.join("demo", "Order-Creation-Orchestration-Architecture.pptx")
prs.save(out)
print("Saved:", out, "slides:", len(prs.slides._sldIdLst))
