MOCK MASTER DATA (Corporate Account Hierarchy & Ship-To Validation)
===================================================================

IMPORTANT: For the POC, NO real ERP, CRM, WMS, OMS, or SMTP systems are used.
All "systems / data needed" are simulated with a single local Excel
workbook (master-data.xlsx) read by modules/account_validator.py.

FILE: master-data.xlsx  (regenerate with: python create_master_data_excel.py)
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
                  File: sample-po-text.txt

UNMATCHED CUST  : CUST-9999 (not in customer master) -> "Unmatched customer"
                  exception.
                  File: scenario-unmatched-customer.txt

DUPLICATE CUST  : CUST-7000 (two master records) -> "Duplicate customer"
                  exception; both candidate records shown.
                  File: scenario-duplicate-customer.txt

INVALID SHIP-TO : CUST-1001 + ZIP 99999 (ZIP not in any ship-to master record)
                  -> "Invalid ship-to" exception; possible ship-tos for the
                  customer are listed.
                  File: scenario-invalid-shipto.txt

HIERARCHY       : CUST-1001 (Acme) + ZIP 90001 (Globex LA — exists but belongs
  MISMATCH        to a different parent) -> "Hierarchy mismatch" exception.
                  File: scenario-hierarchy-mismatch.txt
