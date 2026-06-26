"""
test_pipeline.py
End-to-end regression harness for the full orchestration pipeline.

For every sample PO (text and Excel) it runs:
  extraction -> account validation -> decision pipeline
and asserts the expected outcome (clean pass, or the exact exception type at
the expected stage). Run:  python test_pipeline.py
"""
import os
from modules.extractor import POExtractor
from modules.excel_parser import parse_excel
from modules.account_validator import AccountValidator
from modules.pipeline import build_context, run_orchestration

EXTRACTOR = POExtractor()
ACCOUNT = AccountValidator()
SD = os.path.join(os.path.dirname(__file__), "sample-data")

# (path, expected_outcome)  expected = None means full clean pass
CASES = [
    ("US-01/sample-po-text.txt",          None),
    ("US-01/sample-po-happy-path.xlsx",   None),   # Excel path — buyer/cost-center round-trip
    ("US-03/happy-path.txt", None),
    ("US-03/scenario-unauthorized-buyer.txt", "UNAUTHORIZED_BUYER"),
    ("US-03/scenario-restricted-product.txt", "RESTRICTED_PRODUCT"),
    ("US-03/scenario-invalid-cost-center.txt", "INVALID_COST_CENTER"),
    ("US-04/scenario-obsolete-sku.txt", "OBSOLETE_SKU"),
    ("US-04/scenario-invalid-uom.txt", "INVALID_UOM"),
    ("US-04/scenario-unknown-sku.txt", "PRODUCT_CONFIG_EXCEPTION"),
    ("US-05/scenario-restricted-region.txt", "COMPLIANCE_RESTRICTION"),
    ("US-05/scenario-missing-sds.txt", "MISSING_SDS"),
    ("US-06/scenario-pricing-exception.txt", "PRICING_EXCEPTION"),
    ("US-06/happy-path.txt", None),
    ("US-07/scenario-budget-exceeded.txt", "BUDGET_EXCEEDED"),
    ("US-07/scenario-approval-required.txt", "APPROVAL_REQUIRED"),
    ("US-08/scenario-credit-hold.txt", "CREDIT_HOLD"),
    ("US-09/scenario-inventory-shortage.txt", "INVENTORY_SHORTAGE"),
    ("US-10/scenario-zip-not-serviceable.txt", "ZIP_NOT_SERVICEABLE"),
    ("US-11/happy-autonomous.txt", None),
    ("US-11/scenario-governed-exception.txt", "CREDIT_HOLD"),
    ("US-12/happy-path.txt", None),
    ("US-12/scenario-execution-failure.txt", "EXECUTION_FAILURE"),
]


def run_file(path):
    full = os.path.join(SD, path)
    if path.lower().endswith((".xlsx", ".xls")):
        with open(full, "rb") as f:
            text = parse_excel(f.read())
    else:
        with open(full, encoding="utf-8") as f:
            text = f.read()
    po = EXTRACTOR.extract_from_text(text)
    if po.missing_fields:
        return f"INTAKE_MISSING:{po.missing_fields}", []
    av = ACCOUNT.validate(po.customer_account, po.ship_to_zip)
    if av.is_exception:
        return f"ACCOUNT_{av.exception_type}", []
    ctx = build_context(po, av)
    results = run_orchestration(ctx)
    exc = next((r for r in results if r.is_exception), None)
    return (exc.exception_type if exc else None), results


def main():
    passed = 0
    for path, expected in CASES:
        try:
            outcome, results = run_file(path)
        except Exception as e:
            outcome, results = f"ERROR:{type(e).__name__}:{e}", []
        ok = outcome == expected
        passed += ok
        flag = "PASS" if ok else "FAIL"
        exp = expected or "clean-pass"
        got = outcome or "clean-pass"
        print(f"[{flag}] {path:<45} expected={exp:<24} got={got}")
        if not ok and results:
            print("        stages:", " | ".join(
                f"{r.stage_key}:{'EXC:'+str(r.exception_type) if r.is_exception else 'PASS'}"
                for r in results))
    print(f"\n{passed}/{len(CASES)} cases passed.")
    return passed == len(CASES)


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
