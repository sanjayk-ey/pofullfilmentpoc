"""
Generate a client-ready architecture slide deck for the
PO-to-Fulfillment Orchestration AI Accelerator.

Covers: business context, solution, high-level architecture, the AI agent team,
the master-data foundation, the orchestration pipeline, and the two processing
paths (Happy Flow / straight-through and CSR Approval / human-in-the-loop).

Output: demo/PO-Fulfillment-Orchestration-Architecture.pptx
"""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

# ── Palette (EY-inspired: near-black + signature yellow) ──────────────────────
BG       = RGBColor(0x14, 0x14, 0x1E)   # deep near-black
PANEL    = RGBColor(0x24, 0x24, 0x33)   # card panel
PANEL2   = RGBColor(0x2E, 0x2E, 0x40)   # alt card panel
YELLOW   = RGBColor(0xFF, 0xE6, 0x00)   # EY yellow
WHITE    = RGBColor(0xFF, 0xFF, 0xFF)
GREY     = RGBColor(0xB8, 0xB8, 0xC6)
DGREY    = RGBColor(0x8A, 0x8A, 0x99)
GREEN    = RGBColor(0x35, 0xC7, 0x59)
RED      = RGBColor(0xFF, 0x5A, 0x5A)
AMBER    = RGBColor(0xFF, 0xB0, 0x20)
BLUE     = RGBColor(0x4A, 0x9E, 0xFF)
LINE     = RGBColor(0x3C, 0x3C, 0x4E)

FONT = "Segoe UI"
FONT_L = "Segoe UI Light"

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
SW, SH = prs.slide_width, prs.slide_height
BLANK = prs.slide_layouts[6]


# ── Helpers ───────────────────────────────────────────────────────────────────
def slide():
    s = prs.slides.add_slide(BLANK)
    r = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SW, SH)
    r.fill.solid(); r.fill.fore_color.rgb = BG
    r.line.fill.background()
    r.shadow.inherit = False
    r.text_frame.paragraphs[0].text = ""
    return s


def _set_fill(shape, color, line_color=None, line_w=None):
    shape.fill.solid(); shape.fill.fore_color.rgb = color
    if line_color is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line_color
        shape.line.width = Pt(line_w or 1)
    shape.shadow.inherit = False


def box(s, x, y, w, h, fill=PANEL, line_color=None, line_w=None, radius=True):
    shp = s.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
        Inches(x), Inches(y), Inches(w), Inches(h))
    _set_fill(shp, fill, line_color, line_w)
    if radius:
        try:
            shp.adjustments[0] = 0.08
        except Exception:
            pass
    shp.text_frame.word_wrap = True
    return shp


def txt(s, x, y, w, h, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
        space_after=2, line_spacing=1.0):
    """runs: list of paragraphs; each paragraph is a list of (text, size, color,
    bold, italic) tuples OR a single such tuple."""
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = 0; tf.margin_right = 0
    tf.margin_top = 0; tf.margin_bottom = 0
    first = True
    for para in runs:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment = align
        p.space_after = Pt(space_after)
        p.space_before = Pt(0)
        p.line_spacing = line_spacing
        if isinstance(para, tuple):
            para = [para]
        for (t, sz, col, bold, ital) in para:
            r = p.add_run(); r.text = t
            r.font.size = Pt(sz); r.font.color.rgb = col
            r.font.bold = bold; r.font.italic = ital
            r.font.name = FONT
    return tb


def fill_text(shape, lines, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE):
    tf = shape.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = Inches(0.08); tf.margin_right = Inches(0.08)
    tf.margin_top = Inches(0.04); tf.margin_bottom = Inches(0.04)
    first = True
    for line in lines:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment = align
        p.space_after = Pt(1); p.space_before = Pt(0)
        if isinstance(line, tuple):
            line = [line]
        for (t, sz, col, bold, ital) in line:
            r = p.add_run(); r.text = t
            r.font.size = Pt(sz); r.font.color.rgb = col
            r.font.bold = bold; r.font.italic = ital
            r.font.name = FONT


def accent_bar(s, x=0.0, y=0.0, w=0.18, h=7.5):
    box(s, x, y, w, h, fill=YELLOW, radius=False)


def header(s, kicker, title, num=None):
    accent_bar(s, 0, 0, 0.16, 7.5)
    txt(s, 0.6, 0.42, 11.5, 0.4,
        [[(kicker.upper(), 12, YELLOW, True, False)]])
    txt(s, 0.6, 0.72, 12.0, 0.9,
        [[(title, 30, WHITE, True, False)]])
    box(s, 0.62, 1.58, 2.2, 0.03, fill=YELLOW, radius=False)
    if num:
        txt(s, 12.2, 6.95, 0.9, 0.4,
            [[(num, 10, DGREY, False, False)]], align=PP_ALIGN.RIGHT)
    txt(s, 0.6, 6.95, 8.0, 0.4,
        [[("PO-to-Fulfillment Orchestration  ·  AI Accelerator", 9, DGREY, False, False)]])


def chip(s, x, y, w, h, label, color, txtcolor=None):
    b = box(s, x, y, w, h, fill=color, radius=True)
    fill_text(b, [[(label, 10.5, txtcolor or BG, True, False)]])
    return b


def arrow(s, x, y, w, h=0.28, color=YELLOW):
    a = s.shapes.add_shape(MSO_SHAPE.CHEVRON, Inches(x), Inches(y),
                           Inches(w), Inches(h))
    _set_fill(a, color)
    return a


def down_arrow(s, x, y, w=0.35, h=0.4, color=YELLOW):
    a = s.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, Inches(x), Inches(y),
                           Inches(w), Inches(h))
    _set_fill(a, color)
    return a


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 1 — TITLE
# ══════════════════════════════════════════════════════════════════════════════
s = slide()
box(s, 0, 0, 13.333, 0.16, fill=YELLOW, radius=False)
box(s, 0, 7.34, 13.333, 0.16, fill=YELLOW, radius=False)
txt(s, 0.9, 2.0, 11.5, 0.5, [[("AI ACCELERATOR  ·  ARCHITECTURE OVERVIEW", 14, YELLOW, True, False)]])
txt(s, 0.9, 2.6, 11.6, 1.8,
    [[("Autonomous Purchase Order", 44, WHITE, True, False)],
     [("to Fulfillment Orchestration", 44, WHITE, True, False)]],
    line_spacing=1.0)
box(s, 0.94, 4.5, 3.0, 0.04, fill=YELLOW, radius=False)
txt(s, 0.9, 4.7, 11.4, 1.0,
    [[("A team of specialised AI agents that validate, price, source, plan and ",
       15, GREY, False, False)],
     [("create orders end-to-end — with human-in-the-loop control on exceptions.",
       15, GREY, False, False)]])
txt(s, 0.9, 6.5, 11.4, 0.5,
    [[("Includes: Happy Flow (straight-through processing)   ·   CSR Approval Flow (human-in-the-loop)",
       12, DGREY, False, True)]])

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 2 — THE CHALLENGE
# ══════════════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Business Context", "The order-management challenge today", "02")
pains = [
    ("Manual, repetitive review", "CSRs re-key POs and check every line against multiple systems — catalog, pricing, credit, inventory, buyer directory."),
    ("Slow, error-prone intake", "Obsolete SKUs, bad quantities, mismatched units and unknown buyers stall orders and cause costly mistakes."),
    ("Inconsistent decisions", "Policy interpretation varies by person; margin, credit and approval rules are applied unevenly."),
    ("Limited traceability", "Little audit of who decided what and why — hard to govern and improve."),
]
cx = 0.6
cw = 5.9
gap = 0.35
cy = 2.0
ch = 2.15
positions = [(cx, cy), (cx + cw + gap, cy), (cx, cy + ch + 0.3), (cx + cw + gap, cy + ch + 0.3)]
for (px, py), (t, d) in zip(positions, pains):
    b = box(s, px, py, cw, ch, fill=PANEL)
    box(s, px, py, 0.09, ch, fill=RED, radius=False)
    txt(s, px + 0.35, py + 0.28, cw - 0.6, 0.6, [[(t, 16, WHITE, True, False)]])
    txt(s, px + 0.35, py + 0.92, cw - 0.6, 1.1, [[(d, 12.5, GREY, False, False)]],
        line_spacing=1.05)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 3 — SOLUTION AT A GLANCE
# ══════════════════════════════════════════════════════════════════════════════
s = slide()
header(s, "The Solution", "Agentic orchestration with human-in-the-loop", "03")
txt(s, 0.6, 1.75, 12.0, 0.6,
    [[("An orchestration engine runs a pipeline of specialist AI agents. Each agent makes master-data-driven decisions "
       "automatically and only pauses for a human when a decision is ambiguous or breaches policy.",
       13.5, GREY, False, False)]], line_spacing=1.1)
cards = [
    ("Straight-through", "Clean orders are validated, priced, sourced, planned and created with zero human touch.", GREEN),
    ("Human-in-the-loop", "Risky or ambiguous decisions pause the pipeline and hand off to a CSR, then resume automatically.", AMBER),
    ("Master-data driven", "Decisions come from governed master data — not hard-coded rules — so behaviour is transparent and tunable.", YELLOW),
    ("Fully auditable", "Every automated and human decision is captured with its rationale for governance and traceability.", BLUE),
]
cw = 2.92; gap = 0.13; x0 = 0.6; y0 = 2.7; chh = 3.6
for i, (t, d, col) in enumerate(cards):
    px = x0 + i * (cw + gap)
    b = box(s, px, y0, cw, chh, fill=PANEL)
    box(s, px, y0, cw, 0.12, fill=col, radius=False)
    circ = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(px + 0.32), Inches(y0 + 0.42),
                              Inches(0.55), Inches(0.55))
    _set_fill(circ, col)
    fill_text(circ, [[(str(i + 1), 18, BG, True, False)]])
    txt(s, px + 0.3, y0 + 1.2, cw - 0.55, 0.7, [[(t, 16, WHITE, True, False)]])
    txt(s, px + 0.3, y0 + 1.95, cw - 0.55, 1.5, [[(d, 12, GREY, False, False)]],
        line_spacing=1.1)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 4 — HIGH-LEVEL ARCHITECTURE
# ══════════════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Architecture", "High-level solution architecture", "04")

# Layer 1: Channels / UI
b = box(s, 0.6, 1.85, 12.13, 0.85, fill=PANEL2)
txt(s, 0.8, 1.95, 3.0, 0.65, [[("EXPERIENCE", 10, YELLOW, True, False)],
    [("CSR Workspace UI", 13, WHITE, True, False)]])
for i, (lab) in enumerate(["Conversational order intake", "Live agent panels & audit trail", "One-click CSR decisions"]):
    chip(s, 4.0 + i*2.9, 2.02, 2.7, 0.5, lab, PANEL, WHITE)
down_arrow(s, 6.5, 2.75, 0.4, 0.32)

# Layer 2: Orchestration engine
b = box(s, 0.6, 3.2, 12.13, 1.75, fill=PANEL)
box(s, 0.6, 3.2, 12.13, 0.12, fill=YELLOW, radius=False)
txt(s, 0.8, 3.4, 5.0, 0.4, [[("ORCHESTRATION ENGINE", 11, YELLOW, True, False),
    ("   (resumable pipeline / state machine)", 10, DGREY, False, True)]])
agents = ["Intake", "Customer\nValidation", "Product\nMatching", "Pricing &\nPromo",
          "Credit", "Inventory", "Shipments", "Approvals"]
aw = 1.35; agap = 0.12; ax = 0.85; ay = 3.95
for i, a in enumerate(agents):
    px = ax + i * (aw + agap)
    ab = box(s, px, ay, aw, 0.82, fill=PANEL2, line_color=YELLOW, line_w=0.75)
    fill_text(ab, [[(line, 10, WHITE, True, False)] for line in a.split("\n")])
# governance + execution ribbon
txt(s, 0.85, 4.82, 11.6, 0.3,
    [[("Cross-cutting:  Exception Governance & Routing   ·   Order Execution   ·   Mock Integrations (email / ERP)",
       10.5, GREY, False, True)]])
down_arrow(s, 6.5, 4.98, 0.4, 0.3)

# Layer 3: Master data foundation
b = box(s, 0.6, 5.42, 12.13, 1.15, fill=PANEL2)
txt(s, 0.8, 5.52, 4.0, 0.4, [[("MASTER-DATA FOUNDATION", 11, YELLOW, True, False)]])
md = ["Customer", "Buyer", "Product", "Pricing", "Credit", "Inventory", "Logistics", "Budget", "Compliance", "Governance"]
mw = 1.13; mgap = 0.075; mx = 0.85; my = 5.92
for i, m in enumerate(md):
    px = mx + i * (mw + mgap)
    mb = box(s, px, my, mw, 0.5, fill=BG, line_color=LINE, line_w=0.75)
    fill_text(mb, [[(m, 9.5, GREY, True, False)]])

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 5 — THE AI AGENT TEAM
# ══════════════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Components", "The AI agent team", "05")
team = [
    ("Intake Agent", "Digitises the raw PO, extracts header/buyer/ship-to/lines, and reconciles every line against master data.", "Obsolete SKU · bad qty · UOM · unknown buyer"),
    ("Customer Validation Agent", "Resolves customer & account hierarchy, validates ship-to, and authorises the buyer.", "Account · ship-to · buyer authority"),
    ("Product Matching Agent", "Confirms each SKU against the catalog and runs the compliance sub-check.", "Catalog match · compliance"),
    ("Pricing & Promo Agent", "Builds the price waterfall (list → contract → tier → promo → rebate → net) and totals.", "Margin / discount policy"),
    ("Credit Agent", "Checks order value against available credit and payment terms.", "Credit limit · terms · risk"),
    ("Inventory Agent", "Sources each line across distribution centres and confirms availability.", "ATP · allocation"),
    ("Shipments Agent", "Confirms carrier serviceability, freight and delivery SLA.", "Fulfillment plan · ETA"),
    ("Approvals Agent", "Runs the approval-matrix / budget check last, before execution.", "Budget · self-approval"),
    ("Order Execution Agent", "Creates the sales order and emits the completion record.", "Order created · audit"),
]
cw = 3.95; ch = 1.55; gapx = 0.13; gapy = 0.16; x0 = 0.6; y0 = 1.85
for i, (t, d, tag) in enumerate(team):
    r, c = divmod(i, 3)
    px = x0 + c * (cw + gapx); py = y0 + r * (ch + gapy)
    b = box(s, px, py, cw, ch, fill=PANEL)
    box(s, px, py, 0.08, ch, fill=YELLOW, radius=False)
    txt(s, px + 0.28, py + 0.16, cw - 0.5, 0.4, [[("\U0001F916  " + t, 12.5, WHITE, True, False)]])
    txt(s, px + 0.28, py + 0.62, cw - 0.5, 0.7, [[(d, 10.5, GREY, False, False)]], line_spacing=1.02)
    txt(s, px + 0.28, py + 1.24, cw - 0.5, 0.3, [[(tag, 9, YELLOW, False, True)]])

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 6 — MASTER DATA FOUNDATION
# ══════════════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Foundation", "Master data drives every decision", "06")
txt(s, 0.6, 1.75, 12.0, 0.5,
    [[("Each agent reads governed master data (mock Excel workbooks in the POC; enterprise systems in production). "
       "Change the data, not the code, to change behaviour.", 13, GREY, False, False)]], line_spacing=1.1)
data = [
    ("Customer", "Account hierarchy, tiers, buying history, fulfillment rules"),
    ("Buyer", "Buyer profiles, roles, permissions, product-family access"),
    ("Product", "Catalog, lifecycle status, substitutes, UOM conversions"),
    ("Pricing", "Price lists, contracts, volume tiers, promos, rebates"),
    ("Credit", "Credit limits, available credit, payment terms, risk"),
    ("Inventory", "Plant / DC stock, in-transit, ATP, allocation"),
    ("Logistics", "Carriers, serviceability, freight, delivery SLA"),
    ("Budget", "Cost-centre budgets, approval matrix, buyer authority"),
    ("Compliance", "Regional restrictions, approvals, required documents"),
    ("Governance", "Exception routing, escalation targets, SLAs"),
]
cw = 3.95; ch = 0.92; gapx = 0.13; gapy = 0.14; x0 = 0.6; y0 = 2.55
for i, (t, d) in enumerate(data):
    r, c = divmod(i, 3)
    px = x0 + c * (cw + gapx); py = y0 + r * (ch + gapy)
    b = box(s, px, py, cw, ch, fill=PANEL2)
    dot = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(px + 0.22), Inches(py + 0.3),
                             Inches(0.28), Inches(0.28))
    _set_fill(dot, YELLOW)
    txt(s, px + 0.66, py + 0.14, cw - 0.85, 0.35, [[(t, 12.5, WHITE, True, False)]])
    txt(s, px + 0.66, py + 0.5, cw - 0.85, 0.4, [[(d, 9.5, GREY, False, False)]], line_spacing=1.0)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 7 — THE ORCHESTRATION PIPELINE
# ══════════════════════════════════════════════════════════════════════════════
s = slide()
header(s, "How it works", "The orchestration pipeline", "07")
txt(s, 0.6, 1.7, 12.0, 0.45,
    [[("Sequential decision layers thread a shared context. The pipeline pauses on the first exception and resumes after the CSR decides.",
       12.5, GREY, False, False)]], line_spacing=1.05)

stages = ["Intake", "Customer\nValidation", "Product\nMatching", "Pricing &\nPromo",
          "Credit", "Inventory", "Shipments", "Approvals"]
n = len(stages)
bw = 1.28; bh = 1.0; gap = 0.145; x0 = 0.62; y0 = 2.55
for i, stg in enumerate(stages):
    px = x0 + i * (bw + gap)
    b = box(s, px, y0, bw, bh, fill=PANEL, line_color=YELLOW, line_w=1)
    fill_text(b, [[(str(i + 1), 10, YELLOW, True, False)]] +
                 [[(line, 10, WHITE, True, False)] for line in stg.split("\n")])
    if i < n - 1:
        arrow(s, px + bw - 0.02, y0 + bh/2 - 0.13, gap + 0.06, 0.26)
# to governance + execution
down_arrow(s, x0 + (n-1)*(bw+gap) + bw/2 - 0.2, y0 + bh + 0.05, 0.4, 0.32)
gbox = box(s, 8.6, 3.95, 4.12, 0.72, fill=PANEL2, line_color=GREEN, line_w=1)
fill_text(gbox, [[("Order Execution Agent  ·  create order", 11.5, WHITE, True, False)]])
govb = box(s, 0.62, 3.95, 7.7, 0.72, fill=PANEL2)
fill_text(govb, [[("Exception Governance & Routing  —  runs on every order (records + routes exceptions)", 11, GREY, True, False)]])

# legend / notes
notes = [
    ("Pauses on first exception", "The pipeline stops at the layer that needs a decision — nothing downstream runs on bad data.", AMBER),
    ("Resumes automatically", "Once the CSR decides, the shared context is updated and the pipeline continues from where it paused.", GREEN),
    ("Approvals run last", "Budget / approval-matrix check runs only after product, pricing, credit, inventory and logistics pass.", YELLOW),
]
cw = 3.95; x0n = 0.6; y0n = 5.15; chh = 1.5
for i, (t, d, col) in enumerate(notes):
    px = x0n + i * (cw + 0.13)
    b = box(s, px, y0n, cw, chh, fill=PANEL)
    box(s, px, y0n, 0.08, chh, fill=col, radius=False)
    txt(s, px + 0.28, y0n + 0.2, cw - 0.5, 0.4, [[(t, 13, WHITE, True, False)]])
    txt(s, px + 0.28, y0n + 0.68, cw - 0.5, 0.7, [[(d, 11, GREY, False, False)]], line_spacing=1.05)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 8 — TWO PROCESSING PATHS
# ══════════════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Processing paths", "One engine, two paths", "08")
# Happy
b = box(s, 0.6, 1.95, 5.95, 4.6, fill=PANEL)
box(s, 0.6, 1.95, 5.95, 0.13, fill=GREEN, radius=False)
txt(s, 0.9, 2.25, 5.4, 0.5, [[("HAPPY FLOW", 12, GREEN, True, False)]])
txt(s, 0.9, 2.6, 5.4, 0.5, [[("Straight-through processing", 18, WHITE, True, False)]])
for i, t in enumerate(["Clean PO, no ambiguity or policy breach",
                       "Every agent validates & passes automatically",
                       "Zero human intervention",
                       "Order created in a single pass",
                       "Full audit trail produced"]):
    yy = 3.25 + i*0.55
    dot = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(0.95), Inches(yy+0.06), Inches(0.16), Inches(0.16))
    _set_fill(dot, GREEN)
    txt(s, 1.25, yy, 5.1, 0.5, [[(t, 12.5, GREY, False, False)]])
chip(s, 0.9, 6.05, 5.3, 0.42, "Outcome:  order created with no CSR touch", PANEL2, WHITE)
# CSR
b = box(s, 6.78, 1.95, 5.95, 4.6, fill=PANEL)
box(s, 6.78, 1.95, 5.95, 0.13, fill=AMBER, radius=False)
txt(s, 7.08, 2.25, 5.4, 0.5, [[("CSR APPROVAL FLOW", 12, AMBER, True, False)]])
txt(s, 7.08, 2.6, 5.4, 0.5, [[("Human-in-the-loop", 18, WHITE, True, False)]])
for i, t in enumerate(["AI auto-resolves everything it can from data",
                       "Ambiguous / policy-breaching items PAUSE",
                       "CSR gets a pre-investigated, one-click decision",
                       "Guardrails validate every manual entry",
                       "Pipeline resumes automatically after each gate"]):
    yy = 3.25 + i*0.55
    dot = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(7.13), Inches(yy+0.06), Inches(0.16), Inches(0.16))
    _set_fill(dot, AMBER)
    txt(s, 7.43, yy, 5.1, 0.5, [[(t, 12.5, GREY, False, False)]])
chip(s, 7.08, 6.05, 5.3, 0.42, "Outcome:  CSR decides only the exceptions", PANEL2, WHITE)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 9 — HAPPY FLOW DETAIL
# ══════════════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Demo 1", "Happy Flow — straight-through processing", "09")
# flow strip
steps = ["Submit\nPO", "Intake\nextract + review", "Customer\nValidation", "Product\nMatching",
         "Pricing", "Credit", "Inventory", "Shipments", "Approvals", "Order\nCreated"]
bw = 1.12; bh = 0.95; gap = 0.055; x0 = 0.62; y0 = 2.0
for i, stp in enumerate(steps):
    px = x0 + i * (bw + gap)
    last = (i == len(steps) - 1)
    b = box(s, px, y0, bw, bh, fill=(GREEN if last else PANEL),
            line_color=(None if last else GREEN), line_w=0.75)
    col = BG if last else WHITE
    fill_text(b, [[(line, 9, col, True, False)] for line in stp.split("\n")])
    if i < len(steps) - 1:
        arrow(s, px + bw - 0.02, y0 + bh/2 - 0.1, gap + 0.05, 0.2, color=GREEN)
txt(s, 0.62, 3.1, 12.0, 0.3, [[("All checks pass automatically — no ", 12, GREY, False, False),
    ("CSR DECISION NEEDED", 12, GREEN, True, False), (" banners appear.", 12, GREY, False, False)]])

# Example PO + totals
b = box(s, 0.6, 3.6, 6.5, 2.95, fill=PANEL)
txt(s, 0.85, 3.78, 6.0, 0.4, [[("EXAMPLE PO  —  PO-2026-30001", 11, YELLOW, True, False)]])
lines = [
    "Great Lakes Plumbing Supply Co  ·  john.miller@glps.com",
    "Ship to: Chicago DC, IL 60639",
    "",
    "1  SKU-CTG-4520  Ceramic Disc Cartridge     100 EA",
    "2  SKU-SEL-1150  Tank-to-Bowl Gasket Kit    120 EA",
    "3  SKU-VLV-2201  Pressure-Balancing Valve    15 EA",
]
txt(s, 0.85, 4.2, 6.0, 2.2, [[(l, 11, GREY if not l.startswith(("1","2","3")) else WHITE, False, False)] for l in lines], line_spacing=1.15)

b = box(s, 7.28, 3.6, 5.45, 2.95, fill=PANEL2)
box(s, 7.28, 3.6, 0.1, 2.95, fill=GREEN, radius=False)
txt(s, 7.55, 3.78, 5.0, 0.4, [[("AUTOMATED RESULT", 11, GREEN, True, False)]])
totals = [("Subtotal", "$3,083.00"), ("Freight", "$151.62"), ("Tax", "$271.79")]
for i, (k, v) in enumerate(totals):
    yy = 4.25 + i*0.5
    txt(s, 7.55, yy, 3.0, 0.4, [[(k, 12.5, GREY, False, False)]])
    txt(s, 10.3, yy, 2.2, 0.4, [[(v, 12.5, WHITE, True, False)]], align=PP_ALIGN.RIGHT)
box(s, 7.55, 5.75, 4.95, 0.02, fill=LINE, radius=False)
txt(s, 7.55, 5.85, 3.0, 0.4, [[("ORDER TOTAL", 14, YELLOW, True, False)]])
txt(s, 10.0, 5.85, 2.5, 0.4, [[("$3,529.53", 15, YELLOW, True, False)]], align=PP_ALIGN.RIGHT)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 10 — CSR APPROVAL FLOW DETAIL (the 5 gates)
# ══════════════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Demo 2", "CSR Approval Flow — five decision gates", "10")
txt(s, 0.6, 1.72, 12.1, 0.4,
    [[("A single PO engineered to trigger five gates. The AI investigates, presents a one-click choice, captures the decision, and resumes.",
       12, GREY, False, False)]], line_spacing=1.05)
gates = [
    ("1", "Obsolete product", "Line 1 SKU is obsolete — AI proposes approved substitutes with price impact.", "INTAKE"),
    ("2", "Invalid quantity", "Line 4 quantity is 0 — CSR enters a valid, positive whole number (validated).", "INTAKE"),
    ("3", "UOM conversion", "Line 5 ordered in EA but sold in KIT — CSR picks the kit quantity to fulfil.", "INTAKE"),
    ("4", "Unresolved buyer", "PO email isn't a registered buyer — CSR selects from the account's buyers.", "INTAKE"),
    ("5", "Pricing / margin exception", "Discount 21.5% exceeds the 10% family policy — CSR approves the override.", "PIPELINE"),
]
cw = 2.35; ch = 3.0; gap = 0.12; x0 = 0.6; y0 = 2.35
for i, (num, t, d, phase) in enumerate(gates):
    px = x0 + i * (cw + gap)
    pcol = BLUE if phase == "INTAKE" else AMBER
    b = box(s, px, y0, cw, ch, fill=PANEL)
    box(s, px, y0, cw, 0.1, fill=pcol, radius=False)
    circ = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(px + 0.28), Inches(y0 + 0.3),
                              Inches(0.55), Inches(0.55))
    _set_fill(circ, pcol)
    fill_text(circ, [[(num, 18, BG, True, False)]])
    txt(s, px + 0.24, y0 + 1.0, cw - 0.45, 0.7, [[(t, 13, WHITE, True, False)]], line_spacing=0.95)
    txt(s, px + 0.24, y0 + 1.75, cw - 0.45, 1.0, [[(d, 10, GREY, False, False)]], line_spacing=1.05)
    chip(s, px + 0.24, y0 + 2.62, cw - 0.48, 0.32, phase, pcol, BG)
# legend
txt(s, 0.6, 5.6, 12.0, 0.4,
    [[("Blue = INTAKE gates (data reconciliation)      Amber = PIPELINE gate (policy breach)", 11, GREY, False, True)]])
b = box(s, 0.6, 6.0, 12.13, 0.62, fill=PANEL2)
box(s, 0.6, 6.0, 0.1, 0.62, fill=YELLOW, radius=False)
txt(s, 0.9, 6.12, 11.6, 0.4,
    [[("Approx. order total after CSR choices: ", 12, GREY, False, False),
      ("$10,659.50", 13, YELLOW, True, False),
      ("   —   five multi-system lookups reduced to five one-click decisions.", 12, GREY, False, False)]])

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 11 — EXCEPTION MODEL & ROUTING
# ══════════════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Governance", "Exception model & escalation routing", "11")
# two gate types
b = box(s, 0.6, 1.9, 6.0, 2.3, fill=PANEL)
box(s, 0.6, 1.9, 0.1, 2.3, fill=BLUE, radius=False)
txt(s, 0.9, 2.08, 5.5, 0.4, [[("INTAKE GATES  —  data reconciliation", 12.5, BLUE, True, False)]])
txt(s, 0.9, 2.55, 5.5, 1.5,
    [[("Obsolete / substitute SKU  ·  unresolved or missing SKU", 11.5, GREY, False, False)],
     [("Invalid quantity  ·  unit-of-measure conversion", 11.5, GREY, False, False)],
     [("Unresolved buyer  ·  partial / unresolved ship-to", 11.5, GREY, False, False)]], line_spacing=1.2)
b = box(s, 6.73, 1.9, 6.0, 2.3, fill=PANEL)
box(s, 6.73, 1.9, 0.1, 2.3, fill=AMBER, radius=False)
txt(s, 7.03, 2.08, 5.5, 0.4, [[("PIPELINE GATES  —  policy breach", 12.5, AMBER, True, False)]])
txt(s, 7.03, 2.55, 5.5, 1.5,
    [[("Pricing / margin-policy exception", 11.5, GREY, False, False)],
     [("Credit hold  ·  budget exceeded / approval required", 11.5, GREY, False, False)],
     [("Compliance restriction  ·  inventory / logistics constraints", 11.5, GREY, False, False)]], line_spacing=1.2)
# routing
txt(s, 0.6, 4.45, 12.0, 0.4, [[("Every exception is routed to the responsible team", 15, WHITE, True, False)]])
routes = [
    ("Product Specialist", "SKU / substitution"),
    ("Order Ops Supervisor", "Quantity / intake"),
    ("Sales Ops / Account Mgr", "Buyer / ship-to"),
    ("Pricing Desk", "Margin exception"),
    ("Credit / Approver", "Credit & budget"),
]
cw = 2.35; gap = 0.12; x0 = 0.6; y0 = 5.05; chh = 1.35
for i, (t, d) in enumerate(routes):
    px = x0 + i * (cw + gap)
    b = box(s, px, y0, cw, chh, fill=PANEL2)
    txt(s, px + 0.22, y0 + 0.22, cw - 0.4, 0.7, [[(t, 12, WHITE, True, False)]], line_spacing=0.95)
    txt(s, px + 0.22, y0 + 0.9, cw - 0.4, 0.4, [[(d, 10, YELLOW, False, True)]])

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 12 — AUDIT & GOVERNANCE
# ══════════════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Trust", "Built-in audit & governance", "12")
left = box(s, 0.6, 1.95, 6.0, 4.5, fill=PANEL)
txt(s, 0.9, 2.15, 5.5, 0.5, [[("Every decision is captured", 16, WHITE, True, False)]])
for i, t in enumerate([
        "What the agent decided automatically from master data",
        "Why it paused for a CSR (the exception & rationale)",
        "The exact action the CSR took (approve / pick / enter)",
        "The final outcome applied to the order",
        "Step-by-step audit trail per decision layer"]):
    yy = 2.75 + i*0.68
    dot = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(0.95), Inches(yy+0.05), Inches(0.16), Inches(0.16))
    _set_fill(dot, YELLOW)
    txt(s, 1.25, yy, 5.1, 0.6, [[(t, 12, GREY, False, False)]], line_spacing=1.05)
right = box(s, 6.73, 1.95, 6.0, 4.5, fill=PANEL2)
box(s, 6.73, 1.95, 6.0, 0.12, fill=YELLOW, radius=False)
txt(s, 7.03, 2.2, 5.5, 0.4, [[("WHY IT MATTERS", 11, YELLOW, True, False)]])
for i, (t, d) in enumerate([
        ("Governance", "Consistent, policy-aligned decisions across all CSRs."),
        ("Traceability", "Full lineage of automated and human decisions."),
        ("Continuous improvement", "Exception patterns reveal data & policy gaps to fix."),
        ("Compliance-ready", "Defensible record for audits and disputes.")]):
    yy = 2.75 + i*0.9
    txt(s, 7.03, yy, 5.4, 0.4, [[(t, 13.5, WHITE, True, False)]])
    txt(s, 7.03, yy+0.36, 5.4, 0.5, [[(d, 11, GREY, False, False)]], line_spacing=1.0)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 13 — TECHNOLOGY & DEPLOYMENT
# ══════════════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Under the hood", "Technology & deployment", "13")
cols = [
    ("POC (today)", GREEN, [
        "Python orchestration engine",
        "Streamlit CSR workspace UI",
        "Master data as Excel workbooks",
        "Mock integrations (email / ERP)",
        "Runs locally — fast to demo & iterate"]),
    ("Architecture principles", YELLOW, [
        "Modular agents & decision layers",
        "Resumable pipeline / state machine",
        "Data-driven, not hard-coded rules",
        "Human-in-the-loop by design",
        "Audit-first for governance"]),
    ("Production path", BLUE, [
        "Connect to ERP / MDM / pricing systems",
        "Swap workbooks for live master data",
        "LLM-assisted extraction & reasoning",
        "Enterprise auth, roles & SLAs",
        "Cloud deployment & monitoring"]),
]
cw = 3.95; gap = 0.13; x0 = 0.6; y0 = 1.95; chh = 4.5
for i, (t, col, items) in enumerate(cols):
    px = x0 + i * (cw + gap)
    b = box(s, px, y0, cw, chh, fill=PANEL)
    box(s, px, y0, cw, 0.12, fill=col, radius=False)
    txt(s, px + 0.3, y0 + 0.35, cw - 0.55, 0.5, [[(t, 15, WHITE, True, False)]])
    for j, it in enumerate(items):
        yy = y0 + 1.05 + j*0.68
        dot = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(px+0.32), Inches(yy+0.05), Inches(0.14), Inches(0.14))
        _set_fill(dot, col)
        txt(s, px + 0.6, yy, cw - 0.85, 0.6, [[(it, 11.5, GREY, False, False)]], line_spacing=1.0)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 14 — BUSINESS VALUE
# ══════════════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Outcomes", "Business value", "14")
metrics = [
    ("Straight-through", "Clean orders processed with zero manual effort"),
    ("Faster cycle time", "Investigation done in seconds, not minutes of lookups"),
    ("Fewer errors", "Guardrails validate SKUs, quantities, units and buyers"),
    ("Consistent decisions", "Policy applied uniformly from governed master data"),
    ("CSR focus", "People spend time only on genuine judgement calls"),
    ("Full auditability", "Every decision captured for governance & trust"),
]
cw = 3.95; ch = 1.55; gapx = 0.13; gapy = 0.18; x0 = 0.6; y0 = 1.95
for i, (t, d) in enumerate(metrics):
    r, c = divmod(i, 3)
    px = x0 + c * (cw + gapx); py = y0 + r * (ch + gapy)
    b = box(s, px, py, cw, ch, fill=PANEL)
    box(s, px, py, 0.08, ch, fill=YELLOW, radius=False)
    txt(s, px + 0.3, py + 0.22, cw - 0.5, 0.5, [[(t, 15, YELLOW, True, False)]])
    txt(s, px + 0.3, py + 0.75, cw - 0.5, 0.7, [[(d, 11.5, GREY, False, False)]], line_spacing=1.05)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 15 — CLOSING
# ══════════════════════════════════════════════════════════════════════════════
s = slide()
box(s, 0, 0, 13.333, 0.16, fill=YELLOW, radius=False)
box(s, 0, 7.34, 13.333, 0.16, fill=YELLOW, radius=False)
txt(s, 0.9, 2.4, 11.5, 0.5, [[("THANK YOU", 14, YELLOW, True, False)]])
txt(s, 0.9, 2.95, 11.5, 1.2, [[("Autonomous PO-to-Fulfillment Orchestration", 34, WHITE, True, False)]])
box(s, 0.94, 4.15, 3.0, 0.04, fill=YELLOW, radius=False)
txt(s, 0.9, 4.4, 11.4, 1.0,
    [[("A working accelerator today — a clear path to production.", 15, GREY, False, False)],
     [("Next: connect live systems, add LLM-assisted reasoning, and pilot with real POs.", 13, DGREY, False, True)]],
    line_spacing=1.2)

# ── Save ──────────────────────────────────────────────────────────────────────
import os
out = os.path.join("demo", "PO-Fulfillment-Orchestration-Architecture.pptx")
prs.save(out)
print("Saved:", out, "slides:", len(prs.slides._sldIdLst))
