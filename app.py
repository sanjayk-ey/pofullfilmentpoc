"""
app.py  —  PO Fulfillment Order Assistant
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


def inject_autoscroll(active: bool = True, force_follow: bool = False,
                      suppress_idle_scroll: bool = False):
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
    suppress = "true" if suppress_idle_scroll else "false"
    _components.html(
        """
        <script>
          (function () {
            try {
              const w = window.parent || window;
              const doc = w.document;
              const ACTIVE = %s;
              const FORCE_FOLLOW = %s;
              const SUPPRESS_IDLE = %s;
              // A CSR decision card is on screen and scroll_to_csr_top() will
              // position the viewport on the banner — so release follow and do
              // NOT perform the idle scroll-to-bottom (it would fight the pin
              // and cause 2–3 competing scrolls).
              if (SUPPRESS_IDLE) w.__poFollow = false;
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
              if (w.__poBurst) { try { clearInterval(w.__poBurst); } catch (_) {} w.__poBurst = null; }

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

                // A resume just started (FORCE_FOLLOW). After a decision is
                // approved the page has scrolled UP to the card and the history
                // replay is large, so the MutationObserver can miss the first
                // streamed deltas — leaving the resuming pipeline BELOW the fold
                // (the user sees the card get replaced but "no process appears
                // next to the button"). Pin follow ON and hard-scroll to the
                // bottom on a fast cadence for a sustained window so the resuming
                // agents are guaranteed to stream into view right where the CSR
                // just clicked. The user can break out any time by scrolling up.
                if (FORCE_FOLLOW) {
                  w.__poFollow = true;
                  let ticks = 0;
                  const burst = setInterval(() => {
                    w.__poFollow = true;   // ignore spurious disengage mid-resume
                    const el = findScrollable();
                    if (el) { try { el.scrollTo({ top: el.scrollHeight, behavior: 'auto' }); }
                              catch (_) { el.scrollTop = el.scrollHeight; } }
                    if (++ticks > 260) { clearInterval(burst); w.__poBurst = null; }  // ~39s @150ms
                  }, 150);
                  w.__poBurst = burst;
                  const stopBurst = (e) => {
                    const up = !e || (e.deltaY && e.deltaY < 0)
                             || (e.key && ['PageUp','ArrowUp','Home'].includes(e.key));
                    if (up) {
                      try { clearInterval(burst); } catch (_) {}
                      w.__poBurst = null;
                      w.removeEventListener('wheel', stopBurst);
                      w.removeEventListener('keydown', stopBurst);
                    }
                  };
                  w.addEventListener('wheel', stopBurst, { passive: true });
                  w.addEventListener('keydown', stopBurst);
                }
              } else {
                // Terminal / idle: one final scroll to reveal the last
                // message, then hand full control back to the user. When a CSR
                // decision card is on screen (SUPPRESS_IDLE) we skip this —
                // scroll_to_csr_top() owns the viewport position instead.
                w.__poObs = null; w.__poInt = null;
                if (w.__poFollow && !SUPPRESS_IDLE) {
                  const el = findScrollable();
                  if (el) { try { el.scrollTo({ top: el.scrollHeight,
                                                behavior: 'smooth' }); }
                            catch (_) { el.scrollTop = el.scrollHeight; } }
                }
              }
            } catch (e) { /* cross-origin / startup race — ignore */ }
          })();
        </script>
        """ % (flag, force, suppress),
        height=0,
    )


def scroll_to_csr_top(anchor_id: str):
    """Scroll the page so the 'CSR DECISION NEEDED' warning banner lands at
    the top of the viewport.

    Emits JS that finds the warning element by its visible text content and
    scrolls to it. Only fires once per unique anchor_id (so a radio click /
    text-box interaction inside the card doesn't re-scroll). The auto-follow
    observer is killed first so it can't fight the scroll position."""
    if st.session_state.get("_csr_scrolled_to") == anchor_id:
        return
    st.session_state["_csr_scrolled_to"] = anchor_id
    _components.html(
        """
        <script>
          (function () {
            try {
              const w = window.parent || window;
              // Kill auto-follow so it doesn't drag us back to the bottom.
              w.__poFollow = false;
              if (w.__poObs) { try { w.__poObs.disconnect(); } catch (_) {} w.__poObs = null; }
              if (w.__poInt) { try { clearInterval(w.__poInt); } catch (_) {} w.__poInt = null; }

              const doc = w.document;
              const tryScroll = (n) => {
                // Find the warning element containing "CSR DECISION NEEDED".
                const alerts = doc.querySelectorAll(
                  '[data-testid="stAlert"], [data-testid="stNotification"], ' +
                  '[role="alert"], .stAlert, .element-container div[data-testid]'
                );
                let target = null;
                for (const el of alerts) {
                  if (el.textContent && el.textContent.indexOf('CSR DECISION NEEDED') !== -1) {
                    target = el; break;
                  }
                }
                // Fallback: search ALL elements for the text.
                if (!target) {
                  const all = doc.querySelectorAll('div, p, span');
                  for (const el of all) {
                    if (el.textContent && el.textContent.indexOf('CSR DECISION NEEDED') !== -1
                        && el.offsetHeight > 0) {
                      target = el; break;
                    }
                  }
                }
                if (target) {
                  // Keep follow OFF so nothing drags us back to the bottom.
                  w.__poFollow = false;
                  // Give the banner a little breathing room from the top edge so
                  // the single scroll lands cleanly (no second nudge scroll).
                  try { target.style.scrollMarginTop = '16px'; } catch (_) {}
                  let done = false;
                  const doScroll = () => {
                    if (done) return; done = true;
                    w.__poFollow = false;
                    try { target.scrollIntoView({behavior:'smooth', block:'start'}); }
                    catch (_) { target.scrollIntoView(true); }
                  };
                  // The decision card renders progressively (banner, detail,
                  // impact table, picklist, buttons), so its position keeps
                  // shifting for a moment. Wait until the page height stops
                  // changing, THEN scroll exactly once — no jitter, no 2–3
                  // competing jumps.
                  let lastH = -1, stable = 0;
                  const settle = setInterval(() => {
                    const h = doc.body.scrollHeight;
                    if (h === lastH) { stable++; } else { stable = 0; lastH = h; }
                    if (stable >= 3) { clearInterval(settle); doScroll(); }
                  }, 90);
                  // Hard cap: always scroll even if the height never fully settles.
                  setTimeout(() => { try { clearInterval(settle); } catch (_) {} doScroll(); }, 1400);
                  return;
                }
                if (n > 0) setTimeout(() => tryScroll(n - 1), 100);
              };
              // Delay first attempt to let the Streamlit DOM settle after rerun.
              setTimeout(() => tryScroll(40), 200);
            } catch (e) { /* cross-origin / startup race — ignore */ }
          })();
        </script>
        """,
        height=0,
    )


from modules.extractor        import POExtractor, ExtractedPO
from modules.excel_parser     import parse_excel
from modules                  import duplicate_checker as dup
from modules.account_validator import AccountValidator, AccountValidationResult
from modules.pipeline         import build_context, SEQUENTIAL_STAGES, GOVERNANCE, EXECUTION
from modules.intake_resolver  import IntakeResolver
from modules.integrations     import system_meta, describe_systems
# Outlook / Microsoft 365 PO email intake — kept internal but HIDDEN for now.
# Turn on by setting EMAIL_INTAKE_ENABLED=1 (env) once the Entra app
# registration (tenant id + client id + Mail.Read consent) is available.
from modules                  import email_intake
EMAIL_INTAKE_ENABLED = os.environ.get("EMAIL_INTAKE_ENABLED", "0") == "1"
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

/* Make the selected substitute-SKU radio button clearly bolder/highlighted */
.stButton > button[kind="primary"] {
    font-weight: 800 !important;
    border: 2px solid #34D399 !important;
    box-shadow: 0 0 0 2px rgba(52,211,153,0.35) !important;
}

/* Disable dialog open/close transition so "View details" popup appears instantly */
[data-testid="stDialog"],
[data-testid="stModal"],
div[role="dialog"],
div[role="dialog"] > div {
    animation: none !important;
    transition: none !important;
}
div[data-testid="stModal"] > div[data-testid="stModalBackdrop"] {
    animation: none !important;
    transition: none !important;
}
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
    "PARTIAL_SHIP_TO":      "Shipments / Account Manager",
    "UNRESOLVED_SHIP_TO":   "Shipments / Account Manager",
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
    "SPLIT_SHIPMENT":       "Fulfillment Planner",
    "OUT_OF_STOCK":         "Procurement / Planning",
    "MIN_ORDER_QTY_NOT_MET":"Fulfillment Planner",
    "ZIP_NOT_SERVICEABLE":  "Shipments Team",
    "SLA_MISS":             "Shipments Team",
    "EXECUTION_FAILURE":    "Integration Support",
    "ACCOUNT_UNMATCHED_CUSTOMER": "Account Manager",
    "ACCOUNT_INVALID_SHIP_TO":    "Shipments / Account Manager",
    "ACCOUNT_HIERARCHY_MISMATCH": "Account Manager",
    "ACCOUNT_DUPLICATE_CUSTOMER": "Account Manager",
    "DUPLICATE_PO":         "Order Operations Supervisor",
}


def escalation_target(exc_type) -> str:
    return ESCALATION_ROUTING.get(exc_type, "Order Operations Supervisor")


# ── Multi-agent presentation (display only) ───────────────────────────────────
# Each process is shown as if it were handled by its own dedicated, specialized
# Order assistant. This is purely cosmetic — the orchestration is a single engine — but
# it makes the "team of collaborating agents" story legible in the demo. Every
# process (intake, customer validation, and each decision layer) gets a distinct
# agent name and is badged accordingly wherever that process is rendered.
AGENT_ICON = "🤖"
AGENT_NAMES = {
    "intake":               "Intake Agent",
    "extraction":           "Intake Agent",
    "account":              "Customer Validation Agent",
    # Buyer authorization is a sub-check of Customer Validation — it is handled
    # by the same agent so it reads as one process, not a separate agent.
    "buyer_authorization":  "Customer Validation Agent",
    "product_match":        "Product Validation Agent",
    # Compliance is a sub-check of Product Match — it is handled by the same
    # agent so it reads as one process, not a separate agent.
    "compliance":           "Product Validation Agent",
    "pricing":              "Pricing & Promo Agent",
    "credit":               "Credit Agent",
    "inventory":            "Inventory Agent",
    "logistics":            "Shipment Selection Agent",
    "budget_approval":      "Approvals Agent",
    "exception_governance": "Exception Governance Agent",
    "order_execution":      "Order Execution Agent",
}


def agent_name(stage_key) -> str:
    return AGENT_NAMES.get(stage_key, "Orchestration Agent")


# ── Which agent owns each intake issue ──────────────────────────────────────
# The intake resolver detects every "soft" issue up front, but each decision is
# surfaced during the run of the agent that owns it (so the multi-agent flow
# reads naturally): quantity at Intake, buyer/ship-to at Customer Validation,
# and product/UOM at Product Matching. Issues are processed in this order with a
# single monotonic pointer, pausing at each bucket boundary to animate the agent
# in between.
ISSUE_BUCKET = {
    "INVALID_QUANTITY":    "intake",
    "UNRESOLVED_BUYER":    "customer",
    "PARTIAL_SHIP_TO":     "customer",
    "UNRESOLVED_SHIP_TO":  "customer",
    "SUBSTITUTE_SKU":      "product",
    "UOM_CONVERSION":      "product",
    "UOM_AMBIGUOUS":       "product",
    "UNRESOLVED_SKU":      "product",
    "MISSING_SKU":         "product",
}
_BUCKET_ORDER = {"intake": 0, "customer": 1, "product": 2}


def _bucket_for(issue) -> str:
    return ISSUE_BUCKET.get(getattr(issue, "kind", ""), "product")


def _order_issues_by_agent(issues):
    """Return (sorted_issues, bounds). Issues are grouped in agent order and
    ``bounds`` gives the boundary indices: intake=[0,c), customer=[c,p),
    product=[p,n)."""
    ordered = sorted(issues, key=lambda i: _BUCKET_ORDER.get(_bucket_for(i), 2))
    c = sum(1 for i in ordered if _bucket_for(i) == "intake")
    p = c + sum(1 for i in ordered if _bucket_for(i) == "customer")
    n = len(ordered)
    return ordered, {"c": c, "p": p, "n": n}


def agent_tag(stage_key) -> str:
    """Plain-text agent tag for st.status labels (no HTML there)."""
    return f"{AGENT_ICON} {agent_name(stage_key)}"


def render_agent_badge(stage_key):
    """Small styled pill shown under a process header in the settled view."""
    st.markdown(
        f"<div style='display:inline-block;background:#0B3D2E;color:#6EE7B7;"
        f"border:1px solid #10B981;border-radius:12px;padding:2px 10px;"
        f"font-size:0.78rem;font-weight:600;margin:0 0 10px;'>"
        f"{AGENT_ICON} {html_safe(agent_name(stage_key))}</div>",
        unsafe_allow_html=True)


# ── Mock enterprise-system connections per agent ────────────────────────────
# Each agent fetches & validates its data from one or more mock systems (ERP /
# PIM / Commerce / OMS / Shipping). The pipeline stage classes carry a `systems`
# attribute; these entries cover the non-stage agents (Customer Validation,
# buyer authorization sub-check, intake).
AGENT_SYSTEMS = {
    "account":             ("COMMERCE", "OMS"),   # customer details + buying history
    "buyer_authorization": ("COMMERCE", "PIM"),   # buyer directory + SKU family
    "intake":              (),                     # reads the PO document only
    "extraction":          (),
}


def _build_stage_systems_map():
    m = dict(AGENT_SYSTEMS)
    for s in SEQUENTIAL_STAGES:
        k = getattr(s, "stage_key", None)
        sysx = getattr(s, "systems", None)
        if k and sysx:
            m[k] = tuple(sysx)
    return m


STAGE_SYSTEMS = _build_stage_systems_map()


def systems_for(stage_key) -> tuple:
    """Mock systems an agent/process connects to (for the 'connecting to…' UI)."""
    return STAGE_SYSTEMS.get(stage_key, ())


def _system_label(code) -> str:
    m = system_meta(code)
    host = (m.get("endpoint") or "").split("//")[-1].split("/")[0]
    return f"{m['icon']} **{m['name']}**" + (f" `{host}`" if host else "")


def render_systems_connect(codes):
    """Live 'connecting to mock system' line rendered inside an agent's running
    status panel (shows the agent reaching out to ERP / PIM / etc.)."""
    codes = tuple(codes or ())
    if not codes:
        return
    st.write("🔌 Connecting to " + "  ·  ".join(_system_label(c) for c in codes)
             + " to fetch & validate data…")


def render_systems_validated(codes):
    """Live 'data validated against …' line shown after the fetch succeeds."""
    codes = tuple(codes or ())
    if not codes:
        return
    st.write(f"🟢 Data fetched & validated against {describe_systems(list(codes))}.")


def render_systems_static(codes):
    """Persistent 'Data systems' pill row under a settled agent card, so the
    system connections remain visible after the live animation is gone."""
    codes = tuple(codes or ())
    if not codes:
        return
    pills = "".join(
        f"<span style='display:inline-block;background:#0B1F3A;color:#93C5FD;"
        f"border:1px solid #1D4ED8;border-radius:10px;padding:1px 8px;"
        f"font-size:0.72rem;margin:0 6px 6px 0;'>"
        f"{system_meta(c)['icon']} {html_safe(system_meta(c)['name'])}</span>"
        for c in codes)
    st.markdown(
        "<div style='margin:2px 0 8px;'><span style='color:#7C8DA6;"
        "font-size:0.72rem;'>🔌 Data systems:&nbsp;</span>" + pills + "</div>",
        unsafe_allow_html=True)


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
def render_account_result(av: AccountValidationResult, subchecks=None):
    st.markdown("### 🧭 Customer Validation")
    render_agent_badge("account")
    # Customer Validation pulls customer details from Mock Commerce and buying
    # history from Mock OMS (buyer authorization also checks Commerce + PIM).
    _acct_systems = tuple(dict.fromkeys(
        systems_for("account") + systems_for("buyer_authorization")))
    render_systems_static(_acct_systems)

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

    # Sub-checks handled by the SAME Customer Validation agent (buyer
    # authorization) — indented and folded into the single audit trail below.
    subchecks = subchecks or []
    for sub in subchecks:
        _render_subcheck_sections(sub)

    _render_combined_audit(
        [("Customer Validation", av.audit_trail)]
        + [(sub.title, sub.audit_trail) for sub in subchecks]
    )


# Stages that are folded UNDER a decision layer (rendered as a nested sub-check
# rather than a separate top-level layer heading), matching the decision-layer
# taxonomy in Autonomous_PO_to_Fulfillment_Orchestration.docx:
#   buyer_authorization → within "Customer Validation"
#   compliance          → within "Product Match"
SUBCHECK_STAGES = {"buyer_authorization", "compliance"}

# Sub-checks folded into a PARENT's single live panel so one agent shows exactly
# ONE running panel during processing:
#   buyer_authorization → folded into the Customer Validation panel
#                         (handled by _run_account_layer)
#   compliance          → folded into the Product Match panel
#                         (handled by _run_stage_animation via _folded_subchecks)
FOLDED_SUBCHECKS = {"product_match": ["compliance"]}


def _stage_by_key(key):
    for s in SEQUENTIAL_STAGES:
        if getattr(s, "stage_key", None) == key:
            return s
    return None


def _folded_subchecks(stage):
    keys = FOLDED_SUBCHECKS.get(getattr(stage, "stage_key", None), [])
    return [s for s in SEQUENTIAL_STAGES if getattr(s, "stage_key", None) in keys]


# ─── Helper: generic stage-result renderer (US-03 … US-12) ────────────────────
def _render_stage_sections(res):
    """Render a stage's PASS/EXCEPTION headline + its sections + the optional
    approval-email banner — everything EXCEPT the audit-trail expander (that is
    rendered once per agent by the caller, so a parent process and its
    sub-checks share a single audit trail)."""
    if res.is_exception:
        if res.exception_type == "PRICING_EXCEPTION":
            st.warning(f"🟡  CSR DECISION NEEDED — {res.exception_type}")
        else:
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


def _render_subcheck_sections(sub):
    """Render a sub-check (same agent's sub-process) indented one level so it
    reads as part of the parent process — heading + sections only, no separate
    agent badge and no separate audit-trail expander."""
    _, body = st.columns([1, 22], gap="small")
    with body:
        st.markdown(f"#### ↳ {sub.icon} {sub.title}")
        _render_stage_sections(sub)


def _render_combined_audit(blocks):
    """Render ONE audit-trail expander for a single agent. `blocks` is a list of
    (label, audit_lines). When more than one block has content each is shown
    under its own bold sub-heading, so the parent process and its sub-checks
    share a single, complete audit trail — one agent, one audit trail."""
    blocks = [(lbl, lines) for lbl, lines in blocks if lines]
    if not blocks:
        return
    multi = len(blocks) > 1
    with st.expander("🧾 View audit trail"):
        for i, (lbl, lines) in enumerate(blocks):
            if multi:
                st.markdown(f"**{md_safe(lbl)}**")
            for line in lines:
                st.markdown(f"- {md_safe(line)}")
            if multi and i < len(blocks) - 1:
                st.write("")


def render_stage_result(res, divider=True, subchecks=None):
    """Render a settled decision-layer card.

    `subchecks` (list of StageResult) are folded UNDER this stage because they
    are the SAME agent's sub-processes (e.g. compliance under Product Match).
    They render as indented sub-sections and their audit lines join this
    stage's single audit trail — one agent, one audit trail."""
    subchecks = subchecks or []
    is_subcheck = getattr(res, "stage_key", None) in SUBCHECK_STAGES
    if is_subcheck and not subchecks:
        # Standalone render of a sub-check (e.g. a paused compliance exception):
        # smaller heading, no divider.
        st.markdown(f"#### ↳ {res.icon} {res.title}")
    else:
        # `divider` is suppressed when the layer is already wrapped in its own
        # bordered container (the tree layout) so we don't draw a rule inside
        # the box.
        if divider:
            st.markdown("---")
        st.markdown(f"### {res.icon} {res.title}")
    render_agent_badge(getattr(res, "stage_key", None))
    render_systems_static(systems_for(getattr(res, "stage_key", None)))
    _render_stage_sections(res)

    for sub in subchecks:
        _render_subcheck_sections(sub)

    _render_combined_audit(
        [(res.title, res.audit_trail)]
        + [(sub.title, sub.audit_trail) for sub in subchecks]
    )


# Agents that never get a standalone "completed successfully" banner:
# buyer authorization is folded into Customer Validation, governance is internal,
# and order execution reports its own "Order created" success message.
_SKIP_SUCCESS_BANNER = {"buyer_authorization", "exception_governance", "order_execution"}


def _agent_success_banner(stage_key):
    """Green 'completed successfully' banner shown after an agent's process
    passes with no exception. Rendered both live (during the animation) and in
    the settled transcript (render_orch_static) so it persists across reruns and
    each agent visibly wraps up before the next one begins."""
    st.success(f"✅ {agent_name(stage_key)} — process completed successfully.")


def _animate_agent_scan(stage):
    """Animate a stage's process steps in a status panel WITHOUT validating.

    Used to show an agent visibly executing its checks BEFORE it pauses for a
    CSR decision that its own scan surfaced (e.g. Product Validation discovers an
    obsolete SKU / UOM mismatch). The panel is left in an "action required"
    state; the caller then routes to the decision phase."""
    tag = agent_tag(getattr(stage, "stage_key", None))
    with st.status(f"{tag}  ·  {stage.icon} {stage.title}...", expanded=True) as status:
        st.caption(f"{tag} is handling this step.")
        render_systems_connect(tuple(getattr(stage, "systems", ()) or ()))
        for delay, emoji, text in stage.steps:
            st.write(f"{emoji} {text}")
            nap(paced_delay(delay))
        # Hold on a clear "found something" beat so the CSR sees the scan finish
        # and understands WHY the pipeline is about to pause — before the rerun
        # swaps in the decision card.
        st.write("🟡 Found line item(s) that need your confirmation before the "
                 "match can be finalized...")
        nap(paced_delay(0.6))
        status.update(
            label=f"{tag}  ·  {stage.icon} {stage.title} — action required",
            state="complete", expanded=True)


def _render_product_scan_panel_static():
    """Persistent 'Product Validation ran its scan' panel for the product
    decision screen.

    The live scan (``_animate_agent_scan``) is transient and is gone after the
    rerun that surfaces the decision, so re-render the agent's completed checks
    ABOVE the decision card. This keeps clear, lasting visibility that the
    Product Validation agent actually executed its catalog / lifecycle / UOM
    scan and only THEN surfaced the CSR decision."""
    tag = agent_tag("product_match")
    steps = next((getattr(s, "steps", []) for s in SEQUENTIAL_STAGES
                  if getattr(s, "stage_key", None) == "product_match"), [])
    with st.status(f"{tag}  ·  📦 Product Match — scan complete, action required",
                   state="complete", expanded=True):
        st.caption(f"{tag} scanned each order line against the catalog, product "
                   "lifecycle and units of measure.")
        render_systems_connect(systems_for("product_match"))
        for _delay, emoji, text in steps:
            st.write(f"{emoji} {text}")
        st.write("🟡 Found line item(s) that need your confirmation below.")


def _run_stage_animation(stage, ctx, subchecks=None, animate_steps=True):
    """Animate a pipeline stage step-by-step, optionally folding its sub-checks
    (the SAME agent's sub-processes) into the SAME status panel so one agent
    shows exactly ONE running panel during processing.

    We keep the status widget `expanded=True` after completion (instead of
    collapsing it to a one-line accordion header) so every processing step
    stays on screen. This matters after CSR interactive decisions — the user
    needs to *see* the pipeline resume and progress stage-by-stage, not just
    watch a stack of collapsed headers appear.

    When ``animate_steps`` is False the main step loop is skipped (the agent's
    scan already animated before a CSR decision) and the stage simply finalizes
    with the resolved context — avoids replaying the same steps twice.

    Returns ``(stage_result, folded_subcheck_results)``. Folded sub-checks only
    run when the parent stage passes; they stop at the first sub-check that
    raises an exception."""
    subchecks = subchecks or []
    result = [None]
    folded = []
    tag = agent_tag(getattr(stage, "stage_key", None))
    _sys = tuple(getattr(stage, "systems", ()) or ())
    with st.status(f"{tag}  ·  {stage.icon} {stage.title}...", expanded=True) as status:
        st.caption(f"{tag} is handling this step.")
        render_systems_connect(_sys)
        if animate_steps:
            for delay, emoji, text in stage.steps:
                st.write(f"{emoji} {text}")
                nap(paced_delay(delay))
        else:
            # Scan already animated before the CSR decisions — finalize the match
            # with the resolved lines (shown as a few visible steps, not a flash).
            for delay, emoji, text in [
                (0.30, "🔁", "Applying your decisions to the order lines..."),
                (0.30, "🔎", "Re-matching the resolved lines against the catalog..."),
                (0.25, "✅", "Confirming SKUs, configuration and units of measure..."),
            ]:
                st.write(f"{emoji} {text}")
                nap(paced_delay(delay))
        result[0] = stage.validate(ctx)

        # Fold the same agent's sub-checks into THIS panel (indented) so the
        # agent renders as a single running process, not two.
        if subchecks and not result[0].is_exception:
            sub_ctx = dict(ctx)
            sub_ctx.update(result[0].data or {})
            for sub in subchecks:
                st.markdown(f"↳ **{sub.icon} {sub.title}**")
                for delay, emoji, text in sub.steps:
                    st.write(f"{emoji} {text}")
                    nap(paced_delay(delay))
                sub_res = sub.validate(sub_ctx)
                folded.append(sub_res)
                sub_ctx.update(sub_res.data or {})
                if sub_res.is_exception:
                    break

        _exc = result[0].is_exception or any(s.is_exception for s in folded)
        if not _exc:
            render_systems_validated(_sys)
        state_txt = "action required" if _exc else "complete"
        status.update(label=f"{tag}  ·  {stage.icon} {stage.title} — {state_txt}",
                      state="complete", expanded=True)
    return result[0], folded


def _run_full_pipeline_legacy(po: ExtractedPO, av: AccountValidationResult):
    """(Retained for reference — superseded by the interactive orchestrator.)"""
    ctx = build_context(po, av)
    results = []
    paused = False

    for stage in SEQUENTIAL_STAGES:
        res, _ = _run_stage_animation(stage, ctx)
        ctx.update(res.data or {})
        render_stage_result(res)
        results.append(res)
        if res.is_exception:
            paused = True
            break

    # Exception governance (always runs)
    _gtag = agent_tag("exception_governance")
    with st.status(f"{_gtag}  ·  {GOVERNANCE.title}...", expanded=True) as status:
        for delay, emoji, text in GOVERNANCE.steps:
            st.write(f"{emoji} {text}")
            nap(paced_delay(delay))
        gov = GOVERNANCE.route(results, ctx)
        status.update(label=f"{_gtag}  ·  {GOVERNANCE.title} — complete",
                      state="complete", expanded=False)
    render_stage_result(gov)
    results.append(gov)

    # Order execution (only when nothing paused)
    if not paused:
        ex, _ = _run_stage_animation(EXECUTION, ctx)
        ctx.update(ex.data or {})
        render_stage_result(ex)
        results.append(ex)

    return results


# ─── Helper: AI processing animation ─────────────────────────────────────────
def run_intake(orch, raw_text: str, source_label: str) -> ExtractedPO:
    """Single Intake Agent process: read + extract the PO inside ONE status
    panel. Master-data resolution runs silently (for routing) but is NOT
    narrated here — intake only reads and extracts.

    Side effects on ``orch``:
      * sets ``po`` / ``is_dup`` / ``dup_rec`` after extraction,
      * sets ``issues`` (the resolver output) — left as ``[]`` when the PO is a
        duplicate or is missing mandatory fields (review narration is skipped in
        that case and the caller routes to the escalation card).
    """
    extract_steps = [
        (0.35, "📄", "Analyzing document format and structure..."),
        (0.30, "🔍", "Reading PO header section..."),
        (0.30, "🔢", "Extracting Purchase Order number..."),
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
    _tag = agent_tag("intake")
    with st.status(f"{_tag}  ·  Reading & extracting PO — {source_label}",
                   expanded=True) as status:
        st.caption(f"{_tag} is handling this step.")

        # Read & extract the PO in THIS single panel. Intake does not narrate the
        # master-data review — that resolution happens silently and each decision
        # surfaces during the owning agent's run.
        for i, (delay, emoji, text) in enumerate(extract_steps):
            st.write(f"{emoji} {text}")
            nap(paced_delay(delay))
            # Run actual extraction halfway through animation
            if i == 7 and extracted[0] is None:
                extracted[0] = EXTRACTOR.extract_from_text(raw_text)
        if extracted[0] is None:
            extracted[0] = EXTRACTOR.extract_from_text(raw_text)
        po = extracted[0]

        # Duplicate / mandatory-field detection (routing handled by caller).
        is_dup, dup_rec = dup.check(po.po_number, po.customer_account)
        if not is_dup and po.po_number:
            dup.register(po.po_number, po.customer_account, st.session_state.session_id)
        orch.update(po=po, is_dup=is_dup, dup_rec=dup_rec)

        if is_dup or po.missing_fields:
            # Skip the master-data review — the caller shows the escalation card.
            orch["issues"] = []
            orch["bucket_bounds"] = {"c": 0, "p": 0, "n": 0}
            status.update(
                label=f"{_tag}  ·  Extraction complete",
                state="complete",
                expanded=False,
            )
            nap(0.15)
            return po

        # Resolve the PO against master data SILENTLY so the orchestrator knows
        # which decisions to surface later — but intake itself only READS and
        # EXTRACTS, so no master-data review narration is shown in this panel.
        # Each detected issue is surfaced during the run of the agent that owns
        # it (quantity → Intake decision, buyer/ship-to → Customer Validation,
        # product/UOM → Product Validation).
        _issues, _bounds = _order_issues_by_agent(INTAKE_RESOLVER.resolve(po))
        orch["issues"] = _issues
        orch["bucket_bounds"] = _bounds
        orch["issue_ptr"] = 0
        status.update(
            label=f"{_tag}  ·  Extraction complete",
            state="complete",
            expanded=False,
        )
    # Intake read + extracted the PO cleanly. When no intake-level decision
    # (e.g. invalid quantity) is pending, announce success before the next
    # agent begins. (Intake-bucket issues open a decision card instead.)
    if orch["bucket_bounds"].get("c", 0) == 0:
        _agent_success_banner("intake")
    nap(0.15)
    return po


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
    st.session_state.pop("_csr_scrolled_to", None)
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
        # Boundary indices for the per-agent issue buckets (see run_intake):
        # intake=[0,c), customer=[c,p), product=[p,n).
        "bucket_bounds": {"c": 0, "p": 0, "n": 0},
        "decisions": [],       # settled CSR decisions (rendered as history)
        # Persistent record of decision CARDS the CSR has already actioned.
        # We keep them on screen (in render_orch_static) so the next stage's
        # animation appears BELOW the button the CSR just clicked, matching
        # the natural reading order. Each entry is a dict with:
        #   title, kind, detail, rationale, decision, outcome
        "resolved_issues": [],
        "ctx": None,
        "stage_index": 0,
        # Guard so the Product Validation agent's scan animates exactly once
        # (before its product-line CSR decisions); the match is finalized after.
        "product_scan_done": False,
        "governance_done": False,  # guard so a stage-exception re-entry does
                                   # not re-run governance twice
        "results": [],         # settled StageResults
        "pending": None,       # current stage exception awaiting CSR
        "terminal": None,      # ('rejected'|'escalated', message)
    }


def _decision_key(prefix: str) -> str:
    o = st.session_state.orch
    return f"{prefix}_{o['phase']}_{o['issue_ptr']}_{o['stage_index']}"


def _reset_widget_state(key: str, value):
    """on_change callback: reset another widget's state so only one CSR input
    (a picked option OR a typed correction) is ever active at a time."""
    st.session_state[key] = value


def _pick_row(sel_key: str, idx: int, clear_txt_key: str = None):
    """on_click callback for radio-style 'Select' buttons. Runs BEFORE the
    natural button rerun, so the new selection is rendered in that single run —
    no extra st.rerun() (which would double the render work and cause lag)."""
    st.session_state[sel_key] = idx
    if clear_txt_key is not None:
        st.session_state[clear_txt_key] = ""


# ── Rendering: settled (static) portion of a run ──────────────────────────────
def render_decision_log(decisions):
    if not decisions:
        return
    st.markdown("#### 🧾 CSR Decision Audit Trail")
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
                "<b>Order Assistant decided automatically from master data:</b>"
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
        f"<div style='color:#E2E8F0; font-size:0.9rem;'>"
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
        # Intake wrapped up cleanly (no duplicate / missing-field escalation and
        # no pending intake-level decision) → persist its success banner.
        if (not orch["is_dup"] and not orch["po"].missing_fields
                and orch.get("bucket_bounds", {}).get("c", 0) == 0):
            _agent_success_banner("intake")
        st.markdown("---")

        results = orch["results"]
        rendered = set()

        # ── Customer Validation (+ Buyer Authorization sub-check) ─────────
        # A settled (non-exception, or overridden) account result is history.
        # An unresolved account exception is rendered by the drive step instead.
        if orch["av"] is not None and (not orch["av"].is_exception
                                       or orch["phase"] not in ("account_pending",)):
            buyer_subs = [r for r in results if r.stage_key == "buyer_authorization"]
            render_account_result(orch["av"], subchecks=buyer_subs)
            for r in buyer_subs:
                rendered.add(id(r))
            # Customer Validation is only "complete" once buyer authorization has
            # settled and passed (the buyer decision, if any, is resolved).
            if not orch["av"].is_exception and any(not r.is_exception for r in buyer_subs):
                _agent_success_banner("account")
            st.markdown("---")

        # ── Remaining decision layers ────────────────────────────────────
        # Each non-subcheck stage is a heading + processes + separator.
        # Compliance is a sub-check folded into the Product Match agent.
        for res in results:
            if id(res) in rendered:
                continue
            if res.stage_key in SUBCHECK_STAGES:
                continue  # folded into its parent agent below
            if res.stage_key == "product_match":
                comp_subs = [s for s in results if s.stage_key == "compliance"]
                render_stage_result(res, divider=False, subchecks=comp_subs)
                for s in comp_subs:
                    rendered.add(id(s))
                stage_ok = (not res.is_exception
                            and all(not s.is_exception for s in comp_subs))
            else:
                render_stage_result(res, divider=False)
                stage_ok = not res.is_exception
            # Persist the per-agent success banner for passed pipeline stages.
            if stage_ok and res.stage_key not in _SKIP_SUCCESS_BANNER:
                _agent_success_banner(res.stage_key)
            st.markdown("---")


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


def _fmt_price(cur, amount):
    """Currency-code price string (avoids Streamlit '$' LaTeX handling)."""
    return f"{cur} {amount:,.2f}" if isinstance(amount, (int, float)) else "—"


def _render_reason_list(options):
    """Plain-language 'why this is suggested' lines, one per candidate."""
    for s in options:
        if s.get("reason"):
            st.markdown(f"<div style='margin:2px 0 6px 2px;color:#CBD5E1;'>"
                        f"💡 {html_safe(s['reason'])}</div>", unsafe_allow_html=True)


# Column layout for the interactive substitute-SKU table (radio-select first).
_SUBST_COL_WEIGHTS = [1.5, 1.7, 3.0, 1.5, 1.5, 1.5, 1.8]
_SUBST_COL_HEADERS = ["Select", "Suggested SKU", "Description",
                      "Original Price", "Suggested Price", "Difference",
                      "Why suggested"]


@st.dialog(" ")
def _show_substitute_reason_dialog(sku: str, reason: str):
    """Modal popup showing the plain-language rationale for a suggested SKU.
    Streamlit renders a native ✕ close button in the top-right of the dialog
    header, so no explicit close control is needed inside the body."""
    st.markdown(f"**Why {html_safe(sku)} is suggested**")
    st.markdown(f"<div style='color:#CBD5E1;'>💡 {html_safe(reason)}</div>",
                unsafe_allow_html=True)


def _render_substitute_sku_selector(orch, issue):
    """Interactive 'actual vs. suggested SKU' table for obsolete-product
    substitution. The first column is a radio-style selector and the last column
    carries the plain-language reason, so the whole decision reads from ONE
    table (no separate 'pick one' list). Returns the selected suggestion dict."""
    st.markdown("**Suggested replacement"
                f"{'s' if len(issue.suggestions) > 1 else ''} — actual vs. suggested "
                "SKU (CSR approval required):**")
    sugg = issue.suggestions
    rec_sku = (issue.recommended or {}).get("sku")

    sel_key = f"subst_sel_{orch['issue_ptr']}"
    if sel_key not in st.session_state:
        st.session_state[sel_key] = -1          # nothing selected by default
    selected_idx = st.session_state[sel_key]

    with st.container(border=True):
        hc = st.columns(_SUBST_COL_WEIGHTS, vertical_alignment="center")
        for c, h in zip(hc, _SUBST_COL_HEADERS):
            c.markdown(f"<div style='font-weight:700;font-size:0.78rem;color:#93C5FD;'>"
                       f"{h}</div>", unsafe_allow_html=True)

    for i, s in enumerate(sugg):
        cur = s.get("currency") or "USD"
        op, cp = s.get("original_price"), s.get("price")
        diff, pct = s.get("price_diff"), s.get("price_diff_pct")
        if isinstance(diff, (int, float)) and pct is not None and diff != 0:
            sign = "+" if diff > 0 else "−"
            color = "#F87171" if diff > 0 else "#34D399"
            diff_txt = (f"<span style='color:{color};'>{sign}{cur} "
                        f"{abs(diff):,.2f} ({sign}{abs(pct)}%)</span>")
        elif isinstance(diff, (int, float)) and diff == 0:
            diff_txt = "no change"
        else:
            diff_txt = "—"
        with st.container(border=True):
            rc = st.columns(_SUBST_COL_WEIGHTS, vertical_alignment="center")
            is_sel = (i == selected_idx)
            # Picking a row clears any manual SKU entry — only one option (a
            # picked row OR a typed SKU) can be active at a time. Using an
            # on_click callback avoids a second st.rerun() (no lag).
            rc[0].button("🔘 Selected" if is_sel else "⚪ Select",
                         key=f"subst_pick_{orch['issue_ptr']}_{i}",
                         help="Select this replacement",
                         type="primary" if is_sel else "secondary",
                         use_container_width=True,
                         on_click=_pick_row,
                         args=(sel_key, i, _decision_key("subst_txt")))
            rc[1].markdown(f"<b>{html_safe(s.get('sku'))}</b>", unsafe_allow_html=True)
            rc[2].markdown(html_safe(s.get('description')), unsafe_allow_html=True)
            rc[3].markdown(_fmt_price(cur, op), unsafe_allow_html=True)
            rc[4].markdown(f"<b>{_fmt_price(cur, cp)}</b>", unsafe_allow_html=True)
            rc[5].markdown(diff_txt, unsafe_allow_html=True)
            reason = s.get("reason")
            if reason:
                if rc[6].button("🔍 View details",
                                key=f"subst_view_{orch['issue_ptr']}_{i}",
                                use_container_width=True):
                    _show_substitute_reason_dialog(s.get("sku"), reason)
            else:
                rc[6].markdown("—")

    if 0 <= selected_idx < len(sugg):
        return sugg[selected_idx]
    return None


_UOM_CUSTOM_LABEL = "Enter custom value"


def _render_uom_conversion_selector(orch, issue):
    """Dropdown-based UOM conversion picker: the CSR chooses how many base-UOM
    units (e.g. KIT) to order from a 1–10 dropdown, or picks 'Enter custom
    value' to type any positive whole number. The product's base UOM is shown
    next to the dropdown. Returns a choice dict (or None if nothing valid yet)."""
    s0 = issue.suggestions[0] if issue.suggestions else {}
    base_uom = s0.get("uom", "KIT")
    orig_uom = s0.get("original_uom", "EA")
    orig_qty = s0.get("original_qty")
    currency = s0.get("currency", "USD")
    kits0 = s0.get("kits", 1) or 1
    ea_per_kit = round((s0.get("ea_equivalent", 0) / kits0)) if kits0 else 1
    price_per_kit = (s0.get("total_price", 0) / kits0) if kits0 else 0

    st.markdown(f"**Select the quantity to order in {base_uom} "
                f"(the PO requested {orig_qty} {orig_uom}; "
                f"1 {base_uom} = {ea_per_kit} {orig_uom}):**")

    options = [str(n) for n in range(1, 11)] + [_UOM_CUSTOM_LABEL]
    c1, c2 = st.columns([3, 1], vertical_alignment="center")
    picked = c1.selectbox(
        "Quantity", options, index=None,
        placeholder=f"Select number of {base_uom}…",
        key=_decision_key("uom_dd"), label_visibility="collapsed",
    )
    c2.markdown(
        f"<div style='font-weight:700;font-size:1rem;'>{base_uom}</div>",
        unsafe_allow_html=True,
    )

    kits = None
    if picked == _UOM_CUSTOM_LABEL:
        custom = st.text_input(
            "Custom quantity", key=_decision_key("uom_custom"),
            placeholder=f"Enter number of {base_uom} (positive whole number)",
            label_visibility="collapsed",
        )
        if custom:
            err = validate_manual_quantity(custom)
            if err:
                st.error(f"❌ {err}")
            else:
                kits = int(float(custom))
    elif picked is not None:
        kits = int(picked)

    if not kits or kits <= 0:
        return None

    ea = kits * ea_per_kit
    total = kits * price_per_kit
    # Delta vs. what the PO originally requested: rounding up to whole base-UOM
    # units usually fulfills MORE than the requested quantity, so show the price
    # impact of those extra units (price-per-EA × extra EA).
    price_per_ea = (total / ea) if ea else 0
    delta_ea = (ea - orig_qty) if isinstance(orig_qty, (int, float)) else None
    delta_price = (delta_ea * price_per_ea) if delta_ea is not None else None

    caption = (f"Selected: **{kits} {base_uom}** = {ea} {orig_uom}  ·  "
               f"Total {currency} {total:,.2f}")
    if delta_price is not None and abs(delta_price) >= 0.005:
        sign = "+" if delta_price > 0 else "−"
        caption += (f"  ·  Δ {sign}{currency} {abs(delta_price):,.2f} "
                    f"({_fmt_qty(abs(delta_ea))} {orig_uom} "
                    f"{'over' if delta_ea > 0 else 'under'} the "
                    f"{_fmt_qty(orig_qty)} {orig_uom} requested)")
    st.caption(caption)

    return {
        "kind": "convert_pick",
        "original_qty": orig_qty, "original_uom": orig_uom,
        "qty_base": kits, "uom": base_uom,
        "ea_equivalent": ea, "total_price": round(total, 2),
        "currency": currency,
        "logic": f"{kits} {base_uom} × {ea_per_kit} {orig_uom}/{base_uom} = {ea} {orig_uom}",
    }


_BUYER_COL_WEIGHTS = [1.3, 2.0, 2.5, 1.8, 1.8]
_BUYER_COL_HEADERS = ["Select", "Buyer", "Email", "Role", "Cost Center"]


def _render_buyer_selector(orch, issue):
    """Interactive bordered table for buyer selection — same visual style as
    the obsolete-SKU and UOM-rounding selectors. Returns the selected
    suggestion dict."""
    sugg = issue.suggestions
    if not sugg:
        st.info("No buyers are registered against this customer in the "
                "buyer directory. CSR to type the correct buyer name.")
        return None

    st.markdown("**Buyers registered for this customer — pick one:**")

    sel_key = f"buyer_sel_{orch['issue_ptr']}"
    if sel_key not in st.session_state:
        st.session_state[sel_key] = -1          # nothing selected by default
    selected_idx = st.session_state[sel_key]

    with st.container(border=True):
        hc = st.columns(_BUYER_COL_WEIGHTS, vertical_alignment="center")
        for c, h in zip(hc, _BUYER_COL_HEADERS):
            c.markdown(f"<div style='font-weight:700;font-size:0.78rem;color:#93C5FD;'>"
                       f"{h}</div>", unsafe_allow_html=True)

    for i, s in enumerate(sugg):
        is_sel = (i == selected_idx)
        with st.container(border=True):
            rc = st.columns(_BUYER_COL_WEIGHTS, vertical_alignment="center")
            # Picking a buyer clears any manual entry — one option at a time.
            # on_click callback avoids a second st.rerun() (no lag).
            rc[0].button("🔘 Selected" if is_sel else "⚪ Select",
                         key=f"buyer_pick_{orch['issue_ptr']}_{i}",
                         type="primary" if is_sel else "secondary",
                         use_container_width=True,
                         on_click=_pick_row,
                         args=(sel_key, i, _decision_key("buyer_txt")))
            rc[1].markdown(f"<b>{html_safe(s.get('buyer_name'))}</b>",
                           unsafe_allow_html=True)
            rc[2].markdown(html_safe(s.get('email')), unsafe_allow_html=True)
            rc[3].markdown(html_safe(s.get('role')), unsafe_allow_html=True)
            rc[4].markdown(html_safe(s.get('default_cost_center') or '—'),
                           unsafe_allow_html=True)

    if 0 <= selected_idx < len(sugg):
        return sugg[selected_idx]
    return None


def _impact_table_for_issue(issue):
    if issue.kind == "SUBSTITUTE_SKU":
        # Obsolete-product substitution is rendered as an INTERACTIVE table
        # (radio-select column + "Why suggested" reason column) by
        # _render_substitute_sku_selector() in render_intake_issue — so there is
        # nothing to render here.
        return
    if issue.kind == "UOM_CONVERSION" and issue.suggestions and len(issue.suggestions) >= 2:
        # Rounding scenario (e.g. 52 EA → non-whole KIT). Rendered as a
        # quantity dropdown by _render_uom_conversion_selector — skip here.
        return
    if issue.kind == "UOM_CONVERSION" and issue.recommended:
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
    elif issue.kind == "UNRESOLVED_BUYER":
        # Buyer selection is rendered as an interactive bordered table by
        # _render_buyer_selector() in render_intake_issue.
        return
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
    elif issue.kind in ("UNRESOLVED_SKU", "MISSING_SKU") and issue.suggestions:
        # SKU identified from the description. Present each candidate's price +
        # attributes in plain language (MISSING_SKU intentionally omits any
        # match-confidence text). The pick-list below is the selector.
        st.markdown("**Suggested product"
                    f"{'s' if len(issue.suggestions) > 1 else ''} from master data:**")
        _render_reason_list(issue.suggestions)
    elif issue.suggestions and not _uses_radio(issue):
        head = "<th>Ship-To</th><th>Address</th><th>ZIP</th><th>Match</th>"
        body = "".join(
            f"<tr><td><b>{html_safe(s.get('name'))}</b></td>"
            f"<td>{html_safe(s.get('address'))}</td><td>{html_safe(s.get('zip'))}</td>"
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
            # Picked  = CSR chose one of the offered substitute options.
            # Enter   = CSR typed a completely different SKU to use instead.
            if decision == "Entered" and isinstance(value, str) and value.strip():
                new_sku = value.strip().upper()
                new_desc = None
            elif isinstance(value, dict):
                new_sku = value.get("substitute_sku") or value.get("sku")
                new_desc = value.get("substitute_description") or value.get("description")
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
    # Price string (currency-code form avoids Streamlit's LaTeX '$' handling).
    price = s.get("price")
    cur = s.get("currency") or "USD"
    price_txt = f"{cur} {price:,.2f}" if isinstance(price, (int, float)) else ""
    if issue.kind == "SUBSTITUTE_SKU":
        diff = s.get("price_diff")
        pct = s.get("price_diff_pct")
        delta = ""
        if isinstance(diff, (int, float)) and diff != 0 and pct is not None:
            sign = "+" if diff > 0 else "−"
            delta = f"  ·  **Δ {sign}{cur} {abs(diff):,.2f} ({sign}{abs(pct)}%)**"
        return (f"**{s.get('sku')}**  ·  {s.get('description')}  ·  "
                f"{s.get('compatibility') or 'FUNCTIONAL'}  ·  {price_txt}{delta}")
    # UNRESOLVED_SKU keeps the confidence score; MISSING_SKU drops it per request.
    tail = f"  ·  {price_txt}" if price_txt else ""
    if issue.kind == "MISSING_SKU":
        return (f"**{s.get('sku')}**  ·  {s.get('description')}  ·  "
                f"{s.get('family') or '—'}{tail}")
    pct = int(s.get('score', 0) * 100)
    return (f"**{s.get('sku')}**  ·  {s.get('description')}  ·  "
            f"{s.get('family') or '—'}{tail}  ·  **{pct}% match**")


# Decision kinds whose options are presented as a radio list to pick + approve.
RADIO_KINDS = ("PARTIAL_SHIP_TO", "UNRESOLVED_SHIP_TO",
               "UNRESOLVED_SKU", "MISSING_SKU")


def render_intake_issue(orch, issue):
    """Render an intake issue with Approve / Reject / Escalate + correction input."""
    po = orch.get("po")
    po_id = getattr(po, "po_number", "") if po is not None else ""
    scroll_to_csr_top(
        f"csr-intake-{po_id}-{orch.get('issue_ptr', 0)}-{issue.kind}"
    )
    st.warning(f"🟡  CSR DECISION NEEDED — {issue.title}")
    if issue.kind == "SUBSTITUTE_SKU":
        # Highlight the obsolete/inactive status so it stands out clearly.
        st.markdown(
            "<div style='background:#7F1D1D;color:#FEE2E2;padding:9px 13px;"
            "border-left:4px solid #EF4444;border-radius:6px;font-weight:600;'>"
            f"⛔ {html_safe(issue.detail)}</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(md_safe(issue.detail))
    _impact_table_for_issue(issue)

    # UOM_CONVERSION: two paths depending on whether the conversion yields a
    # whole number (single confirm) or requires rounding (pick from table).
    if issue.kind == "UOM_CONVERSION":
        if len(issue.suggestions) >= 2:
            # Rounding scenario — CSR picks the KIT quantity from a dropdown
            # (1–10 or a custom value); the base UOM is shown alongside.
            selected = _render_uom_conversion_selector(orch, issue)
            cols = st.columns(3)
            if cols[0].button("✅ Approve selected",
                              key=_decision_key("uomc_ok"), use_container_width=True,
                              disabled=selected is None):
                apply_issue_decision(orch, issue, "Picked", value=selected)
                orch["issue_ptr"] += 1
                st.rerun()
            if cols[1].button("⛔ Reject", key=_decision_key("uomc_no"),
                              use_container_width=True):
                _intake_reject(orch, issue)
            if cols[2].button("📧 Notify to customer", key=_decision_key("uomc_esc"),
                              use_container_width=True):
                _intake_escalate(orch, issue)
        else:
            # Exact conversion — single option, straight confirm.
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
            if cols[2].button("📧 Notify to customer", key=_decision_key("uomc_esc"),
                              use_container_width=True):
                _intake_escalate(orch, issue)
        return

    # SUBSTITUTE_SKU (obsolete product): the whole decision lives in one
    # interactive table — a radio-select column, the actual-vs-suggested pricing
    # columns and a "Why suggested" reason column. No separate pick-list.
    if issue.kind == "SUBSTITUTE_SKU":
        # If the CSR has typed a manual SKU, deselect any table row BEFORE the
        # table is drawn so the highlight clears in this same frame (only one
        # option — a picked row OR a manual entry — can be active at a time).
        sel_key = f"subst_sel_{orch['issue_ptr']}"
        pre_typed = (st.session_state.get(_decision_key("subst_txt")) or "").strip()
        if pre_typed and st.session_state.get(sel_key, -1) != -1:
            st.session_state[sel_key] = -1

        selected = _render_substitute_sku_selector(orch, issue)

        typed = None
        entry_error = None
        if "enter" in issue.actions:
            ph = "Or type a different SKU"
            typed = st.text_input(ph, key=_decision_key("subst_txt"),
                                  placeholder=ph, label_visibility="collapsed")
            if typed:
                selected = None
                entry_error = validate_manual_sku(
                    typed, orch["po"], issue.line_number, INTAKE_RESOLVER.products)
                if entry_error:
                    st.error(f"❌ {entry_error}")

        n_cols = 1 + (1 if "enter" in issue.actions else 0) \
                   + (1 if "reject" in issue.actions else 0) + 1
        cols = st.columns(n_cols)
        i = 0
        if cols[i].button("✅ Approve selected", key=_decision_key("subst_ok"),
                          use_container_width=True,
                          disabled=selected is None):
            apply_issue_decision(orch, issue, "Picked", value=selected)
            orch["issue_ptr"] += 1
            st.rerun()
        i += 1
        if "enter" in issue.actions:
            if cols[i].button("✍️ Use my entry", key=_decision_key("subst_use"),
                              use_container_width=True,
                              disabled=not typed or bool(entry_error)):
                apply_issue_decision(orch, issue, "Entered", value=typed)
                orch["issue_ptr"] += 1
                st.rerun()
            i += 1
        if "reject" in issue.actions:
            if cols[i].button("⛔ Reject", key=_decision_key("subst_no"),
                              use_container_width=True):
                _intake_reject(orch, issue)
            i += 1
        if cols[i].button("📧 Notify to customer", key=_decision_key("subst_esc"),
                          use_container_width=True):
            _intake_escalate(orch, issue)
        return

    # UNRESOLVED_BUYER: interactive bordered table with radio-select column.
    if issue.kind == "UNRESOLVED_BUYER":
        # Deselect any table row up-front if a manual entry is present, so the
        # highlight clears in the same frame (one option active at a time).
        sel_key = f"buyer_sel_{orch['issue_ptr']}"
        pre_typed = (st.session_state.get(_decision_key("buyer_txt")) or "").strip()
        if pre_typed and st.session_state.get(sel_key, -1) != -1:
            st.session_state[sel_key] = -1

        selected = _render_buyer_selector(orch, issue)

        typed = None
        buyer_entry_error = None
        if "enter" in issue.actions:
            ph = "Or type a different buyer name or email"
            typed = st.text_input(ph, key=_decision_key("buyer_txt"),
                                  placeholder=ph, label_visibility="collapsed")
            if typed:
                selected = None
                if "@" in typed:
                    import re as _re
                    _email = typed.strip()
                    _email_pat = _re.compile(
                        r'^[a-zA-Z][a-zA-Z0-9._%+\-]*'    # local part starts with a letter
                        r'@'
                        r'[a-zA-Z][a-zA-Z0-9\-]*'         # domain starts with a letter
                        r'(\.[a-zA-Z][a-zA-Z0-9\-]*)*'    # optional sub-domains
                        r'\.[a-zA-Z]{2,6}$'                # TLD: 2-6 letters
                    )
                    if not _email_pat.match(_email):
                        buyer_entry_error = "Please enter a valid email address (e.g. john.doe@company.com)."
                    elif len(_email) > 80:
                        buyer_entry_error = "Email address is too long."
            if buyer_entry_error:
                st.error(f"❌ {buyer_entry_error}")

        n_cols = 1 + (1 if "enter" in issue.actions else 0) \
                   + (1 if "reject" in issue.actions else 0) + 1
        cols = st.columns(n_cols)
        i = 0
        if cols[i].button("✅ Approve selected", key=_decision_key("buyer_ok"),
                          use_container_width=True,
                          disabled=selected is None):
            apply_issue_decision(orch, issue, "Picked", value=selected)
            orch["issue_ptr"] += 1
            st.rerun()
        i += 1
        if "enter" in issue.actions:
            if cols[i].button("✍️ Use my entry", key=_decision_key("buyer_use"),
                              use_container_width=True,
                              disabled=not typed or bool(buyer_entry_error)):
                apply_issue_decision(orch, issue, "Entered", value=typed)
                orch["issue_ptr"] += 1
                st.rerun()
            i += 1
        if "reject" in issue.actions:
            if cols[i].button("⛔ Reject", key=_decision_key("buyer_no"),
                              use_container_width=True):
                _intake_reject(orch, issue)
            i += 1
        if cols[i].button("📧 Notify to customer", key=_decision_key("buyer_esc"),
                          use_container_width=True):
            _intake_escalate(orch, issue)
        return

    # Multi-option decisions (ship-to / multi-match SKU): the CSR picks
    # ONE option with a radio button, optionally types a correction, then
    # approves. Replaces the old one-button-per-suggestion layout.
    if _uses_radio(issue):
        st.markdown("**Possible matches from master data — pick one:**")
        radio_key = _decision_key("radio")
        txt_key = _decision_key("radio_txt")
        idxs = list(range(len(issue.suggestions)))
        # Picking an option clears any typed correction, and vice-versa, so only
        # one CSR choice is ever active at a time.
        sel = st.radio(
            "options", options=idxs, index=None,
            format_func=lambda i: _radio_label_for(issue, issue.suggestions[i]),
            key=radio_key, label_visibility="collapsed",
            on_change=_reset_widget_state, args=(txt_key, ""),
        )
        selected = issue.suggestions[sel] if sel is not None else None

        typed = None
        entry_error = None
        if "enter" in issue.actions:
            if issue.kind in ("PARTIAL_SHIP_TO", "UNRESOLVED_SHIP_TO"):
                ph = "Or type a different ship-to address (include ZIP)"
            else:
                ph = "Or type a different SKU"
            typed = st.text_input(ph, key=txt_key,
                                  placeholder=ph, label_visibility="collapsed",
                                  on_change=_reset_widget_state, args=(radio_key, None))
            if typed:
                selected = None
            if typed and issue.kind in ("UNRESOLVED_SKU", "MISSING_SKU", "SUBSTITUTE_SKU"):
                entry_error = validate_manual_sku(
                    typed, orch["po"], issue.line_number, INTAKE_RESOLVER.products)
            if entry_error:
                st.error(f"❌ {entry_error}")

        cols = st.columns(4)
        i = 0
        if cols[i].button("✅ Approve selected", key=_decision_key("radio_ok"),
                          use_container_width=True,
                          disabled=selected is None):
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
        if cols[i].button("📧 Notify to customer", key=_decision_key("radio_esc"),
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
        if cols[3].button("📧 Notify to customer", key=_decision_key("uom_esc"), use_container_width=True):
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
    if cols[idx].button("📧 Notify to customer", key=_decision_key("intake_esc"), use_container_width=True):
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


def _decision_buttons(orch, what, exc_type, kind, reason="", auto_findings=None,
                      stage_key=None):
    """Shared Approve(override) / Reject / Escalate controls for a paused
    exception. `kind` is 'stage' or 'account' and drives the resume transition.

    `reason` is the master-data-derived explanation of WHY the AI paused for
    CSR approval; `auto_findings` lists what the AI already decided
    automatically from master data. Both are recorded in the audit trail."""
    po = orch.get("po")
    po_id = getattr(po, "po_number", "") if po is not None else ""
    scroll_to_csr_top(
        f"csr-stage-{po_id}-{orch.get('stage_index', 0)}-{exc_type}-{kind}"
    )
    # For PRICING_EXCEPTION the top banner already reads "CSR DECISION NEEDED —
    # PRICING_EXCEPTION", so this second banner would be redundant.
    if exc_type != "PRICING_EXCEPTION":
        agent = agent_name(stage_key).lower() if stage_key else "agent"
        st.warning(f"🟡  CSR DECISION NEEDED — the {agent} paused on this exception.")
    st.caption("Approve to override and continue, Reject to stop the order, or "
               "Notify to customer to route it to the responsible team.")
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
    if cols[2].button("📧 Notify to customer", key=_decision_key(kind + "_esc"), use_container_width=True):
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
                      "stage", reason=res.headline, auto_findings=list(res.audit_trail),
                      stage_key=getattr(res, "stage_key", None))


def _narrate_intake_review(orch, po):
    """Resolve intake issues and animate the intake-review narration.

    IMPORTANT: this is called in the SAME script run as the extraction
    animation so its status panel is appended *below* the extraction panel and
    the messages read in sequence. Previously the narration ran after a
    st.rerun(), so Streamlit reconciled the shorter narration panel onto the
    longer extraction panel at the same position and left stale extraction
    lines behind — which looked like later messages overriding earlier ones."""
    _issues, _bounds = _order_issues_by_agent(INTAKE_RESOLVER.resolve(po))
    orch["issues"] = _issues
    orch["bucket_bounds"] = _bounds
    orch["issue_ptr"] = 0
    n = len(orch["issues"])
    if n > 0:
        think(f"{AGENT_ICON} {agent_name('intake')} — intake review — action required", [
            (THINK_PACE, "🔎 Ran product catalog / lifecycle / UOM / "
                         "ship-to / buyer resolution against master data."),
            (THINK_PACE, f"⚠️ Found **{n} item(s)** that need CSR "
                         "confirmation before I continue."),
            (THINK_PACE, "🛑 **Downstream checks (compliance, inventory, "
                         "pricing, credit, logistics, order creation) "
                         "are paused** until each item is resolved."),
        ], icon="⚠️")
    else:
        think(f"{AGENT_ICON} {agent_name('intake')} — reviewing order against master data", [
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
    """Animate the Customer Validation layer as ONE agent panel.

    Customer identity + account/ship-to hierarchy AND buyer authorization (a
    sub-check of the same Customer Validation agent) run inside a SINGLE status
    panel, so the agent shows exactly one running panel during processing.

    Returns "pause" if it hit an exception that needs CSR input:
      * account exception  → phase set to 'account_pending',
      * buyer-auth exception → phase set to 'pipeline', orch['pending'] set.
    Otherwise builds the shared context, records the buyer-auth result, and
    returns None. Rendered inside the caller's chat_message so it streams in the
    same run as the layers before and after it."""
    po = orch["po"]
    _render_resolved_intake_cards(orch)
    # `first_pass` = the Customer Validation agent has not yet animated its
    # customer-identity checks. On the first pass we run identity resolution and,
    # if a buyer / ship-to decision is still pending, PAUSE right there so the
    # CSR decision surfaces DURING this agent's run (its result card is kept on
    # screen above the decision by render_orch_static). On re-entry (after the
    # decision) we skip identity and fold in buyer authorization.
    first_pass = not orch.get("account_identity_done")
    p_bound = orch["bucket_bounds"]["p"]
    pending_customer = orch.get("issue_ptr", 0) < p_bound

    account_steps = [
        (0.35, "🏢", "Resolving customer identity against customer master..."),
        (0.30, "🔗", "Checking ERP and CRM customer records..."),
        (0.35, "🧭", "Mapping corporate account hierarchy (parent › division › branch)..."),
        (0.30, "📍", "Validating ship-to location against ship-to master..."),
        (0.30, "🔍", "Confirming ship-to belongs to customer hierarchy..."),
        (0.30, "🏷️", "Reading customer tier, distributor classification & payment terms..."),
        (0.30, "📚", "Verifying customer buying history (tenure, volume, payment behaviour)..."),
        (0.30, "⚙️", "Determining applicable hierarchy-level rules..."),
        (0.25, "🧾", "Recording applied hierarchy level in audit trail..."),
        (0.35, "👤", "Looking up buyer email against Buyer Profiles master..."),
        (0.30, "🔐", "Mapping buyer → internal buyer ID + cost center and authorization..."),
    ]
    buyer_stage = _stage_by_key("buyer_authorization")
    av_holder = [orch.get("av")]
    buyer_holder = [None]
    _tag = agent_tag("account")
    _panel_label = (f"{_tag}  ·  Validating customer identity, hierarchy & buyer authorization..."
                    if first_pass else f"{_tag}  ·  Buyer authorization...")
    with st.status(_panel_label, expanded=True) as status:
        st.caption(f"{_tag} is handling this step.")
        # ── Part 1: customer identity + hierarchy (first pass only) ──────────
        if first_pass:
            render_systems_connect(systems_for("account"))
            for i, (delay, emoji, text) in enumerate(account_steps):
                st.write(f"{emoji} {text}")
                nap(paced_delay(delay))
                if i == 4 and av_holder[0] is None:
                    av_holder[0] = ACCOUNT_VALIDATOR.validate(po.customer_account,
                                                              po.ship_to_zip, po.company_name)
            if av_holder[0] is None:
                av_holder[0] = ACCOUNT_VALIDATOR.validate(po.customer_account,
                                                          po.ship_to_zip, po.company_name)
            orch["av"] = av_holder[0]
        av = av_holder[0]

        if av.is_exception:
            status.update(label=f"{_tag}  ·  Customer validation — action required",
                          state="complete", expanded=True)
        elif first_pass and pending_customer:
            # Identity check done and shown; a buyer / ship-to decision is still
            # pending. Pause the agent HERE so the CSR resolves it as part of
            # this Customer Validation run, then buyer authorization resumes.
            orch["account_identity_done"] = True
            status.update(
                label=f"{_tag}  ·  Customer validation — buyer / ship-to confirmation required",
                state="complete", expanded=True)
        else:
            # No pending customer decision (or resuming after one) → build the
            # shared context and fold buyer authorization (same agent) into THIS
            # panel as an indented sub-check.
            orch["ctx"] = build_context(po, av)
            render_systems_validated(systems_for("account"))
            if buyer_stage is not None:
                st.markdown(f"↳ **{buyer_stage.icon} {buyer_stage.title}**")
                render_systems_connect(systems_for("buyer_authorization"))
                for delay, emoji, text in buyer_stage.steps:
                    st.write(f"{emoji} {text}")
                    nap(paced_delay(delay))
                buyer_holder[0] = buyer_stage.validate(orch["ctx"])
                if not buyer_holder[0].is_exception:
                    render_systems_validated(systems_for("buyer_authorization"))
                # Flag so the pipeline loop skips buyer authorization (it has
                # already animated inside this Customer Validation panel).
                orch["buyer_auth_folded"] = True
            state_txt = ("action required"
                         if (buyer_holder[0] is not None and buyer_holder[0].is_exception)
                         else "complete")
            status.update(
                label=f"{_tag}  ·  Customer validation & buyer authorization — {state_txt}",
                state="complete", expanded=True)

    orch["account_identity_done"] = True
    av = av_holder[0]
    if av.is_exception:
        orch["phase"] = "account_pending"
        return "pause"

    # Identity done but a buyer / ship-to decision is pending → hand off to the
    # customer_issues phase so the decision renders below the (now static)
    # Customer Validation result card.
    if first_pass and pending_customer:
        orch["phase"] = "customer_issues"
        return "pause"

    buyer_res = buyer_holder[0]
    if buyer_res is not None and buyer_res.is_exception:
        # Route the buyer-auth gate through the standard stage-pending flow.
        # stage_index stays at buyer_authorization (index 0) so the resume path
        # appends the result and advances to product match.
        orch["pending"] = buyer_res
        orch["phase"] = "pipeline"
        return "pause"

    if buyer_res is not None:
        orch["ctx"].update(buyer_res.data or {})
        orch["results"].append(buyer_res)
    # Customer identity + buyer authorization both passed → announce success
    # before the pipeline agents begin (matches the settled transcript).
    _agent_success_banner("account")
    return None


def _run_pipeline_layers(orch):
    """Animate the downstream decision layers and order execution — every layer
    running to completion, one after another, in the current continuous run.

    Returns "pause" if a stage raised an exception that needs CSR input
    (orch['pending'] is set); otherwise sets phase to 'done' and returns None."""
    # 1) Sequential stages — each finishes before the next begins.
    while orch["stage_index"] < len(SEQUENTIAL_STAGES):
        stage = SEQUENTIAL_STAGES[orch["stage_index"]]
        # Product-line CSR decisions (obsolete SKU / UOM / SKU-not-found) are
        # owned by the Product Validation agent and are surfaced DURING its run:
        # the agent first animates its catalog / lifecycle / UOM scan (so the CSR
        # sees it executing), then pauses to surface the decisions its scan
        # found. After they are resolved the match is finalized (below) with the
        # resolved lines. The monotonic issue pointer reaching bounds['n'] clears
        # this gate.
        if (getattr(stage, "stage_key", None) == "product_match"
                and orch.get("issue_ptr", 0) < orch.get("bucket_bounds", {}).get("n", 0)):
            if not orch.get("product_scan_done"):
                _animate_agent_scan(stage)
                orch["product_scan_done"] = True
            orch["phase"] = "product_issues"
            return "pause"
        # Buyer authorization is normally folded into the Customer Validation
        # panel by _run_account_layer, so skip it here. (If an account exception
        # was overridden the fold never happened, so let it run standalone.)
        if (getattr(stage, "stage_key", None) == "buyer_authorization"
                and orch.get("buyer_auth_folded")):
            orch["stage_index"] += 1
            continue

        # Fold this agent's sub-checks (e.g. compliance under product match)
        # into the SAME panel so the agent shows only one running panel. When the
        # Product Validation scan already animated (before its CSR decisions), we
        # finalize the match without replaying the same steps.
        subs = _folded_subchecks(stage)
        _skip_steps = (getattr(stage, "stage_key", None) == "product_match"
                       and orch.get("product_scan_done"))
        res, folded = _run_stage_animation(stage, orch["ctx"], subchecks=subs,
                                           animate_steps=not _skip_steps)
        if res.is_exception:
            # OUT_OF_STOCK is a hard stop: the product has no stock in ANY
            # warehouse, so there is nothing a CSR can approve to continue. Stop
            # the order outright rather than opening an approve/override gate.
            if res.exception_type == "OUT_OF_STOCK":
                orch["results"].append(res)
                orch["decisions"].append({
                    "what": f"{res.title} — OUT_OF_STOCK",
                    "decision": "Order stopped",
                    "detail": "No stock available in any warehouse — order cannot be fulfilled.",
                    "reason": res.headline,
                    "auto": list(res.audit_trail)})
                orch["terminal"] = ("stopped", res.headline)
                orch["phase"] = "terminal"
                return "pause"
            orch["pending"] = res
            return "pause"
        orch["ctx"].update(res.data or {})
        orch["results"].append(res)
        orch["stage_index"] += 1

        # Record the folded sub-checks (they already animated in the panel
        # above). A sub-check exception opens the standard CSR gate; the resume
        # path appends it and advances past its slot.
        for sub_res in folded:
            if sub_res.is_exception:
                orch["pending"] = sub_res
                return "pause"
            orch["ctx"].update(sub_res.data or {})
            orch["results"].append(sub_res)
            orch["stage_index"] += 1
        # This agent (and any folded sub-checks) passed → success banner before
        # the next agent begins. Matches the settled transcript render.
        if getattr(stage, "stage_key", None) not in _SKIP_SUCCESS_BANNER:
            _agent_success_banner(getattr(stage, "stage_key", None))
        nap(paced_delay(0.35))

    # 2) Order execution.
    ex, _ = _run_stage_animation(EXECUTION, orch["ctx"])
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
                source_label = f"Excel: {fname}"
            else:
                orch["source_label"] = "PO text"
                raw_text = orch["payload"]
                source_label = "PO Text"

            # Single intake process: read + extract AND review against master
            # data inside ONE panel. Sets orch po / is_dup / dup_rec / issues.
            po = run_intake(orch, raw_text, source_label)
            if orch["kind"] == "excel":
                po.source_type = "EXCEL"

            # Dup / missing-field POs need an escalation card → hand off with a
            # rerun (no downstream processing).
            if orch["is_dup"] or po.missing_fields:
                orch["phase"] = "intake_review"
                st.rerun()

            # Flagged items need CSR confirmation, surfaced during the owning
            # agent's run. Route to the earliest bucket that has issues; the
            # per-phase drivers advance the monotonic pointer and hand off to the
            # next agent. (Product-line issues surface inside the pipeline, so a
            # PO with only product issues goes to the account phase first.)
            b = orch["bucket_bounds"]
            if b["c"] > 0:
                orch["phase"] = "intake_issues"
                st.rerun()

            # No intake-level decision → keep streaming in THIS SAME run so the
            # Customer Validation agent's process appears immediately AFTER the
            # "Intake completed" message (no rerun gap between the two agents).
            # The Customer Validation agent animates its identity checks and, if a
            # buyer / ship-to decision is pending, _run_account_layer sets the
            # phase to 'customer_issues' and returns "pause" so the decision
            # surfaces on the next run — as part of that agent's run. Every
            # downstream decision layer then streams one after another with no
            # rerun replacing a panel in between.
            if _run_account_layer(orch) == "pause":
                st.rerun()                       # account exception / buyer decision → CSR
            orch["phase"] = "pipeline"           # so a stage pause resumes here
            if _run_pipeline_layers(orch) == "pause":
                st.rerun()                       # stage / product decision → CSR
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
                if st.button("📧 Notify to customer",
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
                if st.button("📧 Notify to customer", key="intake_missing_esc"):
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

    # ---- intake_issues: Intake Agent's decisions (quantity) ----
    elif phase == "intake_issues":
        with st.chat_message("assistant"):
            # Re-render every already-resolved intake decision card FIRST
            # so the current decision card / next stage always appears
            # BELOW the button the CSR just clicked (chronological order).
            _render_resolved_intake_cards(orch)
            c = orch["bucket_bounds"]["c"]
            if orch["issue_ptr"] < c:
                # Wrap the ACTIVE decision card in a keyed container. The key
                # changes with issue_ptr, so when the CSR resolves this card
                # Streamlit removes the entire container (impact table +
                # button row) instead of trying to diff a container whose
                # element count changed — which could leave the old table /
                # buttons lingering in the browser.
                with st.container(key=f"active_issue_{orch['issue_ptr']}"):
                    render_intake_issue(orch, orch["issues"][orch["issue_ptr"]])
                return   # wait for CSR
        # Intake decisions done → hand off to the Customer Validation agent. It
        # animates its identity checks first, then surfaces any buyer / ship-to
        # decision as part of that run. Re-engage auto-follow so the resuming
        # animation is tracked down the page (the transient rerun below would
        # otherwise consume the flag before the animation starts).
        st.session_state.reengage_scroll = True
        orch["phase"] = "account"
        st.rerun()

    # ---- customer_issues: Customer Validation Agent's decisions (buyer/ship-to)
    #      surfaced BEFORE the customer-validation animation so the resolved
    #      buyer / ship-to feed the account layer + shared context. ----
    elif phase == "customer_issues":
        with st.chat_message("assistant"):
            _render_resolved_intake_cards(orch)
            p = orch["bucket_bounds"]["p"]
            if orch["issue_ptr"] < p:
                with st.container(key=f"active_issue_{orch['issue_ptr']}"):
                    render_intake_issue(orch, orch["issues"][orch["issue_ptr"]])
                return   # wait for CSR
        # Buyer / ship-to resolved → resume the Customer Validation agent. Keep
        # auto-follow engaged so the resuming animation is tracked down the page.
        st.session_state.reengage_scroll = True
        orch["phase"] = "account"
        st.rerun()

    # ---- product_issues: Product Matching Agent's decisions (obsolete SKU /
    #      UOM / SKU-not-found) surfaced as Product Match runs. Resolved lines
    #      are folded back into the shared context before matching continues. ----
    elif phase == "product_issues":
        with st.chat_message("assistant"):
            _render_resolved_intake_cards(orch)
            n = orch["bucket_bounds"]["n"]
            if orch["issue_ptr"] < n:
                # Persistent Product Validation context: the live scan panel is
                # transient (gone after this rerun), so re-render the agent's
                # completed scan here so the product-line decision clearly reads
                # as the RESULT of THIS agent's run rather than appearing on its
                # own with no visibility that the agent executed.
                #
                # The whole decision UI lives in a uniquely-keyed container so
                # that when the pipeline resumes (a DIFFERENTLY-keyed container),
                # Streamlit REMOVES this subtree wholesale instead of positionally
                # reusing its st.status / widgets — otherwise the resolved card
                # lingers and the finalize panel bleeds into the old scan panel.
                with st.container(key=f"product_decision_{orch['issue_ptr']}"):
                    st.markdown("### 📦 Product Validation")
                    render_agent_badge("product_match")
                    _render_product_scan_panel_static()
                    render_intake_issue(orch, orch["issues"][orch["issue_ptr"]])
                return   # wait for CSR
            # All product-line decisions captured → refresh the pipeline context
            # from the (now-resolved) PO order lines before Product Match runs.
            po = orch.get("po")
            if orch.get("ctx") is not None and po is not None:
                orch["ctx"]["order_lines"] = [
                    {"line_number": l.line_number, "sku": l.sku,
                     "quantity": l.quantity, "uom": l.uom,
                     "description": l.description}
                    for l in po.order_lines
                ]
        # Product decisions resolved → rerun into the 'pipeline' phase to stream
        # the finalize + downstream agents. We DELIBERATELY rerun (rather than
        # streaming inline here) so Streamlit prunes the just-resolved decision
        # card's widgets (selectbox + buttons) at a clean rerun boundary — inline
        # streaming in the same 'product_issues' phase leaves the old card
        # lingering on screen for several seconds while new panels render ABOVE
        # it, so the next process does not appear next to the approve button.
        # apply_issue_decision already set reengage_scroll, so the forced-follow
        # burst tracks the resuming pipeline down the page.
        st.session_state.reengage_scroll = True
        orch["phase"] = "pipeline"
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
                                  auto_findings=list(orch["av"].audit_trail),
                                  stage_key=getattr(orch["av"], "stage_key", "account"))
        return

    # ---- pipeline: decision layers  +  execution ----
    # IMPORTANT: these logical phases run in ONE continuous script run.
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
            # Keep every already-actioned CSR decision card on screen (buyer,
            # obsolete SKU, UOM, …) so the resuming pipeline animation streams
            # directly BELOW them — the next process appears right after the
            # decision the CSR just approved, in natural reading order.
            _render_resolved_intake_cards(orch)
            if orch["pending"] is not None:
                with st.container(key=f"active_stage_pending_{orch['stage_index']}"):
                    render_pending_exception(orch, orch["pending"])
                return
            # Resume the downstream layers (after a CSR override or an account
            # exception was cleared). Runs to completion in this continuous run.
            # Stream inside a uniquely-keyed container that never existed in the
            # 'product_issues' decision render, so Streamlit mounts these panels
            # FRESH (and prunes the old decision subtree) instead of reusing its
            # st.status node — this is what makes the resuming process appear
            # cleanly right where the CSR clicked, with no lingering card.
            with st.container(key="pipeline_resume_stream"):
                if _run_pipeline_layers(orch) == "pause":
                    st.rerun()                   # next stage exception → CSR
        st.rerun()                               # phase == 'done'

    # ---- terminal states ----
    elif phase == "done":
        with st.chat_message("assistant"):
            order_no = (orch.get("ctx") or {}).get("order_number") or "—"
            st.success(f"🎉 Order number {order_no} created successfully. "
                       "Customer notification emails has been forwarded.")
    elif phase == "terminal":
        with st.chat_message("assistant"):
            kind, msg = orch["terminal"]
            if kind == "rejected":
                st.error("⛔ **Order stopped.** " + md_safe(msg))
            elif kind == "stopped":
                st.error("⛔ **Order stopped — product unavailable.** " + md_safe(msg))
                st.caption("The requested product has no stock in any warehouse, so the order "
                           "cannot be fulfilled. Escalated to Procurement / Planning for "
                           "replenishment.")
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
if "show_email"     not in st.session_state: st.session_state.show_email     = False
if "email_flow"     not in st.session_state: st.session_state.email_flow     = None
if "email_results"  not in st.session_state: st.session_state.email_results  = None

WELCOME_TEXT = (
    "👋 **Hello! I am your order assistant.**\n\n"
    "Paste a Purchase Order below, or click **➕** to upload an Excel PO "
    "(`.xlsx` / `.xls`). I will read it, resolve it against master data, and "
    "work through customer, product, inventory, pricing, credit and logistics "
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
        # A CSR decision card is on screen (and awaiting input) whenever any of
        # the per-agent issue phases still has an unresolved issue. Auto-follow
        # must RELEASE in that case so the card stays put and stays clickable.
        _issue_waiting = (
            _ph in ("intake_issues", "customer_issues", "product_issues")
            and _orch.get("issue_ptr", 0) < _orch.get("bucket_bounds", {}).get("n", 0)
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
        # A CSR decision banner is on screen whenever a per-agent issue is
        # waiting or a stage / account exception is pending — in those cases
        # scroll_to_csr_top() positions the viewport on the banner, so the idle
        # scroll-to-bottom must be suppressed (otherwise the two fight and the
        # page visibly scrolls 2–3 times before landing on the banner).
        _csr_banner = (
            _issue_waiting or _pipeline_waiting or _ph == "account_pending"
        )
        inject_autoscroll(active=not _waiting, force_follow=_reengage,
                          suppress_idle_scroll=_csr_banner)
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

# ─── Outlook email PO panel (shown when 📧 clicked) ──────────────────────────
if EMAIL_INTAKE_ENABLED and st.session_state.show_email:
    with st.container(border=True):
        st.markdown("#### 📧 Read Purchase Order from Outlook")
        cfg = email_intake.get_config()

        if not email_intake.is_configured():
            st.warning(
                "**Outlook connection is not configured yet.**\n\n"
                "To read POs straight from your mailbox, this needs a Microsoft "
                "Entra app registration (from EY IT) with the delegated "
                "**`Mail.Read`** permission. Then create a `.env` file "
                "(see `.env.example`) with:\n\n"
                "- `GRAPH_CLIENT_ID` — the app's Application (client) ID\n"
                "- `GRAPH_TENANT_ID` — your EY tenant (directory) ID\n"
                "- `PO_SUBJECT_KEYWORD` — subject keyword, e.g. `purchase order`\n\n"
                "Restart the app after saving `.env`."
            )
        else:
            token = None
            try:
                token = email_intake.acquire_token_silent(cfg["client_id"], cfg["tenant_id"])
            except email_intake.EmailIntakeError as e:
                st.error(str(e))

            # ── Step 1: not signed in and no active device-code flow ──────────
            if token is None and st.session_state.email_flow is None:
                st.caption("You need to sign in to your EY mailbox once. A code-based "
                           "sign-in will open — no password is stored by this app.")
                if st.button("🔐 Connect to Outlook", key="email_connect"):
                    try:
                        st.session_state.email_flow = email_intake.begin_device_flow(
                            cfg["client_id"], cfg["tenant_id"])
                    except email_intake.EmailIntakeError as e:
                        st.error(str(e))
                    st.rerun()

            # ── Step 2: device-code flow in progress ─────────────────────────
            elif token is None and st.session_state.email_flow is not None:
                flow = st.session_state.email_flow
                st.info(flow.get("message", "Follow the sign-in instructions."))
                st.markdown(
                    f"1. Open **{flow.get('verification_uri', 'https://microsoft.com/devicelogin')}**  \n"
                    f"2. Enter code **`{flow.get('user_code', '')}`**  \n"
                    "3. Complete sign-in with your EY account, then click below."
                )
                c1, c2 = st.columns([1, 1])
                with c1:
                    if st.button("✅ I've completed sign-in", key="email_complete"):
                        try:
                            email_intake.complete_device_flow(
                                cfg["client_id"], cfg["tenant_id"], flow)
                            st.session_state.email_flow = None
                        except email_intake.EmailIntakeError as e:
                            st.error(str(e))
                        st.rerun()
                with c2:
                    if st.button("Cancel sign-in", key="email_cancel_flow"):
                        st.session_state.email_flow = None
                        st.rerun()

            # ── Step 3: signed in — fetch & pick a PO email ──────────────────
            else:
                st.success(f"Connected. Searching Inbox for subject containing "
                           f"**“{cfg['subject_keyword']}”**.")
                if st.button("🔎 Fetch latest PO emails", key="email_fetch"):
                    try:
                        st.session_state.email_results = email_intake.fetch_po_emails(
                            token, cfg["subject_keyword"])
                    except email_intake.EmailIntakeError as e:
                        st.error(str(e))
                        st.session_state.email_results = None
                    st.rerun()

                results = st.session_state.email_results
                if results is not None:
                    if not results:
                        st.info("No matching PO emails found in your Inbox.")
                    else:
                        labels = [
                            f"{e.subject}  ·  {e.sender}  ·  {e.received_label}"
                            for e in results
                        ]
                        idx = st.selectbox(
                            "Select a PO email to process",
                            range(len(results)),
                            format_func=lambda i: labels[i],
                            key="email_pick",
                        )
                        chosen = results[idx]
                        with st.expander("Preview email body"):
                            st.text(chosen.body_text[:2000] or "(empty body)")
                        if st.button("▶️ Process this PO", key="email_process"):
                            new_orchestration("text", chosen.body_text)
                            st.session_state.welcomed = True
                            st.session_state.show_email = False
                            st.session_state.email_results = None
                            st.rerun()

        if st.button("✖ Close", key="close_email"):
            st.session_state.show_email = False
            st.rerun()

# ─── Bottom input row ─────────────────────────────────────────────────────────
if EMAIL_INTAKE_ENABLED:
    col_plus, col_mail, col_hint = st.columns([1, 1, 9])
    with col_plus:
        if st.button("➕", help="Upload an Excel PO file (.xlsx / .xls only)",
                     use_container_width=True):
            st.session_state.show_upload = not st.session_state.show_upload
            st.rerun()
    with col_mail:
        if st.button("📧", help="Read a PO directly from your Outlook inbox",
                     use_container_width=True):
            st.session_state.show_email = not st.session_state.show_email
            st.rerun()
    with col_hint:
        st.caption("**➕** upload Excel PO  |  **📧** read PO from Outlook  |  or paste text below")
else:
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

