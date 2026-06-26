"""
excel_parser.py
Reads an uploaded Excel PO file and converts it into
a structured text block for the POExtractor.
"""
import pandas as pd
import re
from io import BytesIO
from typing import Tuple


# Column name synonyms (lowercase) → canonical name
COL_ALIASES = {
    "sku":          "sku",
    "part number":  "sku", "part no":  "sku", "part#":    "sku",
    "item number":  "sku", "item no":  "sku", "item code":"sku",
    "material":     "sku", "product":  "sku", "product code":"sku",
    "description":  "description", "desc": "description", "item description":"description",
    "quantity":     "quantity", "qty": "quantity", "amount":"quantity", "order qty":"quantity",
    "uom":          "uom", "unit":  "uom", "unit of measure":"uom", "unit of measurement":"uom",
    "unit price":   "unit_price", "price":"unit_price", "rate":"unit_price", "cost":"unit_price",
}

# Header field label synonyms (lowercase) → canonical attribute name
HEADER_ALIASES = {
    "po number":              "po_number",
    "purchase order number":  "po_number",
    "purchase order no":      "po_number",
    "po no":                  "po_number",
    "po#":                    "po_number",
    "order number":           "po_number",
    "customer id":            "customer_account",
    "customer no":            "customer_account",
    "customer account":       "customer_account",
    "account id":             "customer_account",
    "account number":         "customer_account",
    "company name":           "company_name",
    "buyer":                  "company_name",
    "contract reference":     "contract_reference",
    "contract no":            "contract_reference",
    "contract number":        "contract_reference",
    "contract id":            "contract_reference",
    "agreement no":           "contract_reference",
    "zip":                    "ship_to_zip",
    "zip code":               "ship_to_zip",
    "postal code":            "ship_to_zip",
    "delivery date":          "requested_delivery_date",
    "requested delivery date":"requested_delivery_date",
    "ship date":              "requested_delivery_date",
    "required date":          "requested_delivery_date",
    "delivery instructions":  "delivery_instructions",
    "special instructions":   "delivery_instructions",
    "shipping notes":         "delivery_instructions",
    "notes":                  "delivery_instructions",
    "remarks":                "delivery_instructions",
    "payment terms":          "payment_terms",
    "terms":                  "payment_terms",
    "ship to":                "ship_to_address",
    "ship-to":                "ship_to_address",
    "deliver to":             "ship_to_address",
    "buyer id":               "buyer_id",
    "buyer no":               "buyer_id",
    "buyer number":           "buyer_id",
    "buyer code":             "buyer_id",
    "cost center":            "cost_center",
    "cost centre":            "cost_center",
    "cost center id":         "cost_center",
    "cost center code":       "cost_center",
    "cost centre id":         "cost_center",
}


def parse_excel(file_bytes: bytes) -> str:
    """
    Parse an Excel PO file and return a structured text representation
    that can be fed into the POExtractor.
    """
    xf = pd.ExcelFile(BytesIO(file_bytes))
    # Use first sheet by default; prefer sheet named 'PO' or 'Purchase Order'
    sheet_name = xf.sheet_names[0]
    for name in xf.sheet_names:
        if any(k in name.lower() for k in ["po", "purchase", "order"]):
            sheet_name = name
            break

    df_raw = pd.read_excel(BytesIO(file_bytes), sheet_name=sheet_name, header=None, dtype=str)
    df_raw = df_raw.fillna("")

    header_data = {}   # label → value from key-value header section
    order_lines = []   # list of dicts from tabular section
    in_table    = False
    col_map     = {}   # col_index → canonical name
    table_header_row = -1

    rows = df_raw.values.tolist()

    for row_idx, row in enumerate(rows):
        cells = [str(c).strip() for c in row]

        # Skip fully empty rows
        if not any(cells):
            if in_table and order_lines:
                break
            continue

        # Detect table header row
        non_empty = [c for c in cells if c]
        if not in_table and len(non_empty) >= 3:
            alias_hits = sum(1 for c in cells if c.lower() in COL_ALIASES)
            if alias_hits >= 2:
                in_table = True
                table_header_row = row_idx
                col_map = {}
                for ci, cell in enumerate(cells):
                    canon = COL_ALIASES.get(cell.lower())
                    if canon:
                        col_map[ci] = canon
                continue

        if in_table:
            # Data row — map columns
            row_data = {}
            for ci, canon in col_map.items():
                if ci < len(cells) and cells[ci]:
                    row_data[canon] = cells[ci]
            if row_data.get("sku") or row_data.get("quantity"):
                order_lines.append(row_data)
        else:
            # Key-value header pair: [Label, Value] or [Label:, Value]
            for ci in range(len(cells)-1):
                label = cells[ci].rstrip(":").strip().lower()
                value = cells[ci+1].strip() if ci+1 < len(cells) else ""
                if label and value:
                    canon = HEADER_ALIASES.get(label)
                    if canon:
                        header_data[canon] = value

            # Single cell with "Label: Value" format
            for cell in cells:
                if ":" in cell:
                    parts = cell.split(":", 1)
                    label = parts[0].strip().lower()
                    value = parts[1].strip()
                    canon = HEADER_ALIASES.get(label)
                    if canon and value:
                        header_data[canon] = value

    return _build_text(header_data, order_lines)


def _build_text(header: dict, lines: list) -> str:
    """Convert parsed data into structured text for POExtractor."""
    parts = ["PURCHASE ORDER (Excel Import)"]
    parts.append("")

    # Header fields
    field_display = [
        ("po_number",               "PO Number"),
        ("customer_account",        "Customer ID"),
        ("company_name",            "Company"),
        ("buyer_id",                "Buyer ID"),
        ("cost_center",             "Cost Center"),
        ("contract_reference",      "Contract Reference"),
        ("ship_to_address",         "Ship To"),
        ("ship_to_zip",             "ZIP"),
        ("requested_delivery_date", "Delivery Date"),
        ("payment_terms",           "Payment Terms"),
        ("delivery_instructions",   "Delivery Instructions"),
    ]
    for key, label in field_display:
        val = header.get(key)
        if val:
            parts.append(f"{label}: {val}")

    if lines:
        parts.append("")
        parts.append("Line | SKU | Description | Quantity | UOM | Unit Price")
        parts.append("-" * 60)
        for i, line in enumerate(lines, 1):
            sku   = line.get("sku", "")
            desc  = line.get("description", "")
            qty   = line.get("quantity", "")
            uom   = line.get("uom", "")
            price = line.get("unit_price", "")
            parts.append(f"{i} | {sku} | {desc} | {qty} | {uom} | {price}")

    return "\n".join(parts)
