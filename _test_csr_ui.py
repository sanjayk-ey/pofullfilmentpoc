"""Drive the DECISION-LAYER CSR gates through the real Streamlit app (AppTest).

Confirms that pricing / credit / logistics exceptions actually PAUSE the UI with
the interactive Approve-Override / Reject / Escalate buttons, and that clicking
Approve resumes the pipeline all the way to a completed order.
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from streamlit.testing.v1 import AppTest
from modules import duplicate_checker

CHI = ["Great Lakes Plumbing - Chicago DC", "4500 West Diversey Avenue",
       "Chicago, IL 60639"]


def po_text(po_number, company, email, shipto, lines):
    ship_block = "\n".join(shipto)
    line_rows = "\n".join(
        f"{i+1:<6} | {code:<14} | {desc:<34} | {qty:>5}"
        for i, (code, desc, qty) in enumerate(lines))
    return f"""PURCHASE ORDER
PO Number   : {po_number}
PO Date     : 01 July 2026

BUYER
Company Name : {company}
Email        : {email}

SHIP TO
{ship_block}

Requested Delivery Date : 24 July 2026

ORDER LINES
Item # | Product Code   | Description                        |   Qty
-------+----------------+------------------------------------+------
{line_rows}
"""


def phase(at):
    try:
        o = at.session_state["orch"]
    except (KeyError, AttributeError):
        return None
    return o["phase"] if o else None


def drive(label, text, max_steps=60):
    duplicate_checker.reset_store()
    at = AppTest.from_file("app.py", default_timeout=120)
    at.run(timeout=120)
    at.chat_input[0].set_value(text)
    saw_gate = False
    gate_had_all_three = False
    for i in range(max_steps):
        try:
            at.run(timeout=60)
        except Exception as e:
            print(f"  !! {label}: run raised at phase={phase(at)}: {e}")
            return False
        if at.exception:
            print(f"  !! {label}: app exception: {at.exception}")
            return False
        p = phase(at)
        btns = [b.label for b in at.button]
        # A paused decision-layer gate shows Approve + Reject + Escalate.
        has_override = any("✅ Approve" in (b or "") for b in btns)
        has_reject = any(b == "⛔ Reject" for b in btns)
        has_escalate = any("Escalate" in (b or "") for b in btns)
        if has_override:
            saw_gate = True
            gate_had_all_three = has_override and has_reject and has_escalate
        if p == "done":
            print(f"  {label}: reached DONE (saw_gate={saw_gate}, all_three={gate_had_all_three})")
            return saw_gate and gate_had_all_three
        if p == "terminal":
            print(f"  {label}: TERMINAL unexpectedly")
            return False
        # Click Approve whenever a gate is showing to resume.
        clicked = False
        for b in at.button:
            if "✅ Approve" in (b.label or ""):
                b.click(); clicked = True; break
        # else let the driver advance one unit of work
    print(f"  {label}: did not finish in {max_steps} steps (phase={phase(at)})")
    return False


results = {}

print("== Pricing gate (discount over policy) ==")
results["pricing"] = drive(
    "pricing",
    po_text("PO-UI-PRICE", "Great Lakes Plumbing Supply Co", "john.miller@glps.com",
            CHI, [("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 2000)]))

print("== Credit gate (credit hold) ==")
results["credit"] = drive(
    "credit",
    po_text("PO-UI-CREDIT", "Eastern Kitchen & Bath Distributors", "mark.snow@ekbd.com",
            ["Eastern Kitchen & Bath - New York DC", "55 Water Street",
             "New York, NY 10001"],
            [("SKU-SEL-1150", "Tank-to-Bowl Gasket Kit", 50)]))

print("== Logistics gate (ZIP not serviceable) ==")
results["logistics"] = drive(
    "logistics",
    po_text("PO-UI-ZIP", "Great Lakes Plumbing Supply Co", "john.miller@glps.com",
            ["Great Lakes - Ketchikan Project Site", "1 Industrial Rd",
             "Ketchikan, AK 99950"],
            [("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 100)]))

print("\nSummary:")
for k, v in results.items():
    print(f"  {k}: {'PASS' if v else 'FAIL'}")
ok = all(results.values())
print("\nRESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
