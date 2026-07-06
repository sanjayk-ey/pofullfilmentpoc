"""
_test_csr_scenarios.py
End-to-end verification of EVERY CSR human-in-the-loop approval scenario in the
Autonomous PO-to-Fulfillment Orchestration, driven exactly the way the Streamlit
app does: extract -> intake resolve -> account validation -> sequential pipeline.

For each scenario we report:
  * where the agent paused (intake issue kind, or pipeline stage + exception),
  * whether it is an INTERACTIVE CSR gate (Approve/Reject/Escalate) vs an
    automatic route-to-approver email (hard stop),
  * the escalation target.

Run:  python _test_csr_scenarios.py
"""
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from modules.extractor import POExtractor
from modules.intake_resolver import IntakeResolver
from modules.account_validator import AccountValidator
from modules.pipeline import build_context, run_orchestration
from modules import duplicate_checker as dup

# Reuse the app's escalation routing + interactive check semantics.
import app  # noqa: E402  (app import triggers Streamlit but harmless headless)

EXTRACTOR = POExtractor()
RESOLVER = IntakeResolver()
ACCOUNT = AccountValidator()

_results = []


def check(name, cond, detail=""):
    _results.append((name, bool(cond)))
    flag = "PASS" if cond else "FAIL"
    print(f"  [{flag}] {name}" + (f"  -> {detail}" if detail else ""))


def po_text(po_number, company, email, shipto, delivery, lines):
    ship_block = "\n".join(shipto)
    line_rows = "\n".join(
        f"{i+1:<6} | {code:<14} | {desc:<34} | {qty:>5}"
        for i, (code, desc, qty) in enumerate(lines)
    )
    return f"""================================================================================
                                PURCHASE ORDER
================================================================================
PO Number   : {po_number}
PO Date     : 01 July 2026

BUYER
Company Name : {company}
Email        : {email}

SHIP TO
{ship_block}

Requested Delivery Date : {delivery}

ORDER LINES
Item # | Product Code   | Description                        |   Qty
-------+----------------+------------------------------------+------
{line_rows}
================================================================================
"""


def auto_apply(po):
    """Mirror a CSR accepting the AI's recommendation for every intake issue,
    so the run can proceed to the decision pipeline (used only for scenarios
    that target a DOWNSTREAM stage, not the intake gate itself)."""
    for issue in RESOLVER.resolve(po):
        rec = issue.recommended or (issue.suggestions[0] if issue.suggestions else None)
        for ln in po.order_lines:
            if ln.line_number != issue.line_number:
                continue
            if issue.kind in ("SUBSTITUTE_SKU",) and rec:
                ln.sku = rec.get("substitute_sku") or ln.sku
                ln.description = rec.get("substitute_description") or ln.description
            elif issue.kind in ("UNRESOLVED_SKU", "MISSING_SKU") and rec:
                ln.sku = rec.get("sku") or ln.sku
                ln.description = ln.description or rec.get("description")
            elif issue.kind == "UOM_AMBIGUOUS":
                choice = rec or {}
                ln.uom = choice.get("uom")
                if choice.get("qty_base"):
                    ln.quantity = choice["qty_base"]
        if issue.kind in ("PARTIAL_SHIP_TO", "UNRESOLVED_SHIP_TO") and rec:
            if rec.get("zip"):
                po.ship_to_zip = rec["zip"]
                po.ship_to_name = rec.get("name") or po.ship_to_name


def run_full(text, resolve_intake=False, register_first=False):
    """Return a dict describing where/how the run paused."""
    po = EXTRACTOR.extract_from_text(text)
    out = {"po": po, "intake_issues": [], "stage": None, "exc": None,
           "interactive": None, "escalation": None, "missing": po.missing_fields}

    is_dup, _ = dup.check(po.po_number, po.customer_account)
    if is_dup:
        out["stage"] = "duplicate"
        out["exc"] = "DUPLICATE_PO"
        out["interactive"] = False   # auto-reject, escalate only
        out["escalation"] = app.escalation_target("DUPLICATE_PO")
        return out
    if register_first and po.po_number:
        dup.register(po.po_number, po.customer_account, "sess")

    if po.missing_fields:
        out["stage"] = "intake_missing"
        return out

    issues = RESOLVER.resolve(po)
    if issues and not resolve_intake:
        out["intake_issues"] = issues
        first = issues[0]
        out["stage"] = "intake"
        out["exc"] = first.kind
        out["interactive"] = True
        out["escalation"] = app.escalation_target(first.kind)
        return out
    if resolve_intake:
        auto_apply(po)

    av = ACCOUNT.validate(po.customer_account, po.ship_to_zip, po.company_name)
    if av.is_exception:
        out["stage"] = "account"
        out["exc"] = av.exception_type
        out["interactive"] = True
        out["escalation"] = app.escalation_target(f"ACCOUNT_{av.exception_type}")
        return out

    ctx = build_context(po, av)
    results = run_orchestration(ctx)
    exc = next((r for r in results if r.is_exception), None)
    out["results"] = results
    if exc:
        out["stage"] = exc.stage_key
        out["exc"] = exc.exception_type
        # Interactive when the stage does NOT set a route-to-approver email.
        out["interactive"] = not bool((exc.data or {}).get("approval_email_sent_to"))
        out["escalation"] = app.escalation_target(exc.exception_type)
    return out


# ══════════════════════════════════════════════════════════════════════════════
CHI = ["Great Lakes Plumbing - Chicago DC", "4500 West Diversey Avenue",
       "Chicago, IL 60639"]


def main():
    dup.reset_store()

    print("\n=== INTAKE CSR GATES ===")

    # 1. Missing / unresolved buyer
    dup.reset_store()
    r = run_full(po_text("PO-CSR-BUYER", "Great Lakes Plumbing Supply Co",
                         "nobody@nowhere.com", CHI, "24 July 2026",
                         [("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 100)]))
    check("1. Unresolved buyer -> UNRESOLVED_BUYER (interactive)",
          r["exc"] == "UNRESOLVED_BUYER" and r["interactive"], f"{r['exc']}")

    # 2. Partial ship-to (name only)
    dup.reset_store()
    r = run_full(po_text("PO-CSR-SHIP", "Great Lakes Plumbing Supply Co",
                         "john.miller@glps.com", ["Great Lakes Plumbing - Chicago DC"],
                         "24 July 2026",
                         [("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 100)]))
    check("2. Partial ship-to -> PARTIAL_SHIP_TO (interactive)",
          r["exc"] == "PARTIAL_SHIP_TO" and r["interactive"], f"{r['exc']}")

    # 3. Missing SKU (description + qty only)
    dup.reset_store()
    r = run_full(po_text("PO-CSR-MISSING", "Great Lakes Plumbing Supply Co",
                         "john.miller@glps.com", CHI, "24 July 2026",
                         [("", "Tank-to-Bowl Gasket Kit", 50)]))
    check("3. Missing SKU -> MISSING_SKU (interactive)",
          r["exc"] == "MISSING_SKU" and r["interactive"], f"{r['exc']}")

    # 4. Wrong / invalid SKU code
    dup.reset_store()
    r = run_full(po_text("PO-CSR-WRONG", "Great Lakes Plumbing Supply Co",
                         "john.miller@glps.com", CHI, "24 July 2026",
                         [("PN-DRAIN-STD", "Pop-Up Drain Assembly", 30)]))
    check("4. Wrong SKU -> UNRESOLVED_SKU (interactive)",
          r["exc"] == "UNRESOLVED_SKU" and r["interactive"], f"{r['exc']}")

    # 5. Zero quantity
    dup.reset_store()
    r = run_full(po_text("PO-CSR-QTY", "Great Lakes Plumbing Supply Co",
                         "john.miller@glps.com", CHI, "24 July 2026",
                         [("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 0)]))
    check("5. Zero qty -> INVALID_QUANTITY (interactive)",
          r["exc"] == "INVALID_QUANTITY" and r["interactive"], f"{r['exc']}")

    # 6. Duplicate PO (auto-reject, escalate only)
    dup.reset_store()
    txt = po_text("PO-CSR-DUP", "Great Lakes Plumbing Supply Co",
                  "john.miller@glps.com", CHI, "24 July 2026",
                  [("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 100)])
    run_full(txt, register_first=True)              # first submission registers it
    r = run_full(txt)                               # second submission = duplicate
    check("6. Duplicate PO -> DUPLICATE_PO (auto-reject, NOT interactive)",
          r["exc"] == "DUPLICATE_PO" and r["interactive"] is False, f"{r['exc']}")
    check("6b. Duplicate PO escalates to Duplicate/Order Ops",
          r["escalation"] and "Order" in r["escalation"], r["escalation"])

    print("\n=== PRODUCT MATCH CSR GATE ===")
    # 7. Obsolete SKU substitution
    dup.reset_store()
    r = run_full(po_text("PO-CSR-OBS", "Great Lakes Plumbing Supply Co",
                         "john.miller@glps.com", CHI, "24 July 2026",
                         [("SKU-CTG-1000", "Legacy 2-Handle Faucet Cartridge", 10)]))
    sub = next((i for i in r["intake_issues"] if i.kind == "SUBSTITUTE_SKU"), None)
    check("7. Obsolete SKU -> SUBSTITUTE_SKU (interactive)",
          r["exc"] == "SUBSTITUTE_SKU" and r["interactive"], f"{r['exc']}")
    check("7b. Substitution actions = Approve/Modify/Escalate (no Reject)",
          sub and set(sub.actions) == {"approve", "enter", "escalate"},
          str(sub.actions) if sub else "none")

    print("\n=== PRICING & PROMO CSR GATE ===")
    # 8. Pricing exception (discount over policy)
    dup.reset_store()
    r = run_full(po_text("PO-CSR-PRICE", "Great Lakes Plumbing Supply Co",
                         "john.miller@glps.com", CHI, "24 July 2026",
                         [("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 2000)]),
                 resolve_intake=True)
    check("8. High discount -> PRICING_EXCEPTION at pricing stage",
          r["stage"] == "pricing" and r["exc"] == "PRICING_EXCEPTION", f"{r['stage']}/{r['exc']}")
    check("8b. Pricing gate is INTERACTIVE (Approve exception/Reject/Escalate)",
          r["interactive"] is True, str(r["interactive"]))
    check("8c. Pricing escalates to Pricing Desk",
          r["escalation"] == "Pricing Desk", r["escalation"])

    print("\n=== CREDIT CSR GATE ===")
    # 9. Credit hold (overdue invoices / over limit)
    dup.reset_store()
    r = run_full(po_text("PO-CSR-CREDIT", "Eastern Kitchen & Bath Distributors",
                         "mark.snow@ekbd.com",
                         ["Eastern Kitchen & Bath - New York DC",
                          "55 Water Street", "New York, NY 10001"],
                         "24 July 2026",
                         [("SKU-SEL-1150", "Tank-to-Bowl Gasket Kit", 50)]),
                 resolve_intake=True)
    check("9. Credit-risk customer -> CREDIT_HOLD at credit stage",
          r["exc"] == "CREDIT_HOLD", f"{r['stage']}/{r['exc']}")
    check("9b. Credit gate is INTERACTIVE (Approve override/Escalate to Finance)",
          r["interactive"] is True, str(r["interactive"]))
    check("9c. Credit escalates to Finance / Credit Team",
          r["escalation"] and "Finance" in r["escalation"], r["escalation"])

    print("\n=== INVENTORY CSR GATE ===")
    # 10. Inventory shortage
    dup.reset_store()
    r = run_full(po_text("PO-CSR-INV", "Great Lakes Plumbing Supply Co",
                         "john.miller@glps.com", CHI, "24 July 2026",
                         [("SKU-SHS-7700", "Shower System", 10)]),
                 resolve_intake=True)
    check("10. Low stock -> INVENTORY_SHORTAGE at inventory stage",
          r["stage"] == "inventory" and r["exc"] == "INVENTORY_SHORTAGE",
          f"{r['stage']}/{r['exc']}")
    check("10b. Inventory gate is INTERACTIVE (Approve partial/Escalate)",
          r["interactive"] is True, str(r["interactive"]))

    print("\n=== LOGISTICS CSR GATE ===")
    # 11. ZIP not serviceable
    dup.reset_store()
    r = run_full(po_text("PO-CSR-ZIP", "Great Lakes Plumbing Supply Co",
                         "john.miller@glps.com",
                         ["Great Lakes - Ketchikan Project Site",
                          "1 Industrial Rd", "Ketchikan, AK 99950"],
                         "24 July 2026",
                         [("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 100)]),
                 resolve_intake=True)
    check("11. Unserviceable ZIP -> ZIP_NOT_SERVICEABLE at logistics stage",
          r["stage"] == "logistics" and r["exc"] == "ZIP_NOT_SERVICEABLE",
          f"{r['stage']}/{r['exc']}")
    check("11b. Logistics gate is INTERACTIVE (Approve alternate/Escalate)",
          r["interactive"] is True, str(r["interactive"]))

    print("\n=== APPROVAL ROUTING (auto route-to-approver) ===")
    # 12. Order value over self-approval limit -> Approval layer routes to approver
    dup.reset_store()
    r = run_full(po_text("PO-CSR-APPR", "Great Lakes Plumbing Supply Co",
                         "john.miller@glps.com", CHI, "24 July 2026",
                         [("SKU-SEL-1150", "Tank-to-Bowl Gasket Kit", 60000)]),
                 resolve_intake=True)
    check("12. Large order routes at Approval layer (APPROVAL_REQUIRED/BUDGET_EXCEEDED)",
          r["exc"] in ("APPROVAL_REQUIRED", "BUDGET_EXCEEDED"),
          f"{r['stage']}/{r['exc']}")

    print("\n=== STRATEGIC CUSTOMER (Customer Validation display) ===")
    # 13. Strategic customer standing shown (happy path, no pause)
    dup.reset_store()
    av = ACCOUNT.validate("CUST-1001", "60639")
    check("13. Strategic tier + distributor + buying history available",
          (av.customer or {}).get("customer_tier") == "Strategic"
          and bool(av.buying_history),
          f"tier={(av.customer or {}).get('customer_tier')}, bh={bool(av.buying_history)}")

    print("\n=== HAPPY PATH (no CSR pause) ===")
    dup.reset_store()
    r = run_full(po_text("PO-CSR-HAPPY", "Great Lakes Plumbing Supply Co",
                         "john.miller@glps.com", CHI, "24 July 2026",
                         [("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 100),
                          ("SKU-SEL-1150", "Tank-to-Bowl Gasket Kit", 120),
                          ("SKU-VLV-2201", "Pressure-Balancing Shower Valve", 15)]),
                 resolve_intake=True)
    check("14. Happy path completes with NO exception",
          r["exc"] is None, f"{r['stage']}/{r['exc']}")

    passed = sum(1 for _, ok in _results if ok)
    total = len(_results)
    print(f"\n{passed}/{total} CSR-scenario checks passed.")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
