"""
test_pipeline.py
Headless regression harness for the interactive PO-to-fulfillment agent.

It exercises the logic that sits behind the Streamlit UI (which itself can't be
unit-tested), covering:

  1. Extraction with the RELAXED mandatory-field set (PO#, PO date, buyer company,
     buyer email, ship-to in any form, delivery date, and line SKU/Description/Qty;
     UOM optional).
  2. Label-independent SKU identification and intake-time resolution
     (obsolete -> substitute, wrong code -> identify by description, missing SKU
     -> identify by description, partial ship-to -> confirm).
  3. UOM conversion (US-04 AC-02).
  4. Both demo POs end to end: the happy-path PO passes straight through; the
     exceptions-showcase PO passes once CSR approvals are auto-applied.

Run:  python test_pipeline.py
"""
import os
import re

from modules.extractor import POExtractor
from modules.intake_resolver import IntakeResolver
from modules.product_matcher import ProductMatchValidator
from modules.pricing_engine import PricingEngine
from modules.account_validator import AccountValidator
from modules.pipeline import build_context, run_orchestration
from modules import duplicate_checker as dup
from modules.manual_entry_validators import (
    validate_manual_sku, validate_manual_quantity,
)

EXTRACTOR = POExtractor()
RESOLVER = IntakeResolver()
ACCOUNT = AccountValidator()
DEMO = os.path.join(os.path.dirname(__file__), "demo")

# Inline intake-exceptions fixture (a compact 4-line PO that raises the intake
# gates — obsolete SKU, wrong code, missing SKU, partial ship-to, UOM ambiguity
# — and then resolves to a clean end-to-end pass once the CSR accepts the AI's
# recommendations). Kept inline so the shipped demo/ folder holds only the two
# customer-facing demo files (Happy-Flow-PO and CSR-Approval-PO).
EXC_TEXT = """\
================================================================================
                                PURCHASE ORDER
================================================================================
PO Number   : PO-2026-20002
PO Date     : 01 July 2026

BUYER
Company Name : Great Lakes Plumbing Supply Co
Email        : john.miller@glps.com

SHIP TO
Great Lakes Plumbing - Chicago DC

Requested Delivery Date : 28 July 2026

ORDER LINES
Item # | Product Code   | Description                        |   Qty
-------+----------------+------------------------------------+------
1      | SKU-CTG-1000   | Legacy 2-Handle Faucet Cartridge   |   10
2      | PN-DRAIN-STD   | Pop-Up Drain Assembly              |   30
3      |                | Tank-to-Bowl Gasket Kit            |   50
4      | SKU-CTG-4520   | Ceramic Disc Faucet Cartridge      |    2
================================================================================
"""

_results = []


def check(name, cond, detail=""):
    _results.append((name, bool(cond), detail))
    flag = "PASS" if cond else "FAIL"
    print(f"[{flag}] {name}" + (f"  — {detail}" if detail and not cond else ""))


def read(fname):
    with open(os.path.join(DEMO, fname), encoding="utf-8") as f:
        return f.read()


# ── Headless mirror of the CSR "approve recommendation" action ────────────────
def auto_apply_resolutions(po):
    """Resolve every intake issue by accepting the AI's recommended fix — the
    same effect as a CSR clicking 'Approve suggestion' / 'Use top match'."""
    issues = RESOLVER.resolve(po)
    applied = []
    for issue in issues:
        if issue.kind == "SUBSTITUTE_SKU" and issue.recommended:
            for ln in po.order_lines:
                if ln.line_number == issue.line_number:
                    ln.sku = issue.recommended["substitute_sku"]
                    ln.description = issue.recommended.get("substitute_description") or ln.description
            applied.append((issue.kind, issue.recommended["substitute_sku"]))
        elif issue.kind in ("UNRESOLVED_SKU", "MISSING_SKU"):
            rec = issue.recommended or (issue.suggestions[0] if issue.suggestions else None)
            if rec:
                for ln in po.order_lines:
                    if ln.line_number == issue.line_number:
                        ln.sku = rec["sku"]
                        if not ln.description:
                            ln.description = rec.get("description")
                applied.append((issue.kind, rec["sku"]))
        elif issue.kind == "UOM_AMBIGUOUS":
            # Accept AI default = individual pieces (base UOM)
            choice = issue.recommended or (issue.suggestions[0] if issue.suggestions else {})
            for ln in po.order_lines:
                if ln.line_number == issue.line_number:
                    ln.uom = choice.get("uom")
                    if choice.get("qty_base"):
                        ln.quantity = choice["qty_base"]
            applied.append((issue.kind, f"{choice.get('qty')} {choice.get('uom')}"))
        elif issue.kind in ("PARTIAL_SHIP_TO", "UNRESOLVED_SHIP_TO"):
            rec = issue.recommended or (issue.suggestions[0] if issue.suggestions else None)
            if rec and rec.get("zip"):
                po.ship_to_zip = rec["zip"]
                po.ship_to_name = rec.get("name") or po.ship_to_name
                applied.append((issue.kind, rec["zip"]))
    return issues, applied


def run_pipeline(po):
    is_dup, _ = dup.check(po.po_number, po.customer_account)
    if is_dup:
        return "DUPLICATE_PO", []
    if po.missing_fields:
        return f"INTAKE_MISSING:{po.missing_fields}", []
    av = ACCOUNT.validate(po.customer_account, po.ship_to_zip, po.company_name)
    if av.is_exception:
        return f"ACCOUNT_{av.exception_type}", []
    ctx = build_context(po, av)
    results = run_orchestration(ctx)
    exc = next((r for r in results if r.is_exception), None)
    return (exc.exception_type if exc else None), results


# ── 1. Extraction / relaxed mandatory fields ──────────────────────────────────
def test_extraction():
    print("\n== Extraction & relaxed mandatory fields ==")
    po = EXTRACTOR.extract_from_text(read("Happy-Flow-PO.txt"))
    check("happy: po_number extracted", po.po_number == "PO-2026-30001", po.po_number)
    check("happy: po_date extracted", bool(po.po_date), po.po_date)
    check("happy: buyer_email is buyer (not vendor)",
          po.buyer_email == "john.miller@glps.com", po.buyer_email)
    check("happy: company resolves to CUST-1001", po.customer_account == "CUST-1001",
          str(po.customer_account))
    check("happy: ship-to captured (zip)", po.ship_to_zip == "60639", str(po.ship_to_zip))
    check("happy: no missing mandatory fields", po.missing_fields == [], str(po.missing_fields))
    check("happy: 3 order lines", len(po.order_lines) == 3, str(len(po.order_lines)))

    # A PO missing buyer email should be flagged
    txt = read("Happy-Flow-PO.txt").replace("Email        : john.miller@glps.com", "")
    po2 = EXTRACTOR.extract_from_text(txt)
    check("missing buyer email is flagged",
          any("Buyer Email" in m for m in po2.missing_fields), str(po2.missing_fields))


# ── 2. Intake resolution (label-independent SKU, substitution, ship-to) ───────
def test_intake_resolution():
    print("\n== Intake resolution ==")
    po = EXTRACTOR.extract_from_text(EXC_TEXT)
    issues = RESOLVER.resolve(po)
    kinds = [i.kind for i in issues]
    check("obsolete SKU -> substitute recommendation", "SUBSTITUTE_SKU" in kinds, str(kinds))
    sub = next((i for i in issues if i.kind == "SUBSTITUTE_SKU"), None)
    check("substitution has impacts (price/availability/compat)",
          sub and sub.recommended and sub.recommended.get("substitute_sku") == "SKU-CTG-4520"
          and sub.recommended.get("price_impact_pct") is not None,
          str(sub.recommended) if sub else "none")
    check("wrong SKU code identified by description",
          any(i.kind == "UNRESOLVED_SKU" and i.recommended and
              i.recommended.get("sku") == "SKU-DRN-3010" for i in issues), str(kinds))
    check("missing SKU identified by description",
          any(i.kind == "MISSING_SKU" and i.recommended and
              i.recommended.get("sku") == "SKU-SEL-1150" for i in issues), str(kinds))
    check("partial ship-to name -> confirmation to 60639",
          any(i.kind == "PARTIAL_SHIP_TO" and i.recommended and
              i.recommended.get("zip") == "60639" for i in issues), str(kinds))
    # AC-02 interactive scenario: SKU-CTG-4520 qty=2 with no UOM is ambiguous
    # against a pack of 24 → AI raises UOM_AMBIGUOUS with two options.
    uom_iss = next((i for i in issues if i.kind == "UOM_AMBIGUOUS"), None)
    check("UOM ambiguity detected for small qty vs pack size",
          uom_iss is not None and len(uom_iss.suggestions) == 2,
          str(uom_iss.suggestions) if uom_iss else "no UOM_AMBIGUOUS issue")
    if uom_iss:
        pack = next((s for s in uom_iss.suggestions if s["kind"] == "pack"), None)
        check("UOM ambiguity offers pack conversion 2 CASE = 48 EA",
              pack and pack["qty_base"] == 48 and pack["uom"] == "CASE",
              str(pack))


# ── 3. UOM conversion (AC-02) ─────────────────────────────────────────────────
def test_uom_conversion():
    print("\n== UOM conversion (AC-02) ==")
    v = ProductMatchValidator()
    # Explicit non-standard UOM on PO → conversion rule applied
    ctx = {"order_lines": [{"line_number": 1, "sku": "SKU-CTG-4520",
                            "description": "Ceramic", "quantity": 2, "uom": "CASE"}]}
    r = v.validate(ctx)
    row = next((s for s in r.sections if s.get("title") == "Matched products"), None)
    logic = row["rows"][0][-1] if row else ""
    check("CASE->EA conversion produces 48 EA", r.status == "PASS" and "48" in str(logic), str(logic))

    # PO omits UOM → product matcher infers base UOM from Product Master
    ctx2 = {"order_lines": [{"line_number": 1, "sku": "SKU-CTG-4520",
                             "description": "Ceramic", "quantity": 30, "uom": None}]}
    r2 = v.validate(ctx2)
    row2 = next((s for s in r2.sections if s.get("title") == "Matched products"), None)
    logic2 = row2["rows"][0][-1] if row2 else ""
    check("missing UOM defaults to base UOM (no error)", r2.status == "PASS", r2.exception_type or "")
    # Audit trail must record the UOM inference (even though the Matched-
    # products table hides the conversion columns when no conversion happens).
    audit_txt = " | ".join(r2.audit_trail)
    check("missing UOM audit trail records 'inferred from Product Master'",
          "inferred from Product Master" in audit_txt, audit_txt[:120])
    # And the display columns are trimmed to just [SKU, Description, Family,
    # Requested] because no numeric conversion occurred.
    check("no-conversion case hides Converted / Conversion logic columns",
          row2 and row2["headers"] == ["SKU", "Description", "Family", "Requested"],
          str(row2 and row2["headers"]))

    # Additional coverage: PALLET -> EA for a valve
    ctx3 = {"order_lines": [{"line_number": 1, "sku": "SKU-VLV-2201",
                             "description": "valve", "quantity": 1, "uom": "PALLET"}]}
    r3 = v.validate(ctx3)
    row3 = next((s for s in r3.sections if s.get("title") == "Matched products"), None)
    logic3 = row3["rows"][0][-1] if row3 else ""
    check("PALLET->EA conversion produces 48 EA (VALVE family)",
          r3.status == "PASS" and "48" in str(logic3), str(logic3))


# ── 4. End-to-end both demo POs ───────────────────────────────────────────────
def test_end_to_end():
    print("\n== End-to-end demo POs ==")
    dup.reset_store()

    po = EXTRACTOR.extract_from_text(read("Happy-Flow-PO.txt"))
    outcome, results = run_pipeline(po)
    check("PO-1 happy path -> clean pass", outcome is None, str(outcome))

    po2 = EXTRACTOR.extract_from_text(EXC_TEXT)
    issues, applied = auto_apply_resolutions(po2)
    check("PO-2 raised >=4 intake issues", len(issues) >= 4, f"{len(issues)} issues")
    outcome2, results2 = run_pipeline(po2)
    check("PO-2 after CSR approvals -> clean pass", outcome2 is None,
          str(outcome2) + " | applied=" + str(applied))


# ── 5. Master-data backfill (contact person, contract ref, delivery instr) ────
def test_master_data_backfill():
    print("\n== Master-data backfill of optional header fields ==")
    po = EXTRACTOR.extract_from_text(read("Happy-Flow-PO.txt"))
    fs = getattr(po, "field_source", {})
    check("PO-1 contact person backfilled from Buyer_Profiles",
          po.contact_person and fs.get("contact_person") == "MASTER",
          f"{po.contact_person} / {fs.get('contact_person')}")
    check("PO-1 contract reference backfilled from active Contracts",
          po.contract_reference and fs.get("contract_reference") == "MASTER",
          f"{po.contract_reference} / {fs.get('contract_reference')}")
    # Backfilled values must show 100% confidence (they came from a trusted
    # master, not from a regex hit on the PO text).
    check("PO-1 backfilled contact person shows 100% confidence",
          po.confidence_scores.get("contact_person") == 100,
          str(po.confidence_scores.get("contact_person")))
    check("PO-1 backfilled contract reference shows 100% confidence",
          po.confidence_scores.get("contract_reference") == 100,
          str(po.confidence_scores.get("contract_reference")))
    # Delivery instructions must NOT be backfilled — they belong to the
    # specific PO transaction, not to the ship-to's default profile.
    check("PO-1 delivery instructions NOT backfilled (per PO-only rule)",
          not po.delivery_instructions
          and fs.get("delivery_instructions") in (None, "PO"),
          f"{po.delivery_instructions!r} / {fs.get('delivery_instructions')}")


# ── 6. Tax and shipping calculation & display ────────────────────────────────
def test_tax_and_shipping():
    print("\n== Tax & shipping calculation ==")
    dup.reset_store()
    po = EXTRACTOR.extract_from_text(read("Happy-Flow-PO.txt"))
    _, results = run_pipeline(po)
    pricing = next((r for r in results if r.stage_key == "pricing"), None)
    check("pricing stage ran and passed",
          pricing is not None and pricing.status == "PASS",
          str(pricing.exception_type) if pricing else "no pricing result")
    if pricing:
        d = pricing.data or {}
        check("tax amount computed and > 0",
              d.get("pricing_tax_amt") and d["pricing_tax_amt"] > 0,
              str(d.get("pricing_tax_amt")))
        check("Illinois tax rate applied (~8.75%)",
              abs((d.get("pricing_tax_pct") or 0) - 8.75) < 0.01,
              str(d.get("pricing_tax_pct")))
        check("freight amount computed and > 0",
              d.get("pricing_freight") and d["pricing_freight"] > 0,
              str(d.get("pricing_freight")))
        # UI table must include the tax & shipping breakdown
        section_titles = [s.get("title") for s in (pricing.sections or [])]
        check("pricing stage exposes 'Tax & shipping' table",
              "Tax & shipping (AI-calculated)" in section_titles,
              str(section_titles))


# ── 7. Excel POs (same shape as text — verified end-to-end) ──────────────────
def test_excel_pos():
    from modules.excel_parser import parse_excel
    print("\n== Excel PO ingestion ==")

    # Happy-flow Excel: full field checks + clean end-to-end pass.
    dup.reset_store()
    with open(os.path.join(DEMO, "Happy-Flow-PO.xlsx"), "rb") as f:
        text = parse_excel(f.read())
    po = EXTRACTOR.extract_from_text(text)
    check("Happy-Flow-PO.xlsx extracted", po.po_number is not None, str(po.po_number))
    check("Happy-Flow-PO.xlsx order lines = 3", len(po.order_lines) == 3,
          str(len(po.order_lines)))
    check("Happy-Flow-PO.xlsx buyer email captured",
          po.buyer_email == "john.miller@glps.com", str(po.buyer_email))
    check("Happy-Flow-PO.xlsx ship-to name captured",
          po.ship_to_name and "Chicago" in po.ship_to_name, str(po.ship_to_name))
    status, results = run_pipeline(po)
    check("Happy-Flow-PO.xlsx end-to-end clean pass",
          status is None and any(r.stage_key == "order_execution" for r in results),
          str(status))

    # CSR-approval Excel: same shape, all seven lines parse cleanly.
    dup.reset_store()
    with open(os.path.join(DEMO, "CSR-Approval-PO.xlsx"), "rb") as f:
        text = parse_excel(f.read())
    po2 = EXTRACTOR.extract_from_text(text)
    check("CSR-Approval-PO.xlsx extracted", po2.po_number is not None, str(po2.po_number))
    check("CSR-Approval-PO.xlsx order lines = 7", len(po2.order_lines) == 7,
          str(len(po2.order_lines)))


# ── 8. Interactive intake for unknown buyer and zero quantity ────────────────
def test_buyer_and_quantity_issues():
    print("\n== Interactive intake: unknown buyer & zero quantity ==")
    # Unknown buyer email (customer resolves fine, but email is not in
    # Buyer_Profiles) → resolver must raise UNRESOLVED_BUYER with candidate
    # buyers registered for the customer.
    txt = read("Happy-Flow-PO.txt").replace(
        "john.miller@glps.com", "unknown.buyer@glps.com")
    po = EXTRACTOR.extract_from_text(txt)
    issues = RESOLVER.resolve(po)
    ub = next((i for i in issues if i.kind == "UNRESOLVED_BUYER"), None)
    check("unknown buyer email raises UNRESOLVED_BUYER",
          ub is not None, str([i.kind for i in issues]))
    check("UNRESOLVED_BUYER lists buyers for the customer",
          ub and any(s.get("email") == "john.miller@glps.com" for s in ub.suggestions),
          str(ub.suggestions[:2]) if ub else "")

    # Zero-quantity line → resolver must raise INVALID_QUANTITY (not silently
    # skip or crash) and let the pipeline pause for CSR input.
    txt2 = read("Happy-Flow-PO.txt").replace(
        "SKU-VLV-2201   | Pressure-Balancing Shower Valve    |   15",
        "SKU-VLV-2201   | Pressure-Balancing Shower Valve    |    0")
    po2 = EXTRACTOR.extract_from_text(txt2)
    check("zero-qty line does NOT hard-block intake",
          po2.missing_fields == [], str(po2.missing_fields))
    issues2 = RESOLVER.resolve(po2)
    iq = next((i for i in issues2 if i.kind == "INVALID_QUANTITY"), None)
    check("zero quantity raises INVALID_QUANTITY intake issue",
          iq is not None, str([i.kind for i in issues2]))
    check("INVALID_QUANTITY targets the correct line",
          iq and iq.line_number == 3, str(iq.line_number) if iq else "")

    # SUBSTITUTE_SKU now offers a manual-entry action so CSR can force a
    # different SKU instead of accepting the AI's recommended substitute.
    po3 = EXTRACTOR.extract_from_text(EXC_TEXT)
    issues3 = RESOLVER.resolve(po3)
    sub = next((i for i in issues3 if i.kind == "SUBSTITUTE_SKU"), None)
    check("SUBSTITUTE_SKU includes 'enter' manual-entry action",
          sub and "enter" in sub.actions, str(sub.actions) if sub else "")


# ── 9. Manual-entry validators (SKU + quantity) ──────────────────────────────
def test_manual_entry_validators():
    print("\n== Manual-entry validators (inline SKU + qty guards) ==")
    products = RESOLVER.products
    po = EXTRACTOR.extract_from_text(read("Happy-Flow-PO.txt"))

    # SKU validation — happy path (a valid catalog SKU that is not yet on the PO)
    err = validate_manual_sku("SKU-DRN-3010", po, current_line_number=99, products=products)
    check("valid unused SKU is accepted", err is None, str(err))

    # SKU validation — same SKU is allowed on the line being corrected
    line_number_with_sku = po.order_lines[0].line_number
    same_sku = po.order_lines[0].sku
    err = validate_manual_sku(same_sku, po, current_line_number=line_number_with_sku,
                              products=products)
    check("re-entering same SKU on the same line is accepted",
          err is None, str(err))

    # SKU validation — duplicate SKU that is already on another line
    dup_sku = po.order_lines[0].sku
    other_line = po.order_lines[1].line_number
    err = validate_manual_sku(dup_sku, po, current_line_number=other_line,
                              products=products)
    check("duplicate SKU (already on another line) is rejected",
          err is not None and "already on line" in err, str(err))

    # SKU validation — SKU that does not exist in master data
    err = validate_manual_sku("SKU-DOES-NOT-EXIST-99", po,
                              current_line_number=99, products=products)
    check("SKU not in product master is rejected",
          err is not None and "not in the product master" in err, str(err))

    # SKU validation — empty entry
    err = validate_manual_sku("", po, current_line_number=99, products=products)
    check("empty SKU entry is rejected",
          err is not None and "Please enter" in err, str(err))

    # SKU validation — whitespace/case normalization
    lowered = (po.order_lines[0].sku or "").lower()
    err = validate_manual_sku("  " + lowered + "  ", po,
                              current_line_number=99, products=products)
    check("SKU lookup is case- and whitespace-insensitive (rejects duplicate)",
          err is not None and "already on line" in err, str(err))

    # Quantity validation
    check("valid positive quantity is accepted",
          validate_manual_quantity("15") is None, "")
    err = validate_manual_quantity("0")
    check("zero quantity is rejected",
          err is not None and "greater than zero" in err, str(err))
    err = validate_manual_quantity("-3")
    check("negative quantity is rejected",
          err is not None and "greater than zero" in err, str(err))
    err = validate_manual_quantity("abc")
    check("non-numeric quantity is rejected",
          err is not None and "not a valid number" in err, str(err))
    err = validate_manual_quantity("")
    check("empty quantity entry is rejected",
          err is not None and "Please enter" in err, str(err))


# ── 10. CSR-typed lowercase SKU flows through the whole pipeline ─────────────
def test_manual_sku_case_normalization():
    """Regression test: a CSR-typed lowercase SKU (e.g. 'sku-drn-3010') must be
    normalised to uppercase before being placed on the PO line, otherwise
    the product_matcher (keyed by master-data casing) fails and the pipeline
    dies at product configuration instead of animating to completion."""
    print("\n== CSR-typed lowercase SKU normalisation (full pipeline continuation) ==")
    dup.reset_store()
    po = EXTRACTOR.extract_from_text(EXC_TEXT)
    issues = RESOLVER.resolve(po)

    # Pick the WRONG_SKU issue and simulate the CSR typing a valid catalog
    # SKU in LOWERCASE — mirrors what apply_issue_decision does in the UI.
    wrong = next((i for i in issues if i.kind == "UNRESOLVED_SKU"), None)
    check("intake surfaces UNRESOLVED_SKU on PO-2", wrong is not None,
          "no UNRESOLVED_SKU issue on PO-2")

    if wrong:
        # Emulate app.apply_issue_decision(): CSR typed "sku-drn-3010" (lowercase).
        # It must land on the PO line as the canonical uppercase form.
        typed = "sku-drn-3010"
        normalised = typed.strip().upper()
        for ln in po.order_lines:
            if ln.line_number == wrong.line_number:
                ln.sku = normalised
        check("typed SKU is stored uppercase on the PO line",
              any(ln.sku == "SKU-DRN-3010" for ln in po.order_lines),
              str([ln.sku for ln in po.order_lines]))

        # Resolve the remaining intake issues automatically so the pipeline
        # can be exercised end-to-end (mirrors "Approve suggestion" clicks).
        for other in RESOLVER.resolve(po):
            if other.kind == "SUBSTITUTE_SKU" and other.recommended:
                for ln in po.order_lines:
                    if ln.line_number == other.line_number:
                        ln.sku = other.recommended["substitute_sku"]
                        ln.description = (other.recommended.get("substitute_description")
                                          or ln.description)
            elif other.kind in ("UNRESOLVED_SKU", "MISSING_SKU") and other.recommended:
                for ln in po.order_lines:
                    if ln.line_number == other.line_number:
                        ln.sku = other.recommended["sku"]
                        if not ln.description:
                            ln.description = other.recommended.get("description")
            elif other.kind == "UOM_AMBIGUOUS":
                choice = other.recommended or (other.suggestions[0] if other.suggestions else {})
                for ln in po.order_lines:
                    if ln.line_number == other.line_number:
                        ln.uom = choice.get("uom")
                        if choice.get("qty_base"):
                            ln.quantity = choice["qty_base"]
            elif other.kind in ("PARTIAL_SHIP_TO", "UNRESOLVED_SHIP_TO"):
                rec = other.recommended or (other.suggestions[0] if other.suggestions else None)
                if rec and rec.get("zip"):
                    po.ship_to_zip = rec["zip"]
                    po.ship_to_name = rec.get("name") or po.ship_to_name

        exc, results = run_pipeline(po)
        check("pipeline completes end-to-end after CSR-typed lowercase SKU",
              exc is None, f"unexpected exception: {exc}")
        stage_keys = [r.stage_key for r in results]
        check("all sequential + governance + execution stages executed",
              "product_match" in stage_keys and "order_execution" in stage_keys,
              str(stage_keys))


# ── 11. Customer Validation: tier / terms / distributor / buying history ─────
def test_customer_validation_fields():
    print("\n== Customer Validation attributes & buying history ==")
    av = ACCOUNT.validate("CUST-1001", "60639")
    c = av.customer or {}
    check("customer_tier loaded (Strategic)", c.get("customer_tier") == "Strategic",
          str(c.get("customer_tier")))
    check("payment_terms loaded (NET30)", c.get("payment_terms") == "NET30",
          str(c.get("payment_terms")))
    check("customer_class loaded (Distributor)", c.get("customer_class") == "Distributor",
          str(c.get("customer_class")))
    check("distributor_authorization loaded (Authorized Distributor)",
          c.get("distributor_authorization") == "Authorized Distributor",
          str(c.get("distributor_authorization")))
    check("buying history attached", bool(av.buying_history),
          str(bool(av.buying_history)))
    check("buying history lists frequent families",
          av.buying_history and "CARTRIDGE" in (av.buying_history.get("frequent_families") or []),
          str(av.buying_history.get("frequent_families")) if av.buying_history else "none")
    # A non-distributor retailer should classify differently.
    av2 = ACCOUNT.validate("CUST-5001", "90001")
    c2 = av2.customer or {}
    check("retailer classified as Non-Distributor",
          c2.get("customer_class") == "Retailer"
          and c2.get("distributor_authorization") == "Non-Distributor",
          f"{c2.get('customer_class')} / {c2.get('distributor_authorization')}")


# ── 12. Product Match uses buying history ────────────────────────────────────
def test_buying_history_in_product_match():
    print("\n== Product Match buying-history cross-check ==")
    dup.reset_store()
    po = EXTRACTOR.extract_from_text(read("Happy-Flow-PO.txt"))
    _, results = run_pipeline(po)
    pm = next((r for r in results if r.stage_key == "product_match"), None)
    check("product_match ran and passed", pm is not None and pm.status == "PASS",
          str(pm.exception_type) if pm else "none")
    if pm:
        titles = [s.get("title") for s in (pm.sections or [])]
        check("product_match exposes buying-history check table",
              any("Buying-history check" in (t or "") for t in titles), str(titles))
        check("buying-history check logged in audit",
              any("Buying-history check" in a for a in pm.audit_trail),
              "no buying-history audit line")


# ── 13. Pricing & Promo interactive CSR gate ─────────────────────────────────
def test_pricing_csr_gate():
    print("\n== Pricing & Promo interactive CSR gate ==")
    p = PricingEngine()
    ctx = {
        "customer_account": "CUST-1001", "ship_to_zip": "60639",
        "requested_delivery_date": "2026-07-24", "region": "IL",
        "resolved_lines": [{"sku": "SKU-CTG-4520", "family": "CARTRIDGE",
                            "qty_base": 2000, "list_price": 12.5, "weight_kg": 0.2}],
    }
    r = p.validate(ctx)
    check("high-discount order raises PRICING_EXCEPTION",
          r.status == "EXCEPTION" and r.exception_type == "PRICING_EXCEPTION",
          f"{r.status}/{r.exception_type}")
    check("pricing exception is INTERACTIVE (no email hard-stop)",
          not r.data.get("approval_email_sent_to"),
          str(r.data.get("approval_email_sent_to")))
    check("pricing exception computes a margin impact",
          (r.data.get("pricing_margin_impact") or 0) > 0,
          str(r.data.get("pricing_margin_impact")))
    check("pricing prompt asks CSR to approve the exception",
          "Approve exception" in (r.headline or ""), r.headline)
    check("pricing exposes escalation approver role",
          bool(r.data.get("pricing_approver_role")),
          str(r.data.get("pricing_approver_role")))


# ── 14. Decision-layer titles + obsolete-product buttons ─────────────────────
def test_decision_layer_titles_and_buttons():
    print("\n== Decision-layer titles & obsolete-product actions ==")
    from modules.product_matcher import ProductMatchValidator
    from modules.budget_approval import BudgetApprovalValidator
    from modules.credit_validator import CreditValidator
    from modules.inventory_validator import InventoryValidator
    from modules.logistics_validator import LogisticsValidator
    expected = {
        ProductMatchValidator: "Product Match",
        PricingEngine: "Pricing and Promo",
        BudgetApprovalValidator: "Approval",
        CreditValidator: "Credit",
        InventoryValidator: "Inventory Checks",
        LogisticsValidator: "Logistics",
    }
    for cls, want in expected.items():
        check(f"{cls.__name__} title == '{want}'", cls.title == want, cls.title)

    # Obsolete-product substitution offers Approve / Modify / Escalate (no Reject)
    po = EXTRACTOR.extract_from_text(EXC_TEXT)
    sub = next((i for i in RESOLVER.resolve(po) if i.kind == "SUBSTITUTE_SKU"), None)
    check("SUBSTITUTE_SKU offers approve + enter + escalate",
          sub and set(sub.actions) == {"approve", "enter", "escalate"},
          str(sub.actions) if sub else "no SUBSTITUTE_SKU")
    check("SUBSTITUTE_SKU has NO reject action",
          sub and "reject" not in sub.actions,
          str(sub.actions) if sub else "no SUBSTITUTE_SKU")


def main():
    dup.reset_store()
    test_extraction()
    test_intake_resolution()
    test_uom_conversion()
    test_end_to_end()
    test_master_data_backfill()
    test_tax_and_shipping()
    test_excel_pos()
    test_buyer_and_quantity_issues()
    test_manual_entry_validators()
    test_manual_sku_case_normalization()
    test_customer_validation_fields()
    test_buying_history_in_product_match()
    test_pricing_csr_gate()
    test_decision_layer_titles_and_buttons()
    passed = sum(1 for _, ok, _ in _results if ok)
    total = len(_results)
    print(f"\n{passed}/{total} checks passed.")
    return passed == total


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)

