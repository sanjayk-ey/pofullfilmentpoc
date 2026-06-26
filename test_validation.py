"""Internal test harness for account hierarchy validation. Run: python test_validation.py"""
import sys
sys.path.insert(0, ".")
from modules.account_validator import AccountValidator

v = AccountValidator()


def show(title, cust, zip_):
    print("=" * 64)
    print(title)
    r = v.validate(cust, zip_)
    print(f"  status={r.status}  exception={r.exception_type}")
    print(f"  msg: {r.message}")
    if r.global_parent:
        print(f"  hierarchy: {r.global_parent['name']} > "
              f"{r.regional_division['name']} > {r.branch['name']}")
    if r.ship_to:
        print(f"  ship_to: {r.ship_to['name']} (ZIP {r.ship_to['zip']})")
    if r.applied_rules:
        print(f"  applied_level: {r.applied_level}")
        for k, val in r.applied_rules.items():
            print(f"     {k} = {val}  [{r.applied_rule_sources[k]}]")
    if r.candidates:
        print(f"  duplicate candidates: "
              f"{[(c['company_name'], c['branch_id']) for c in r.candidates]}")
    if r.possible_ship_tos:
        print(f"  possible ship-tos: "
              f"{[(s['name'], s['zip']) for s in r.possible_ship_tos]}")
    print("  --- audit trail ---")
    for line in r.audit_trail:
        print(f"     . {line}")


show("HAPPY PATH        (CUST-1001 + 60639)", "CUST-1001", "60639")
show("UNMATCHED CUST    (CUST-9999 + 60639)", "CUST-9999", "60639")
show("DUPLICATE CUST    (CUST-7000 + 60639)", "CUST-7000", "60639")
show("INVALID SHIP-TO   (CUST-1001 + 99999)", "CUST-1001", "99999")
show("HIERARCHY MISMATCH(CUST-1001 + 90001)", "CUST-1001", "90001")

# ── Full pipeline: extraction + account validation on sample files ─────────────
print("\n\n" + "#" * 64)
print("# FULL PIPELINE TEST (extract -> validate) on sample files")
print("#" * 64)

from modules.extractor import POExtractor
ex = POExtractor()

sample_files = [
    ("sample-data/US-01/sample-po-text.txt",                    "PASS"),
    ("sample-data/US-02/scenario-unmatched-customer.txt",       "UNMATCHED_CUSTOMER"),
    ("sample-data/US-02/scenario-duplicate-customer.txt",       "DUPLICATE_CUSTOMER"),
    ("sample-data/US-02/scenario-invalid-shipto.txt",           "INVALID_SHIP_TO"),
    ("sample-data/US-02/scenario-hierarchy-mismatch.txt",       "HIERARCHY_MISMATCH"),
]

passed = 0
for path, expected in sample_files:
    with open(path, encoding="utf-8") as f:
        po = ex.extract_from_text(f.read())
    print("-" * 64)
    print(f"FILE: {path}")
    print(f"  extract: customer={po.customer_account}  zip={po.ship_to_zip}  "
          f"missing={po.missing_fields}  conf={po.overall_confidence}%")
    if po.missing_fields:
        print(f"  validate: SKIPPED (extraction had missing fields)")
        outcome = "MISSING_FIELDS"
    else:
        av = v.validate(po.customer_account, po.ship_to_zip)
        outcome = av.exception_type or "PASS"
        print(f"  validate: status={av.status}  outcome={outcome}")
    ok = (outcome == expected)
    passed += ok
    print(f"  EXPECTED={expected}  ->  {'OK' if ok else 'FAIL'}")

print("=" * 64)
print(f"Full pipeline: {passed}/{len(sample_files)} scenarios matched expected outcome.")
print("Done.")
