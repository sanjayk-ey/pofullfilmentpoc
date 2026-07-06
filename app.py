"""
app.py  —  PO Fulfillment AI Agent
Streamlit frontend with chat-like interface.
Run with: python -m streamlit run app.py
"""
import streamlit as st
import time
import os
import uuid  # still used for session_id passed to duplicate_checker

# Demo runs deliberately slowly so the audience can follow each step. Set
# PO_DEMO_FAST=1 to disable all pacing delays (used by the headless UI tests).
_FAST = os.environ.get("PO_DEMO_FAST") == "1"


def nap(seconds):
    if not _FAST:
        time.sleep(seconds)


import streamlit.components.v1 as _components  # noqa: E402


def inject_autoscroll(active: bool = True, force_follow: bool = False):
    """Smart chat-style auto-scroll that follows the pipeline as it animates
    but NEVER traps the user.

    Rendered at the TOP of drive_orchestration() so the iframe is mounted
    *before* the nap() sleeps begin: every animating phase ends in
    st.rerun(), which stops the script before a bottom-of-page component is
    reached, so Streamlit would remove that iframe (and kill its observer)
    for the whole animation. Mounting in-flow keeps the observer alive; its
    JS runs in the browser while the Python thread sleeps, scrolling as each
    stage delta streams in.

    Behaviour ("follow" model, like a chat app):
      * While the user is at (or near) the bottom, every new stage / internal
        step scrolls into view automatically.
      * The instant the user scrolls UP (wheel / touch / PageUp / ArrowUp /
        Home), auto-follow DISENGAGES so they can freely read/scroll — this
        is what fixes "can't scroll after the run finishes".
      * Scrolling back to the bottom RE-ENGAGES follow.

    `active=False` (idle welcome / terminal) does one gentle scroll to show
    the final message, then leaves the user in full control.
    """
    flag = "true" if active else "false"
    force = "true" if force_follow else "false"
    _components.html(
        """
        <script>
          (function () {
            try {
              const w = window.parent || window;
              const doc = w.document;
              const ACTIVE = %s;
              const FORCE_FOLLOW = %s;
              // A CSR decision button was just clicked — snap back into
              // follow mode so the resuming pipeline is tracked again.
              if (FORCE_FOLLOW) w.__poFollow = true;

              const findScrollable = () => {
                let el = doc.querySelector('[data-testid="stAppScrollToBottomContainer"]');
                if (el) return el;
                for (const sel of [
                  '[data-testid="ScrollToBottomContainer"]',
                  '[data-testid="stAppViewMain"]',
                  'section.main',
                  '.main .block-container',
                ]) {
                  el = doc.querySelector(sel);
                  if (el && el.scrollHeight > el.clientHeight) return el;
                }
                return doc.scrollingElement || doc.documentElement;
              };

              const nearBottom = () => {
                const el = findScrollable();
                if (!el) return true;
                return (el.scrollHeight - el.scrollTop - el.clientHeight) < 160;
              };

              // Shared follow state on the parent window so it survives the
              // per-run iframe teardown.
              if (typeof w.__poFollow === 'undefined') w.__poFollow = true;

              const scrollNow = () => {
                if (!w.__poFollow) return;          // user scrolled away — respect it
                const el = findScrollable();
                if (!el) return;
                try { el.scrollTo({ top: el.scrollHeight, behavior: 'auto' }); }
                catch (_) { el.scrollTop = el.scrollHeight; }
              };

              // Install user-intent listeners ONCE — they toggle follow.
              if (!w.__poListeners) {
                const disengageIfUp = () => {
                  // After the user's gesture settles, follow only if they are
                  // back at the bottom.
                  setTimeout(() => { w.__poFollow = nearBottom(); }, 60);
                };
                w.addEventListener('wheel', (e) => {
                  if (e.deltaY < 0) w.__poFollow = false;  // scrolling up
                  else disengageIfUp();
                }, { passive: true });
                w.addEventListener('touchmove', disengageIfUp, { passive: true });
                w.addEventListener('keydown', (e) => {
                  if (['PageUp', 'ArrowUp', 'Home'].includes(e.key))
                    w.__poFollow = false;
                  if (['End', 'PageDown', 'ArrowDown'].includes(e.key))
                    disengageIfUp();
                });
                w.addEventListener('resize', scrollNow);
                w.__poListeners = true;
              }

              // Refresh the observer + interval every run (previous iframe is
              // gone, so its observer/interval are dead — replace them).
              if (w.__poObs) { try { w.__poObs.disconnect(); } catch (_) {} }
              if (w.__poInt) { try { clearInterval(w.__poInt); } catch (_) {} }

              if (ACTIVE) {
                w.__poFollow = w.__poFollow;   // keep whatever the user chose
                let pending = null;
                const schedule = () => {
                  if (pending) return;
                  pending = setTimeout(() => { pending = null; scrollNow(); }, 60);
                };
                const obs = new MutationObserver(schedule);
                obs.observe(doc.body, { childList: true, subtree: true,
                                        characterData: true });
                w.__poObs = obs;
                // Safety net for deltas that don't trigger a mutation event.
                w.__poInt = setInterval(scrollNow, 400);
                setTimeout(() => { try { clearInterval(w.__poInt); } catch (_) {} },
                           300000);
                scrollNow();
                setTimeout(scrollNow, 120);
                setTimeout(scrollNow, 400);
              } else {
                // Terminal / idle: one final scroll to reveal the last
                // message, then hand full control back to the user.
                w.__poObs = null; w.__poInt = null;
                if (w.__poFollow) {
                  const el = findScrollable();
                  if (el) { try { el.scrollTo({ top: el.scrollHeight,
                                                behavior: 'smooth' }); }
                            catch (_) { el.scrollTop = el.scrollHeight; } }
                }
              }
            } catch (e) { /* cross-origin / startup race — ignore */ }
          })();
        </script>
        """ % (flag, force),
        height=0,
    )


from modules.extractor        import POExtractor, ExtractedPO
from modules.excel_parser     import parse_excel
from modules                  import duplicate_checker as dup
from modules.account_validator import AccountValidator, AccountValidationResult
from modules.pipeline         import build_context, SEQUENTIAL_STAGES, GOVERNANCE, EXECUTION
from modules.intake_resolver  import IntakeResolver
from modules.manual_entry_validators import (
    validate_manual_sku, validate_manual_quantity,
)

# ─── Page setup ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PO Fulfillment AI",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Loud safety net: if PO_DEMO_FAST leaked into a real browser session (it's
# only meant for the headless test harness), all pacing delays are skipped
# and the pipeline appears to "jump straight to the end". Show a visible
# banner so the operator knows why the demo looks broken.
if _FAST:
    st.error(
        "⚠️  **PO_DEMO_FAST=1 is set in this Streamlit process.** "
        "All animation delays are disabled, so the pipeline will finish "
        "almost instantly and intermediate stages will not appear on "
        "screen. Restart Streamlit from a shell where this environment "
        "variable is **not** set (this flag is only meant for the headless "
        "`test_pipeline.py` / `_apptest_smoke.py` test harness)."
    )

# ─── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Hide only Streamlit chrome we don't need */
#MainMenu, footer { visibility: hidden; }
/* Hide Deploy button only — keep the sidebar expand control working */
[data-testid="stAppDeployButton"] { display: none !important; }
[data-testid="stToolbarActions"]  { display: none !important; }
[data-testid="stDeployButton"]    { display: none !important; }
[data-testid="stStatusWidget"]    { display: none !important; }
.stDeployButton                   { display: none !important; }
span.stAppDeployButton            { display: none !important; }

/* Hidden kickoff button — clicked from JS to start the animation run after the
   clearing frame finishes successfully (see the "Clearing frame" block). */
.st-key-kickoff_wrap { display: none !important; }

/* Push content below the fixed app bar (kept tight so the header sits high) */
.block-container   { padding-top: 1.5rem !important; }

/* Remove anchor link icon that appears on headings */
h1 a, h2 a, h3 a, h4 a { display: none !important; }


/* Confidence bar */
.conf-bar-wrap     { background:#334155; border-radius:6px; height:8px;
                     width:160px; display:inline-block; vertical-align:middle; margin-left:8px; }
.conf-bar          { border-radius:6px; height:8px; display:block; }

/* Extracted fields table */
.field-table       { width:100%; border-collapse:collapse; font-size:14px; }
.field-table th    { background:#1E3A5F; color:#CBD5E1; padding:7px 12px; text-align:left; }
.field-table td    { padding:7px 12px; border-bottom:1px solid #334155; }
.field-table tr:hover td { background:#1E293B; }

/* ── Never fade content during reruns ──────────────────────────────────────
   Streamlit dims "stale" elements (opacity ~0.4) while a rerun is in flight.
   For a step-by-step pipeline this looks like the screen greying out between
   stages. Force everything to stay fully opaque so the process reads as one
   continuous, linear flow. */
[data-stale="true"],
.element-container[data-stale="true"],
.stale-element,
[data-testid="stElementContainer"][data-stale="true"],
[data-testid="stVerticalBlock"] > div[data-stale="true"] {
    opacity: 1 !important;
    filter: none !important;
    transition: none !important;
}
/* Kill the app-level running/skeleton dim + the top progress shimmer */
[data-testid="stStatusWidget"] { display: none !important; }
.stApp [data-testid="stAppViewContainer"] { opacity: 1 !important; }
div[data-testid="stSkeleton"] { opacity: 1 !important; }

/* Remove the default chat avatar icon (orange robot square) entirely and
   close the gap it would otherwise leave beside each message. */
[data-testid="stChatMessageAvatarAssistant"],
[data-testid="stChatMessageAvatarUser"],
[data-testid="chatAvatarIcon-assistant"],
[data-testid="chatAvatarIcon-user"],
[data-testid="stChatMessage"] > img:first-child { display: none !important; }
[data-testid="stChatMessage"] { gap: 0 !important; padding-left: 0 !important; }

/* Tighten spacing: smaller page header, close the gap between the
   "Order Assistant" header and the first "Intake" message, and slimmer
   horizontal rules so the between-layer separators aren't oversized. */
h2 { margin-top: 0.2rem !important; margin-bottom: 0.2rem !important; }
hr { margin-top: 0.6rem !important; margin-bottom: 0.6rem !important; }
[data-testid="stChatMessage"] { margin-top: 0 !important; padding-top: 0 !important; }
[data-testid="stChatMessage"] h3:first-child { margin-top: 0 !important; }
</style>
""", unsafe_allow_html=True)

EXTRACTOR = POExtractor()
ACCOUNT_VALIDATOR = AccountValidator()
INTAKE_RESOLVER = IntakeResolver()

# Demo pacing — the agent deliberately works a little slowly so the audience can
# follow each internal check and decision (like watching an assistant think).
# THINK_PACE is the pause between "thinking" lines; STAGE_PACE is applied on
# top of each stage-step delay so the whole pipeline feels visibly deliberate
# without being tedious. Both are disabled when PO_DEMO_FAST=1 (headless tests).
THINK_PACE = 1.4
STAGE_PACE_MULT = 3.0
MIN_STAGE_DELAY = 0.8


def paced_delay(base):
    """Slow down a stage-step delay so the audience can follow along."""
    if _FAST:
        return 0
    return max(MIN_STAGE_DELAY, base * STAGE_PACE_MULT)

# Where each exception category is escalated when a CSR chooses "Escalate".
ESCALATION_ROUTING = {
    "SUBSTITUTE_SKU":       "Product Specialist",
    "UNRESOLVED_SKU":       "Product Specialist",
    "MISSING_SKU":          "Product Specialist",
    "UOM_AMBIGUOUS":        "Product Specialist",
    "UOM_CONVERSION":       "Product Specialist",
    "INVALID_QUANTITY":     "Order Operations Supervisor",
    "PARTIAL_SHIP_TO":      "Logistics / Account Manager",
    "UNRESOLVED_SHIP_TO":   "Logistics / Account Manager",
    "UNRESOLVED_BUYER":     "Sales Ops / Account Manager",
    "PRODUCT_CONFIG_EXCEPTION": "Product Specialist",
    "OBSOLETE_SKU":         "Product Specialist",
    "INVALID_UOM":          "Product Specialist",
    "COMPLIANCE_RESTRICTION": "Compliance Officer",
    "MISSING_SDS":          "Compliance Officer",
    "PRICING_EXCEPTION":    "Pricing Desk",
    "BUDGET_EXCEEDED":      "Budget Approver",
    "APPROVAL_REQUIRED":    "Budget Approver",
    "CREDIT_HOLD":          "Finance / Credit Team",
    "INVENTORY_SHORTAGE":   "Fulfillment Planner",
    "ALLOCATION_CONFLICT":  "Fulfillment Planner",
    "SPLIT_NOT_ALLOWED":    "Fulfillment Planner",
    "MIN_ORDER_QTY_NOT_MET":"Fulfillment Planner",
    "ZIP_NOT_SERVICEABLE":  "Logistics Team",
    "SLA_MISS":             "Logistics Team",
    "EXECUTION_FAILURE":    "Integration Support",
    "ACCOUNT_UNMATCHED_CUSTOMER": "Account Manager",
    "ACCOUNT_INVALID_SHIP_TO":    "Logistics / Account Manager",
    "ACCOUNT_HIERARCHY_MISMATCH": "Account Manager",
    "ACCOUNT_DUPLICATE_CUSTOMER": "Account Manager",
    "DUPLICATE_PO":         "Order Operations Supervisor",
}


def escalation_target(exc_type) -> str:
    return ESCALATION_ROUTING.get(exc_type, "Order Operations Supervisor")


def think(title: str, lines, icon: str = "🧠"):
    """Render a slow 'thinking' panel that shows the agent's internal checks
    and decisions, one line at a time. The panel stays expanded after
    completion so every internal bullet remains on screen for the CSR to
    scroll through — collapsing them hid the reasoning trail."""
    with st.status(f"{icon} {title}", expanded=True) as status:
        for item in lines:
            if isinstance(item, tuple):
                delay, text = item
            else:
                delay, text = THINK_PACE, item
            st.markdown(text)
            nap(delay)
        status.update(label=f"{icon} {title} — done", state="complete", expanded=True)
    # Small pause so the "complete" delta flushes to the browser BEFORE the
    # next think() panel or st.rerun() replaces this element's DOM position.
    # Without this the last think() panel of a phase sometimes keeps its
    # "running" spinner icon even though the label updated to "— done".
    nap(0.15)

# Friendly labels for hierarchy rule sources
LEVEL_LABEL = {
    "ship_to":           "Ship-To level",
    "branch":            "Branch level",
    "regional_division": "Regional Division level",
    "global_parent":     "Global Parent level",
}


# ── Dollar-sign safety ─────────────────────────────────────────────────────────
# Streamlit / KaTeX treats "$...$" as inline math, which mangles messages like
# "Order $10,786.98 is within budget ($250,000.00)" into spaced-out math glyphs.
# md_safe() escapes "$" for markdown contexts (st.markdown / st.info / st.success /
# st.error / st.warning). html_safe() uses the HTML entity for HTML fragments
# rendered with unsafe_allow_html=True so the visible glyph stays a plain "$".
def md_safe(text) -> str:
    if text is None:
        return ""
    return str(text).replace("$", r"\$")


def html_safe(text) -> str:
    if text is None:
        return ""
    return str(text).replace("$", "&#36;")


def _fmt_qty(q):
    """Format a quantity for display. Whole numbers drop the trailing '.0'
    (e.g. 0.0 -> '0', 120.0 -> '120'); non-whole values keep their digits.
    Returns None when there is no quantity so callers can show 'missing'."""
    if q is None or (isinstance(q, str) and not q.strip()):
        return None
    try:
        f = float(q)
    except (TypeError, ValueError):
        return str(q)
    return str(int(f)) if f == int(f) else f"{f:g}"

# ─── Helper: render extracted PO result card ──────────────────────────────────
def render_po_result(po: ExtractedPO, is_dup: bool, dup_rec: dict = None):
    conf = po.overall_confidence
    has_missing = bool(po.missing_fields)

    # Duplicate PO banner
    if is_dup:
        st.error("🔴  DUPLICATE PO DETECTED")
        st.markdown(
            f"A PO with number **{po.po_number or 'N/A'}** and customer "
            f"**{po.customer_account or 'N/A'}** was already submitted.\n\n"
            + (f"- **Submitted at:** {dup_rec.get('submitted_at','—')}\n"
               f"- **Status:** {dup_rec.get('status','—')}\n" if dup_rec else "")
            + "\n_Processing is paused. Please resolve the duplicate before continuing._"
        )
        return

    # Missing-fields banner
    if has_missing:
        st.warning("🟡  INTAKE EXCEPTION — Missing mandatory fields")
        for mf in po.missing_fields:
            st.markdown(f"  - ❌ **{mf}**")
        st.markdown("_Processing is paused. Please correct the missing fields and resubmit._")
        st.markdown("---")

    # Success banner
    if not has_missing:
        st.success("✅  PO Successfully Extracted — All mandatory fields found. Ready for next validation step.")

    # Confidence bar
    bar_color = "#4ADE80" if conf >= 80 else "#FCD34D" if conf >= 60 else "#F87171"
    st.markdown(
        f"**Overall Extraction Confidence: {conf}%** "
        f'<span class="conf-bar-wrap"><span class="conf-bar" '
        f'style="width:{conf}%; background:{bar_color};"></span></span>',
        unsafe_allow_html=True,
    )
    st.write("")

    # ── Header fields table ────────────────────────────────────────────────────
    st.markdown("#### 📋 Extracted Header Fields")
    scores = po.confidence_scores

    def conf_span(key):
        c = scores.get(key, 0)
        color = "#4ADE80" if c >= 80 else "#FCD34D" if c >= 60 else "#F87171"
        return f'<span style="color:{color}; font-size:12px;">▮ {c}%</span>'

    def val_cell(v, key=None):
        # Optional fields backfilled from master data get a small badge; truly
        # missing values are shown as a soft "not available" (no red).
        if v:
            src = (getattr(po, "field_source", {}) or {}).get(key)
            if src == "MASTER":
                return (f"{html_safe(str(v))} "
                        "<span style='color:#60A5FA; font-size:11px; "
                        "background:#1E293B; padding:1px 6px; border-radius:8px;'>"
                        "from master data</span>")
            return html_safe(str(v))
        return "<span style='color:#94A3B8;'>not available</span>"

    ship_to_disp = (getattr(po, "ship_to_name", None)
                    or getattr(po, "ship_to_address", None)
                    or (f"ZIP {po.ship_to_zip}" if po.ship_to_zip else None))
    fields = [
        ("po_number",               "PO Number *",                 po.po_number),
        ("po_date",                 "PO Date *",                   getattr(po, "po_date", None)),
        ("company_name",            "Buyer Company *",             getattr(po, "company_name", None)),
        ("buyer_email",             "Buyer Email *",               getattr(po, "buyer_email", None)),
        ("contact_person",          "Contact Person",              getattr(po, "contact_person", None)),
        ("customer_account",        "Customer Account (resolved)", po.customer_account),
        ("contract_reference",      "Contract Reference",          po.contract_reference),
        ("ship_to",                 "Ship-To *",                   ship_to_disp),
        ("requested_delivery_date", "Requested Delivery Date *",  po.requested_delivery_date),
        ("delivery_instructions",   "Delivery Instructions",      po.delivery_instructions),
    ]
    rows_html = "".join(
        f"<tr><td><b>{lbl}</b></td><td>{val_cell(v, k)}</td><td>{conf_span(k)}</td></tr>"
        for k, lbl, v in fields
    )
    st.markdown(
        '<table class="field-table"><thead><tr>'
        '<th>Field (* = mandatory)</th><th>Extracted Value</th><th>Confidence</th>'
        '</tr></thead><tbody>' + rows_html + '</tbody></table>',
        unsafe_allow_html=True,
    )
    st.write("")

    # ── Order lines table ──────────────────────────────────────────────────────
    st.markdown("#### 📦 Order Line Items")
    if po.order_lines:
        # Only include the UOM / Unit Price columns if at least one line has
        # them in the PO — the base UOM / unit price will be resolved from the
        # Product Master and displayed in the Product Match stage.
        show_uom   = any(ln.uom is not None and str(ln.uom).strip() for ln in po.order_lines)
        show_price = any(ln.unit_price for ln in po.order_lines)
        line_rows = ""
        for ln in po.order_lines:
            sku_v  = ln.sku  or '<span style="color:#F87171;">needs SKU</span>'
            qty_v  = _fmt_qty(ln.quantity)
            if qty_v is None:
                qty_v = '<span style="color:#F87171;">missing</span>'
            desc_v = ln.description or '<span style="color:#F87171;">missing</span>'
            c = round(ln.confidence * 100)
            col = "#4ADE80" if c >= 80 else "#FCD34D" if c >= 60 else "#F87171"
            row = (f"<tr><td>{ln.line_number}</td><td><b>{sku_v}</b></td>"
                   f"<td>{desc_v}</td><td>{qty_v}</td>")
            if show_uom:
                row += f"<td>{ln.uom or '—'}</td>"
            if show_price:
                row += f"<td>{'$'+format(ln.unit_price,',.2f') if ln.unit_price else '—'}</td>"
            row += f"<td><span style='color:{col};'>{c}%</span></td></tr>"
            line_rows += row
        headers = ['#', 'SKU', 'Description', 'Qty']
        if show_uom:   headers.append('UOM')
        if show_price: headers.append('Unit Price')
        headers.append('Confidence')
        hdr_html = "".join(f"<th>{h}</th>" for h in headers)
        st.markdown(
            '<table class="field-table"><thead><tr>' + hdr_html +
            '</tr></thead><tbody>' + line_rows + '</tbody></table>',
            unsafe_allow_html=True,
        )
    else:
        st.error("❌ No order line items found. SKU, Description, and Quantity are required per line.")

    st.write("")
    st.caption(f"Source: {po.source_type}  |  Extraction method: AI rule-based pattern engine")


# ─── Helper: render account hierarchy validation result ───────────────────────
def render_account_result(av: AccountValidationResult):
    st.markdown("### 🧭 Customer Validation")

    # ── Exception banners ───────────────────────────────────────────────────────
    if av.is_exception:
        if av.exception_type == "UNMATCHED_CUSTOMER":
            st.error("🔴  EXCEPTION — Unmatched Customer")
        elif av.exception_type == "DUPLICATE_CUSTOMER":
            st.warning("🟠  EXCEPTION — Duplicate Customer")
        elif av.exception_type == "INVALID_SHIP_TO":
            st.warning("🟡  EXCEPTION — Invalid Ship-To")
        elif av.exception_type == "HIERARCHY_MISMATCH":
            st.error("🔴  EXCEPTION — Account Hierarchy Mismatch")
        st.markdown(md_safe(av.message))

        # Show resolved customer/hierarchy so far (if any)
        if av.global_parent:
            st.markdown(
                f"**Customer hierarchy:** {av.global_parent['name']} › "
                f"{av.regional_division['name']} › {av.branch['name']}"
            )

        # Duplicate customer candidates
        if av.candidates:
            st.markdown("**Matching customer records (resolve to one):**")
            rows = "".join(
                f"<tr><td>{c['customer_account']}</td><td>{c['company_name']}</td>"
                f"<td>{c['branch_id']}</td><td>{c['erp_customer_id']}</td>"
                f"<td>{c['crm_account_id']}</td></tr>"
                for c in av.candidates
            )
            st.markdown(
                '<table class="field-table"><thead><tr>'
                '<th>Account</th><th>Company</th><th>Branch</th><th>ERP ID</th><th>CRM ID</th>'
                '</tr></thead><tbody>' + rows + '</tbody></table>',
                unsafe_allow_html=True,
            )

        # Possible ship-tos for the customer
        if av.possible_ship_tos:
            st.markdown("**Possible valid ship-to locations for this customer:**")
            rows = "".join(
                f"<tr><td>{s['ship_to_id']}</td><td>{s['name']}</td>"
                f"<td>{s['zip']}</td><td>{s['address']}</td></tr>"
                for s in av.possible_ship_tos
            )
            st.markdown(
                '<table class="field-table"><thead><tr>'
                '<th>Ship-To ID</th><th>Name</th><th>ZIP</th><th>Address</th>'
                '</tr></thead><tbody>' + rows + '</tbody></table>',
                unsafe_allow_html=True,
            )

        st.markdown("_Automated processing is paused. Please resolve this exception and resubmit._")
        with st.expander("🧾 View audit trail"):
            for line in av.audit_trail:
                st.markdown(f"- {md_safe(line)}")
        return

    # ── PASS — hierarchy identified ─────────────────────────────────────────────
    st.success("✅  Customer validated — account hierarchy identified, ship-to "
               "confirmed, standing & buying history verified.")

    # Hierarchy breadcrumb + customer standing (tier / terms / distributor)
    cust = av.customer or {}
    tier   = cust.get("customer_tier") or "—"
    terms  = cust.get("payment_terms") or "—"
    cls    = cust.get("customer_class") or "—"
    dist   = cust.get("distributor_authorization") or "—"
    dist_disp = f"{cls} · {dist}" if (cls != "—" or dist != "—") else "—"
    st.markdown("#### 🧭 Resolved Account Hierarchy")
    st.markdown(
        f"<table class='field-table'><tbody>"
        f"<tr><td><b>Global Parent</b></td><td>{av.global_parent['name']} "
        f"<span style='color:#64748B'>({av.global_parent['id']})</span></td></tr>"
        f"<tr><td><b>Regional Division</b></td><td>{av.regional_division['name']} "
        f"<span style='color:#64748B'>({av.regional_division['id']})</span></td></tr>"
        f"<tr><td><b>Local Branch</b></td><td>{av.branch['name']} "
        f"<span style='color:#64748B'>({av.branch['id']})</span></td></tr>"
        f"<tr><td><b>Ship-To Location</b></td><td>{av.ship_to['name']} "
        f"<span style='color:#64748B'>(ZIP {av.ship_to['zip']})</span></td></tr>"
        f"<tr><td><b>Customer</b></td><td>{av.customer['company_name']} "
        f"<span style='color:#64748B'>(ERP {av.customer['erp_customer_id']}, "
        f"CRM {av.customer['crm_account_id']})</span></td></tr>"
        f"<tr><td><b>Customer Tier</b></td><td>{html_safe(tier)}</td></tr>"
        f"<tr><td><b>Payment Terms</b></td><td>{html_safe(terms)}</td></tr>"
        f"<tr><td><b>Distributor Classification</b></td><td>{html_safe(dist_disp)}</td></tr>"
        f"</tbody></table>",
        unsafe_allow_html=True,
    )
    st.write("")

    # Buying history summary (Customer Validation decision layer)
    bh = av.buying_history
    if bh:
        st.markdown("#### 📚 Customer Buying History")
        fam = ", ".join(bh.get("frequent_families") or []) or "—"
        lv  = bh.get("lifetime_value")
        aov = bh.get("avg_order_value")
        lv_disp  = f"${int(float(lv)):,}"  if str(lv).replace('.', '', 1).isdigit()  else (lv or "—")
        aov_disp = f"${int(float(aov)):,}" if str(aov).replace('.', '', 1).isdigit() else (aov or "—")
        st.markdown(
            f"<table class='field-table'><tbody>"
            f"<tr><td><b>Customer Since</b></td><td>{html_safe(bh.get('customer_since') or '—')}</td></tr>"
            f"<tr><td><b>Lifetime Orders</b></td><td>{html_safe(bh.get('total_orders') or '—')}</td></tr>"
            f"<tr><td><b>Lifetime Value</b></td><td>{html_safe(lv_disp)}</td></tr>"
            f"<tr><td><b>Avg Order Value</b></td><td>{html_safe(aov_disp)}</td></tr>"
            f"<tr><td><b>Frequently Ordered Families</b></td><td>{html_safe(fam)}</td></tr>"
            f"<tr><td><b>Last Order</b></td><td>{html_safe(bh.get('last_order_date') or '—')}</td></tr>"
            f"</tbody></table>",
            unsafe_allow_html=True,
        )
        recent = bh.get("recent_orders") or []
        if recent:
            rows_html = ""
            for o in recent:
                skus = ", ".join(
                    f"{ln.get('sku')} ×{int(ln.get('quantity'))}"
                    for ln in (o.get("lines") or [])
                ) or "—"
                try:
                    tot = f"${float(o.get('order_total')):,.2f} {o.get('currency') or ''}".strip()
                except (TypeError, ValueError):
                    tot = "—"
                rows_html += (
                    f"<tr><td>{html_safe(o.get('order_date') or '—')}</td>"
                    f"<td>{html_safe(o.get('po_number') or '—')}</td>"
                    f"<td>{html_safe(skus)}</td>"
                    f"<td>{html_safe(tot)}</td></tr>"
                )
            st.markdown(
                "<div style='margin-top:6px;font-weight:600;'>Recent orders</div>"
                "<table class='field-table'><thead><tr>"
                "<th>Date</th><th>PO #</th><th>Items</th><th>Order Total</th>"
                "</tr></thead><tbody>" + rows_html + "</tbody></table>",
                unsafe_allow_html=True,
            )
        st.write("")

    # Applied rules with the level each came from
    st.markdown("#### ⚙️ Applied Hierarchy Rules (most specific level wins)")
    rule_label = {
        "pricing_tier":       "Pricing Tier",
        "product_visibility": "Product Visibility",
        "budget_limit":       "Budget Limit",
        "approval_routing":   "Approval Routing",
        "fulfillment_rule":   "Fulfillment Rule",
    }
    rows = ""
    for key, val in av.applied_rules.items():
        src = LEVEL_LABEL.get(av.applied_rule_sources.get(key), av.applied_rule_sources.get(key))
        display_val = f"${val:,}" if key == "budget_limit" and isinstance(val, (int, float)) else val
        rows += (f"<tr><td><b>{rule_label.get(key, key)}</b></td>"
                 f"<td>{html_safe(display_val)}</td>"
                 f"<td><span style='color:#38BDF8'>{src}</span></td></tr>")
    st.markdown(
        '<table class="field-table"><thead><tr>'
        '<th>Rule</th><th>Applied Value</th><th>Source Level</th>'
        '</tr></thead><tbody>' + rows + '</tbody></table>',
        unsafe_allow_html=True,
    )
    st.write("")
    st.caption(f"Most specific level applied: {LEVEL_LABEL.get(av.applied_level, av.applied_level)}")

    with st.expander("🧾 View audit trail"):
        for line in av.audit_trail:
            st.markdown(f"- {md_safe(line)}")


# Stages that are folded UNDER a decision layer (rendered as a nested sub-check
# rather than a separate top-level layer heading), matching the decision-layer
# taxonomy in Autonomous_PO_to_Fulfillment_Orchestration.docx:
#   buyer_authorization → within "Customer Validation"
#   compliance          → within "Product Match"
SUBCHECK_STAGES = {"buyer_authorization", "compliance"}


# ─── Helper: generic stage-result renderer (US-03 … US-12) ────────────────────
def render_stage_result(res, divider=True):
    is_subcheck = getattr(res, "stage_key", None) in SUBCHECK_STAGES
    if is_subcheck:
        # Nested sub-check: no divider, smaller heading so it visibly belongs
        # to the decision layer above it.
        st.markdown(f"#### ↳ {res.icon} {res.title}")
    else:
        # `divider` is suppressed when the layer is already wrapped in its own
        # bordered container (the tree layout) so we don't draw a rule inside
        # the box.
        if divider:
            st.markdown("---")
        st.markdown(f"### {res.icon} {res.title}")
    if res.is_exception:
        st.error(f"🔴  EXCEPTION — {res.exception_type}")
        st.markdown(md_safe(res.headline))
    else:
        st.success(f"✅  {md_safe(res.headline)}")

    for sec in res.sections:
        if sec["type"] == "kv":
            if sec.get("title"):
                st.markdown(f"**{md_safe(sec['title'])}**")
            rows = "".join(
                f"<tr><td><b>{html_safe(l)}</b></td><td>{html_safe(v)}</td></tr>"
                for l, v in sec["rows"]
            )
            st.markdown(f"<table class='field-table'><tbody>{rows}</tbody></table>",
                        unsafe_allow_html=True)
            st.write("")
        elif sec["type"] == "table":
            if sec.get("title"):
                st.markdown(f"**{md_safe(sec['title'])}**")
            head = "".join(f"<th>{html_safe(h)}</th>" for h in sec["headers"])
            body = "".join("<tr>" + "".join(f"<td>{html_safe(c)}</td>" for c in r) + "</tr>"
                           for r in sec["rows"])
            st.markdown(f"<table class='field-table'><thead><tr>{head}</tr></thead>"
                        f"<tbody>{body}</tbody></table>", unsafe_allow_html=True)
            st.write("")
        elif sec["type"] == "note":
            st.markdown(f"_{md_safe(sec['text'])}_")

    # ── Non-CSR approval: email notification + hard stop banner ──────────
    if res.data.get("approval_email_sent_to"):
        approver  = res.data["approval_email_sent_to"]
        role      = res.data.get("approval_email_role", "")
        role_disp = f" ({role})" if role else ""
        st.info(
            f"📧 **Triggered email to respective approver and awaiting approval.**\n\n"
            f"A notification has been sent to **{approver}{role_disp}**. "
            f"The order will resume automatically once the approver responds."
        )
        st.markdown(
            "<div style='background:#1E293B; border-left:4px solid #F59E0B; "
            "padding:12px 16px; border-radius:6px; margin-top:8px;'>"
            "⏸ <b>Process halted</b> — no further actions will be executed until "
            "approval is granted or rejected."
            "</div>",
            unsafe_allow_html=True,
        )
        st.write("")

    if res.audit_trail:
        with st.expander("🧾 View audit trail"):
            for line in res.audit_trail:
                st.markdown(f"- {md_safe(line)}")


def _run_stage_animation(stage, ctx):
    """Animate a pipeline stage step-by-step.

    We keep the status widget `expanded=True` after completion (instead of
    collapsing it to a one-line accordion header) so every processing step
    stays on screen. This matters after CSR interactive decisions — the user
    needs to *see* the pipeline resume and progress stage-by-stage, not just
    watch a stack of collapsed headers appear."""
    result = [None]
    # Subcheck stages (buyer authorization, compliance) belong UNDER a parent
    # decision layer, so mark them with a "↳" during the live animation too —
    # matching how the settled view nests them (see render_stage_result).
    prefix = "↳ " if getattr(stage, "stage_key", None) in SUBCHECK_STAGES else ""
    with st.status(f"{prefix}{stage.icon} {stage.title}...", expanded=True) as status:
        for delay, emoji, text in stage.steps:
            st.write(f"{emoji} {text}")
            nap(paced_delay(delay))
        result[0] = stage.validate(ctx)
        status.update(label=f"{prefix}{stage.icon} {stage.title} — complete",
                      state="complete", expanded=True)
    return result[0]


def _run_full_pipeline_legacy(po: ExtractedPO, av: AccountValidationResult):
    """(Retained for reference — superseded by the interactive orchestrator.)"""
    ctx = build_context(po, av)
    results = []
    paused = False

    for stage in SEQUENTIAL_STAGES:
        res = _run_stage_animation(stage, ctx)
        ctx.update(res.data or {})
        render_stage_result(res)
        results.append(res)
        if res.is_exception:
            paused = True
            break

    # Exception governance (always runs)
    with st.status(f"{GOVERNANCE.icon} {GOVERNANCE.title}...", expanded=True) as status:
        for delay, emoji, text in GOVERNANCE.steps:
            st.write(f"{emoji} {text}")
            nap(paced_delay(delay))
        gov = GOVERNANCE.route(results, ctx)
        status.update(label=f"{GOVERNANCE.icon} {GOVERNANCE.title} — complete",
                      state="complete", expanded=False)
    render_stage_result(gov)
    results.append(gov)

    # Order execution (only when nothing paused)
    if not paused:
        ex = _run_stage_animation(EXECUTION, ctx)
        ctx.update(ex.data or {})
        render_stage_result(ex)
        results.append(ex)

    return results


# ─── Helper: account validation processing animation ──────────────────────────
def run_account_validation(customer_account, ship_to_zip, company_name=None) -> AccountValidationResult:
    steps = [
        (0.35, "🏢", "Resolving customer identity against customer master..."),
        (0.30, "🔗", "Checking ERP and CRM customer records..."),
        (0.35, "🧭", "Mapping corporate account hierarchy (parent › division › branch)..."),
        (0.30, "📍", "Validating ship-to location against ship-to master..."),
        (0.30, "🔍", "Confirming ship-to belongs to customer hierarchy..."),
        (0.30, "🏷️", "Reading customer tier, distributor classification & payment terms..."),
        (0.30, "📚", "Verifying customer buying history (tenure, volume, payment behaviour)..."),
        (0.30, "⚙️", "Determining applicable hierarchy-level rules..."),
        (0.25, "🧾", "Recording applied hierarchy level in audit trail..."),
    ]
    result = [None]
    with st.status("AI Agent Validating Customer...", expanded=True) as status:
        for i, (delay, emoji, text) in enumerate(steps):
            st.write(f"{emoji} {text}")
            nap(paced_delay(delay))
            if i == 4 and result[0] is None:
                result[0] = ACCOUNT_VALIDATOR.validate(customer_account, ship_to_zip, company_name)
        status.update(label="✅ Account validation complete — results below",
                      state="complete", expanded=True)
    if result[0] is None:
        result[0] = ACCOUNT_VALIDATOR.validate(customer_account, ship_to_zip, company_name)
    return result[0]


# ─── Helper: AI processing animation ─────────────────────────────────────────
def run_ai_processing(raw_text: str, source_label: str) -> ExtractedPO:
    steps = [
        (0.35, "📄", "Analyzing document format and structure..."),
        (0.30, "🔍", "Reading PO header section..."),
        (0.30, "🔢", "Extracting Purchase Order number..."),
        (0.30, "👤", "Identifying customer account information..."),
        (0.40, "📦", "Scanning order line items (SKU / Qty / UOM)..."),
        (0.25, "🏷️", "Matching unit-of-measure codes to known standards..."),
        (0.30, "📍", "Extracting ship-to location and ZIP code..."),
        (0.30, "📅", "Parsing requested delivery date..."),
        (0.25, "📋", "Reading delivery and special instructions..."),
        (0.20, "📄", "Checking for contract reference..."),
        (0.40, "🔄", "Scanning duplicate PO submissions registry..."),
        (0.30, "🧮", "Calculating confidence scores for each field..."),
        (0.20, "✔️",  "Validating mandatory fields..."),
        (0.20, "📊", "Preparing extraction report..."),
    ]

    extracted = [None]

    with st.status(f"AI Agent Processing — {source_label}", expanded=True) as status:
        for i, (delay, emoji, text) in enumerate(steps):
            st.write(f"{emoji} {text}")
            nap(paced_delay(delay))
            # Run actual extraction halfway through animation
            if i == 7 and extracted[0] is None:
                extracted[0] = EXTRACTOR.extract_from_text(raw_text)
        status.update(
            label="✅ Processing Complete — results below",
            state="complete",
            expanded=False,
        )

    # Ensure extraction ran even if steps were very fast
    if extracted[0] is None:
        extracted[0] = EXTRACTOR.extract_from_text(raw_text)
    return extracted[0]


# ══════════════════════════════════════════════════════════════════════════════
#  INTERACTIVE ORCHESTRATOR
#  A resumable, human-in-the-loop run stored in st.session_state.orch. Each
#  Streamlit rerun renders everything already settled, then performs ONE unit of
#  work: it either animates the next step, or pauses on a decision and shows the
#  CSR "Approve / Reject / Escalate" (and correction) controls. This lets the
#  agent stop mid-process, take CSR input, and resume — exactly like a real
#  order desk (US-11 AC-01 / AC-02).
# ══════════════════════════════════════════════════════════════════════════════
def new_orchestration(kind: str, payload):
    st.session_state.orch = {
        # Unique id per submitted PO. The whole run is rendered inside a
        # container keyed by this id, so submitting a NEW PO changes the key and
        # Streamlit tears down the previous PO's entire subtree (instead of
        # trying to reconcile old content into the new run and leaving it on
        # screen).
        "run_id": uuid.uuid4().hex[:8],
        # False until the one-shot "clearing frame" has run and finished
        # successfully (which prunes the previous PO's DOM). See the main render.
        "cleared": False,
        "kind": kind, "payload": payload,
        "phase": "start",
        "po": None, "source_label": None,
        "is_dup": False, "dup_rec": None,
        "av": None,
        "issues": [], "issue_ptr": 0,
        "decisions": [],       # settled CSR decisions (rendered as history)
        # Persistent record of decision CARDS the CSR has already actioned.
        # We keep them on screen (in render_orch_static) so the next stage's
        # animation appears BELOW the button the CSR just clicked, matching
        # the natural reading order. Each entry is a dict with:
        #   title, kind, detail, rationale, decision, outcome
        "resolved_issues": [],
        "ctx": None,
        "stage_index": 0,
        "governance_done": False,  # guard so a stage-exception re-entry does
                                   # not re-run governance twice
        "results": [],         # settled StageResults
        "pending": None,       # current stage exception awaiting CSR
        "terminal": None,      # ('rejected'|'escalated', message)
    }


def _decision_key(prefix: str) -> str:
    o = st.session_state.orch
    return f"{prefix}_{o['phase']}_{o['issue_ptr']}_{o['stage_index']}"


# ── Rendering: settled (static) portion of a run ──────────────────────────────
def render_decision_log(decisions):
    if not decisions:
        return
    st.markdown("#### 🧾 CSR Decision Audit Trail")
    st.caption("For every gate: why the AI paused for CSR approval, what it had "
               "already decided automatically from master data, and the CSR's action.")
    action_style = {
        "Approved":      ("✅", "#10B981"),
        "Picked":        ("✅", "#10B981"),
        "Entered":       ("✍️", "#0EA5E9"),
        "Rejected":      ("⛔", "#EF4444"),
        "Auto-rejected": ("⛔", "#EF4444"),
        "Escalated":     ("⏫", "#F59E0B"),
    }
    for n, d in enumerate(decisions, 1):
        action = d.get("decision", "")
        icon, colour = action_style.get(action, ("•", "#64748B"))
        reason = (d.get("reason") or "").strip()
        auto = [a for a in (d.get("auto") or []) if a]
        auto_html = ""
        if auto:
            items = "".join(f"<li>{html_safe(a)}</li>" for a in auto)
            auto_html = (
                "<div style='color:#94A3B8; font-size:0.85rem; margin-top:4px;'>"
                "<b>AI decided automatically from master data:</b>"
                f"<ul style='margin:2px 0 0 0; padding-left:18px;'>{items}</ul></div>"
            )
        reason_html = (
            "<div style='color:#CBD5E1; font-size:0.88rem; margin-top:2px;'>"
            f"<b>Why CSR approval was needed:</b> {html_safe(reason)}</div>"
            if reason else ""
        )
        st.markdown(
            f"<div style='background:#0F172A; border-left:4px solid {colour}; "
            f"padding:10px 14px; border-radius:6px; margin-bottom:8px;'>"
            f"<div style='color:#E2E8F0; font-weight:600;'>"
            f"Step {n} · {html_safe(d.get('what',''))}</div>"
            f"{reason_html}{auto_html}"
            f"<div style='color:#E2E8F0; font-size:0.88rem; margin-top:6px;'>"
            f"<b>CSR action:</b> {icon} {html_safe(action)}"
            + (f" &nbsp;—&nbsp; {html_safe(d.get('detail',''))}" if d.get('detail') else "")
            + "</div></div>",
            unsafe_allow_html=True,
        )
    st.write("")


def _render_resolved_issue_card(entry):
    """Static replay of a CSR-actioned intake decision card. Kept on screen
    so the next stage's animation appears BELOW it (natural reading order),
    not in the space the card used to occupy."""
    decision = entry.get("decision", "Resolved")
    icon, colour = {
        "Approved":  ("✅", "#10B981"),
        "Picked":    ("✅", "#10B981"),
        "Entered":   ("✍️", "#0EA5E9"),
        "Rejected":  ("⛔", "#EF4444"),
        "Escalated": ("⏫", "#F59E0B"),
    }.get(decision, ("✅", "#10B981"))
    st.markdown(
        f"<div style='background:#0F172A; border-left:4px solid {colour}; "
        f"padding:12px 16px; border-radius:6px;'>"
        f"<div style='color:{colour}; font-weight:600; margin-bottom:4px;'>"
        f"{icon}  CSR DECISION APPLIED — {html_safe(entry['title'])}</div>"
        f"<div style='color:#CBD5E1; font-size:0.9rem; margin-bottom:6px;'>"
        f"{md_safe(entry.get('detail', ''))}</div>"
        + (f"<div style='color:#94A3B8; font-size:0.85rem; margin-bottom:6px;'>"
           f"🧠 <i>AI reasoning: {html_safe(entry['rationale'])}</i></div>"
           if entry.get('rationale') else "")
        + f"<div style='color:#E2E8F0; font-size:0.9rem;'>"
          f"<b>Action:</b> {icon} {html_safe(decision)} &nbsp; "
          f"<b>Outcome:</b> {html_safe(entry.get('outcome', ''))}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.write("")


def render_orch_static(orch):
    """Render everything already settled for the active run (no animation).

    Layout strategy: the extracted PO card stays in ONE stable chat_message
    at the top (so the widget IDs of any live inputs below it never shift).
    Resolved intake decision cards are NOT rendered here — they are rendered
    inside `drive_orchestration` right before the current decision card /
    resuming animation, so new content always stacks BELOW the button the
    CSR just clicked."""
    with st.chat_message("assistant"):
        # Layout: each main decision layer is a heading followed by its
        # processes, then a horizontal line separator before the next layer:
        #     Intake  →  (rest of intake)  →  ───
        #     Customer Validation  →  (rest)  →  ───
        #     ...
        # Sub-checks (buyer authorization, compliance) are indented one level
        # so they read as children of their parent decision layer.

        # ── Intake ───────────────────────────────────────────────────────
        st.markdown("### 📥 Intake")
        if orch["po"] is None:
            return
        # The duplicate banner is handled interactively by the driver, so
        # always show the full PO card here (never short-circuit on is_dup).
        render_po_result(orch["po"], False, None)
        # Rolling CSR decision log (compact summary — the individual card
        # bubbles are re-rendered inline inside drive_orchestration).
        render_decision_log(orch["decisions"])
        st.markdown("---")

        results = orch["results"]
        rendered = set()

        # ── Customer Validation (+ Buyer Authorization sub-check) ─────────
        # A settled (non-exception, or overridden) account result is history.
        # An unresolved account exception is rendered by the drive step instead.
        if orch["av"] is not None and (not orch["av"].is_exception
                                       or orch["phase"] not in ("account_pending",)):
            render_account_result(orch["av"])
            for res in results:
                if res.stage_key == "buyer_authorization":
                    _render_nested_subcheck(res)
                    rendered.add(id(res))
            st.markdown("---")

        # ── Remaining decision layers ────────────────────────────────────
        # Each non-subcheck stage is a heading + processes + separator.
        # Compliance is a sub-check nested under the Product Match layer.
        for res in results:
            if id(res) in rendered:
                continue
            if res.stage_key in SUBCHECK_STAGES:
                continue  # nested under its parent layer below
            render_stage_result(res, divider=False)
            if res.stage_key == "product_match":
                for sub in results:
                    if sub.stage_key == "compliance":
                        _render_nested_subcheck(sub)
                        rendered.add(id(sub))
            st.markdown("---")


def _render_nested_subcheck(res):
    """Render a sub-check (e.g. buyer authorization, compliance) indented one
    level so it reads as a child of the decision layer above it."""
    _, body = st.columns([1, 22], gap="small")
    with body:
        render_stage_result(res, divider=False)


def _render_resolved_intake_cards(orch):
    """Render all CSR-actioned intake decision cards in chronological order.
    Called from the intake_issues / account driver so the just-resolved
    card appears in the same chat bubble flow as (and immediately above)
    the next decision card OR the resuming pipeline animation."""
    for entry in orch.get("resolved_issues", []):
        _render_resolved_issue_card(entry)


# ── Rendering: interactive decision cards ─────────────────────────────────────
def _uses_radio(issue):
    """True when this issue's candidate options are presented as a radio
    pick-list. In that case the plain 'Possible matches' HTML table must NOT
    be rendered separately — the radio list IS the table (with a selector),
    so the same options are not repeated twice on screen."""
    return (issue.kind in RADIO_KINDS and bool(issue.suggestions)
            and (len(issue.suggestions) >= 2 or issue.kind == "UNRESOLVED_BUYER"))


def _impact_table_for_issue(issue):
    if issue.kind == "SUBSTITUTE_SKU" and issue.recommended:
        r = issue.recommended
        st.markdown("**Substitution recommendation (CSR approval required):**")
        st.markdown(
            "<table class='field-table'><thead><tr>"
            "<th>Original SKU</th><th>Recommended Substitute</th><th>Compatibility</th>"
            "<th>Price Impact</th><th>Availability</th></tr></thead><tbody>"
            f"<tr><td>{html_safe(r['original_sku'])}</td>"
            f"<td><b>{html_safe(r['substitute_sku'])}</b> — {html_safe(r.get('substitute_description') or '')}</td>"
            f"<td>{html_safe(r['compatibility'])}</td>"
            f"<td>{html_safe(str(r['price_impact_pct'])+'%' if r.get('price_impact_pct') is not None else '—')}</td>"
            f"<td>{html_safe(r['availability_impact'])}</td></tr>"
            "</tbody></table>",
            unsafe_allow_html=True,
        )
    elif issue.kind == "UOM_CONVERSION" and issue.recommended:
        c = issue.recommended
        st.markdown("**Unit-of-measure conversion (CSR to confirm):**")
        st.markdown(
            "<table class='field-table'><thead><tr>"
            "<th>Original Qty</th><th>Original UOM</th>"
            "<th>Converted Qty</th><th>Converted UOM</th>"
            "<th>Conversion Logic</th></tr></thead><tbody>"
            f"<tr><td>{html_safe(c.get('original_qty'))}</td>"
            f"<td>{html_safe(c.get('original_uom'))}</td>"
            f"<td><b>{html_safe(c.get('qty_base'))}</b></td>"
            f"<td><b>{html_safe(c.get('uom'))}</b></td>"
            f"<td>{html_safe(c.get('logic'))}</td></tr>"
            "</tbody></table>",
            unsafe_allow_html=True,
        )
        if c.get("rule"):
            st.caption(f"Approved conversion rule: {html_safe(c['rule'])}")
    elif issue.kind == "UOM_AMBIGUOUS" and issue.suggestions:
        st.markdown("**Which UOM did the customer intend? (CSR to confirm)**")
        head = ("<th>Option</th><th>Requested Qty</th><th>UOM</th>"
                "<th>Converted to Base UOM</th><th>Conversion Rule</th>")
        rows = []
        for s in issue.suggestions:
            is_rec = (issue.recommended and s.get("kind") == issue.recommended.get("kind"))
            marker = " (AI default)" if is_rec else ""
            rule   = ("no conversion needed" if s["kind"] == "base"
                      else f"{int(s['qty'])} {s['uom']} × "
                           f"{int(s['qty_base']/s['qty']) if s['qty'] else 0} = "
                           f"{s['qty_base']} {s['label'].split()[-2] if s.get('label') else ''}")
            rows.append(
                f"<tr><td><b>{'Individual pieces' if s['kind']=='base' else 'Full packs'}{marker}</b></td>"
                f"<td>{int(s['qty'])}</td><td>{html_safe(s['uom'])}</td>"
                f"<td><b>{s['qty_base']} {html_safe(issue.recommended['uom']) if issue.recommended else ''}</b></td>"
                f"<td>{html_safe(rule)}</td></tr>"
            )
        st.markdown(f"<table class='field-table'><thead><tr>{head}</tr></thead>"
                    f"<tbody>{''.join(rows)}</tbody></table>", unsafe_allow_html=True)
    elif issue.kind == "UNRESOLVED_BUYER" and not _uses_radio(issue):
        st.markdown("**Buyers registered for this customer (CSR to pick or type a name):**")
        if issue.suggestions:
            body = "".join(
                f"<tr><td><b>{html_safe(s.get('buyer_name'))}</b></td>"
                f"<td>{html_safe(s.get('email'))}</td>"
                f"<td>{html_safe(s.get('role'))}</td>"
                f"<td>{html_safe(s.get('customer_account'))}</td>"
                f"<td>{html_safe(s.get('default_cost_center'))}</td></tr>"
                for s in issue.suggestions
            )
            st.markdown(
                "<table class='field-table'><thead><tr>"
                "<th>Buyer</th><th>Email</th><th>Role</th>"
                "<th>Customer</th><th>Default Cost Center</th>"
                "</tr></thead><tbody>" + body + "</tbody></table>",
                unsafe_allow_html=True,
            )
        else:
            st.info("No buyers are registered against this customer in the "
                    "buyer directory. CSR to type the correct buyer name.")
    elif issue.kind == "INVALID_QUANTITY":
        rec = issue.recommended or {}
        line_label = rec.get("line_label") or issue.original
        qty_disp = _fmt_qty(rec.get("qty_raw", issue.original))
        qty_cell = qty_disp if qty_disp is not None else "missing"
        st.markdown("**Quantity on this line cannot be processed:**")
        st.markdown(
            "<table class='field-table'><thead><tr>"
            "<th>Line</th><th>SKU / Description</th><th>Quantity on PO</th>"
            "</tr></thead><tbody>"
            f"<tr><td>{issue.line_number}</td>"
            f"<td>{html_safe(line_label) or '&mdash;'}</td>"
            f"<td><span style='color:#F87171;'><b>{html_safe(qty_cell)}</b></span></td>"
            "</tr></tbody></table>",
            unsafe_allow_html=True,
        )
    elif issue.suggestions and not _uses_radio(issue):
        if issue.kind in ("PARTIAL_SHIP_TO", "UNRESOLVED_SHIP_TO"):
            head = "<th>Ship-To</th><th>Address</th><th>ZIP</th><th>Match</th>"
            body = "".join(
                f"<tr><td><b>{html_safe(s.get('name'))}</b></td>"
                f"<td>{html_safe(s.get('address'))}</td><td>{html_safe(s.get('zip'))}</td>"
                f"<td>{int(s.get('score',0)*100)}%</td></tr>" for s in issue.suggestions
            )
        else:
            head = "<th>SKU</th><th>Description</th><th>Family</th><th>Match</th>"
            body = "".join(
                f"<tr><td><b>{html_safe(s.get('sku'))}</b></td>"
                f"<td>{html_safe(s.get('description'))}</td><td>{html_safe(s.get('family'))}</td>"
                f"<td>{int(s.get('score',0)*100)}%</td></tr>" for s in issue.suggestions
            )
        st.markdown("**Possible matches from master data:**")
        st.markdown(f"<table class='field-table'><thead><tr>{head}</tr></thead>"
                    f"<tbody>{body}</tbody></table>", unsafe_allow_html=True)


def apply_issue_decision(orch, issue, decision, value=None):
    """Mutate the PO for a resolved intake issue and record the CSR decision."""
    # The CSR usually scrolls up to read the card / type a correction before
    # clicking, which disengages auto-follow. Re-engage it so the resuming
    # pipeline animation is followed down the page again.
    st.session_state.reengage_scroll = True
    po = orch["po"]
    detail = ""
    if decision in ("Approved", "Picked", "Entered"):
        if issue.kind == "SUBSTITUTE_SKU":
            # Approve = accept the AI's recommended substitute.
            # Enter    = CSR typed a completely different SKU to use instead.
            if decision == "Entered" and isinstance(value, str) and value.strip():
                new_sku = value.strip().upper()
                new_desc = None
            else:
                new_sku = (issue.recommended or {}).get("substitute_sku")
                new_desc = (issue.recommended or {}).get("substitute_description")
            for ln in po.order_lines:
                if ln.line_number == issue.line_number:
                    ln.sku = new_sku
                    if new_desc:
                        ln.description = new_desc
            detail = (f"Substituted with {new_sku}" +
                      (" (CSR entry)" if decision == "Entered" else ""))
        elif issue.kind in ("UNRESOLVED_SKU", "MISSING_SKU"):
            top = issue.recommended or (issue.suggestions[0] if issue.suggestions else None)
            if isinstance(value, dict):
                # CSR picked one of the candidate SKUs from the radio list.
                top = value
                new_sku = value.get("sku")
            elif isinstance(value, str) and value.strip():
                # CSR typed the SKU — normalize case + whitespace so downstream
                # product_matcher (which keys on the master-data casing) can
                # find it. Without this, "sku-drn-3010" typed by the CSR would
                # miss the "SKU-DRN-3010" key and the pipeline would fail with
                # PRODUCT_CONFIG_EXCEPTION at product matching.
                new_sku = value.strip().upper()
            else:
                new_sku = top.get("sku") if top else None
            for ln in po.order_lines:
                if ln.line_number == issue.line_number:
                    ln.sku = new_sku
                    if not ln.description and top:
                        ln.description = top.get("description")
            detail = f"SKU set to {new_sku}"
        elif issue.kind == "UOM_CONVERSION":
            # Non-standard UOM converted to the base UOM using an approved rule.
            choice = value if isinstance(value, dict) else (issue.recommended or {})
            new_uom = choice.get("uom")
            new_qty = choice.get("qty_base")
            for ln in po.order_lines:
                if ln.line_number == issue.line_number:
                    ln.uom = new_uom
                    if new_qty:
                        ln.quantity = new_qty
            detail = (f"Converted {choice.get('original_qty')} "
                      f"{choice.get('original_uom')} → {new_qty} {new_uom} "
                      f"({choice.get('logic')})")
        elif issue.kind == "UOM_AMBIGUOUS":
            # decision comes from either "Approve" (AI default = base) or
            # "Pick" (whichever option index the CSR chose via `value`)
            choice = None
            if isinstance(value, dict) and value.get("kind"):
                choice = value
            elif decision == "Picked" and issue.suggestions:
                choice = issue.suggestions[-1]     # user chose "packs"
            else:
                choice = issue.recommended or (issue.suggestions[0] if issue.suggestions else {})
            new_uom = choice.get("uom")
            new_qty = choice.get("qty_base")
            for ln in po.order_lines:
                if ln.line_number == issue.line_number:
                    ln.uom = new_uom
                    if new_qty:
                        ln.quantity = new_qty
            detail = (f"UOM confirmed as {new_uom}; qty resolved to "
                      f"{new_qty} {choice.get('uom') if choice.get('kind')=='base' else 'base UOM'} "
                      f"({choice.get('label')})")
        elif issue.kind in ("PARTIAL_SHIP_TO", "UNRESOLVED_SHIP_TO"):
            if isinstance(value, dict):     # CSR picked a match from the radio list
                chosen = value
                if chosen.get("zip"):
                    po.ship_to_zip = chosen["zip"]
                po.ship_to_name = chosen.get("name") or po.ship_to_name
                if chosen.get("address"):
                    po.ship_to_address = chosen["address"]
                detail = f"Ship-to set to {chosen.get('name')} (ZIP {chosen.get('zip')})"
            elif isinstance(value, str) and value.strip():   # CSR typed a correction
                po.ship_to_address = value
                zip_m = __import__("re").search(r"\b(\d{5})(?:-\d{4})?\b", value)
                if zip_m:
                    po.ship_to_zip = zip_m.group(1)
                detail = f"Ship-to corrected: {value}"
            else:
                chosen = issue.recommended or (issue.suggestions[0] if issue.suggestions else {})
                if chosen.get("zip"):
                    po.ship_to_zip = chosen["zip"]
                po.ship_to_name = chosen.get("name") or po.ship_to_name
                detail = f"Ship-to set to {chosen.get('name')} (ZIP {chosen.get('zip')})"
        elif issue.kind == "UNRESOLVED_BUYER":
            # Value can be either:
            #   * a dict picked from the suggestions (Picked action), or
            #   * a free-text buyer name / email typed by the CSR (Entered).
            chosen = value if isinstance(value, dict) else None
            if chosen is None and isinstance(value, str) and value.strip():
                # Try to resolve the typed value against the buyer directory
                # (by name first, then by email).
                needle = value.strip().lower()
                for b in issue.suggestions:
                    if (b.get("buyer_name") or "").lower() == needle \
                       or (b.get("email") or "").lower() == needle:
                        chosen = b; break
                if chosen is None:
                    # Free-text buyer that isn't in master — set the name only
                    # and let downstream authorization handle it.
                    po.contact_person = value.strip()
                    po.field_source["contact_person"] = "CSR"
                    po.confidence_scores["contact_person"] = 100
                    detail = f"Contact person set from CSR entry: {value.strip()}"
            if chosen is not None:
                po.contact_person = chosen.get("buyer_name") or po.contact_person
                po.buyer_id       = chosen.get("buyer_id")   or po.buyer_id
                po.cost_center    = chosen.get("default_cost_center") or po.cost_center
                if not po.customer_account and chosen.get("customer_account"):
                    po.customer_account = chosen["customer_account"]
                if chosen.get("email"):
                    po.buyer_email = chosen["email"]
                po.field_source["contact_person"] = "CSR"
                po.confidence_scores["contact_person"] = 100
                detail = (f"Buyer set to {chosen.get('buyer_name')} "
                          f"(id {chosen.get('buyer_id')})")
        elif issue.kind == "INVALID_QUANTITY":
            # CSR types the correct quantity for this line.
            new_qty = None
            if value not in (None, ""):
                try:
                    new_qty = float(value)
                except (TypeError, ValueError):
                    new_qty = None
            if new_qty is not None and new_qty > 0:
                for ln in po.order_lines:
                    if ln.line_number == issue.line_number:
                        ln.quantity = new_qty
                        break
                detail = f"Quantity set to {new_qty} (CSR entry)"
            else:
                detail = f"CSR entered invalid quantity: {value!r} — line still blocked"
    orch["decisions"].append({"what": issue.title, "decision": decision, "detail": detail,
                              "reason": issue.rationale or issue.detail or "",
                              "auto": [issue.detail] if issue.detail else []})
    # Snapshot the resolved card so render_orch_static can keep it visible on
    # subsequent reruns — otherwise the card vanishes on click and the next
    # stage renders where the card USED to be, making it look like new content
    # appeared "above" the button the CSR just clicked.
    orch["resolved_issues"].append({
        "title":     issue.title,
        "kind":      issue.kind,
        "detail":    issue.detail,
        "rationale": issue.rationale,
        "decision":  decision,
        "outcome":   detail,
    })


def _intake_reject(orch, issue):
    """Shared 'Reject' terminal action for an intake decision card."""
    orch["decisions"].append({"what": issue.title, "decision": "Rejected",
                              "detail": "CSR rejected — order stopped.",
                              "reason": issue.rationale or issue.detail or "",
                              "auto": [issue.detail] if issue.detail else []})
    orch["resolved_issues"].append({
        "title": issue.title, "kind": issue.kind, "detail": issue.detail,
        "rationale": issue.rationale, "decision": "Rejected",
        "outcome": "CSR rejected — order stopped.",
    })
    orch["terminal"] = ("rejected", f"Order rejected by CSR at intake: {issue.title}.")
    orch["phase"] = "terminal"
    st.rerun()


def _intake_escalate(orch, issue):
    """Shared 'Escalate' terminal action for an intake decision card."""
    target = escalation_target(issue.kind)
    orch["decisions"].append({"what": issue.title, "decision": "Escalated",
                              "detail": f"Routed to {target}.",
                              "reason": issue.rationale or issue.detail or "",
                              "auto": [issue.detail] if issue.detail else []})
    orch["resolved_issues"].append({
        "title": issue.title, "kind": issue.kind, "detail": issue.detail,
        "rationale": issue.rationale, "decision": "Escalated",
        "outcome": f"Routed to {target}.",
    })
    orch["terminal"] = ("escalated", f"Escalated to {target}: {issue.title}.")
    orch["phase"] = "terminal"
    st.rerun()


def _radio_label_for(issue, s):
    """One-line, column-aligned label for a suggestion in a radio-select card.
    Renders every field the old 'Possible matches' table showed, so the radio
    list fully replaces that table instead of duplicating it."""
    if issue.kind == "UNRESOLVED_BUYER":
        return (f"**{s.get('buyer_name')}**  ·  {s.get('email')}  ·  "
                f"{s.get('role')}  ·  {s.get('customer_account')}  ·  "
                f"cost ctr {s.get('default_cost_center') or '—'}")
    if issue.kind in ("PARTIAL_SHIP_TO", "UNRESOLVED_SHIP_TO"):
        pct = int(s.get('score', 0) * 100)
        return (f"**{s.get('name')}**  ·  {s.get('address')}  ·  "
                f"ZIP {s.get('zip')}  ·  **{pct}% match**")
    pct = int(s.get('score', 0) * 100)
    return (f"**{s.get('sku')}**  ·  {s.get('description')}  ·  "
            f"{s.get('family') or '—'}  ·  **{pct}% match**")


# Decision kinds whose options are presented as a radio list to pick + approve.
RADIO_KINDS = ("UNRESOLVED_BUYER", "PARTIAL_SHIP_TO", "UNRESOLVED_SHIP_TO",
               "UNRESOLVED_SKU", "MISSING_SKU")


def render_intake_issue(orch, issue):
    """Render an intake issue with Approve / Reject / Escalate + correction input."""
    st.markdown("---")
    st.warning(f"🟡  CSR DECISION NEEDED — {issue.title}")
    st.markdown(md_safe(issue.detail))
    if issue.rationale:
        st.caption(f"🧠 AI reasoning: {issue.rationale}")
    _impact_table_for_issue(issue)

    # UOM_CONVERSION (non-standard UOM): Approve the conversion to the base UOM,
    # Reject, or Escalate. The conversion table + rule is shown above.
    if issue.kind == "UOM_CONVERSION":
        c = issue.recommended or {}
        cols = st.columns(3)
        if cols[0].button(
                f"✅ Approve conversion → {c.get('qty_base')} {c.get('uom')}",
                key=_decision_key("uomc_ok"), use_container_width=True):
            apply_issue_decision(orch, issue, "Approved", value=c)
            orch["issue_ptr"] += 1
            st.rerun()
        if cols[1].button("⛔ Reject", key=_decision_key("uomc_no"),
                          use_container_width=True):
            _intake_reject(orch, issue)
        if cols[2].button("⏫ Escalate", key=_decision_key("uomc_esc"),
                          use_container_width=True):
            _intake_escalate(orch, issue)
        return

    # Multi-option decisions (buyer / ship-to / multi-match SKU): the CSR picks
    # ONE option with a radio button, optionally types a correction, then
    # approves. Replaces the old one-button-per-suggestion layout.
    if _uses_radio(issue):
        if issue.kind == "UNRESOLVED_BUYER":
            st.markdown("**Buyers registered for this customer — pick one:**")
        else:
            st.markdown("**Possible matches from master data — pick one:**")
        idxs = list(range(len(issue.suggestions)))
        sel = st.radio(
            "options", options=idxs,
            format_func=lambda i: _radio_label_for(issue, issue.suggestions[i]),
            key=_decision_key("radio"), label_visibility="collapsed",
        )
        selected = issue.suggestions[sel]

        typed = None
        entry_error = None
        if "enter" in issue.actions:
            if issue.kind in ("PARTIAL_SHIP_TO", "UNRESOLVED_SHIP_TO"):
                ph = "Or type a different ship-to address (include ZIP)"
            elif issue.kind == "UNRESOLVED_BUYER":
                ph = "Or type a different buyer name or email"
            else:
                ph = "Or type a different SKU"
            typed = st.text_input(ph, key=_decision_key("radio_txt"),
                                  placeholder=ph, label_visibility="collapsed")
            if typed and issue.kind in ("UNRESOLVED_SKU", "MISSING_SKU"):
                entry_error = validate_manual_sku(
                    typed, orch["po"], issue.line_number, INTAKE_RESOLVER.products)
            if entry_error:
                st.error(f"❌ {entry_error}")

        cols = st.columns(4)
        i = 0
        if cols[i].button("✅ Approve selected", key=_decision_key("radio_ok"),
                          use_container_width=True):
            apply_issue_decision(orch, issue, "Picked", value=selected)
            orch["issue_ptr"] += 1
            st.rerun()
        i += 1
        if "enter" in issue.actions:
            if cols[i].button("✍️ Use my entry", key=_decision_key("radio_use"),
                              use_container_width=True,
                              disabled=not typed or bool(entry_error)):
                apply_issue_decision(orch, issue, "Entered", value=typed)
                orch["issue_ptr"] += 1
                st.rerun()
            i += 1
        if "reject" in issue.actions:
            if cols[i].button("⛔ Reject", key=_decision_key("radio_no"),
                              use_container_width=True):
                _intake_reject(orch, issue)
            i += 1
        if cols[i].button("⏫ Escalate", key=_decision_key("radio_esc"),
                          use_container_width=True):
            _intake_escalate(orch, issue)
        return

    # UOM_AMBIGUOUS has two explicit choice buttons instead of the generic
    # approve/pick flow (individual pieces vs full packs — AC-02 demo).
    if issue.kind == "UOM_AMBIGUOUS" and len(issue.suggestions) == 2:
        base, pack = issue.suggestions
        cols = st.columns(4)
        if cols[0].button(f"✅ Confirm: {int(base['qty'])} {base['uom']} (individual pieces)",
                          key=_decision_key("uom_base"), use_container_width=True):
            apply_issue_decision(orch, issue, "Approved", value=base)
            orch["issue_ptr"] += 1; st.rerun()
        if cols[1].button(
                f"📦 Confirm: {int(pack['qty'])} {pack['uom']} → {pack['qty_base']} {base['uom']}",
                key=_decision_key("uom_pack"), use_container_width=True):
            apply_issue_decision(orch, issue, "Picked", value=pack)
            orch["issue_ptr"] += 1; st.rerun()
        if cols[2].button("⛔ Reject", key=_decision_key("uom_no"), use_container_width=True):
            orch["decisions"].append({"what": issue.title, "decision": "Rejected",
                                      "detail": "CSR rejected — order stopped.",
                                      "reason": issue.rationale or issue.detail or "",
                                      "auto": [issue.detail] if issue.detail else []})
            orch["resolved_issues"].append({
                "title": issue.title, "kind": issue.kind, "detail": issue.detail,
                "rationale": issue.rationale, "decision": "Rejected",
                "outcome": "CSR rejected — order stopped.",
            })
            orch["terminal"] = ("rejected", f"Order rejected by CSR at intake: {issue.title}.")
            orch["phase"] = "terminal"; st.rerun()
        if cols[3].button("⏫ Escalate", key=_decision_key("uom_esc"), use_container_width=True):
            target = escalation_target(issue.kind)
            orch["decisions"].append({"what": issue.title, "decision": "Escalated",
                                      "detail": f"Escalated to {target}.",
                                      "reason": issue.rationale or issue.detail or "",
                                      "auto": [issue.detail] if issue.detail else []})
            orch["resolved_issues"].append({
                "title": issue.title, "kind": issue.kind, "detail": issue.detail,
                "rationale": issue.rationale, "decision": "Escalated",
                "outcome": f"Routed to {target}.",
            })
            orch["terminal"] = ("escalated", f"Escalated to {target}: {issue.title}.")
            orch["phase"] = "terminal"; st.rerun()
        return

    # Optional correction input (type a SKU / qty / buyer / address)
    typed = None
    entry_error = None
    if "enter" in issue.actions:
        if issue.kind in ("PARTIAL_SHIP_TO", "UNRESOLVED_SHIP_TO"):
            placeholder = "Type the correct ship-to address (include ZIP)"
        elif issue.kind == "UNRESOLVED_BUYER":
            placeholder = "Type the correct buyer name or email"
        elif issue.kind == "INVALID_QUANTITY":
            placeholder = "Type the correct quantity (positive number)"
        elif issue.kind == "SUBSTITUTE_SKU":
            placeholder = "Type a different SKU to use instead of the recommendation"
        else:
            placeholder = "Type the correct SKU"
        typed = st.text_input(placeholder, key=_decision_key("intake_txt"),
                              placeholder=placeholder, label_visibility="collapsed")

        # Inline validation — the "Use my entry" button stays disabled and the
        # process cannot move ahead until the CSR fixes the input. SKU-based
        # issues reject anything that is not in the product master OR that
        # duplicates a SKU already on another line of this PO. Quantity
        # entries reject anything that is not a positive number.
        if typed:
            if issue.kind in ("UNRESOLVED_SKU", "MISSING_SKU", "SUBSTITUTE_SKU"):
                entry_error = validate_manual_sku(
                    typed, orch["po"], issue.line_number,
                    INTAKE_RESOLVER.products)
            elif issue.kind == "INVALID_QUANTITY":
                entry_error = validate_manual_quantity(typed)
        if entry_error:
            st.error(f"❌ {entry_error}")

    cols = st.columns(4)
    idx = 0
    # Approve / Pick (accept the AI recommendation)
    if "approve" in issue.actions or "pick" in issue.actions:
        label = "✅ Approve" if "approve" in issue.actions else "✅ Use top match"
        if cols[idx].button(label, key=_decision_key("intake_ok"), use_container_width=True):
            apply_issue_decision(orch, issue, "Picked" if "pick" in issue.actions else "Approved")
            orch["issue_ptr"] += 1
            st.rerun()
        idx += 1
    # Use typed correction (disabled until validation passes)
    if "enter" in issue.actions:
        if cols[idx].button("✍️ Use my entry", key=_decision_key("intake_use"),
                            use_container_width=True,
                            disabled=not typed or bool(entry_error)):
            apply_issue_decision(orch, issue, "Entered", value=typed)
            orch["issue_ptr"] += 1
            st.rerun()
        idx += 1
    # Reject — only when the issue permits it. The obsolete-product
    # substitution (SUBSTITUTE_SKU) omits "reject": the decision layer is
    # Approve / Modify / Escalate only.
    if "reject" in issue.actions:
        if cols[idx].button("⛔ Reject", key=_decision_key("intake_no"), use_container_width=True):
            orch["decisions"].append({"what": issue.title, "decision": "Rejected",
                                      "detail": "CSR rejected — order stopped.",
                                      "reason": issue.rationale or issue.detail or "",
                                      "auto": [issue.detail] if issue.detail else []})
            orch["resolved_issues"].append({
                "title": issue.title, "kind": issue.kind, "detail": issue.detail,
                "rationale": issue.rationale, "decision": "Rejected",
                "outcome": "CSR rejected — order stopped.",
            })
            orch["terminal"] = ("rejected", f"Order rejected by CSR at intake: {issue.title}.")
            orch["phase"] = "terminal"
            st.rerun()
        idx += 1
    # Escalate
    if cols[idx].button("⏫ Escalate", key=_decision_key("intake_esc"), use_container_width=True):
        target = escalation_target(issue.kind)
        orch["decisions"].append({"what": issue.title, "decision": "Escalated",
                                  "detail": f"Routed to {target}.",
                                  "reason": issue.rationale or issue.detail or "",
                                  "auto": [issue.detail] if issue.detail else []})
        orch["resolved_issues"].append({
            "title": issue.title, "kind": issue.kind, "detail": issue.detail,
            "rationale": issue.rationale, "decision": "Escalated",
            "outcome": f"Routed to {target}.",
        })
        orch["terminal"] = ("escalated",
                            f"Escalated to **{target}**: {issue.title}. "
                            f"Automated processing is paused pending their review.")
        orch["phase"] = "terminal"
        st.rerun()


def _decision_buttons(orch, what, exc_type, kind, reason="", auto_findings=None):
    """Shared Approve(override) / Reject / Escalate controls for a paused
    exception. `kind` is 'stage' or 'account' and drives the resume transition.

    `reason` is the master-data-derived explanation of WHY the AI paused for
    CSR approval; `auto_findings` lists what the AI already decided
    automatically from master data. Both are recorded in the audit trail."""
    st.warning("🟡  CSR DECISION NEEDED — the agent paused on this exception.")
    st.caption("Approve to override and continue, Reject to stop the order, or "
               "Escalate to route it to the responsible team.")
    cols = st.columns(3)
    if cols[0].button("✅ Approve", key=_decision_key(kind + "_ok"),
                      use_container_width=True):
        st.session_state.reengage_scroll = True
        orch["decisions"].append({"what": what, "decision": "Approved",
                                  "detail": "CSR override — continue processing.",
                                  "reason": reason, "auto": auto_findings or []})
        if kind == "stage":
            # Flow the overridden stage's computed outputs (order total, pricing,
            # fulfillment plan, etc.) into the shared context so the remaining
            # stages and the final customer confirmation stay correct after a
            # CSR override.
            orch["ctx"].update(orch["pending"].data or {})
            orch["results"].append(orch["pending"])
            orch["pending"] = None
            orch["stage_index"] += 1
        elif kind == "account":
            orch["ctx"] = build_context(orch["po"], orch["av"])
            orch["phase"] = "pipeline"
        elif kind == "dup":
            orch["is_dup"] = False          # override — re-enter intake and resolve
            orch["phase"] = "intake_review"
        st.rerun()
    if cols[1].button("⛔ Reject", key=_decision_key(kind + "_no"), use_container_width=True):
        orch["decisions"].append({"what": what, "decision": "Rejected",
                                  "detail": "Order stopped.",
                                  "reason": reason, "auto": auto_findings or []})
        if kind == "stage":
            orch["results"].append(orch["pending"]); orch["pending"] = None
        orch["terminal"] = ("rejected", f"Order rejected by CSR: {exc_type}.")
        orch["phase"] = "terminal"
        st.rerun()
    if cols[2].button("⏫ Escalate", key=_decision_key(kind + "_esc"), use_container_width=True):
        target = escalation_target(exc_type)
        orch["decisions"].append({"what": what, "decision": "Escalated",
                                  "detail": f"Routed to {target}.",
                                  "reason": reason, "auto": auto_findings or []})
        if kind == "stage":
            orch["results"].append(orch["pending"]); orch["pending"] = None
        orch["terminal"] = ("escalated",
                            f"Escalated to **{target}**: {exc_type}. "
                            f"Automated processing is paused pending their review.")
        orch["phase"] = "terminal"
        st.rerun()


def render_pending_exception(orch, res):
    """Render a paused stage exception with Approve(override) / Reject / Escalate."""
    render_stage_result(res)
    _decision_buttons(orch, f"{res.title} — {res.exception_type}", res.exception_type,
                      "stage", reason=res.headline, auto_findings=list(res.audit_trail))


def _narrate_intake_review(orch, po):
    """Resolve intake issues and animate the intake-review narration.

    IMPORTANT: this is called in the SAME script run as the extraction
    animation so its status panel is appended *below* the extraction panel and
    the messages read in sequence. Previously the narration ran after a
    st.rerun(), so Streamlit reconciled the shorter narration panel onto the
    longer extraction panel at the same position and left stale extraction
    lines behind — which looked like later messages overriding earlier ones."""
    orch["issues"] = INTAKE_RESOLVER.resolve(po)
    n = len(orch["issues"])
    if n > 0:
        think("Intake review — action required", [
            (THINK_PACE, "🔎 Ran product catalog / lifecycle / UOM / "
                         "ship-to / buyer resolution against master data."),
            (THINK_PACE, f"⚠️ Found **{n} item(s)** that need CSR "
                         "confirmation before I continue."),
            (THINK_PACE, "🛑 **Downstream checks (pricing, inventory, "
                         "credit, compliance, logistics, order creation) "
                         "are paused** until each item is resolved."),
        ], icon="⚠️")
    else:
        think("Reviewing order against master data", [
            (THINK_PACE, "🔎 **Product catalog check** — matching each line "
                         "against Product Master by code AND description "
                         "(the AI is label-independent)…"),
            (THINK_PACE, "♻️ **Lifecycle check** — is each SKU ACTIVE, "
                         "OBSOLETE, or INACTIVE?"),
            (THINK_PACE, "📏 **UOM check** — does each line's UOM match the "
                         "product's base UOM? If missing, defaulting to base "
                         "UOM from Product Master."),
            (THINK_PACE, "📍 **Ship-to resolution** — matching the ship-to "
                         "against registered locations for this customer…"),
            (THINK_PACE, "👤 **Buyer resolution** — mapping buyer email → "
                         "internal buyer ID + cost center from Buyer Profiles."),
            (THINK_PACE, "📄 **Optional-field backfill** — looking up contact "
                         "person and contract reference in master data when "
                         "the PO omitted them (delivery instructions come "
                         "only from the PO — never from master)."),
        ])


def _route_after_intake(orch, po):
    """Pick the next phase once extraction + intake narration have completed."""
    if orch["is_dup"] or po.missing_fields:
        orch["phase"] = "intake_review"   # show the escalation card
    elif orch["issues"]:
        orch["phase"] = "intake_issues"   # resolve flagged items one by one
    else:
        orch["phase"] = "account"         # clean → straight to customer validation


def _run_account_layer(orch):
    """Animate the Customer Validation layer (account + ship-to hierarchy).

    Returns "pause" if it hit an exception that needs CSR input (phase is set
    to account_pending); otherwise builds the shared context and returns None.
    Rendered inside the caller's chat_message so it streams in the same run as
    the layers before and after it."""
    po = orch["po"]
    _render_resolved_intake_cards(orch)
    if orch.get("resolved_issues"):
        think("Resuming automated processing", [
            (THINK_PACE, "✅ **All CSR decisions captured** and applied to the PO."),
            (THINK_PACE, "▶️ **Resuming the automated pipeline** — "
                         "account & ship-to hierarchy validation next, "
                         "then every remaining decision layer will animate below."),
        ], icon="▶️")
    av = run_account_validation(po.customer_account, po.ship_to_zip, po.company_name)
    orch["av"] = av
    if av.is_exception:
        orch["phase"] = "account_pending"
        return "pause"
    orch["ctx"] = build_context(po, av)
    return None


def _run_pipeline_layers(orch):
    """Animate the downstream decision layers (US-03 … US-12), then governance
    and order execution — every layer running to completion, one after another,
    in the current continuous run.

    Returns "pause" if a stage raised an exception that needs CSR input
    (orch['pending'] is set); otherwise sets phase to 'done' and returns None."""
    # 1) Sequential stages — each finishes before the next begins.
    while orch["stage_index"] < len(SEQUENTIAL_STAGES):
        stage = SEQUENTIAL_STAGES[orch["stage_index"]]
        res = _run_stage_animation(stage, orch["ctx"])
        if res.is_exception:
            orch["pending"] = res
            return "pause"
        orch["ctx"].update(res.data or {})
        orch["results"].append(res)
        orch["stage_index"] += 1
        nap(paced_delay(0.35))

    # 2) Governance (always runs).
    if not orch.get("governance_done"):
        with st.status(f"{GOVERNANCE.icon} {GOVERNANCE.title}...",
                       expanded=True) as status:
            for delay, emoji, text in GOVERNANCE.steps:
                st.write(f"{emoji} {text}")
                nap(paced_delay(delay))
            gov = GOVERNANCE.route(orch["results"], orch["ctx"])
            status.update(label=f"{GOVERNANCE.icon} {GOVERNANCE.title} — complete",
                          state="complete", expanded=True)
        orch["results"].append(gov)
        orch["governance_done"] = True
        nap(paced_delay(0.35))

    # 3) Order execution.
    ex = _run_stage_animation(EXECUTION, orch["ctx"])
    orch["ctx"].update(ex.data or {})
    orch["results"].append(ex)
    orch["phase"] = "done"
    return None


# ── The driver: performs ONE unit of work per rerun ───────────────────────────
def drive_orchestration():
    orch = st.session_state.orch
    phase = orch["phase"]

    # NOTE: the auto-scroll observer is mounted at a stable top position in the
    # main render flow (before render_orch_static), not here — see that call.
    # Mounting it before the naps keeps it live during the animation while
    # avoiding a mid-tree component whose shifting position broke DOM
    # reconciliation of the active decision card.

    # ---- start: read + extract ----
    if phase == "start":
        with st.chat_message("assistant"):
            if orch["kind"] == "excel":
                file_bytes, fname = orch["payload"]
                orch["source_label"] = f"Excel file `{fname}`"
                with st.spinner("📊 Reading Excel workbook structure..."):
                    try:
                        raw_text = parse_excel(file_bytes)
                    except Exception as exc:
                        st.error(f"❌ Could not read Excel file: {exc}")
                        orch["phase"] = "terminal"
                        orch["terminal"] = ("rejected", f"Unreadable Excel file: {exc}")
                        return
                po = run_ai_processing(raw_text, f"Excel: {fname}")
                po.source_type = "EXCEL"
            else:
                orch["source_label"] = "PO text"
                po = run_ai_processing(orch["payload"], "PO Text")

            is_dup, dup_rec = dup.check(po.po_number, po.customer_account)
            if not is_dup and po.po_number:
                dup.register(po.po_number, po.customer_account, st.session_state.session_id)
            orch.update(po=po, is_dup=is_dup, dup_rec=dup_rec)

            # Dup / missing-field POs need an escalation card → hand off with a
            # rerun (no narration, no downstream processing).
            if is_dup or po.missing_fields:
                orch["phase"] = "intake_review"
                st.rerun()

            # Narrate the intake review in THIS SAME run — directly below the
            # extraction steps — so every message appends in sequence.
            _narrate_intake_review(orch, po)

            # Flagged items need CSR confirmation → resolve them one-by-one.
            if orch["issues"]:
                orch["phase"] = "intake_issues"
                st.rerun()

            # Clean PO → keep streaming Customer Validation and every downstream
            # decision layer in THIS SAME run. Each layer runs all of its
            # processes to completion before the next layer starts, and because
            # there is no rerun between them no panel is ever replaced/overridden.
            if _run_account_layer(orch) == "pause":
                st.rerun()                       # account exception → CSR
            orch["phase"] = "pipeline"           # so a stage pause resumes here
            if _run_pipeline_layers(orch) == "pause":
                st.rerun()                       # stage exception → CSR
        st.rerun()                               # phase == 'done'

    # ---- intake_review: duplicate / missing fields / resolver issues ----
    elif phase == "intake_review":
        po = orch["po"]
        with st.chat_message("assistant"):
            if orch["is_dup"]:
                st.markdown("---")
                st.error("🔴  DUPLICATE PO DETECTED — order auto-rejected")
                st.markdown(
                    f"PO **{po.po_number or 'N/A'}** for customer "
                    f"**{po.customer_account or 'N/A'}** was already submitted"
                    + (f" on {orch['dup_rec'].get('submitted_at','—')} "
                       f"(status: {orch['dup_rec'].get('status','—')})."
                       if orch['dup_rec'] else ".")
                )
                st.warning("⛔  This order will not be processed.")
                # Record the auto-rejection once so the decision log has a
                # single, unambiguous entry (even if the CSR re-runs the page).
                if not any(d.get("what", "").startswith("Duplicate PO ")
                           and d.get("decision") == "Auto-rejected"
                           for d in orch["decisions"]):
                    orch["decisions"].append({
                        "what": f"Duplicate PO {po.po_number}",
                        "decision": "Auto-rejected",
                        "detail": ("Policy: duplicate POs are never approved "
                                   "or re-orchestrated. No override is available."),
                        "reason": ("Duplicate-submission check matched this PO number "
                                   "and customer against an already-registered order "
                                   "in the submission ledger."),
                        "auto": ["Matched an existing submission — flagged as duplicate."],
                    })
                if st.button("⏫ Escalate to Duplicate PO Team",
                             key="dup_esc", use_container_width=True):
                    orch["decisions"].append({
                        "what": f"Duplicate PO {po.po_number}",
                        "decision": "Escalated",
                        "detail": "Routed to Duplicate PO Team for reconciliation.",
                        "reason": ("Duplicate-submission check matched this PO number "
                                   "and customer against an already-registered order."),
                        "auto": ["Matched an existing submission — flagged as duplicate."],
                    })
                    orch["terminal"] = ("escalated",
                                        f"Duplicate PO **{po.po_number}** escalated to "
                                        f"**Duplicate PO Team** for reconciliation with "
                                        f"the original submission.")
                    orch["phase"] = "terminal"
                    st.rerun()
                return
            if po.missing_fields:
                st.markdown("---")
                st.error("🔴  INTAKE EXCEPTION — Missing mandatory fields")
                for mf in po.missing_fields:
                    st.markdown(f"- ❌ **{mf}**")
                st.caption("Only PO Number, PO Date, Buyer Company, Buyer Email, Ship-To, "
                           "Requested Delivery Date, and line SKU/Description/Qty are mandatory.")
                if st.button("⏫ Escalate to Order Operations", key="intake_missing_esc"):
                    orch["terminal"] = ("escalated",
                                        "Missing mandatory fields escalated to Order Operations.")
                    orch["phase"] = "terminal"
                    st.rerun()
                return
            # Re-entry fallback (e.g. a CSR override of a duplicate re-enters
            # intake with is_dup cleared). Narrate + resolve in this same run,
            # then route onward — the happy path already narrated in `start`.
            _narrate_intake_review(orch, po)
        _route_after_intake(orch, po)
        st.rerun()

    # ---- intake_issues: resolve one issue at a time ----
    elif phase == "intake_issues":
        with st.chat_message("assistant"):
            # Re-render every already-resolved intake decision card FIRST
            # so the current decision card / next stage always appears
            # BELOW the button the CSR just clicked (chronological order).
            _render_resolved_intake_cards(orch)
            if orch["issue_ptr"] < len(orch["issues"]):
                # Wrap the ACTIVE decision card in a keyed container. The key
                # changes with issue_ptr, so when the CSR resolves this card
                # Streamlit removes the entire container (impact table +
                # button row) instead of trying to diff a container whose
                # element count changed — which could leave the old table /
                # buttons lingering in the browser.
                with st.container(key=f"active_issue_{orch['issue_ptr']}"):
                    render_intake_issue(orch, orch["issues"][orch["issue_ptr"]])
                return   # wait for CSR
        orch["phase"] = "account"
        st.rerun()

    # ---- account: customer validation → straight into the pipeline ----
    elif phase == "account":
        with st.chat_message("assistant"):
            # Stream Customer Validation and then every downstream layer in this
            # one continuous run so the layers appear one after another with no
            # rerun replacing a panel in between.
            if _run_account_layer(orch) == "pause":
                st.rerun()                       # account exception → CSR
            orch["phase"] = "pipeline"           # so a stage pause resumes here
            if _run_pipeline_layers(orch) == "pause":
                st.rerun()                       # stage exception → CSR
        st.rerun()                               # phase == 'done'

    elif phase == "account_pending":
        with st.chat_message("assistant"):
            with st.container(key="active_account_pending"):
                render_account_result(orch["av"])
                _decision_buttons(orch, f"Account validation — {orch['av'].exception_type}",
                                  f"ACCOUNT_{orch['av'].exception_type}", "account",
                                  reason=orch["av"].headline,
                                  auto_findings=list(orch["av"].audit_trail))
        return

    # ---- pipeline: US-03 … US-12  +  governance  +  execution ----
    # IMPORTANT: these three logical phases run in ONE continuous script run.
    # Previously each stage ended in st.rerun(), which forced
    # render_orch_static() to replay an ever-growing history and made
    # Streamlit fade the whole app on every rerun. Past the intake step the
    # replay+fade window grew large enough that the browser appeared to
    # "freeze after Intake decision, then jump straight to Order Created".
    # Streaming every stage in a single run (exactly like the intake think
    # panels) keeps the animation smooth top-to-bottom and lets the scroll
    # observer follow it. We only break out to a rerun when a stage raises an
    # exception that needs CSR input.
    elif phase == "pipeline":
        with st.chat_message("assistant"):
            if orch["pending"] is not None:
                with st.container(key=f"active_stage_pending_{orch['stage_index']}"):
                    render_pending_exception(orch, orch["pending"])
                return
            # Resume the downstream layers (after a CSR override or an account
            # exception was cleared). Runs to completion in this continuous run.
            if _run_pipeline_layers(orch) == "pause":
                st.rerun()                       # next stage exception → CSR
        st.rerun()                               # phase == 'done'

    # ---- terminal states ----
    elif phase == "done":
        with st.chat_message("assistant"):
            st.success("🎉 Order fully processed — customer confirmation sent with price, "
                       "ETA, fulfillment source and tracking details.")
    elif phase == "terminal":
        with st.chat_message("assistant"):
            kind, msg = orch["terminal"]
            if kind == "rejected":
                st.error("⛔ **Order stopped.** " + md_safe(msg))
            else:
                st.info("⏫ **Escalated.** " + msg)


def _fake_result(title, icon, exc_type, message):
    """Wrap a non-StageResult exception (duplicate/account) so it can be rendered
    and governed like a pipeline stage exception."""
    from modules.stage_result import StageResult
    r = StageResult("intake", title, icon)
    r.fail(exc_type, message)
    return r


# ─── Session state init ────────────────────────────────────────────────────────
# Bump PO_SCHEMA_VERSION whenever ExtractedPO / the orchestrator state shape
# changes so any existing browser session with stale objects is reset
# automatically instead of throwing AttributeError.
PO_SCHEMA_VERSION = "2026-07-04-buying-history-transactions"
if st.session_state.get("po_schema_version") != PO_SCHEMA_VERSION:
    st.session_state.orch = None
    st.session_state.welcomed = False
    st.session_state.po_schema_version = PO_SCHEMA_VERSION

if "orch"           not in st.session_state: st.session_state.orch           = None
if "show_upload"    not in st.session_state: st.session_state.show_upload    = False
if "session_id"     not in st.session_state: st.session_state.session_id     = str(uuid.uuid4())[:8]
if "upload_key"     not in st.session_state: st.session_state.upload_key     = 0
if "welcomed"       not in st.session_state: st.session_state.welcomed       = False

WELCOME_TEXT = (
    "👋 **Hello! I am your order assistant.**\n\n"
    "Paste a Purchase Order below, or click **➕** to upload an Excel PO "
    "(`.xlsx` / `.xls`). I will read it, resolve it against master data, and "
    "work through customer, product, pricing, credit, inventory and logistics "
    "checks step by step.\n\n"
    "Whenever something is missing, ambiguous, obsolete, or breaks a business "
    "rule, I will pause and ask you to **Approve**, **Reject**, or **Escalate** "
    "— or type a correction — before I continue."
)

# ─── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Settings")
    st.markdown("---")
    if st.button("🗑️ New / clear conversation", use_container_width=True):
        st.session_state.orch        = None
        st.session_state.welcomed    = False
        st.session_state.show_upload = False
        st.rerun()
    if st.button("🔄 Clear created orders log", use_container_width=True):
        dup.reset_store()
        st.success("Created orders log cleared.")
    st.markdown("---")
    st.caption("Version 2.0 — interactive human-in-the-loop")

# ─── Page header ───────────────────────────────────────────────────────────────
st.markdown("## Order Assistant")
st.markdown("---")

# ─── Main area: welcome OR the active interactive run ─────────────────────────
if st.session_state.orch is None:
    with st.chat_message("assistant"):
        st.markdown(WELCOME_TEXT)
else:
    _orch = st.session_state.orch
    if not _orch.get("cleared"):
        # ── Clearing frame ──────────────────────────────────────────────────
        # A freshly-submitted PO must wipe the previous PO off the screen BEFORE
        # its (long, continuous) animation starts. Streamlit's frontend only
        # prunes elements left over from a prior run when a run FINISHES
        # SUCCESSFULLY — a run that ends in st.rerun() is flagged "finished early"
        # and its stale elements are kept. Since the animation streams for many
        # seconds inside one run, the old PO would stay visible that whole time.
        #
        # So we render one tiny frame here and let the script finish NORMALLY
        # (no st.rerun) — that success prunes the previous PO's DOM. We then
        # kick off the animation run with a hidden-button click driven from JS
        # (a real widget interaction triggers a fresh rerun without losing
        # session state, which st.rerun cannot do here without skipping prune).
        _orch["cleared"] = True
        with st.chat_message("assistant"):
            st.markdown("### 📥 Intake")
            st.caption("Reading new PO…")
        with st.container(key="kickoff_wrap"):
            st.button("kickoff", key="kickoff_btn")
        _components.html(
            """
            <script>
              const doc = window.parent.document;
              let tries = 0;
              const t = setInterval(() => {
                tries += 1;
                const btn = doc.querySelector('.st-key-kickoff_wrap button');
                if (btn) { btn.click(); clearInterval(t); }
                if (tries > 60) clearInterval(t);
              }, 25);
            </script>
            """,
            height=0,
        )
        # NOTE: intentionally NO st.rerun() and NO further main-area rendering —
        # the run finishes successfully so the previous PO's DOM is pruned.
    else:
        # Mount the auto-scroll observer at a STABLE top position (before any
        # history/active-card content) so the iframe keeps a fixed element path
        # across reruns. A mid-tree component whose position shifts every run can
        # disrupt Streamlit's DOM reconciliation and leave a just-resolved
        # decision card (its impact table + buttons) lingering on screen instead
        # of being cleanly replaced by the resolved banner + next step.
        _ph = _orch.get("phase")
        _reengage = st.session_state.pop("reengage_scroll", False)
        # Auto-follow should track the pipeline ONLY while a run is actively
        # animating (streaming stage panels). The moment a run is parked on a
        # CSR decision card or a dead-end, follow must RELEASE — otherwise the
        # observer's snap-to-bottom loop traps the user on the card and they
        # cannot scroll up to read the intake / earlier-stage details.
        #
        # Runs that WAIT for input (drive renders a card / banner then returns,
        # with no naps): a pending intake issue, an account exception, a stage
        # exception, a duplicate/missing-fields dead-end, or a finished run.
        # Every other phase (start / account / resuming pipeline / intake
        # re-entry) streams content and should follow.
        _po = _orch.get("po")
        _issue_waiting = (
            _ph == "intake_issues"
            and _orch.get("issue_ptr", 0) < len(_orch.get("issues", []))
        )
        _intake_deadend = _ph == "intake_review" and (
            _orch.get("is_dup")
            or (_po is not None and getattr(_po, "missing_fields", None))
        )
        _pipeline_waiting = _ph == "pipeline" and _orch.get("pending") is not None
        _waiting = (
            _ph in ("done", "terminal", "account_pending")
            or _issue_waiting or _intake_deadend or _pipeline_waiting
        )
        inject_autoscroll(active=not _waiting, force_follow=_reengage)
        # Render the whole run inside a container keyed by this PO's run_id so
        # the subtree has a stable identity across the reruns of ONE PO.
        with st.container(key=f"po_run_{_orch.get('run_id', 'active')}"):
            render_orch_static(_orch)
            drive_orchestration()

# ─── Upload panel (shown when ➕ clicked) ─────────────────────────────────────
if st.session_state.show_upload:
    with st.container(border=True):
        st.markdown("#### 📁 Upload Purchase Order — Excel Only")
        st.caption(
            "Accepted: **.xlsx** and **.xls** files only.  "
            "PDF, Word, CSV, and other formats are **not accepted**."
        )
        uploaded = st.file_uploader(
            "Drop your Excel PO file here or click Browse",
            type=["xlsx", "xls"],
            key=f"uploader_{st.session_state.upload_key}",
            label_visibility="collapsed",
        )
        if uploaded is not None:
            ext = uploaded.name.rsplit(".", 1)[-1].lower()
            if ext not in ("xlsx", "xls"):
                st.error(
                    f"⛔ **File type '.{ext}' is not supported.**\n\n"
                    "Please upload an Excel file in **.xlsx** or **.xls** format.\n"
                    "PDF, Word (.docx), CSV, and other formats cannot be processed here."
                )
            else:
                # Capture bytes now so the payload survives the upcoming rerun
                new_orchestration("excel", (uploaded.read(), uploaded.name))
                st.session_state.welcomed = True
                st.session_state.show_upload = False
                st.session_state.upload_key += 1
                st.rerun()
        col_close, _ = st.columns([1, 5])
        with col_close:
            if st.button("✖ Close", key="close_upload"):
                st.session_state.show_upload = False
                st.rerun()

# ─── Bottom input row ─────────────────────────────────────────────────────────
col_plus, col_hint = st.columns([1, 10])
with col_plus:
    if st.button("➕", help="Upload an Excel PO file (.xlsx / .xls only)",
                 use_container_width=True):
        st.session_state.show_upload = not st.session_state.show_upload
        st.rerun()
with col_hint:
    st.caption("Click **➕** to upload Excel PO  |  or paste text directly below")

# Text input — stays pinned at bottom of chat
if prompt := st.chat_input("Paste your PO text here, or click ➕ above to upload an Excel file..."):
    if prompt.strip():
        new_orchestration("text", prompt)
        st.session_state.welcomed = True
        st.rerun()


# ─── Auto-scroll for the welcome screen only ─────────────────────────────────
# Active runs mount the observer at a stable top position in the main render
# flow (before render_orch_static); we do NOT re-inject here for them to avoid
# a second, position-shifting component that could disrupt reconciliation.
if st.session_state.orch is None:
    inject_autoscroll(active=False)

