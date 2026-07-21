"""
Generate a standalone, single-slide architecture diagram:

    "Order Creation & Orchestration - Architecture with Human-in-the-Loop Governance"

Layout follows the business reference diagram:
  - Customer Interaction Layer  (4 PO intake methods: Email / PDF / Excel / Scanned)
  - Decision Layer              (9 agent stages, each with what it does + a worked
                                 example + human-in-the-loop CSR asks where policy
                                 or ambiguity requires a decision)
  - Execution Orchestration Layer (Order creation / Communication / Exception handling)
  - Confirmed order outcome

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
HDR    = RGBColor(0x30, 0x3B, 0x52)
YELLOW = RGBColor(0xFF, 0xE6, 0x00)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
GREY   = RGBColor(0xC2, 0xC2, 0xD0)
DGREY  = RGBColor(0x8A, 0x8A, 0x99)
GREEN  = RGBColor(0x35, 0xC7, 0x59)
RED    = RGBColor(0xFF, 0x5A, 0x5A)
AMBER  = RGBColor(0xFF, 0xB0, 0x20)
BLUE   = RGBColor(0x4A, 0x9E, 0xFF)
TEAL   = RGBColor(0x33, 0xC9, 0xC9)
PURPLE = RGBColor(0xA9, 0x7B, 0xFF)
LINE   = RGBColor(0x3C, 0x3C, 0x4E)
FONT = "Segoe UI"

prs = Presentation()
prs.slide_width = Inches(13.333); prs.slide_height = Inches(7.5)
SW, SH = prs.slide_width, prs.slide_height
BLANK = prs.slide_layouts[6]

T, F = True, False


def _fill(shape, color, line_color=None, line_w=None):
    if color is None: shape.fill.background()
    else: shape.fill.solid(); shape.fill.fore_color.rgb = color
    if line_color is None: shape.line.fill.background()
    else: shape.line.color.rgb = line_color; shape.line.width = Pt(line_w or 1)
    shape.shadow.inherit = False


def box(s, x, y, w, h, fill=PANEL, line_color=None, line_w=None, radius=True, adj=0.05):
    shp = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
                             Inches(x), Inches(y), Inches(w), Inches(h))
    _fill(shp, fill, line_color, line_w)
    if radius:
        try: shp.adjustments[0] = adj
        except Exception: pass
    shp.text_frame.word_wrap = True
    return shp


def txt(s, x, y, w, h, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, line_spacing=1.0, space_after=0):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = True; tf.vertical_anchor = anchor
    tf.margin_left = 0; tf.margin_right = 0; tf.margin_top = 0; tf.margin_bottom = 0
    first = True
    for para in runs:
        p = tf.paragraphs[0] if first else tf.add_paragraph(); first = False
        p.alignment = align; p.space_after = Pt(space_after); p.space_before = Pt(0); p.line_spacing = line_spacing
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


def _lp(conn, color, w, dash=None, tail=False, head=False):
    ln = conn.line; ln.color.rgb = color; ln.width = Pt(w)
    el = ln._get_or_add_ln()
    if dash: el.append(el.makeelement(qn('a:prstDash'), {'val': dash}))
    if head: el.append(el.makeelement(qn('a:headEnd'), {'type': 'triangle', 'w': 'med', 'len': 'med'}))
    if tail: el.append(el.makeelement(qn('a:tailEnd'), {'type': 'triangle', 'w': 'med', 'len': 'med'}))


def down(s, x, y, w=0.34, h=0.16, color=YELLOW):
    a = s.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, Inches(x), Inches(y), Inches(w), Inches(h)); _fill(a, color); return a


# ── slide bg ──
s = prs.slides.add_slide(BLANK)
bgr = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SW, SH); _fill(bgr, BG)
bgr.text_frame.paragraphs[0].text = ""
box(s, 0, 0, 13.333, 0.10, fill=YELLOW, radius=False)

# ── title ──
txt(s, 0.4, 0.14, 9.0, 0.22, [[("SOLUTION ARCHITECTURE", 10, YELLOW, T, F)]])
txt(s, 0.4, 0.34, 12.6, 0.4,
    [[("Order Creation & Orchestration \u2014 Architecture ", 18, WHITE, T, F),
      ("with Human-in-the-Loop Governance", 18, YELLOW, T, F)]])

# ── CSR persona + speech bubble ──
head = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(4.55), Inches(0.72), Inches(0.16), Inches(0.16)); _fill(head, YELLOW)
body = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(4.5), Inches(0.88), Inches(0.26), Inches(0.14)); _fill(body, YELLOW)
bub = box(s, 4.9, 0.68, 3.95, 0.34, fill=PANEL2, line_color=YELLOW, line_w=0.75)
fill_text(bub, [[("\u201cNeed 250 units of SKU SV-200  \u00b7  deliver to ZIP 75201\u201d", 8.5, WHITE, F, T)]], align=PP_ALIGN.LEFT)
txt(s, 4.5, 1.02, 0.5, 0.16, [[("CSR", 6.5, DGREY, T, F)]], align=PP_ALIGN.CENTER)

# ── Customer Interaction Layer band ──
band = box(s, 0.3, 1.10, 12.73, 0.30, fill=BLUE, radius=False)
txt(s, 5.35, 1.15, 2.6, 0.22, [[("Customer Interaction Layer", 9.5, BG, T, T)]], align=PP_ALIGN.CENTER)
for x, lbl in [(0.55, "\u2709  Email PO"), (3.05, "\u25A4  PDF PO"), (8.35, "\u25A6  Excel PO"), (10.9, "\u2317  Scanned PO")]:
    txt(s, x, 1.16, 2.1, 0.22, [[(lbl, 9, BG, T, F)]])

# ── Decision Layer box ──
DX, DY, DW, DH = 0.3, 1.46, 12.73, 3.94
box(s, DX, DY, DW, DH, fill=BG2, line_color=LINE, line_w=1)
txt(s, DX, DY + 0.05, DW, 0.24, [[("\u2699  Decision Layer", 11, YELLOW, T, F)]], align=PP_ALIGN.CENTER)

cols = [
    ("Intake", BLUE, [
        ("Extracts:", 6.6, YELLOW, T, F), ("\u2022 SKU", 6.3, GREY, F, F), ("\u2022 Qty", 6.3, GREY, F, F),
        ("\u2022 Ship-to ZIP", 6.3, GREY, F, F), ("\u2022 Delivery date", 6.3, GREY, F, F),
        ("Example O/P:", 6.3, YELLOW, T, F), ("SKU \u2192 SV-200", 6.3, WHITE, F, F),
        ("Qty \u2192 250", 6.3, WHITE, F, F), ("ZIP \u2192 75201", 6.3, WHITE, F, F)]),
    ("Customer\nValidation", BLUE, [
        ("Identifies:", 6.6, YELLOW, T, F), ("\u2022 Customer tier", 6.3, GREY, F, F), ("\u2022 Account type", 6.3, GREY, F, F),
        ("\u2022 Contractor", 6.3, GREY, F, F), ("\u2022 Buying history", 6.3, GREY, F, F),
        ("Example O/P:", 6.3, YELLOW, T, F), ("ABC Supply Co", 6.3, WHITE, F, F),
        ("Key account", 6.3, WHITE, F, F), ("Net 45 terms", 6.3, WHITE, F, F)]),
    ("Product\nMatch", TEAL, [
        ("Validates:", 6.6, YELLOW, T, F), ("\u2022 SKU active", 6.3, GREY, F, F), ("\u2022 UOM conversion", 6.3, GREY, F, F),
        ("\u2022 Compatibility", 6.3, GREY, F, F), ("\u2022 Substitutes", 6.3, GREY, F, F),
        ("Example:", 6.3, YELLOW, T, F), ("AI: SV-200 obsolete", 6.3, WHITE, F, F), ("\u2192 recommend SV-220", 6.3, WHITE, F, F),
        ("CSR > Approve /", 6.2, AMBER, F, T), ("modify / escalate", 6.2, AMBER, F, T)]),
    ("Pricing &\nPromo", TEAL, [
        ("Determines:", 6.6, YELLOW, T, F), ("\u2022 Contract price", 6.3, GREY, F, F), ("\u2022 Rebates", 6.3, GREY, F, F),
        ("\u2022 Volume discounts", 6.3, GREY, F, F), ("\u2022 Promos", 6.3, GREY, F, F), ("\u2022 Freight terms", 6.3, GREY, F, F),
        ("Example:", 6.3, YELLOW, T, F), ("List $120 \u00b7 Contract", 6.3, WHITE, F, F), ("$105 \u00b7 Vol 5% \u2192 $99.75", 6.3, WHITE, F, F),
        ("CSR > discount >10%:", 6.2, AMBER, F, T), ("\u201cmargin impact $12K \u2014", 6.2, AMBER, F, T), ("approve exception?\u201d", 6.2, AMBER, F, T)]),
    ("Approval", PURPLE, [
        ("Evaluates:", 6.6, YELLOW, T, F), ("\u2022 Margin rules", 6.3, GREY, F, F), ("\u2022 Discount limits", 6.3, GREY, F, F),
        ("\u2022 Approval matrix", 6.3, GREY, F, F), ("\u2022 Auto-approval", 6.3, GREY, F, F),
        ("Example:", 6.3, YELLOW, T, F), ("Order < $100K \u00b7", 6.3, WHITE, F, F), ("Margin > 15% \u2192", 6.3, WHITE, F, F),
        ("Auto Approval", 6.3, GREEN, T, F)]),
    ("Credit", GREEN, [
        ("Checks:", 6.6, YELLOW, T, F), ("\u2022 Credit limit", 6.3, GREY, F, F), ("\u2022 Open invoices", 6.3, GREY, F, F),
        ("\u2022 Payment risk", 6.3, GREY, F, F), ("\u2022 Fraud signals", 6.3, GREY, F, F),
        ("Example:", 6.3, YELLOW, T, F), ("Limit $500K \u00b7 avail", 6.3, WHITE, F, F), ("$410K \u2192 PASS", 6.3, WHITE, F, F),
        ("CSR > credit hold:", 6.2, AMBER, F, T), ("\u201capprove override or", 6.2, AMBER, F, T), ("send to Finance?\u201d", 6.2, AMBER, F, T)]),
    ("Inventory\nChecks", GREEN, [
        ("Checks:", 6.6, YELLOW, T, F), ("\u2022 Plant stock", 6.3, GREY, F, F), ("\u2022 DC inventory", 6.3, GREY, F, F),
        ("\u2022 In-transit", 6.3, GREY, F, F), ("\u2022 ATP", 6.3, GREY, F, F),
        ("Example:", 6.3, YELLOW, T, F), ("DC-A 350 \u00b7 DC-B 150", 6.3, WHITE, F, F), ("\u2192 avail 500 \u00b7 OK", 6.3, WHITE, F, F),
        ("CSR > shortage:", 6.2, AMBER, F, T), ("\u201c400 now, 100 next", 6.2, AMBER, F, T), ("week\u201d \u2014 CSR approves", 6.2, AMBER, F, T)]),
    ("Logistics", AMBER, [
        ("Determines:", 6.6, YELLOW, T, F), ("\u2022 ZIP serviceability", 6.3, GREY, F, F), ("\u2022 Carrier coverage", 6.3, GREY, F, F),
        ("\u2022 Delivery SLA", 6.3, GREY, F, F), ("\u2022 ETA prediction", 6.3, GREY, F, F),
        ("Example:", 6.3, YELLOW, T, F), ("ZIP 75201 \u00b7 carrier set", 6.3, WHITE, F, F), ("\u00b7 ETA Jun 29 \u2192 OK", 6.3, WHITE, F, F),
        ("CSR > ZIP unsupported:", 6.2, AMBER, F, T), ("suggest pickup; CSR", 6.2, AMBER, F, T), ("reviews customer comms", 6.2, AMBER, F, T)]),
    ("Optimization", AMBER, [
        ("Optimizes:", 6.6, YELLOW, T, F), ("\u2022 Warehouse choice", 6.3, GREY, F, F), ("\u2022 Shipment split", 6.3, GREY, F, F),
        ("\u2022 Freight cost", 6.3, GREY, F, F), ("\u2022 Inventory balance", 6.3, GREY, F, F),
        ("Example:", 6.3, YELLOW, T, F), ("A: DC-A  $1,200", 6.3, WHITE, F, F), ("B: DC-B  $1,700", 6.3, WHITE, F, F),
        ("C: split  $1,400", 6.3, WHITE, F, F)]),
]

n = len(cols); cw = 1.35; gap = (DW - 0.2 - n * cw) / (n - 1); x0 = DX + 0.1
hy = DY + 0.34; hh = 0.44; by = hy + hh + 0.04; bh = DH - (hy - DY) - hh - 0.12
for i, (title, accent, body_runs) in enumerate(cols):
    cx = x0 + i * (cw + gap)
    hb = box(s, cx, hy, cw, hh, fill=HDR, line_color=LINE, line_w=0.5)
    box(s, cx, hy, cw, 0.05, fill=accent, radius=False)
    fill_text(hb, [[(ln, 8, WHITE, T, F)] for ln in title.split("\n")], ls=0.95)
    cbb = box(s, cx, by, cw, bh, fill=PANEL, line_color=LINE, line_w=0.5)
    txt(s, cx + 0.09, by + 0.06, cw - 0.16, bh - 0.1, body_runs, line_spacing=0.98, space_after=0.5)

# ── down arrow to execution ──
ecx = 6.665
down(s, ecx - 0.17, DY + DH + 0.01, 0.34, 0.14, color=YELLOW)

# ── Execution Orchestration Layer ──
EX, EY_, EW, EH = 3.25, 5.54, 6.83, 0.98
box(s, EX, EY_, EW, EH, fill=BG2, line_color=YELLOW, line_w=1)
txt(s, EX, EY_ + 0.04, EW, 0.22, [[("\u2699  Execution Orchestration Layer", 10, YELLOW, T, F)]], align=PP_ALIGN.CENTER)
exec_cols = [
    ("Order", GREEN, "Creates:", ["ERP sales order", "OMS request", "WMS pick ticket", "Shipment order"]),
    ("Communication", BLUE, "Creates:", ["Order accepted", "Price confirmed", "ETA confirmed", "Tracking shared"]),
    ("Exception Handling", AMBER, "Resolves:", ["Inventory shortage", "Product obsolete", "ZIP not serviceable", "Approval escalation"]),
]
ecw = 2.16; egap = 0.09; ex0 = EX + 0.15; eby = EY_ + 0.30
for i, (t, col, lead, items) in enumerate(exec_cols):
    px = ex0 + i * (ecw + egap)
    cbb = box(s, px, eby, ecw, 0.60, fill=PANEL, line_color=col, line_w=0.9)
    txt(s, px + 0.12, eby + 0.05, ecw - 0.24, 0.5,
        [[(t + "  ", 7.6, WHITE, T, F), (lead, 7, col, T, F)],
         [("  ".join(items[:2]), 6.6, GREY, F, F)],
         [("  ".join(items[2:]), 6.6, GREY, F, F)]], line_spacing=0.98)

# ── exception governance strip ──
txt(s, 3.25, EY_ + EH + 0.05, 6.83, 0.2,
    [[("Product Substitution \u00b7 Pricing Exception \u00b7 Credit Hold \u00b7 Inventory Shortage \u00b7 Delivery Constraint \u00b7 Strategic Review",
       6.6, DGREY, F, T)]], align=PP_ALIGN.CENTER)

# ── confirmed outcome ──
down(s, ecx - 0.17, 6.82, 0.34, 0.14, color=GREEN)
txt(s, 3.25, 6.98, 6.83, 0.24, [[("CUSTOMER RECEIVES CONFIRMED ORDER", 11.5, YELLOW, T, F)]], align=PP_ALIGN.CENTER)
txt(s, 3.25, 7.22, 6.83, 0.2, [[("Order #SO-98765   \u00b7   ETA Jun 29   \u00b7   Tracking available", 8, GREY, F, F)]], align=PP_ALIGN.CENTER)

# ── EY-style mark ──
txt(s, 12.55, 7.08, 0.6, 0.34, [[("EY", 16, YELLOW, T, F)]], align=PP_ALIGN.RIGHT)

out = os.path.join("demo", "Order-Creation-Orchestration-Architecture.pptx")
prs.save(out)
print("Saved:", out, "slides:", len(prs.slides._sldIdLst))
