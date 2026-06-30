"""
create_unit_test_plan.py
Generates docs/Unit_Test_Plan_US01-US12.xlsx — a business-friendly unit-testing
workbook covering every demo scenario (US-01 .. US-12). Written in plain language
so a non-technical business user can run each test during the demo.

Run:  python create_unit_test_plan.py
"""
import os
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

OUT_DIR = os.path.join(os.path.dirname(__file__), "docs")
os.makedirs(OUT_DIR, exist_ok=True)

NAVY = "1F2A44"
BLUE = "2563EB"
LBLUE = "EAF1FB"
GREEN = "1E7D44"
AMBER = "B45309"
GREY = "F3F4F6"


def _border():
    s = Side(style="thin", color="C7CDD6")
    return Border(left=s, right=s, top=s, bottom=s)


# How a tester loads each kind of file
LOAD_TXT = "Open the .txt file, select all text, copy it, paste into the chat box at the bottom, press Enter."
LOAD_XLSX = "Click the + (plus) button, then upload the Excel (.xlsx) file."

# ── Test rows ────────────────────────────────────────────────────────────────
# (Test ID, User Story, Area, Scenario in plain words, input file,
#  how to load, what it checks, expected result in plain words)
ROWS = [
    # ---- US-01 : PO intake & extraction ----
    ("T-01", "US-01", "PO Intake & Data Extraction", "Normal text PO is read correctly",
     "sample-data/US-01/sample-po-text.txt", LOAD_TXT,
     "The agent reads a pasted PO and pulls out all the key fields (PO number, customer, items, quantities, ship-to ZIP, delivery date).",
     "All fields are extracted and shown with high confidence. No missing-field warning. The PO moves forward."),

    ("T-02", "US-01", "PO Intake & Data Extraction", "Normal Excel PO is read correctly",
     "sample-data/US-01/sample-po-happy-path.xlsx", LOAD_XLSX,
     "The agent reads an uploaded Excel PO and extracts the same fields, including buyer and cost center.",
     "All fields extracted correctly from Excel. No missing-field warning. The PO moves forward."),

    ("T-03", "US-01", "PO Intake & Data Extraction", "PO with missing required fields is flagged",
     "sample-data/US-01/sample-po-missing-fields.xlsx", LOAD_XLSX,
     "The agent should notice when required fields (like delivery date or unit of measure) are missing.",
     "The agent clearly lists the missing fields (Requested Delivery Date and Unit of Measure) and asks for them. It does NOT proceed."),

    ("T-04", "US-01", "PO Intake & Data Extraction", "Full PO passes all 12 steps (text)",
     "sample-data/US-01/sample-po-comprehensive.txt", LOAD_TXT,
     "A complete, clean PO should pass every one of the 12 checks end-to-end.",
     "All 12 steps show green / pass. A sales order is created at the end."),

    ("T-05", "US-01", "PO Intake & Data Extraction", "Full PO passes all 12 steps (Excel)",
     "sample-data/US-01/sample-po-comprehensive.xlsx", LOAD_XLSX,
     "Same complete PO but uploaded as Excel — should also pass every check.",
     "All 12 steps show green / pass. A sales order is created at the end."),

    # ---- US-02 : Account hierarchy & ship-to ----
    ("T-06", "US-02", "Account Hierarchy & Ship-To", "Customer account cannot be found",
     "sample-data/US-02/scenario-unmatched-customer.txt", LOAD_TXT,
     "The agent checks the customer account against the customer master list.",
     "Stops with 'Unmatched Customer'. The agent explains the account was not found and routes it for review."),

    ("T-07", "US-02", "Account Hierarchy & Ship-To", "Ship-to address does not belong to the customer",
     "sample-data/US-02/scenario-invalid-shipto.txt", LOAD_TXT,
     "The agent confirms the ship-to ZIP belongs to the customer's account hierarchy.",
     "Stops with 'Invalid Ship-To'. The agent explains the ship-to is not valid for this customer."),

    ("T-08", "US-02", "Account Hierarchy & Ship-To", "Ship-to belongs to a different branch (mismatch)",
     "sample-data/US-02/scenario-hierarchy-mismatch.txt", LOAD_TXT,
     "The agent checks that the ship-to sits under the correct branch / division in the hierarchy.",
     "Stops with 'Hierarchy Mismatch'. The agent explains the ship-to is under a different branch."),

    ("T-09", "US-02", "Account Hierarchy & Ship-To", "Two customer records match (duplicate)",
     "sample-data/US-02/scenario-duplicate-customer.txt", LOAD_TXT,
     "The agent detects when the same customer name maps to more than one account record.",
     "Stops with 'Duplicate Customer'. The agent asks a human to confirm which account is correct."),

    # ---- US-03 : Buyer authorization ----
    ("T-10", "US-03", "Buyer Authorization", "Authorized buyer — clean pass",
     "sample-data/US-03/happy-path.txt", LOAD_TXT,
     "An approved buyer ordering allowed products on a valid cost center should pass.",
     "Buyer is authorized. The PO continues to the next checks."),

    ("T-11", "US-03", "Buyer Authorization", "Buyer is not allowed to place this order",
     "sample-data/US-03/scenario-unauthorized-buyer.txt", LOAD_TXT,
     "The agent checks whether the buyer is active and within their ordering rights.",
     "Stops with 'Unauthorized Buyer'. The agent explains the buyer is not permitted."),

    ("T-12", "US-03", "Buyer Authorization", "Buyer ordered a product they are not allowed to buy",
     "sample-data/US-03/scenario-restricted-product.txt", LOAD_TXT,
     "The agent checks the product is within the buyer's allowed product families.",
     "Stops with 'Restricted Product'. The agent explains the product is not allowed for this buyer."),

    ("T-13", "US-03", "Buyer Authorization", "Cost center is invalid or inactive",
     "sample-data/US-03/scenario-invalid-cost-center.txt", LOAD_TXT,
     "The agent confirms the cost center on the PO is valid and active.",
     "Stops with 'Invalid Cost Center'. The agent explains the cost center cannot be used."),

    # ---- US-04 : Product matching & UOM ----
    ("T-14", "US-04", "Product Matching & UOM", "Obsolete product is replaced by its successor",
     "sample-data/US-04/scenario-obsolete-sku.txt", LOAD_TXT,
     "The agent checks product status and suggests the approved replacement for obsolete items.",
     "Stops with 'Obsolete SKU'. The agent recommends the approved substitute product."),

    ("T-15", "US-04", "Product Matching & UOM", "Unit of measure cannot be converted",
     "sample-data/US-04/scenario-invalid-uom.txt", LOAD_TXT,
     "The agent checks the ordered unit of measure can be converted to the base unit.",
     "Stops with 'Invalid UOM'. The agent explains the unit of measure is not supported."),

    ("T-16", "US-04", "Product Matching & UOM", "Product code is unknown",
     "sample-data/US-04/scenario-unknown-sku.txt", LOAD_TXT,
     "The agent checks the product code exists in the product master.",
     "Stops with a product configuration exception. The agent explains the SKU was not found."),

    # ---- US-05 : Compliance ----
    ("T-17", "US-05", "Compliance & Documentation", "Product is restricted in the destination region",
     "sample-data/US-05/scenario-restricted-region.txt", LOAD_TXT,
     "The agent checks regional rules (e.g. VOC-restricted finish into California).",
     "Stops with 'Compliance Restriction'. The agent explains the product cannot ship to that region."),

    ("T-18", "US-05", "Compliance & Documentation", "Required safety document (SDS) is missing",
     "sample-data/US-05/scenario-missing-sds.txt", LOAD_TXT,
     "The agent checks that required compliance documents are on file.",
     "Stops with 'Missing SDS'. The agent explains the safety data sheet is required."),

    # ---- US-06 : Pricing ----
    ("T-19", "US-06", "Pricing Engine", "Correct price is built step by step (price waterfall)",
     "sample-data/US-06/happy-path.txt", LOAD_TXT,
     "The agent builds the final price from list price -> contract -> volume -> promo -> rebate, and shows each step.",
     "Pass. A 'Price waterfall' table shows each step and the final net unit price. Order total is calculated."),

    ("T-20", "US-06", "Pricing Engine", "Discount is too deep and breaks the margin rule",
     "sample-data/US-06/scenario-pricing-exception.txt", LOAD_TXT,
     "The agent checks the final discount does not break the margin policy.",
     "Stops with 'Pricing Exception'. A mock email is sent to the pricing approver and the process pauses."),

    # ---- US-07 : Budget & approval ----
    ("T-21", "US-07", "Budget & Approval", "Order needs manager approval",
     "sample-data/US-07/scenario-approval-required.txt", LOAD_TXT,
     "The agent checks if the order value is over the buyer's self-approval limit.",
     "Stops with 'Approval Required'. A mock approval email is sent to the right manager and the process pauses."),

    ("T-22", "US-07", "Budget & Approval", "Order is over the available budget",
     "sample-data/US-07/scenario-budget-exceeded.txt", LOAD_TXT,
     "The agent checks the order against the remaining budget for the cost center.",
     "Stops with 'Budget Exceeded'. The agent explains there is not enough budget."),

    # ---- US-08 : Credit ----
    ("T-23", "US-08", "Credit Check", "Customer is over their credit limit",
     "sample-data/US-08/scenario-credit-hold.txt", LOAD_TXT,
     "The agent checks available credit and overdue invoices before confirming.",
     "Stops with 'Credit Hold'. The agent explains the order is on credit hold."),

    # ---- US-09 : Inventory & allocation ----
    ("T-24", "US-09", "Inventory & Allocation", "Not enough stock to fulfil the order",
     "sample-data/US-09/scenario-inventory-shortage.txt", LOAD_TXT,
     "The agent checks available stock across the distribution centers.",
     "Stops with 'Inventory Shortage'. The agent explains stock is not enough and shows the gap."),

    ("T-25", "US-09", "Inventory & Allocation", "Order cannot be split but stock is in two places",
     "sample-data/US-09/scenario-split-not-allowed.txt", LOAD_TXT,
     "The agent respects the customer rule that does not allow split shipments.",
     "Stops with 'Split Not Allowed'. The agent explains a single-location fulfilment is not possible."),

    ("T-26", "US-09", "Inventory & Allocation", "Customer fulfilment rule is applied (clean pass)",
     "sample-data/US-09/scenario-restricted-warehouse.txt", LOAD_TXT,
     "The agent applies the customer's preferred / restricted warehouse rule.",
     "Pass. The agent applies the rule and allocates from the allowed warehouse."),

    ("T-27", "US-09", "Inventory & Allocation", "Order is below the minimum order quantity",
     "sample-data/US-09/scenario-min-order-qty.txt", LOAD_TXT,
     "The agent checks the order meets the minimum order quantity.",
     "Stops with 'Minimum Order Qty Not Met'. The agent explains the minimum quantity rule."),

    # ---- US-10 : Logistics ----
    ("T-28", "US-10", "Logistics & Serviceability", "Delivery ZIP cannot be serviced by any carrier",
     "sample-data/US-10/scenario-zip-not-serviceable.txt", LOAD_TXT,
     "The agent checks a carrier can deliver to the ship-to ZIP within the SLA.",
     "Stops with 'ZIP Not Serviceable'. The agent explains no carrier covers that ZIP."),

    # ---- US-11 : Exception governance ----
    ("T-29", "US-11", "Exception Governance", "Clean order runs fully autonomously",
     "sample-data/US-11/happy-autonomous.txt", LOAD_TXT,
     "When everything is fine, the agent should complete with no human involvement.",
     "All steps pass automatically. No human routing needed. Order is created."),

    ("T-30", "US-11", "Exception Governance", "A problem is routed to the right team",
     "sample-data/US-11/scenario-governed-exception.txt", LOAD_TXT,
     "When a problem is found, the agent routes it to the correct role with a recommendation.",
     "Stops with 'Credit Hold' and routes to the right team with an AI recommendation."),

    # ---- US-12 : Order execution ----
    ("T-31", "US-12", "Order Execution", "Order is created in downstream systems (happy path)",
     "sample-data/US-12/happy-path.txt", LOAD_TXT,
     "After all checks pass, the agent creates the order in ERP / OMS and notifies systems (mocked).",
     "Pass. Mock messages confirm the order was created in ERP/OMS/WMS/TMS and a confirmation email is sent."),

    ("T-32", "US-12", "Order Execution", "A downstream system fails during order creation",
     "sample-data/US-12/scenario-execution-failure.txt", LOAD_TXT,
     "The agent handles a failure from a downstream system gracefully.",
     "Stops with 'Execution Failure'. The agent explains which system failed and routes for follow-up."),
]

HEADERS = ["Test ID", "User Story", "Area", "Scenario (plain words)", "Input file to use",
           "How to load it", "What this test checks", "What you should see (expected result)",
           "Pass / Fail", "Tester notes"]
WIDTHS = [9, 11, 26, 34, 40, 46, 50, 56, 12, 24]


def banner(ws, text, ncols, height=26, fill=NAVY, size=14):
    ws.merge_cells(start_row=ws.max_row, start_column=1, end_row=ws.max_row, end_column=ncols)
    c = ws.cell(row=ws.max_row, column=1, value=text)
    c.font = Font(bold=True, size=size, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor=fill)
    c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[ws.max_row].height = height


def main():
    wb = openpyxl.Workbook()

    # ── Tab 1: How to test ──────────────────────────────────────────────
    ws = wb.active
    ws.title = "How To Test"
    ws.sheet_view.showGridLines = False
    ws.append([""]); banner(ws, "PO FULFILMENT AI — UNIT TEST PLAN (US-01 to US-12)", 2, 30, NAVY, 16)
    intro = [
        "",
        "This workbook lists every test we run on the AI agent. It is written in simple language so anyone",
        "on the business team can run a test during the demo and confirm the result.",
        "",
        "HOW TO START THE DEMO APP",
        "1. Open the app (your engineer will start it, or follow the Demo Start Guide).",
        "2. The app opens in your web browser — it looks like a chat window.",
        "",
        "TWO WAYS TO SEND A PO TO THE AGENT",
        "A) TEXT PO  ->  Open the .txt file, copy all the text, paste it into the chat box at the bottom, press Enter.",
        "B) EXCEL PO ->  Click the + (plus) button near the chat box, then upload the .xlsx file.",
        "",
        "HOW TO READ THE RESULT",
        "- GREEN / PASS means that step is fine and the agent moves on.",
        "- An EXCEPTION (amber/red) means the agent found a problem, explains it in plain words, and",
        "  routes it to the right person. This is expected behaviour for the 'problem' scenarios below.",
        "- For approval / pricing problems, the agent shows a MOCK email being sent — no real email goes out.",
        "",
        "WHAT TO DO FOR EACH TEST",
        "1. Go to the 'Test Cases' tab.",
        "2. Pick a row. Open the file in the 'Input file to use' column.",
        "3. Follow 'How to load it'.",
        "4. Compare what you see to 'What you should see'.",
        "5. Write Pass or Fail in the 'Pass / Fail' column.",
        "",
        "TIP: Tests T-04 and T-05 are the 'everything works' demos — great to show first.",
    ]
    for line in intro:
        ws.append([line])
        if line.isupper() and line.strip():
            ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=11, color=BLUE)
        else:
            ws.cell(row=ws.max_row, column=1).font = Font(size=11)
    ws.column_dimensions["A"].width = 110

    # ── Tab 2: Test Cases ───────────────────────────────────────────────
    ws2 = wb.create_sheet("Test Cases")
    ws2.sheet_view.showGridLines = False
    ws2.append([""])
    banner(ws2, "TEST CASES  —  run each row and mark Pass / Fail", len(HEADERS), 28, NAVY, 14)
    ws2.append(HEADERS)
    hr = ws2.max_row
    for ci, h in enumerate(HEADERS, 1):
        cell = ws2.cell(row=hr, column=ci, value=h)
        cell.font = Font(bold=True, size=10, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=BLUE)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _border()
    ws2.row_dimensions[hr].height = 32

    story_fill = {}
    palette = ["EAF1FB", "FFF7ED"]
    for r in ROWS:
        ws2.append(list(r) + ["", ""])
        ri = ws2.max_row
        us = r[1]
        if us not in story_fill:
            story_fill[us] = palette[len(story_fill) % 2]
        fill = story_fill[us]
        for ci in range(1, len(HEADERS) + 1):
            cell = ws2.cell(row=ri, column=ci)
            cell.font = Font(size=10)
            cell.fill = PatternFill("solid", fgColor=fill)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = _border()
        ws2.cell(row=ri, column=1).font = Font(size=10, bold=True)
        ws2.cell(row=ri, column=2).font = Font(size=10, bold=True, color=NAVY)

    for ci, w in enumerate(WIDTHS, 1):
        ws2.column_dimensions[get_column_letter(ci)].width = w
    ws2.freeze_panes = "A4"

    # ── Tab 3: Summary ──────────────────────────────────────────────────
    ws3 = wb.create_sheet("Summary")
    ws3.sheet_view.showGridLines = False
    ws3.append([""]); banner(ws3, "COVERAGE SUMMARY", 3, 26, NAVY, 14)
    ws3.append(["User Story", "Area", "Number of tests"])
    for ci in range(1, 4):
        c = ws3.cell(row=ws3.max_row, column=ci)
        c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor=BLUE)
        c.alignment = Alignment(horizontal="center"); c.border = _border()
    areas = {}
    for r in ROWS:
        areas.setdefault(r[1], [r[2], 0])
        areas[r[1]][1] += 1
    for us in sorted(areas):
        ws3.append([us, areas[us][0], areas[us][1]])
        for ci in range(1, 4):
            c = ws3.cell(row=ws3.max_row, column=ci)
            c.font = Font(size=10); c.border = _border()
            c.alignment = Alignment(vertical="center")
    ws3.append(["TOTAL", "", len(ROWS)])
    for ci in range(1, 4):
        c = ws3.cell(row=ws3.max_row, column=ci)
        c.font = Font(bold=True); c.fill = PatternFill("solid", fgColor=GREY); c.border = _border()
    ws3.column_dimensions["A"].width = 14
    ws3.column_dimensions["B"].width = 30
    ws3.column_dimensions["C"].width = 16

    out = os.path.join(OUT_DIR, "Unit_Test_Plan_US01-US12.xlsx")
    wb.save(out)
    print("Created:", out, f"({len(ROWS)} test cases)")


if __name__ == "__main__":
    main()
