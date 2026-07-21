"""
Generate a standalone, single-slide architecture diagram:

    "Order Creation & Orchestration - Architecture with Human-in-the-Loop Governance"

This diagram reflects the ACTUAL implementation (as running locally), not a
generic reference:

  Intake         : PO text / email paste + Excel upload -> rule-based, offline,
                   confidence-scored extraction -> identity & account resolution
                   -> intake resolver (obsolete-SKU substitution, SKU match,
                   invalid qty, UOM conversion, unresolved buyer, ship-to)
  Experience     : CSR workspace - decision cards, one-click actions, audit viewer
  Orchestration  : resumable pipeline / state machine running the 8 decision
                   stages in real order (Buyer Authorization -> Product Match ->
                   Compliance -> Pricing -> Credit -> Inventory -> Shipments ->
                   Approval [last]); pauses on first exception, resumes on CSR
                   decision; straight-through when clean
  Governance     : Exception Governance & Human-in-the-Loop - routes each
                   exception to its owner with severity + SLA
  Order creation : Order Execution -> ERP / OMS / WMS / TMS / SMTP + audit & docs
  Data           : governed master-data workbooks read by every decision

Output: demo/Order-Creation-Orchestration-Architecture.pptx
"""
import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.oxml.ns import qn

# ── Palette ───────────────────────────────────────────────────────────────────
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
    tf.margin_left = Inches(0.04); tf.margin_right = Inches(0.04); tf.margin_top = Inches(0.01); tf.margin_bottom = Inches(0.01)
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
txt(s, 0.35, 0.13, 9.0, 0.22, [[("SOLUTION ARCHITECTURE", 10, YELLOW, T, F)]])
txt(s, 0.35, 0.33, 12.6, 0.4,
    [[("Order Creation & Orchestration \u2014 Architecture ", 18, WHITE, T, F),
      ("with Human-in-the-Loop Governance", 18, YELLOW, T, F)]])

# ── geometry ──────────────────────────────────────────────────────────────────
LX, LW = 0.33, 1.34
MX, MW = 1.82, 9.18
XR, XRW = 11.12, 1.9
MCX = MX + MW / 2

L1 = (0.98, 1.30, "INTAKE\n& RESOLUTION", BLUE)
L2 = (2.36, 0.46, "EXPERIENCE\nCSR WORKSPACE", TEAL)
L3 = (2.90, 1.86, "ORCHESTRATION", YELLOW)
L4 = (4.84, 0.40, "GOVERNANCE", RED)
L5 = (5.32, 0.86, "ORDER CREATION\n& DOWNSTREAM", GREEN)
L6 = (6.26, 0.92, "DATA\nFOUNDATION", PURPLE)


def tier(band):
    y, h, name, color = band
    b = box(s, LX, y, LW, h, fill=PANEL)
    box(s, LX, y, 0.06, h, fill=color, radius=False)
    fill_text(b, [[(w, 8.5, WHITE, T, F)] for w in name.split("\n")], ls=0.98)


for b in (L1, L2, L3, L4, L5, L6):
    tier(b)


def flowbox(x, y, w, h, title, accent, lines):
    box(s, x, y, w, h, fill=PANEL, line_color=LINE, line_w=0.6)
    box(s, x, y, w, 0.05, fill=accent, radius=False)
    txt(s, x + 0.1, y + 0.09, w - 0.2, 0.2, [[(title, 7.6, accent, T, F)]])
    txt(s, x + 0.1, y + 0.31, w - 0.2, h - 0.35, [[(ln, 6.5, GREY, F, F)] for ln in lines], ls=1.03)


# ── L1 INTAKE (4-step horizontal flow) ───────────────────────────────────────
y = L1[0]
txt(s, MX + 0.02, y + 0.02, 8.0, 0.2, [[("INTAKE \u2014 raw PO \u2192 extracted \u2192 resolved \u2192 CSR-cleared", 8, YELLOW, T, F)]])
fbw = 1.98; fby = y + 0.30; fbh = 0.90
xs = [MX + 0.05, MX + 0.05 + (fbw + 0.36), MX + 0.05 + 2 * (fbw + 0.36), MX + 0.05 + 3 * (fbw + 0.36)]
flowbox(xs[0], fby, fbw, fbh, "PO INTAKE", BLUE,
        ["\u2022 PO text / email (paste)", "\u2022 Excel PO (.xlsx / .xls)", "extensible: PDF \u00b7 scan"])
flowbox(xs[1], fby, fbw, fbh, "EXTRACTION", BLUE,
        ["Rule-based \u00b7 offline", "confidence-scored", "+ Excel parser"])
flowbox(xs[2], fby, fbw, fbh, "RESOLUTION", TEAL,
        ["company/email \u2192 customer", "account hierarchy \u00b7 buyer", "ship-to match"])
flowbox(xs[3], fby, fbw, fbh, "INTAKE GATES  (CSR)", AMBER,
        ["obsolete \u2192 substitute \u00b7 SKU", "invalid qty \u00b7 UOM convert", "unresolved buyer \u00b7 ship-to"])
for i in range(3):
    chev(s, xs[i] + fbw + 0.02, fby + 0.34, 0.32, 0.22, color=BLUE)

# ── L2 EXPERIENCE ─────────────────────────────────────────────────────────────
y, h = L2[0], L2[1]
eb = box(s, MX, y, MW, h, fill=PANEL2, line_color=TEAL, line_w=1)
fill_text(eb, [[("CSR WORKSPACE  ", 9.5, WHITE, T, F),
                ("decision cards \u00b7 one-click actions (Approve \u00b7 Reject \u00b7 Escalate \u00b7 Correct \u00b7 Pick \u00b7 Enter) \u00b7 live agent panels \u00b7 audit viewer",
                 8, GREY, F, F)]])

# ── L3 ORCHESTRATION ─────────────────────────────────────────────────────────
y, h = L3[0], L3[1]
box(s, MX, y, MW, h, fill=BG2, line_color=LINE, line_w=0.8)
txt(s, MX + 0.12, y + 0.05, MW - 0.24, 0.22,
    [[("ORCHESTRATION ENGINE  ", 9.5, YELLOW, T, F),
      ("\u2014 resumable pipeline / state machine  \u00b7  pauses on first exception  \u00b7  resumes on CSR decision  \u00b7  Approval runs LAST",
       7.8, GREY, F, T)]])
stages = [
    ("1  Buyer\nAuthorization", "unauthorized \u00b7 cost ctr"),
    ("2  Product\nMatch", "obsolete \u00b7 UOM"),
    ("3  Compliance\n& SDS", "restriction \u00b7 SDS"),
    ("4  Pricing\n& Promo", "margin \u00b7 discount"),
    ("5  Credit", "credit hold"),
    ("6  Inventory\nChecks", "shortage \u00b7 alloc"),
    ("7  Shipments", "serviceability \u00b7 SLA"),
    ("8  Approval", "budget \u00b7 matrix"),
]
n = len(stages); sg = 0.08; sw = (MW - 0.24 - sg * (n - 1)) / n; sx0 = MX + 0.12; sty = y + 0.36
for i, (nm, exc) in enumerate(stages):
    b = box(s, sx0 + i * (sw + sg), sty, sw, 0.74, fill=PANEL2, line_color=YELLOW, line_w=0.7)
    fill_text(b, [[(ln, 7.2, WHITE, T, F)] for ln in nm.split("\n")] + [[(exc, 5.8, DGREY, F, T)]], ls=0.96)
    if i < n - 1:
        chev(s, sx0 + i * (sw + sg) + sw - 0.03, sty + 0.27, sg + 0.05, 0.2, color=YELLOW)
# two behaviours
pby = y + 1.24; ph = 0.5; halfw = (MW - 0.24 - 0.16) / 2
pb1 = box(s, MX + 0.12, pby, halfw, ph, fill=PANEL, line_color=GREEN, line_w=1)
box(s, MX + 0.12, pby, 0.07, ph, fill=GREEN, radius=False)
txt(s, MX + 0.28, pby + 0.06, halfw - 0.3, 0.4,
    [[("\u2713 Straight-through", 8.5, GREEN, T, F), ("  \u2014 all gates pass \u2192 autonomous \u2192 order creation", 7.6, GREY, F, F)]], ls=0.95)
pb2x = MX + 0.12 + halfw + 0.16
pb2 = box(s, pb2x, pby, halfw, ph, fill=PANEL, line_color=AMBER, line_w=1)
box(s, pb2x, pby, 0.07, ph, fill=AMBER, radius=False)
txt(s, pb2x + 0.16, pby + 0.06, halfw - 0.3, 0.4,
    [[("\u26A0 Human-in-the-loop", 8.5, AMBER, T, F), ("  \u2014 exception pauses \u2192 CSR decides \u2192 resumes", 7.6, GREY, F, F)]], ls=0.95)

# ── L4 GOVERNANCE bar ─────────────────────────────────────────────────────────
y, h = L4[0], L4[1]
gb = box(s, MX, y, MW, h, fill=PANEL, line_color=RED, line_w=1)
box(s, MX, y, 0.07, h, fill=RED, radius=False)
fill_text(gb, [[("EXCEPTION GOVERNANCE & HUMAN-IN-THE-LOOP   ", 8.5, RED, T, F),
                ("routes every exception to its owner with severity + SLA (governance master \u00b7 severity matrix \u00b7 role routing)",
                 7.8, GREY, F, F)]], align=PP_ALIGN.LEFT)

# ── L5 ORDER CREATION & DOWNSTREAM ───────────────────────────────────────────
y, h = L5[0], L5[1]
txt(s, MX + 0.02, y + 0.02, 8.0, 0.2, [[("ORDER CREATION & DOWNSTREAM", 8, YELLOW, T, F)]])
oe = box(s, MX + 0.05, y + 0.26, 2.15, 0.52, fill=PANEL2, line_color=GREEN, line_w=1.1)
fill_text(oe, [[("ORDER EXECUTION", 8.5, WHITE, T, F)], [("create sales order", 7, GREY, F, F)]])
chev(s, MX + 2.24, y + 0.42, 0.32, 0.2, color=GREEN)
ds = ["ERP\nsales order", "OMS\nrequest", "WMS\npick ticket", "TMS\nshipment + track", "SMTP\nconfirmation", "Audit\n& documents"]
dx0 = MX + 2.72; dn = len(ds); dg = 0.08; dw = (MW - 2.72 - 0.05 - dg * (dn - 1)) / dn
for i, d in enumerate(ds):
    b = box(s, dx0 + i * (dw + dg), y + 0.26, dw, 0.52, fill=PANEL2, line_color=LINE, line_w=0.7)
    fill_text(b, [[(ln, 6.8, WHITE, T, F)] for ln in d.split("\n")], ls=0.95)

# ── L6 DATA FOUNDATION ───────────────────────────────────────────────────────
y, h = L6[0], L6[1]
box(s, MX, y, MW, h, fill=BG2, line_color=PURPLE, line_w=0.9)
txt(s, MX + 0.12, y + 0.06, MW - 0.24, 0.2,
    [[("GOVERNED MASTER DATA  ", 8.5, YELLOW, T, F),
      ("\u2014 read by every decision (the data process); change the data, not the code", 7.6, GREY, F, T)]])
ent = ["Product\ncatalog\u00b7subs\u00b7UOM", "Customer\n& Ship-to", "Buyer", "Pricing", "Credit", "Inventory",
       "Logistics", "Budget &\nApproval", "Compliance\n& SDS", "Execution\nendpoints", "Governance\nmatrix"]
en = len(ent); eg = 0.06; ew = (MW - 0.24 - eg * (en - 1)) / en; ex0 = MX + 0.12; ety = y + 0.35
for i, e in enumerate(ent):
    b = box(s, ex0 + i * (ew + eg), ety, ew, 0.48, fill=PANEL, line_color=LINE, line_w=0.6)
    fill_text(b, [[(ln, 6.3, GREY, T, F)] for ln in e.split("\n")], ls=0.95)

# ── vertical spine + data-read arrow ──────────────────────────────────────────
for gy in (L1[0] + L1[1], L2[0] + L2[1], L3[0] + L3[1], L4[0] + L4[1]):
    down(s, MCX - 0.16, gy - 0.02, 0.32, 0.12, color=YELLOW)
conn(s, MX - 0.06, L6[0], MX - 0.06, L3[0] + L3[1], color=PURPLE, w=1.1, dash='dash', tail=True)

# ── cross-cutting rail ───────────────────────────────────────────────────────
cc_y = L1[0]; cc_h = (L5[0] + L5[1]) - L1[0]
box(s, XR, cc_y, XRW, cc_h, fill=PANEL)
box(s, XR, cc_y, XRW, 0.09, fill=YELLOW, radius=False)
txt(s, XR + 0.12, cc_y + 0.13, XRW - 0.24, 0.22, [[("CROSS-CUTTING", 8.5, YELLOW, T, F)]])
cross = [("Human-in-the-loop\ncontrol", AMBER), ("Exception governance\n& SLA routing", RED),
         ("Audit &\ntraceability", BLUE), ("Confidence\nscoring", TEAL), ("Resumable\nstate machine", GREEN)]
inner = cc_h - 0.46; ch = (inner - 0.4) / 5
for i, (t, col) in enumerate(cross):
    yy = cc_y + 0.44 + i * (ch + 0.1)
    b = box(s, XR + 0.12, yy, XRW - 0.24, ch, fill=PANEL2, line_color=LINE, line_w=0.6)
    box(s, XR + 0.12, yy, 0.05, ch, fill=col, radius=False)
    fill_text(b, [[(ln, 7.6, WHITE, T, F)] for ln in t.split("\n")], ls=0.95)

# ── footer legend ────────────────────────────────────────────────────────────
txt(s, 0.35, 7.2, 12.6, 0.24,
    [[("solid = order flow    \u00b7    ", 8, YELLOW, F, T),
      ("dashed purple = master-data reads    \u00b7    ", 8, PURPLE, F, T),
      ("green = straight-through (autonomous)    \u00b7    ", 8, GREEN, F, T),
      ("amber = human-in-the-loop decision", 8, AMBER, F, T)]])

out = os.path.join("demo", "Order-Creation-Orchestration-Architecture.pptx")
prs.save(out)
print("Saved:", out, "slides:", len(prs.slides._sldIdLst))
