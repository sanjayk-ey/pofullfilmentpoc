"""
app.py  —  PO Fulfillment AI Agent
Streamlit frontend with chat-like interface.
Run with: python -m streamlit run app.py
"""
import streamlit as st
import time
import uuid  # still used for session_id passed to duplicate_checker
from modules.extractor        import POExtractor, ExtractedPO
from modules.excel_parser     import parse_excel
from modules                  import duplicate_checker as dup
from modules.account_validator import AccountValidator, AccountValidationResult
from modules.pipeline         import build_context, SEQUENTIAL_STAGES, GOVERNANCE, EXECUTION

# ─── Page setup ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PO Fulfillment AI",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
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

/* Push content below the fixed app bar */
.block-container   { padding-top: 3.5rem; }

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
</style>
""", unsafe_allow_html=True)

EXTRACTOR = POExtractor()
ACCOUNT_VALIDATOR = AccountValidator()

# Friendly labels for hierarchy rule sources
LEVEL_LABEL = {
    "ship_to":           "Ship-To level",
    "branch":            "Branch level",
    "regional_division": "Regional Division level",
    "global_parent":     "Global Parent level",
}

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

    def val_cell(v):
        return v if v else '<span style="color:#F87171;">— not found —</span>'

    fields = [
        ("po_number",               "PO Number *",               po.po_number),
        ("customer_account",        "Customer Account *",         po.customer_account),
        ("contract_reference",      "Contract Reference",         po.contract_reference),
        ("ship_to_zip",             "Ship-To ZIP Code *",         po.ship_to_zip),
        ("requested_delivery_date", "Requested Delivery Date *",  po.requested_delivery_date),
        ("delivery_instructions",   "Delivery Instructions",      po.delivery_instructions),
    ]
    rows_html = "".join(
        f"<tr><td><b>{lbl}</b></td><td>{val_cell(v)}</td><td>{conf_span(k)}</td></tr>"
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
        line_rows = ""
        for ln in po.order_lines:
            sku_v  = ln.sku  or '<span style="color:#F87171;">missing</span>'
            qty_v  = str(ln.quantity) if ln.quantity is not None else '<span style="color:#F87171;">missing</span>'
            uom_v  = ln.uom  or '<span style="color:#F87171;">missing</span>'
            desc_v = ln.description or "—"
            price_v = f"${ln.unit_price:,.2f}" if ln.unit_price else "—"
            c = round(ln.confidence * 100)
            col = "#4ADE80" if c >= 80 else "#FCD34D" if c >= 60 else "#F87171"
            line_rows += (
                f"<tr><td>{ln.line_number}</td><td><b>{sku_v}</b></td>"
                f"<td>{desc_v}</td><td>{qty_v}</td><td>{uom_v}</td>"
                f"<td>{price_v}</td>"
                f"<td><span style='color:{col};'>{c}%</span></td></tr>"
            )
        st.markdown(
            '<table class="field-table"><thead><tr>'
            '<th>#</th><th>SKU</th><th>Description</th>'
            '<th>Qty</th><th>UOM</th><th>Unit Price</th><th>Confidence</th>'
            '</tr></thead><tbody>' + line_rows + '</tbody></table>',
            unsafe_allow_html=True,
        )
    else:
        st.error("❌ No order line items found. SKU, Quantity, and UOM are mandatory.")

    st.write("")
    st.caption(f"Source: {po.source_type}  |  Extraction method: AI rule-based pattern engine")


# ─── Helper: render account hierarchy validation result ───────────────────────
def render_account_result(av: AccountValidationResult):
    st.markdown("---")
    st.markdown("### 🏢 Corporate Account Hierarchy & Ship-To Validation")

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
        st.markdown(av.message)

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
                st.markdown(f"- {line}")
        return

    # ── PASS — hierarchy identified ─────────────────────────────────────────────
    st.success("✅  Account hierarchy identified & ship-to validated. "
               "Ready to proceed to buyer authorization.")

    # Hierarchy breadcrumb
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
        f"</tbody></table>",
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
                 f"<td>{display_val}</td>"
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
            st.markdown(f"- {line}")


# ─── Helper: generic stage-result renderer (US-03 … US-12) ────────────────────
def render_stage_result(res):
    st.markdown("---")
    st.markdown(f"### {res.icon} {res.title}")
    if res.is_exception:
        st.error(f"🔴  EXCEPTION — {res.exception_type}")
        st.markdown(res.headline)
    else:
        st.success(f"✅  {res.headline}")

    for sec in res.sections:
        if sec["type"] == "kv":
            if sec.get("title"):
                st.markdown(f"**{sec['title']}**")
            rows = "".join(f"<tr><td><b>{l}</b></td><td>{v}</td></tr>" for l, v in sec["rows"])
            st.markdown(f"<table class='field-table'><tbody>{rows}</tbody></table>",
                        unsafe_allow_html=True)
            st.write("")
        elif sec["type"] == "table":
            if sec.get("title"):
                st.markdown(f"**{sec['title']}**")
            head = "".join(f"<th>{h}</th>" for h in sec["headers"])
            body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
                           for r in sec["rows"])
            st.markdown(f"<table class='field-table'><thead><tr>{head}</tr></thead>"
                        f"<tbody>{body}</tbody></table>", unsafe_allow_html=True)
            st.write("")
        elif sec["type"] == "note":
            st.markdown(f"_{sec['text']}_")

    if res.audit_trail:
        with st.expander("🧾 View audit trail"):
            for line in res.audit_trail:
                st.markdown(f"- {line}")


def _run_stage_animation(stage, ctx):
    result = [None]
    with st.status(f"{stage.icon} {stage.title}...", expanded=True) as status:
        for delay, emoji, text in stage.steps:
            st.write(f"{emoji} {text}")
            time.sleep(delay)
        result[0] = stage.validate(ctx)
        status.update(label=f"{stage.icon} {stage.title} — complete",
                      state="complete", expanded=False)
    return result[0]


def run_full_pipeline(po: ExtractedPO, av: AccountValidationResult):
    """Run US-03 … US-12 with per-stage animation and rendering. Returns results list."""
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
            time.sleep(delay)
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
def run_account_validation(customer_account, ship_to_zip) -> AccountValidationResult:
    steps = [
        (0.35, "🏢", "Resolving customer identity against customer master..."),
        (0.30, "🔗", "Checking ERP and CRM customer records..."),
        (0.35, "🧭", "Mapping corporate account hierarchy (parent › division › branch)..."),
        (0.30, "📍", "Validating ship-to location against ship-to master..."),
        (0.30, "🔍", "Confirming ship-to belongs to customer hierarchy..."),
        (0.30, "⚙️", "Determining applicable hierarchy-level rules..."),
        (0.25, "🧾", "Recording applied hierarchy level in audit trail..."),
    ]
    result = [None]
    with st.status("🤖 AI Agent Validating Account Hierarchy...", expanded=True) as status:
        for i, (delay, emoji, text) in enumerate(steps):
            st.write(f"{emoji} {text}")
            time.sleep(delay)
            if i == 4 and result[0] is None:
                result[0] = ACCOUNT_VALIDATOR.validate(customer_account, ship_to_zip)
        status.update(label="✅ Account validation complete — results below",
                      state="complete", expanded=False)
    if result[0] is None:
        result[0] = ACCOUNT_VALIDATOR.validate(customer_account, ship_to_zip)
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

    with st.status(f"🤖 AI Agent Processing — {source_label}", expanded=True) as status:
        for i, (delay, emoji, text) in enumerate(steps):
            st.write(f"{emoji} {text}")
            time.sleep(delay)
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


# ─── Helper: process text input ───────────────────────────────────────────────
def process_text_input(text: str):
    if not text.strip():
        return
    # User bubble
    st.session_state.messages.append(
        {"role": "user", "type": "user_input",
         "text": f"📋 **PO text submitted** — {len(text)} characters"}
    )
    with st.chat_message("user", avatar="👤"):
        st.markdown(f"📋 **PO text submitted** — {len(text)} characters")

    # AI processing
    with st.chat_message("assistant", avatar="🤖"):
        po = run_ai_processing(text, "PO Text")
        is_dup, dup_rec = dup.check(po.po_number, po.customer_account)
        if not is_dup and po.po_number:
            dup.register(po.po_number, po.customer_account, st.session_state.session_id)
        render_po_result(po, is_dup, dup_rec)

        # Account validation runs only when extraction is clean (no duplicate, no missing fields)
        av = None
        stage_results = None
        if not is_dup and not po.missing_fields:
            av = run_account_validation(po.customer_account, po.ship_to_zip)
            render_account_result(av)
            if not av.is_exception:
                stage_results = run_full_pipeline(po, av)

    st.session_state.messages.append(
        {"role": "assistant", "type": "po_result",
         "po": po, "is_dup": is_dup, "dup_rec": dup_rec, "av": av,
         "stage_results": stage_results}
    )


# ─── Helper: process Excel upload ─────────────────────────────────────────────
def process_excel_input(uploaded_file):
    fname = uploaded_file.name
    st.session_state.messages.append(
        {"role": "user", "type": "user_input",
         "text": f"📁 **Excel file uploaded:** `{fname}`"}
    )
    with st.chat_message("user", avatar="👤"):
        st.markdown(f"📁 **Excel file uploaded:** `{fname}`")

    with st.chat_message("assistant", avatar="🤖"):
        file_bytes = uploaded_file.read()
        with st.spinner("📊 Reading Excel file structure..."):
            try:
                raw_text = parse_excel(file_bytes)
            except Exception as exc:
                st.error(f"❌ Could not read Excel file: {exc}")
                return
        po = run_ai_processing(raw_text, f"Excel: {fname}")
        po.source_type = "EXCEL"
        is_dup, dup_rec = dup.check(po.po_number, po.customer_account)
        if not is_dup and po.po_number:
            dup.register(po.po_number, po.customer_account, st.session_state.session_id)
        render_po_result(po, is_dup, dup_rec)

        # Account validation runs only when extraction is clean (no duplicate, no missing fields)
        av = None
        stage_results = None
        if not is_dup and not po.missing_fields:
            av = run_account_validation(po.customer_account, po.ship_to_zip)
            render_account_result(av)
            if not av.is_exception:
                stage_results = run_full_pipeline(po, av)

    st.session_state.messages.append(
        {"role": "assistant", "type": "po_result",
         "po": po, "is_dup": is_dup, "dup_rec": dup_rec, "av": av,
         "stage_results": stage_results}
    )
    st.session_state.show_upload = False
    st.session_state.upload_key += 1


# ─── Session state init ────────────────────────────────────────────────────────
if "messages"    not in st.session_state: st.session_state.messages    = []
if "show_upload" not in st.session_state: st.session_state.show_upload = False
if "session_id"  not in st.session_state: st.session_state.session_id  = str(uuid.uuid4())[:8]
if "upload_key"  not in st.session_state: st.session_state.upload_key  = 0
if "welcomed"    not in st.session_state: st.session_state.welcomed     = False

# ─── Welcome message (first run only) ─────────────────────────────────────────
if not st.session_state.welcomed:
    st.session_state.messages.append({
        "role": "assistant",
        "type": "welcome",
        "text": (
            "👋 **Hello! I am your PO Fulfillment AI Agent.**\n\n"
            "I can automatically read and extract all key information from a "
            "Purchase Order — customer account, SKUs, quantities, delivery date, "
            "ship-to location, contract reference, and more.\n\n"
            "**How to submit a PO:**\n"
            "- Click **➕** below to upload an **Excel file** (`.xlsx` or `.xls` only)\n"
            "- Or **paste your PO text** directly into the input box below\n\n"
            "Once I receive the PO, I will process it step by step and show you exactly what was extracted."
        ),
    })
    st.session_state.welcomed = True

# ─── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Settings")
    st.markdown("---")
    if st.button("🗑️ Clear conversation", use_container_width=True):
        st.session_state.messages    = []
        st.session_state.welcomed    = False
        st.session_state.show_upload = False
        st.rerun()
    if st.button("🔄 Clear submitted PO logs", use_container_width=True):
        dup.reset_store()
        st.success("Submitted PO logs cleared.")
    st.markdown("---")
    st.caption("Version 1.0")

# ─── Page header ───────────────────────────────────────────────────────────────
st.markdown("## 🤖 PO Fulfillment AI Agent")
st.markdown("---")

# ─── Chat message history ─────────────────────────────────────────────────────
for msg in st.session_state.messages:
    avatar = "🤖" if msg["role"] == "assistant" else "👤"
    with st.chat_message(msg["role"], avatar=avatar):
        if msg["type"] in ("welcome", "text", "user_input"):
            st.markdown(msg["text"])
        elif msg["type"] == "po_result":
            render_po_result(msg["po"], msg.get("is_dup", False), msg.get("dup_rec"))
            if msg.get("av") is not None:
                render_account_result(msg["av"])
            if msg.get("stage_results"):
                for res in msg["stage_results"]:
                    render_stage_result(res)

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
                process_excel_input(uploaded)
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
    process_text_input(prompt)
    st.rerun()
