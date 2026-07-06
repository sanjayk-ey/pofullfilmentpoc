"""
_verify_all_csr.py
Drive the CSR-Approval demo PO through the FULL pipeline exactly like the app,
auto-accepting the AI recommendation at every gate, and print the complete
ordered list of CSR approval gates plus the headline numbers for each decision
layer. Used to confirm a single PO exercises every CSR approval process.

Run:  python _verify_all_csr.py [path-to-po.txt|.xlsx]
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from modules.extractor import POExtractor
from modules.excel_parser import parse_excel
from modules.intake_resolver import IntakeResolver
from modules.account_validator import AccountValidator
from modules.pipeline import build_context, SEQUENTIAL_STAGES, GOVERNANCE, EXECUTION
from modules import duplicate_checker as dup
import app

EXTRACTOR = POExtractor()
RESOLVER = IntakeResolver()
ACCOUNT = AccountValidator()


def apply_issue(po, issue):
    rec = issue.recommended or (issue.suggestions[0] if issue.suggestions else None)
    for ln in po.order_lines:
        if ln.line_number != issue.line_number:
            continue
        if issue.kind == "SUBSTITUTE_SKU" and rec:
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
        elif issue.kind == "INVALID_QUANTITY":
            ln.quantity = 1  # CSR enters a valid quantity
    if issue.kind in ("PARTIAL_SHIP_TO", "UNRESOLVED_SHIP_TO") and rec:
        if rec.get("zip"):
            po.ship_to_zip = rec["zip"]
            po.ship_to_name = rec.get("name") or po.ship_to_name
    if issue.kind == "UNRESOLVED_BUYER" and rec:
        po.buyer_id = rec.get("buyer_id") or po.buyer_id
        po.cost_center = rec.get("default_cost_center") or getattr(po, "cost_center", None)


def main(path):
    dup.reset_store()
    if path.lower().endswith(".xlsx"):
        with open(path, "rb") as f:
            text = parse_excel(f.read())
    else:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    po = EXTRACTOR.extract_from_text(text)

    gates = []

    # --- Intake gates (each issue is a separate CSR gate) ---
    for issue in RESOLVER.resolve(po):
        gates.append(("INTAKE", issue.kind, app.escalation_target(issue.kind)))
        apply_issue(po, issue)

    # --- Account validation ---
    av = ACCOUNT.validate(po.customer_account, po.ship_to_zip, po.company_name)
    if av.is_exception:
        gates.append(("ACCOUNT", av.exception_type,
                      app.escalation_target(f"ACCOUNT_{av.exception_type}")))

    # --- Sequential decision layers, overriding each exception like a CSR ---
    ctx = build_context(po, av)
    ctx["buyer_id"] = getattr(po, "buyer_id", None)
    ctx["cost_center"] = getattr(po, "cost_center", None)
    headline = {}
    for stage in SEQUENTIAL_STAGES:
        res = stage.validate(ctx)
        ctx.update(res.data or {})
        if res.is_exception:
            interactive = not bool((res.data or {}).get("approval_email_sent_to"))
            gates.append((res.stage_key, res.exception_type,
                          app.escalation_target(res.exception_type),
                          "interactive" if interactive else "auto-route"))
        # capture headline numbers
        d = res.data or {}
        if res.stage_key == "pricing":
            headline["order_total"] = d.get("order_total")
            headline["pricing_msg"] = res.headline
        if res.stage_key == "credit":
            headline["credit_msg"] = res.headline
        if res.stage_key == "inventory":
            headline["inventory_msg"] = res.headline
        if res.stage_key == "logistics":
            headline["logistics_msg"] = res.headline

    print(f"\nPO: {po.po_number}  customer={po.customer_account}  lines={len(po.order_lines)}")
    print(f"order_total = {headline.get('order_total')}")
    print("\n=== FULL CSR GATE SEQUENCE ===")
    for i, g in enumerate(gates, 1):
        print(f"{i:>2}. layer={g[0]:<12} exc={g[1]:<22} route={g[2]}"
              + (f"  [{g[3]}]" if len(g) > 3 else "  [interactive]"))

    print("\n=== HEADLINES ===")
    for k in ("pricing_msg", "credit_msg", "inventory_msg", "logistics_msg"):
        if headline.get(k):
            print(f"{k}: {headline[k]}")

    interactive_count = sum(1 for g in gates if len(g) <= 3 or g[3] == "interactive")
    print(f"\nTotal gates: {len(gates)}  (interactive CSR gates: {interactive_count})")


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "demo/CSR-Approval-PO.txt"
    main(p)
