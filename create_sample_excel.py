"""
Run this once to generate the sample Excel PO files in sample-data/US-01/.
  python create_sample_excel.py
"""
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils  import get_column_letter
import os

OUT_DIR = os.path.join(os.path.dirname(__file__), "sample-data", "US-01")
os.makedirs(OUT_DIR, exist_ok=True)

# ── Style helpers ─────────────────────────────────────────────────────────────
def fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)

thin  = Side(style="thin",   color="AAAAAA")
thick = Side(style="medium", color="1E3A5F")

def thin_border():
    return Border(left=thin, right=thin, top=thin, bottom=thin)

def thick_border():
    return Border(left=thick, right=thick, top=thick, bottom=thick)

# ─────────────────────────────────────────────────────────────────────────────
# FILE 1: Happy-path PO (all fields present)
# ─────────────────────────────────────────────────────────────────────────────
def make_happy_path():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Purchase Order"
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 10
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 8
    ws.column_dimensions["F"].width = 12
    ws.column_dimensions["G"].width = 14

    BLUE   = "0369A1"
    LBLUE  = "DBEAFE"
    YELLOW = "FEF9C3"
    GREY   = "F1F5F9"
    WHITE  = "FFFFFF"
    GREEN  = "F0FDF4"

    row = 1

    # Title row
    ws.merge_cells(f"A{row}:G{row}")
    c = ws.cell(row=row, column=1, value="PURCHASE ORDER")
    c.font      = Font(bold=True, size=18, color="FFFFFF")
    c.fill      = fill(BLUE)
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[row].height = 36
    row += 1

    # ── Header metadata ────────────────────────────────────────────────────────
    header_fields = [
        ("PO Number",               "PO-2026-EXCEL-001"),
        ("PO Date",                 "24 June 2026"),
        ("Customer ID",             "CUST-1001"),
        ("Company Name",            "Acme Industrial Supplies Ltd"),
        ("Contact Person",          "John Miller"),
        ("Contract Reference",      "CONTRACT-ACME-2026-007"),
        ("Payment Terms",           "Net 30"),
        ("Ship To",                 "Acme Industrial – Chicago Warehouse, 4500 West Diversey Ave, Chicago IL 60639"),
        ("ZIP",                     "60639"),
        ("Delivery Date",           "15 July 2026"),
        ("Delivery Instructions",   "Deliver to Dock 3. Forklift required. Call 312-555-0199 before arrival."),
    ]

    for label, value in header_fields:
        ws.row_dimensions[row].height = 22
        lc = ws.cell(row=row, column=1, value=label)
        lc.font  = Font(bold=True, size=11)
        lc.fill  = fill(GREY)
        lc.alignment = Alignment(vertical="center")
        lc.border = thin_border()

        ws.merge_cells(f"B{row}:G{row}")
        vc = ws.cell(row=row, column=2, value=value)
        vc.font  = Font(size=11)
        vc.fill  = fill(WHITE)
        vc.alignment = Alignment(vertical="center", wrap_text=True)
        vc.border = thin_border()
        row += 1

    row += 1  # blank

    # ── Order lines table ──────────────────────────────────────────────────────
    headers = ["Line", "SKU", "Description", "Quantity", "UOM", "Unit Price", "Line Total"]
    for ci, h in enumerate(headers, 1):
        c = ws.cell(row=row, column=ci, value=h)
        c.font      = Font(bold=True, size=11, color="FFFFFF")
        c.fill      = fill("1E3A5F")
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border    = thin_border()
    ws.row_dimensions[row].height = 26
    row += 1

    lines = [
        (1, "SKU-STL-4520", "Carbon Steel Pipe 4 inch SCH40",     500, "FT",  10.80,  5400.00),
        (2, "SKU-FLG-3010", "Stainless Steel Flange 3 inch 150LB", 80, "EA",  76.00,  6080.00),
        (3, "SKU-VLV-2201", "Ball Valve 2 inch Full Port CS",       25, "EA", 185.00,  4625.00),
    ]

    for line_data in lines:
        for ci, val in enumerate(line_data, 1):
            c = ws.cell(row=row, column=ci, value=val)
            c.font  = Font(size=11)
            c.fill  = fill(LBLUE if row % 2 == 0 else WHITE)
            c.alignment = Alignment(horizontal="center" if ci != 3 else "left",
                                     vertical="center")
            c.border = thin_border()
            if ci in (6, 7) and isinstance(val, float):
                c.number_format = '"$"#,##0.00'
        ws.row_dimensions[row].height = 22
        row += 1

    # Total row
    total = sum(l[6] for l in lines)
    ws.merge_cells(f"A{row}:F{row}")
    tc = ws.cell(row=row, column=1, value="ORDER TOTAL")
    tc.font = Font(bold=True, size=11); tc.fill=fill(YELLOW)
    tc.alignment = Alignment(horizontal="right", vertical="center")
    tc.border = thin_border()
    vc2 = ws.cell(row=row, column=7, value=total)
    vc2.font = Font(bold=True, size=11); vc2.fill=fill(YELLOW)
    vc2.number_format = '"$"#,##0.00'
    vc2.border = thin_border()
    ws.row_dimensions[row].height = 24

    wb.save(os.path.join(OUT_DIR, "sample-po-happy-path.xlsx"))
    print("Created: sample-po-happy-path.xlsx")


# ─────────────────────────────────────────────────────────────────────────────
# FILE 2: PO with missing fields (triggers missing-field exception)
# ─────────────────────────────────────────────────────────────────────────────
def make_missing_fields():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Purchase Order"
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 10
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 8
    ws.column_dimensions["F"].width = 12
    ws.column_dimensions["G"].width = 14

    row = 1
    ws.merge_cells(f"A{row}:G{row}")
    c = ws.cell(row=row, column=1, value="PURCHASE ORDER — INCOMPLETE (Demo)")
    c.font = Font(bold=True, size=16, color="FFFFFF")
    c.fill = fill("991B1B")
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[row].height = 32
    row += 1

    # Missing: Customer ID, Delivery Date, ZIP
    header_fields = [
        ("PO Number",          "PO-2026-EXCEL-002"),
        ("PO Date",            "24 June 2026"),
        ("Customer ID",        ""),                    # ← MISSING
        ("Company Name",       "Delta Energy Services"),
        ("Contract Reference", ""),                    # ← MISSING
        ("Payment Terms",      ""),                    # ← MISSING
        ("Ship To",            "Delta Energy, Remote Site, Texas"),
        ("ZIP",                ""),                    # ← MISSING
        ("Delivery Date",      ""),                    # ← MISSING
        ("Delivery Instructions", "Call before delivery"),
    ]
    for label, value in header_fields:
        ws.row_dimensions[row].height = 22
        lc = ws.cell(row=row, column=1, value=label)
        lc.font = Font(bold=True, size=11)
        lc.fill = fill("F1F5F9")
        lc.border = thin_border()
        ws.merge_cells(f"B{row}:G{row}")
        vc = ws.cell(row=row, column=2, value=value if value else "— MISSING —")
        vc.font = Font(size=11, color="991B1B" if not value else "000000")
        vc.border = thin_border()
        row += 1

    row += 1
    headers = ["Line", "SKU", "Description", "Quantity", "UOM", "Unit Price", "Line Total"]
    for ci, h in enumerate(headers, 1):
        c = ws.cell(row=row, column=ci, value=h)
        c.font = Font(bold=True, size=11, color="FFFFFF")
        c.fill = fill("1E3A5F")
        c.alignment = Alignment(horizontal="center")
        c.border = thin_border()
    ws.row_dimensions[row].height = 26
    row += 1

    # One line with missing UOM
    for ci, val in enumerate([1, "SKU-PMP-6601", "Centrifugal Pump 6 inch", 5, "", 4200.00, 21000.00], 1):
        c = ws.cell(row=row, column=ci, value=val if val != "" else "— MISSING —")
        c.font = Font(size=11, color="991B1B" if val == "" else "000000")
        c.border = thin_border()

    wb.save(os.path.join(OUT_DIR, "sample-po-missing-fields.xlsx"))
    print("Created: sample-po-missing-fields.xlsx")


if __name__ == "__main__":
    make_happy_path()
    make_missing_fields()
    print("\nAll sample Excel files created in sample-data/US-01/")
