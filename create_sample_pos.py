"""
create_sample_pos.py
Generates per-user-story sample purchase-order text files under
sample-data/US-03 ... sample-data/US-12. Each story folder contains a
happy-path PO that flows through that stage plus one file per exception type.

Run once:  python create_sample_pos.py
"""
import os

BASE = os.path.join(os.path.dirname(__file__), "sample-data")


def po_text(po_number, customer, buyer, cost_center, ship_name, ship_city_line,
            lines, contract="CONTRACT-ACME-2026-007", date="15 July 2026",
            instr="Deliver to Dock 3. Forklift required on site."):
    rows = "\n".join(
        f"{i:<4} | {sku:<16} | {desc:<32} | {qty:<7} | {uom}"
        for i, (sku, desc, qty, uom) in enumerate(lines, 1)
    )
    return f"""PURCHASE ORDER

PO Number       : {po_number}
PO Date         : 24 June 2026

BUYER DETAILS
Customer ID     : {customer}
Buyer ID        : {buyer}
Cost Center     : {cost_center}

SHIP TO
{ship_name}
{ship_city_line}
USA

Contract Reference : {contract}
Payment Terms      : Net 30
Requested Delivery Date : {date}

ORDER LINES
--------------------------------------------------------------------------------
Line | SKU              | Description                      | Qty     | UOM
--------------------------------------------------------------------------------
{rows}
--------------------------------------------------------------------------------

Delivery Instructions : {instr}
"""


CHI = ("Acme Chicago Warehouse", "4500 West Diversey Avenue, Chicago, IL 60639")
NYC = ("Acme New York Distribution Center", "55 Water Street, New York, NY 10001")
AK  = ("Acme Remote Site (Alaska)", "1 Industrial Rd, Ketchikan, AK 99950")
CA  = ("Acme California Project Site", "9000 Sunset Blvd, Beverly Hills, CA 90210")

HAPPY_LINES = [
    ("SKU-STL-4520", "Carbon Steel Pipe 4 inch SCH40", 200, "FT"),
    ("SKU-FLG-3010", "Stainless Steel Flange 3 inch", 80, "EA"),
    ("SKU-VLV-2201", "Ball Valve 2 inch Full Port", 25, "EA"),
]

# (relative folder, filename, kwargs)
SAMPLES = [
    # US-03 Buyer Authorization
    ("US-03", "happy-path.txt",
     dict(po_number="PO-US03-HAPPY", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-STL-4520", "Carbon Steel Pipe", 200, "FT")])),
    ("US-03", "scenario-unauthorized-buyer.txt",
     dict(po_number="PO-US03-UNAUTH", customer="CUST-1001", buyer="BUY-900",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-STL-4520", "Carbon Steel Pipe", 200, "FT")])),
    ("US-03", "scenario-restricted-product.txt",
     dict(po_number="PO-US03-RESTRICT", customer="CUST-1001", buyer="BUY-002",
          cost_center="CC-MW-200", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-VLV-2201", "Ball Valve 2 inch", 10, "EA")])),
    ("US-03", "scenario-invalid-cost-center.txt",
     dict(po_number="PO-US03-BADCC", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-OLD-900", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-STL-4520", "Carbon Steel Pipe", 200, "FT")])),

    # US-04 Product Matching / UOM
    ("US-04", "scenario-obsolete-sku.txt",
     dict(po_number="PO-US04-OBS", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-OBS-1000", "Legacy Carbon Pipe", 100, "FT")])),
    ("US-04", "scenario-invalid-uom.txt",
     dict(po_number="PO-US04-UOM", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-STL-4520", "Carbon Steel Pipe", 100, "KG")])),
    ("US-04", "scenario-unknown-sku.txt",
     dict(po_number="PO-US04-UNK", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-UNKNOWN-9999", "Mystery Pipe Fitting", 50, "EA")])),

    # US-05 Compliance / SDS
    ("US-05", "scenario-restricted-region.txt",
     dict(po_number="PO-US05-REGION", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CA[0], ship_city_line=CA[1],
          lines=[("SKU-CHM-9100", "Industrial Solvent Drum", 20, "GAL")])),
    ("US-05", "scenario-missing-sds.txt",
     dict(po_number="PO-US05-SDS", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-CHM-9200", "Aerosol Degreaser", 15, "GAL")])),

    # US-06 Pricing
    ("US-06", "scenario-pricing-exception.txt",
     dict(po_number="PO-US06-PRICE", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-STL-4520", "Carbon Steel Pipe", 2000, "FT")])),
    ("US-06", "happy-path.txt",
     dict(po_number="PO-US06-HAPPY", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=HAPPY_LINES)),

    # US-07 Budget / Approval
    ("US-07", "scenario-budget-exceeded.txt",
     dict(po_number="PO-US07-BUDGET", customer="CUST-1002", buyer="BUY-003",
          cost_center="CC-NE-100", ship_name=NYC[0], ship_city_line=NYC[1],
          lines=[("SKU-VLV-2201", "Ball Valve 2 inch", 1400, "EA")])),
    ("US-07", "scenario-approval-required.txt",
     dict(po_number="PO-US07-APPROVE", customer="CUST-1001", buyer="BUY-002",
          cost_center="CC-MW-200", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-STL-4520", "Carbon Steel Pipe", 200, "FT"),
                 ("SKU-FLG-3010", "Stainless Steel Flange", 80, "EA")])),

    # US-08 Credit
    ("US-08", "scenario-credit-hold.txt",
     dict(po_number="PO-US08-CREDIT", customer="CUST-1002", buyer="BUY-003",
          cost_center="CC-NE-100", ship_name=NYC[0], ship_city_line=NYC[1],
          lines=[("SKU-STL-4520", "Carbon Steel Pipe", 200, "FT")])),

    # US-09 Inventory
    ("US-09", "scenario-inventory-shortage.txt",
     dict(po_number="PO-US09-INV", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-PMP-7700", "Centrifugal Pump 5HP", 10, "EA")])),

    # US-10 Logistics
    ("US-10", "scenario-zip-not-serviceable.txt",
     dict(po_number="PO-US10-ZIP", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=AK[0], ship_city_line=AK[1],
          lines=[("SKU-STL-4520", "Carbon Steel Pipe", 200, "FT")])),

    # US-11 Exception Governance
    ("US-11", "happy-autonomous.txt",
     dict(po_number="PO-US11-AUTO", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=HAPPY_LINES)),
    ("US-11", "scenario-governed-exception.txt",
     dict(po_number="PO-US11-GOV", customer="CUST-1002", buyer="BUY-003",
          cost_center="CC-NE-100", ship_name=NYC[0], ship_city_line=NYC[1],
          lines=[("SKU-STL-4520", "Carbon Steel Pipe", 200, "FT")])),

    # US-12 Execution
    ("US-12", "happy-path.txt",
     dict(po_number="PO-US12-HAPPY", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=HAPPY_LINES)),
    ("US-12", "scenario-execution-failure.txt",
     dict(po_number="PO-2026-FAIL-001", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=HAPPY_LINES)),
]


def main():
    for folder, fname, kwargs in SAMPLES:
        d = os.path.join(BASE, folder)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, fname), "w", encoding="utf-8") as f:
            f.write(po_text(**kwargs))
        print("Created:", os.path.join("sample-data", folder, fname))
    print(f"\n{len(SAMPLES)} sample PO files created.")


if __name__ == "__main__":
    main()
