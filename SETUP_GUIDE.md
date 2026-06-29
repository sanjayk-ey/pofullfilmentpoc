# PO Fulfillment AI Agent — Setup & User Guide

**Project:** AI PO-to-Fulfillment Orchestration  
**Module:** Full 12-Stage Orchestration Pipeline (US-01 – US-12)  
**Prepared by:** Sanjay Kumar Kesarvani  
**Date:** 26 June 2026  
**Version:** 2.0 — POC

---

## What This POC Does

This is a local Proof of Concept that demonstrates how an AI Agent can
automatically read a Purchase Order (PO), extract its key business fields,
and run it through a **12-stage orchestration pipeline** — from intake to
order creation — without manual data entry.

The system accepts a PO in two ways:
1. **Excel upload** (.xlsx files only)
2. **Text paste** (copy-paste into the chat window)

Once submitted, the AI agent processes the PO step by step (visible on screen).
Each stage either **passes** and hands off to the next, or **pauses with an
exception** that requires human intervention.

**Approval Matrix Flow:** When approval is required from an approver other than
the CSR (e.g. pricing, compliance, finance, budget approver), the system
displays a mocked notification — *"Triggered email to respective approver and
awaiting approval."* — and the process stops. No further actions are executed
until the approval is granted.

---

## Orchestration Pipeline — All 12 Stages

| # | Stage | Description | Exceptions |
|---|-------|-------------|------------|
| 1 | **PO Intake & Extraction** | Extract SKU, qty, UOM, ZIP, date, customer, contract, PO#, buyer, cost center, instructions | Missing fields; duplicate PO |
| 2 | **Account Hierarchy & Ship-To** | Resolve global parent → division → branch → ship-to; apply most-specific rules | Unmatched customer; duplicate customer; invalid ship-to; hierarchy mismatch |
| 3 | **Buyer Authorization & Product Visibility** | Validate buyer role, branch, cost center, ordering rights, product visibility | Unauthorized buyer; restricted product; invalid cost center |
| 4 | **Product Matching & UOM** | Match SKU to catalog variant, convert UOM, recommend substitutes for obsolete SKUs | Obsolete SKU; invalid UOM; product config exception |
| 5 | **Regional Compliance & SDS** | Validate product-region eligibility, attach required safety documents | Compliance restriction; missing SDS |
| 6 | **Pricing Engine** | List/contract pricing, volume tiers, rebates, promos, surcharges, freight, margin policy | Pricing exception (discount breach) |
| 7 | **Budget & Approval Routing** | Check cost-center/branch budgets, buyer authority, approval matrix | Budget exceeded; approval required |
| 8 | **Credit & Payment Terms** | Credit limit, overdue invoices, risk/watchlist, payment terms | Credit hold |
| 9 | **Inventory & ATP** | Plant/DC/in-transit/ATP check, partial fulfillment, allocation rules | Inventory shortage |
| 10 | **Logistics & SLA** | ZIP serviceability, carrier, ETA, freight rating, optimization | ZIP not serviceable; SLA miss |
| 11 | **Exception Governance** | Classify severity, route to role, attach SLA (human-in-the-loop) | All categories |
| 12 | **Order Execution** | Create ERP/OMS/WMS/TMS records, customer confirmation, audit trail | Execution failure |

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.9 or higher | Download from https://www.python.org/downloads |
| pip | Latest | Comes automatically with Python |
| Any web browser | Chrome / Edge recommended | For the Streamlit UI |

---

## Installation — Step by Step

### Step 1: Install Python (first time only)

1. Go to **https://www.python.org/downloads**
2. Click **"Download Python 3.x.x"** (latest version)
3. Run the installer
4. **IMPORTANT:** On the first installer screen, tick the box **"Add Python to PATH"** before clicking Install
5. Click **"Install Now"**
6. When done, click **Close**

To verify Python installed correctly, open Command Prompt and run:
```
python --version
```
You should see something like: `Python 3.12.x`

### Step 2: Open a terminal / command prompt

Press `Win + R`, type `cmd`, press Enter.

### Step 3: Navigate to the project folder

```
cd C:\projects\po-fullfiment-poc
```

### Step 4: (Recommended) Create a virtual environment

```
python -m venv venv
venv\Scripts\activate
```

You will see `(venv)` at the start of the command prompt when it is active.

### Step 5: Install required packages

```
python -m pip install -r requirements.txt
```

This installs: Streamlit, pandas, openpyxl, python-dateutil, python-docx.
Installation takes 1-3 minutes depending on internet speed.

### Step 6: Generate sample files and master data

```
python create_sample_excel.py
python create_customer_master_data_excel.py
python create_master_data.py
python create_sample_pos.py
```

- `create_sample_excel.py` — sample PO Excel files in `sample-data/US-01/`
- `create_customer_master_data_excel.py` — `mock-data/customer-master-data.xlsx`
- `create_master_data.py` — all other domain master-data workbooks in `mock-data/`
- `create_sample_pos.py` — per-story sample PO text files in `sample-data/US-03/` … `US-12/`

### Step 7: (Optional) Generate manager summary documents

```
python generate_story_docs.py
```

This creates a `US-XX_Summary_for_Manager.docx` inside each `sample-data/US-XX/` folder.

### Step 8: Run the application

```
python -m streamlit run app.py
```

A browser window will open automatically at `http://localhost:8501`.
If it does not open, copy and paste that URL into your browser.

---

## How to Use the Application

### Main Screen

When you open the application, you will see a chat window with a welcome message
from the AI agent. At the bottom of the screen there are two ways to submit a PO:

```
[ ➕ ]  [ Paste your PO text here, or click ➕ to upload Excel... ]
```

### Option 1: Upload Excel PO File

1. Click the **➕** button
2. An upload panel appears — click **Browse** or drag and drop an Excel file
3. **Only .xlsx and .xls files are accepted**
   - If you try to upload a PDF or any other format, the system will reject it with an error
4. Once the file is selected, the AI agent starts processing automatically

### Option 2: Paste PO Text

1. Copy your PO text (from email or document)
2. Click inside the text input box at the bottom
3. Paste the text (Ctrl+V)
4. Press **Enter** to submit

### AI Processing Display

Once a PO is submitted, you will see the AI agent processing each stage step by step:

```
🤖 AI Agent Processing — PO Text
  📄 Analyzing document format and structure...
  🔍 Reading PO header section...
  ...
✅ Processing Complete — results below

🏢 Account hierarchy validation...
✅ Account validation complete

🔐 Buyer Authorization & Product Visibility...
✅ Complete

📦 Product Matching, Configuration & UOM Validation...
✅ Complete

🛡️ Regional Compliance & SDS Validation...
✅ Complete

💲 Enterprise B2B Pricing Engine...
✅ Complete

💰 Budget, Spend Limit & Approval Routing...
✅ Complete

🏦 Credit, Payment Terms & Financial Risk...
✅ Complete

📦 Inventory Availability & ATP...
✅ Complete

🚚 Logistics, Serviceability & Delivery SLA...
✅ Complete

🧑‍⚖️ Exception Governance & Human-in-the-Loop
✅ No human intervention required

✅ Order Creation, Fulfillment & Confirmation
   (ERP/OMS/WMS/TMS records created, customer confirmation sent)
```

### Approval Flow (Non-CSR Approver)

When an exception requires approval from someone other than the CSR
(pricing approver, compliance approver, finance, budget approver), the UI shows:

> 📧 **Triggered email to respective approver and awaiting approval.**
> A notification has been sent to *[Approver Name]* (*[Role]*).

Followed by:

> ⏸ **Process halted** — no further actions will be executed until approval is
> granted or rejected.

The pipeline stops at that point. No further stages run.

---

## Sample Data Files

Sample files are organized per story under `sample-data/`:

### `sample-data/US-01/` — PO intake & data extraction

| File | Purpose |
|------|---------|
| `sample-po-happy-path.xlsx` | All fields complete — full pipeline runs to order creation |
| `sample-po-missing-fields.xlsx` | Missing Customer ID, ZIP, Delivery Date — triggers intake exception |
| `sample-po-text.txt` | Copy and paste into the chat box for a happy-path text demo |

### `sample-data/US-02/` — Account hierarchy & ship-to

| File | Purpose |
|------|---------|
| `scenario-unmatched-customer.txt` | Unmatched customer exception |
| `scenario-duplicate-customer.txt` | Duplicate customer exception |
| `scenario-invalid-shipto.txt` | Invalid ship-to exception |
| `scenario-hierarchy-mismatch.txt` | Hierarchy mismatch exception |

### `sample-data/US-03/` — Buyer authorization

| File | Purpose |
|------|---------|
| `happy-path.txt` | Authorized buyer — passes to product validation |
| `scenario-unauthorized-buyer.txt` | Suspended buyer — unauthorized exception |
| `scenario-restricted-product.txt` | Junior buyer ordering denied product — restricted exception |
| `scenario-invalid-cost-center.txt` | Inactive cost center — invalid cost center exception |

### `sample-data/US-04/` — Product matching & UOM

| File | Purpose |
|------|---------|
| `scenario-obsolete-sku.txt` | Obsolete SKU — substitution recommendation |
| `scenario-invalid-uom.txt` | KG cannot convert to FT — invalid UOM exception |
| `scenario-unknown-sku.txt` | Unknown SKU — product config exception with possible matches |

### `sample-data/US-05/` — Compliance & SDS

| File | Purpose |
|------|---------|
| `scenario-restricted-region.txt` | Chemical to California — compliance restriction + email to approver |
| `scenario-missing-sds.txt` | Hazardous product without SDS — missing SDS exception + email to approver |

### `sample-data/US-06/` — Pricing

| File | Purpose |
|------|---------|
| `happy-path.txt` | Priced within policy — proceeds to budget |
| `scenario-pricing-exception.txt` | Discount exceeds policy — pricing exception + email to approver |

### `sample-data/US-07/` — Budget & approval

| File | Purpose |
|------|---------|
| `scenario-budget-exceeded.txt` | Order exceeds budget — budget exception + email to approver |
| `scenario-approval-required.txt` | Order above buyer limit — approval task + email to approver, process halted |

### `sample-data/US-08/` — Credit

| File | Purpose |
|------|---------|
| `scenario-credit-hold.txt` | Overdue invoices — credit hold + email to finance |

### `sample-data/US-09/` — Inventory

| File | Purpose |
|------|---------|
| `scenario-inventory-shortage.txt` | Pump quantity exceeds ATP — partial fulfillment proposal |

### `sample-data/US-10/` — Logistics

| File | Purpose |
|------|---------|
| `scenario-zip-not-serviceable.txt` | Alaska ZIP not serviceable — alternatives suggested |

### `sample-data/US-11/` — Exception governance

| File | Purpose |
|------|---------|
| `happy-autonomous.txt` | Full pass — "No human intervention required" |
| `scenario-governed-exception.txt` | Exception routed with severity, role, SLA |

### `sample-data/US-12/` — Order execution

| File | Purpose |
|------|---------|
| `happy-path.txt` | Full execution — ERP/OMS/WMS/TMS created, confirmation sent |
| `scenario-execution-failure.txt` | Mock WMS outage — execution exception |

---

## Demo Scenarios for Manager Presentation

### Demo 1: Happy Path — Full Pipeline (Text)
1. Open `sample-data/US-01/sample-po-text.txt`, copy all text
2. Paste into the chat input box, press Enter
3. Watch the AI agent run through all 12 stages
4. Result: Order created, customer confirmation displayed

### Demo 2: Happy Path — Excel Upload
1. Click **➕**
2. Upload `sample-data/US-01/sample-po-happy-path.xlsx`
3. Watch full pipeline — same result as Demo 1

### Demo 3: Missing Fields Exception
1. Upload `sample-data/US-01/sample-po-missing-fields.xlsx`
2. Result: Yellow warning listing missing fields, processing paused

### Demo 4: Duplicate PO Exception
1. Upload `sample-data/US-01/sample-po-happy-path.xlsx` (first time — succeeds)
2. Upload the same file again immediately
3. Result: Red error — duplicate PO detected

### Demo 5: Approval Matrix — Email + Process Halt
1. Paste `sample-data/US-07/scenario-approval-required.txt`
2. Watch stages run until Budget & Approval
3. Result: "Triggered email to respective approver and awaiting approval." +
   "Process halted — no further actions will be executed."

### Demo 6: Credit Hold — Email to Finance
1. Paste `sample-data/US-08/scenario-credit-hold.txt`
2. Result: Credit hold exception + email sent to Finance team

### Demo 7: Compliance Restriction
1. Paste `sample-data/US-05/scenario-restricted-region.txt`
2. Result: VOC-restricted finish blocked for California + email to compliance approver

### Demo 8: Inventory Shortage — Partial Fulfillment
1. Paste `sample-data/US-09/scenario-inventory-shortage.txt`
2. Result: Partial fulfillment proposal with available, backordered, and ETA

### Demo 9: Full Autonomous Order (No Exceptions)
1. Paste `sample-data/US-11/happy-autonomous.txt`
2. Result: All 12 stages pass, governance says "No human intervention required",
   order created and confirmed end-to-end

---

## Project Structure

```
po-fullfiment-poc/
├── app.py                        ← Main Streamlit application (12-stage pipeline)
├── requirements.txt              ← Python package dependencies
├── SETUP_GUIDE.md                ← This file
│
├── .streamlit/
│   └── config.toml               ← Streamlit theme and settings
│
├── modules/
│   ├── extractor.py              ← Rule-based PO field extraction engine
│   ├── excel_parser.py           ← Excel file reader and parser
│   ├── duplicate_checker.py      ← Duplicate PO detection (JSON store)
│   ├── account_validator.py      ← Account hierarchy & ship-to validation
│   ├── stage_result.py           ← Uniform stage result object
│   ├── xlsx_util.py              ← Shared master-data readers
│   ├── pipeline.py               ← Orchestration runner + context builder
│   ├── buyer_authorization.py    ← Buyer auth & product visibility
│   ├── product_matcher.py        ← Product match, config, UOM
│   ├── compliance_validator.py   ← Regional compliance & SDS
│   ├── pricing_engine.py         ← Enterprise B2B pricing
│   ├── budget_approval.py        ← Budget & approval routing
│   ├── credit_validator.py       ← Credit & payment terms
│   ├── inventory_validator.py    ← Inventory & ATP
│   ├── logistics_validator.py    ← Logistics & SLA
│   ├── exception_governance.py   ← Exception routing (human-in-the-loop)
│   └── order_execution.py        ← Downstream creation, confirmation, audit
│
├── create_sample_excel.py        ← Generate sample PO Excel files (US-01)
├── create_sample_pos.py          ← Generate per-story sample PO text files
├── create_customer_master_data_excel.py  ← Generate customer-master-data.xlsx
├── create_master_data.py         ← Generate all domain master-data workbooks
├── generate_story_docs.py        ← Generate per-story manager .docx
├── test_validation.py            ← Account validation test harness
├── test_pipeline.py              ← End-to-end pipeline test harness (22 cases)
│
├── mock-data/                    ← Mock master data workbooks + README
│   ├── customer-master-data.xlsx
│   ├── buyer-master-data.xlsx
│   ├── product-master-data.xlsx
│   ├── compliance-master-data.xlsx
│   ├── pricing-master-data.xlsx
│   ├── budget-master-data.xlsx
│   ├── credit-master-data.xlsx
│   ├── inventory-master-data.xlsx
│   ├── logistics-master-data.xlsx
│   ├── exception-governance-master-data.xlsx
│   ├── execution-master-data.xlsx
│   └── README.txt
│
├── sample-data/                  ← Sample POs + manager docs per story
│   ├── US-01/ … US-12/
│   │   ├── *.txt                 ← Sample PO text files
│   │   └── US-XX_Summary_for_Manager.docx
│
└── data/
    └── submitted_pos.json        ← Auto-created — stores submitted PO log
```

---

## Technical Notes

- **No external API required** — extraction works entirely with rule-based patterns
- **No real integrations** — all domain data is mocked in Excel workbooks under `mock-data/`
- **No database** — duplicate PO log stored in `data/submitted_pos.json`
- **Single user** — designed for one user at a time on local machine
- **File type restriction** — only .xlsx and .xls files accepted for upload
- **Tests** — run `python test_pipeline.py` (22 cases) and `python test_validation.py` (5 cases)

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `streamlit: command not found` | Run `pip install streamlit` again or check venv is activated |
| Browser does not open | Go to http://localhost:8501 manually |
| Port 8501 in use | Run `python -m streamlit run app.py --server.port 8502` |
| Excel file shows parsing error | Ensure the file is a real Excel format, not a renamed CSV |
| Duplicate not detected | Check `data/submitted_pos.json` — use the sidebar "Clear submitted PO logs" button to reset |
| Account validation skipped | It runs only after a clean extraction (no missing fields, not a duplicate) |
| Pipeline stages not running | Ensure all master-data workbooks exist: run `python create_master_data.py` |
| Master data not found | Run `python create_customer_master_data_excel.py` and `python create_master_data.py` |
