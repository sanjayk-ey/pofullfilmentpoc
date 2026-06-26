MOCK MASTER DATA (full PO-to-Fulfillment orchestration)
=======================================================

IMPORTANT: For the POC, NO real ERP, CRM, WMS, OMS, TMS, or SMTP systems are
used. Every "systems / data needed" input is simulated with local Excel
workbooks read by the modules in ../modules/.

DOMAIN WORKBOOKS (regenerate all new ones with: python create_master_data.py)
-----------------------------------------------------------------------------
  customer-master-data.xlsx            (US-02)  account hierarchy & ship-to
      -> python create_customer_master_data_excel.py
  buyer-master-data.xlsx               (US-03)  buyer profiles, permissions, cost
                                                centers, product visibility rules
  product-master-data.xlsx             (US-04)  product master, attributes, UOM
                                                conversions, substitution rules
  compliance-master-data.xlsx          (US-05)  compliance rules, regional
                                                restrictions, SDS repository, eligibility
  pricing-master-data.xlsx             (US-06)  price list, contracts, volume tiers,
                                                rebates, promos, surcharges, freight, margin
  budget-master-data.xlsx              (US-07)  budgets, cost centers, approval matrix
  credit-master-data.xlsx              (US-08)  credit, invoice aging, payment terms, risk
  inventory-master-data.xlsx           (US-09)  plant/DC/in-transit stock, ATP, allocation
  logistics-master-data.xlsx           (US-10)  carrier coverage, freight rating, SLA, warehouses
  exception-governance-master-data.xlsx(US-11)  severity matrix, role routing, SLA thresholds
  execution-master-data.xlsx           (US-12)  integration endpoints, templates, documents

The sections below describe customer-master-data.xlsx (US-02). The other
workbooks follow the same layout (row 1 title, row 2 headers, row 3+ data) and
their sheets/fields are documented per story in
../sample-data/US-XX/US-XX_Summary_for_Manager.docx.

FILE: customer-master-data.xlsx  (regenerate with: python create_customer_master_data_excel.py)
SHEETS
------
1. Customer_Master
   Customer accounts with company name, status, owning branch, plus the mock
   ERP customer records (erp_customer_id) and CRM/account records
   (crm_account_id). (CUST-7000 appears twice on purpose — this is the
   duplicate-customer test scenario.)

2. Account_Hierarchy
   One row per branch mapping: branch -> regional division -> global parent.
   This reconstructs the corporate tree
   Global Parent -> Regional Division -> Local Branch -> Ship-To Location.

3. Ship_To_Master
   Ship-to locations with ZIP, address, owning branch, and status. The PO
   ship-to ZIP extracted from the order is matched against this sheet.

4. Hierarchy_Rules
   Rules defined at each level (global parent, regional division, branch,
   ship-to): pricing tier, product visibility, budget, approval routing,
   fulfillment rule. A blank cell means that rule is not set at that level.
   Rules cascade — the most specific level wins (ship-to first, then branch,
   then regional, then global parent).

HIERARCHY MAP (quick reference)
-------------------------------
GP-ACME (Acme Global Holdings)
  RD-ACME-NA (Acme North America)
    BR-ACME-MW (Midwest)   -> ST-CHI-001 (ZIP 60639), ST-DET-002 (ZIP 48201)
    BR-ACME-NE (Northeast) -> ST-NYC-003 (ZIP 10001)
  RD-ACME-EU (Acme Europe)
    BR-ACME-UK (UK)        -> ST-LON-004 (ZIP E145AB)
GP-GLOBEX (Globex Corporation)
  RD-GLOBEX-NA
    BR-GLOBEX-WEST         -> ST-LA-005 (ZIP 90001)

CUSTOMER -> BRANCH MAP
----------------------
CUST-1001 Acme Industrial Supplies Ltd   -> BR-ACME-MW
CUST-1002 Acme Northeast Operations       -> BR-ACME-NE
CUST-2001 Acme UK Distribution            -> BR-ACME-UK
CUST-5001 Globex West Industrial          -> BR-GLOBEX-WEST
CUST-7000 Initech Manufacturing           -> BR-ACME-MW  (DUPLICATE)
CUST-7000 Initech Manufacturing (Legacy)  -> BR-ACME-NE  (DUPLICATE)

TEST SCENARIOS  (sample PO files in ../sample-data/)
----------------------------------------------------
HAPPY PATH      : CUST-1001 + ZIP 60639  -> resolves Chicago Warehouse under
                  Midwest Branch / North America / Acme Global. Rules applied
                  from ship-to level. Proceeds to buyer authorization.
                  File: US-01/sample-po-text.txt

UNMATCHED CUST  : CUST-9999 (not in customer master) -> "Unmatched customer"
                  exception.
                  File: US-02/scenario-unmatched-customer.txt

DUPLICATE CUST  : CUST-7000 (two master records) -> "Duplicate customer"
                  exception; both candidate records shown.
                  File: US-02/scenario-duplicate-customer.txt

INVALID SHIP-TO : CUST-1001 + ZIP 99999 (ZIP not in any ship-to master record)
                  -> "Invalid ship-to" exception; possible ship-tos for the
                  customer are listed.
                  File: US-02/scenario-invalid-shipto.txt

HIERARCHY       : CUST-1001 (Acme) + ZIP 90001 (Globex LA — exists but belongs
  MISMATCH        to a different parent) -> "Hierarchy mismatch" exception.
                  File: US-02/scenario-hierarchy-mismatch.txt
