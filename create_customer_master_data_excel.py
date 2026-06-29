"""
Generates the customer master data workbook: mock-data/customer-master-data.xlsx
Run once:  python create_customer_master_data_excel.py

Sheets:
  Customer_Master   - customer accounts + ERP customer records + CRM/account records
  Account_Hierarchy - branch -> regional division -> global parent mapping
  Ship_To_Master    - ship-to locations with ZIP and owning branch
  Hierarchy_Rules   - rules defined at each hierarchy level (most specific wins)

NOTE: For the POC there is NO real ERP / CRM / WMS / OMS / SMTP. This workbook
simulates the customer-side "Systems / Data Needed" for account validation.
Other master data (e.g. product master) will live in its own workbook.
"""
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import os

OUT_DIR = os.path.join(os.path.dirname(__file__), "mock-data")
os.makedirs(OUT_DIR, exist_ok=True)

NAVY  = "1E3A5F"
LBLUE = "DBEAFE"
thin  = Side(style="thin", color="AAAAAA")


def _border():
    return Border(left=thin, right=thin, top=thin, bottom=thin)


def write_sheet(ws, title, headers, rows, widths):
    # Title banner
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    c = ws.cell(row=1, column=1, value=title)
    c.font = Font(bold=True, size=14, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor=NAVY)
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 26

    # Header row
    for ci, h in enumerate(headers, 1):
        cell = ws.cell(row=2, column=ci, value=h)
        cell.font = Font(bold=True, size=11, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2563EB")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = _border()
    ws.row_dimensions[2].height = 22

    # Data rows
    for ri, rowdata in enumerate(rows, start=3):
        for ci, val in enumerate(rowdata, 1):
            cell = ws.cell(row=ri, column=ci, value=val)
            cell.font = Font(size=11)
            cell.fill = PatternFill("solid", fgColor=LBLUE if ri % 2 == 0 else "FFFFFF")
            cell.alignment = Alignment(vertical="center")
            cell.border = _border()

    for ci, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(ci)].width = w


wb = openpyxl.Workbook()

# ── Sheet 1: Customer_Master (incl. ERP + CRM records) ─────────────────────────
ws1 = wb.active
ws1.title = "Customer_Master"
write_sheet(
    ws1,
    "CUSTOMER MASTER  (includes ERP customer records + CRM / account records)",
    ["customer_account", "company_name", "status", "branch_id",
     "erp_customer_id", "crm_account_id"],
    [
        ["CUST-1001", "Great Lakes Plumbing Supply Co",  "ACTIVE", "BR-GLP-MW", "ERP-GL-7781", "CRM-GLP-001"],
        ["CUST-1002", "Eastern Kitchen & Bath Distributors", "ACTIVE", "BR-GLP-NE", "ERP-GL-7782", "CRM-GLP-002"],
        ["CUST-2001", "Continental Canada Distribution", "ACTIVE", "BR-GLP-CA", "ERP-GL-7790", "CRM-GLP-010"],
        ["CUST-5001", "Pacific Coast Bath & Kitchen",    "ACTIVE", "BR-PCBK-WEST", "ERP-PC-3310", "CRM-PCBK-001"],
        ["CUST-7000", "Midtown Building Supply",         "ACTIVE", "BR-GLP-MW", "ERP-MT-9001", "CRM-MT-001"],
        ["CUST-7000", "Midtown Building Supply (Legacy)","ACTIVE", "BR-GLP-NE", "ERP-MT-9002", "CRM-MT-002"],
    ],
    [18, 32, 10, 16, 16, 18],
)

# ── Sheet 2: Account_Hierarchy ─────────────────────────────────────────────────
ws2 = wb.create_sheet("Account_Hierarchy")
write_sheet(
    ws2,
    "ACCOUNT HIERARCHY  (branch -> regional division -> global parent)",
    ["branch_id", "branch_name", "regional_division_id", "regional_division_name",
     "global_parent_id", "global_parent_name"],
    [
        ["BR-GLP-MW", "Great Lakes Midwest Branch",   "RD-CONT-NA", "Continental North America", "GP-CONT", "Continental Building Products Group"],
        ["BR-GLP-NE", "Great Lakes Northeast Branch", "RD-CONT-NA", "Continental North America", "GP-CONT", "Continental Building Products Group"],
        ["BR-GLP-CA", "Great Lakes Canada Branch",    "RD-CONT-CA", "Continental Canada",        "GP-CONT", "Continental Building Products Group"],
        ["BR-PCBK-WEST", "Pacific Coast West Branch",  "RD-WSH-NA", "Western Supply North America", "GP-WSH", "Western Supply Holdings"],
    ],
    [16, 26, 20, 24, 16, 24],
)

# ── Sheet 3: Ship_To_Master ────────────────────────────────────────────────────
ws3 = wb.create_sheet("Ship_To_Master")
write_sheet(
    ws3,
    "SHIP-TO MASTER  (ship-to locations matched by ZIP)",
    ["ship_to_id", "name", "address", "zip", "branch_id", "status"],
    [
        ["ST-CHI-001", "Great Lakes Plumbing - Chicago DC", "4500 West Diversey Avenue, Chicago, IL", "60639", "BR-GLP-MW", "ACTIVE"],
        ["ST-DET-002", "Great Lakes Plumbing - Detroit Branch", "1200 Woodward Avenue, Detroit, MI", "48201", "BR-GLP-MW", "ACTIVE"],
        ["ST-NYC-003", "Eastern Kitchen & Bath - New York DC", "55 Water Street, New York, NY", "10001", "BR-GLP-NE", "ACTIVE"],
        ["ST-LON-004", "Continental Canada - Toronto Depot", "120 Bremner Boulevard, Toronto, ON", "M5J2N1", "BR-GLP-CA", "ACTIVE"],
        ["ST-LA-005", "Pacific Coast - Los Angeles DC", "800 South Hope Street, Los Angeles, CA", "90001", "BR-PCBK-WEST", "ACTIVE"],
        ["ST-AK-006", "Great Lakes - Ketchikan Project Site", "1 Industrial Rd, Ketchikan, AK", "99950", "BR-GLP-MW", "ACTIVE"],
        ["ST-CA-007", "Great Lakes - Beverly Hills Showroom Project", "9000 Sunset Blvd, Beverly Hills, CA", "90210", "BR-GLP-MW", "ACTIVE"],
    ],
    [14, 32, 40, 10, 16, 10],
)

# ── Sheet 4: Hierarchy_Rules ───────────────────────────────────────────────────
# The `fulfillment_rule` column stores a RULE PROFILE ID. The actual structured
# business rules (preferred warehouse, split allowed, backorder allowed, etc.)
# are defined in the Fulfillment_Rules sheet below and looked up by this ID.
ws4 = wb.create_sheet("Hierarchy_Rules")
write_sheet(
    ws4,
    "HIERARCHY RULES  (blank = rule not set at that level; most specific level wins)",
    ["level_type", "level_id", "pricing_tier", "product_visibility",
     "budget_limit", "approval_routing", "fulfillment_rule"],
    [
        # Global parents
        ["global_parent", "GP-CONT", "TIER-3", "GLOBAL_CATALOG",  5000000, "CORPORATE_PROCUREMENT", "RULE-GLOBAL-STD"],
        ["global_parent", "GP-WSH",  "TIER-1", "STANDARD_CATALOG", 2000000, "CORPORATE_PROCUREMENT", "RULE-GLOBAL-STD"],
        # Regional divisions
        ["regional_division", "RD-CONT-NA", "TIER-2",    "", "", "REGIONAL_MANAGER",    "RULE-NA-STD"],
        ["regional_division", "RD-CONT-CA", "TIER-2-CA", "", "", "CA_REGIONAL_MANAGER", "RULE-CA-STD"],
        ["regional_division", "RD-WSH-NA", "TIER-1",  "", "", "REGIONAL_MANAGER",    ""],
        # Branches
        ["branch", "BR-GLP-MW", "", "", 500000, "BRANCH_MANAGER", "RULE-MW-STD"],
        ["branch", "BR-GLP-NE", "", "", 350000, "BRANCH_MANAGER", ""],
        ["branch", "BR-GLP-CA", "", "", 300000, "BRANCH_MANAGER", ""],
        ["branch", "BR-PCBK-WEST", "", "", 400000, "BRANCH_MANAGER", "RULE-WEST-STD"],
        # Ship-to (most specific level — overrides any branch/regional default)
        ["ship_to", "ST-CHI-001", "", "", "", "SITE_SUPERVISOR", "RULE-CHI-PRIORITY"],
        ["ship_to", "ST-DET-002", "", "", "", "", "RULE-DET-NO-SPLIT"],
        ["ship_to", "ST-NYC-003", "", "", "", "", "RULE-NYC-BACKORDER-OK"],
        ["ship_to", "ST-LON-004", "", "", "", "", "RULE-CA-STD"],
        ["ship_to", "ST-LA-005", "", "", "", "", "RULE-LA-RESTRICTED"],
        ["ship_to", "ST-CA-007", "", "", "", "", "RULE-LARGE-MOQ"],
    ],
    [18, 16, 12, 18, 14, 22, 22],
)

# ── Sheet 5: Fulfillment_Rules ─────────────────────────────────────────────────
# Each row defines the actual business rules behind a fulfillment_rule profile
# referenced from Hierarchy_Rules. Validators in US-09 (inventory) and US-10
# (logistics) read these columns to decide:
#   - preferred_warehouse        first DC to attempt fulfillment from
#   - alternate_warehouses       fallback DCs to try (in order)
#   - restricted_warehouses      DCs that must NEVER be used for this customer
#   - split_shipment_allowed     Y = order may be split across DCs
#                                N = must ship in a single shipment
#   - backorder_allowed          Y = partial fulfillment OK; remainder backordered
#                                N = if not fully available, raise an exception
#   - max_backorder_days         max days the customer will accept for backorder
#   - min_order_qty              minimum total order quantity (lines aggregated)
#   - delivery_sla_days          target days from order to delivery
#   - allocation_priority        used when inventory is constrained
ws5 = wb.create_sheet("Fulfillment_Rules")
write_sheet(
    ws5,
    "FULFILLMENT RULES  (business rules referenced by hierarchy fulfillment_rule)",
    ["rule_id", "rule_name", "preferred_warehouse", "alternate_warehouses",
     "restricted_warehouses", "split_shipment_allowed", "backorder_allowed",
     "max_backorder_days", "min_order_qty", "delivery_sla_days",
     "allocation_priority", "description"],
    [
        ["RULE-GLOBAL-STD",       "Global standard",
         "DC-CHI-01", "DC-DET-02,DC-LA-05", "",
         "Y", "Y", 15, 1, 7, "SILVER",
         "Default global rule. Ship from nearest DC; split and backorder allowed."],

        ["RULE-NA-STD",           "North America standard",
         "DC-CHI-01", "DC-DET-02", "",
         "Y", "Y", 10, 1, 5, "SILVER",
         "Ship from Chicago first, then Detroit. Split and backorder allowed."],

        ["RULE-CA-STD",           "Canada standard",
         "DC-TOR-10", "", "",
         "Y", "N", 0, 1, 7, "SILVER",
         "Ship from Toronto depot only. Split allowed; no backorder (must be fully available)."],

        ["RULE-MW-STD",           "Midwest standard",
         "DC-CHI-01", "DC-DET-02", "",
         "Y", "Y", 10, 1, 4, "SILVER",
         "Ship from Chicago (preferred) or Detroit; split and short backorder allowed."],

        ["RULE-WEST-STD",         "West Coast standard",
         "DC-LA-05", "", "",
         "Y", "Y", 7, 1, 4, "SILVER",
         "Ship from LA DC. Split allowed; short backorder window."],

        ["RULE-CHI-PRIORITY",     "Priority Chicago (GOLD)",
         "DC-CHI-01", "DC-DET-02", "",
         "Y", "Y", 5, 1, 2, "GOLD",
         "Ship priority from Chicago DC. Same-day priority; minor backorder allowed."],

        ["RULE-DET-NO-SPLIT",     "Detroit single-shipment",
         "DC-DET-02", "DC-CHI-01", "",
         "N", "N", 0, 1, 5, "SILVER",
         "Customer requires one shipment, no split, no backorder. Full quantity must "
         "come from a single DC or the order is held for CSR review."],

        ["RULE-NYC-BACKORDER-OK", "NYC backorder allowed",
         "DC-NYC-03", "DC-CHI-01", "",
         "Y", "Y", 20, 1, 6, "SILVER",
         "Customer accepts long backorder windows. Ship what's available from NYC, "
         "backorder the rest up to 20 days."],

        ["RULE-LA-RESTRICTED",    "LA DC restricted",
         "DC-CHI-01", "DC-DET-02", "DC-LA-05",
         "Y", "Y", 10, 1, 6, "SILVER",
         "LA DC is restricted (customer audit failure). Must ship from Chicago/Detroit "
         "even if LA has stock."],

        ["RULE-LARGE-MOQ",        "Large minimum order quantity",
         "DC-CHI-01", "DC-DET-02", "",
         "Y", "Y", 7, 500, 5, "GOLD",
         "Bulk customer. Minimum total order quantity = 500 units. Smaller orders "
         "are rejected to protect margins."],
    ],
    [22, 28, 18, 22, 22, 14, 14, 14, 14, 14, 14, 48],
)

out = os.path.join(OUT_DIR, "customer-master-data.xlsx")
wb.save(out)
print("Created:", out)
