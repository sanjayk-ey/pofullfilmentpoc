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
            lines, contract="CONTRACT-GLP-2026-007", date="15 July 2026",
            instr="Deliver to receiving dock. Pallet jack required on site."):
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


CHI = ("Great Lakes Plumbing - Chicago DC", "4500 West Diversey Avenue, Chicago, IL 60639")
NYC = ("Eastern Kitchen & Bath - New York DC", "55 Water Street, New York, NY 10001")
AK  = ("Great Lakes - Ketchikan Project Site", "1 Industrial Rd, Ketchikan, AK 99950")
CA  = ("Great Lakes - Beverly Hills Showroom Project", "9000 Sunset Blvd, Beverly Hills, CA 90210")

HAPPY_LINES = [
    ("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 200, "EA"),
    ("SKU-DRN-3010", "Pop-Up Drain Assembly", 80, "EA"),
    ("SKU-VLV-2201", "Pressure-Balancing Shower Valve", 25, "EA"),
]

# (relative folder, filename, kwargs)
SAMPLES = [
    # US-03 Buyer Authorization
    ("US-03", "happy-path.txt",
     dict(po_number="PO-2026-10030", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 200, "EA")])),
    ("US-03", "scenario-unauthorized-buyer.txt",
     dict(po_number="PO-2026-10031", customer="CUST-1001", buyer="BUY-900",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 200, "EA")])),
    ("US-03", "scenario-restricted-product.txt",
     dict(po_number="PO-2026-10032", customer="CUST-1001", buyer="BUY-002",
          cost_center="CC-MW-200", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-VLV-2201", "Pressure-Balancing Shower Valve", 10, "EA")])),
    ("US-03", "scenario-invalid-cost-center.txt",
     dict(po_number="PO-2026-10033", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-OLD-900", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 200, "EA")])),

    # US-04 Product Matching / UOM
    ("US-04", "scenario-obsolete-sku.txt",
     dict(po_number="PO-2026-10040", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-CTG-1000", "Legacy 2-Handle Faucet Cartridge", 100, "EA")])),
    ("US-04", "scenario-invalid-uom.txt",
     dict(po_number="PO-2026-10041", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 100, "KG")])),
    ("US-04", "scenario-unknown-sku.txt",
     dict(po_number="PO-2026-10042", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-CTG-0000", "Unlisted Fixture Trim Kit", 50, "EA")])),

    # US-05 Compliance / SDS
    ("US-05", "scenario-restricted-region.txt",
     dict(po_number="PO-2026-10050", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CA[0], ship_city_line=CA[1],
          lines=[("SKU-FIN-9100", "Enameled Cast Iron Touch-Up Finish", 20, "GAL")])),
    ("US-05", "scenario-missing-sds.txt",
     dict(po_number="PO-2026-10051", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-FIN-9200", "Cast Iron Touch-Up Aerosol", 15, "GAL")])),

    # US-06 Pricing
    ("US-06", "scenario-pricing-exception.txt",
     dict(po_number="PO-2026-10060", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 2000, "EA")])),
    ("US-06", "happy-path.txt",
     dict(po_number="PO-2026-10061", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=HAPPY_LINES)),

    # US-07 Budget / Approval
    ("US-07", "scenario-budget-exceeded.txt",
     dict(po_number="PO-2026-10070", customer="CUST-1002", buyer="BUY-003",
          cost_center="CC-NE-100", ship_name=NYC[0], ship_city_line=NYC[1],
          lines=[("SKU-VLV-2201", "Pressure-Balancing Shower Valve", 1400, "EA")])),
    ("US-07", "scenario-approval-required.txt",
     dict(po_number="PO-2026-10071", customer="CUST-1001", buyer="BUY-002",
          cost_center="CC-MW-200", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 200, "EA"),
                 ("SKU-DRN-3010", "Pop-Up Drain Assembly", 80, "EA")])),

    # US-08 Credit
    ("US-08", "scenario-credit-hold.txt",
     dict(po_number="PO-2026-10080", customer="CUST-1002", buyer="BUY-003",
          cost_center="CC-NE-100", ship_name=NYC[0], ship_city_line=NYC[1],
          lines=[("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 200, "EA")])),

    # US-09 Inventory
    ("US-09", "scenario-inventory-shortage.txt",
     dict(po_number="PO-2026-10090", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=[("SKU-SHS-7700", "Digital Shower Interface System", 10, "EA")])),

    # US-10 Logistics
    ("US-10", "scenario-zip-not-serviceable.txt",
     dict(po_number="PO-2026-10100", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=AK[0], ship_city_line=AK[1],
          lines=[("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 200, "EA")])),

    # US-11 Exception Governance
    ("US-11", "happy-autonomous.txt",
     dict(po_number="PO-2026-10110", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=HAPPY_LINES)),
    ("US-11", "scenario-governed-exception.txt",
     dict(po_number="PO-2026-10111", customer="CUST-1002", buyer="BUY-003",
          cost_center="CC-NE-100", ship_name=NYC[0], ship_city_line=NYC[1],
          lines=[("SKU-CTG-4520", "Ceramic Disc Faucet Cartridge", 200, "EA")])),

    # US-12 Execution
    ("US-12", "happy-path.txt",
     dict(po_number="PO-2026-10120", customer="CUST-1001", buyer="BUY-001",
          cost_center="CC-MW-100", ship_name=CHI[0], ship_city_line=CHI[1],
          lines=HAPPY_LINES)),
    ("US-12", "scenario-execution-failure.txt",
     dict(po_number="PO-2026-10121-FAIL", customer="CUST-1001", buyer="BUY-001",
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
