# PO Fulfillment AI Agent — Setup & User Guide

**Project:** AI PO-to-Fulfillment Orchestration  
**Module:** PO Intake, Data Extraction & Account Hierarchy Validation  
**Prepared by:** Sanjay Kumar Kesarvani  
**Date:** 24 June 2026  
**Version:** 1.0 — POC

---

## What This POC Does

This is a local Proof of Concept that demonstrates how an AI Agent can automatically
read a Purchase Order (PO) and extract all key business fields — without manual data entry.

The system accepts a PO in two ways:
1. **Excel upload** (.xlsx files only)
2. **Text paste** (copy-paste into the chat window)

Once submitted, the AI agent processes the PO step by step (visible on screen),
extracts all fields, and shows a structured result with confidence scores.

---

## Capabilities Implemented

| Capability | Description | Status |
|-----------|-------------|--------|
| PO field extraction | Extract all mandatory PO fields (SKU, Qty, UOM, ZIP, Date, Account, Contract, PO#, Instructions) | ✅ Done |
| Missing-field detection | Flag missing mandatory fields and pause processing | ✅ Done |
| Duplicate PO detection | Detect duplicate PO and prevent reprocessing | ✅ Done |
| Account hierarchy validation | Resolve customer hierarchy, validate ship-to, apply most-specific rules | ✅ Done |
| Hierarchy exceptions | Unmatched customer, duplicate customer, invalid ship-to, hierarchy mismatch | ✅ Done |

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

This installs: Streamlit, pandas, openpyxl, python-dateutil.
Installation takes 1-3 minutes depending on internet speed.

### Step 6: Create sample Excel files and master data

```
python create_sample_excel.py
python create_master_data_excel.py
```

The first creates sample PO Excel files in `sample-data/`.
The second creates the master data workbook `mock-data/master-data.xlsx`
(customer master, account hierarchy, ship-to master, ERP/CRM records) used by
the account-hierarchy validation.

### Step 7: Run the application

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

Once a PO is submitted, you will see the AI agent processing it step by step:

```
🤖 AI Agent Processing PO Text...
  📄 Analyzing document format and structure...
  🔍 Reading PO header section...
  🔢 Extracting Purchase Order number...
  👤 Identifying customer account information...
  📦 Scanning order line items (SKU / Qty / UOM)...
  ...
✅ Processing Complete — see results below
```

### Results Display

After processing, the AI agent shows:

1. **Status banner** — PASS (green), WARNING (yellow), or ERROR (red)
2. **Overall Confidence** — percentage bar showing extraction quality
3. **Header Fields table** — all extracted fields with confidence per field
4. **Order Lines table** — all SKUs, quantities, UOM, and prices found

### Exception Handling

**Missing Fields:**
If mandatory fields (Customer Account, PO Number, ZIP, Delivery Date) are missing,
the system shows a yellow warning and lists each missing field. Processing is paused.

**Duplicate PO:**
If the same PO Number and Customer Account combination was already submitted,
the system shows a red error and blocks reprocessing. The original submission
details (timestamp, status) are displayed.

**Account hierarchy exceptions:**
After a clean extraction, the agent validates the customer and ship-to against the
master data and raises one of: unmatched customer, duplicate customer, invalid
ship-to, or hierarchy mismatch — each with the detail needed to resolve it.

---

## Sample Data Files

All sample files are in the `sample-data/` folder:

| File | Purpose |
|------|---------|
| `sample-po-happy-path.xlsx` | All fields complete — processes with no exceptions |
| `sample-po-missing-fields.xlsx` | Intentionally missing Customer ID, ZIP, Delivery Date — triggers a missing-field exception |
| `sample-po-text.txt` | Copy and paste this text into the chat box for a happy-path text demo |
| `scenario-unmatched-customer.txt` | Customer not in master — triggers unmatched-customer exception |
| `scenario-duplicate-customer.txt` | Customer matches two records — triggers duplicate-customer exception |
| `scenario-invalid-shipto.txt` | Ship-to ZIP not registered — triggers invalid ship-to exception |
| `scenario-hierarchy-mismatch.txt` | Ship-to belongs to another parent — triggers hierarchy-mismatch exception |

---

## Demo Scenarios for Manager Presentation

### Demo 1: Happy Path — Excel Upload
1. Click **➕**
2. Upload `sample-po-happy-path.xlsx`
3. Watch the AI process step by step
4. Result: All fields extracted, confidence scores shown, order proceeds

### Demo 2: Missing Fields Exception
1. Click **➕**
2. Upload `sample-po-missing-fields.xlsx`
3. Watch AI processing
4. Result: Yellow warning showing which fields are missing

### Demo 3: Duplicate PO Exception
1. Upload `sample-po-happy-path.xlsx` (first time — succeeds)
2. Upload the same file again immediately
3. Result: Red error showing duplicate PO detected with original submission details

### Demo 4: Text Paste (Happy Path + Account Validation)
1. Open `sample-data/sample-po-text.txt`, copy all text
2. Paste into the chat input box, press Enter
3. Watch extraction, then account hierarchy validation with applied rules

### Demo 5: Account Hierarchy Exceptions
Paste the text of any of these files to trigger the matching exception:
- `scenario-unmatched-customer.txt`
- `scenario-duplicate-customer.txt`
- `scenario-invalid-shipto.txt`
- `scenario-hierarchy-mismatch.txt`

---

## Project Structure

```
po-fullfiment-poc/
├── app.py                        ← Main Streamlit application (run this)
├── requirements.txt              ← Python package dependencies
├── create_sample_excel.py        ← Script to create sample Excel files
├── SETUP_GUIDE.md                ← This file
│
├── .streamlit/
│   └── config.toml               ← Streamlit theme and settings
│
├── modules/
│   ├── extractor.py              ← AI rule-based PO field extraction engine
│   ├── excel_parser.py           ← Excel file reader and parser
│   ├── duplicate_checker.py      ← Duplicate PO detection (JSON store)
│   └── account_validator.py      ← Account hierarchy & ship-to validation (Excel master data)
│
├── create_master_data_excel.py  ← Script to create the master-data.xlsx workbook
│
├── mock-data/
│   ├── master-data.xlsx          ← Mock customer/hierarchy/ship-to/rules master
│   └── README.txt                ← Master data structure and test scenarios
│
├── sample-data/
│   ├── sample-po-happy-path.xlsx ← Sample Excel PO (all fields present)
│   ├── sample-po-missing-fields.xlsx ← Sample Excel PO (missing fields)
│   ├── sample-po-text.txt        ← Happy-path text PO for copy-paste testing
│   └── scenario-*.txt            ← Account hierarchy exception scenarios
│
└── data/
    └── submitted_pos.json        ← Auto-created — stores submitted PO log
```

---

## Fields Extracted

| Field | Mandatory | Source |
|-------|-----------|--------|
| PO Number | Yes | Pattern matching on PO/Order Number labels |
| Customer Account | Yes | Pattern matching on Customer ID/Account labels |
| SKU | Yes | Pattern matching on SKU/Part Number in order lines |
| Quantity | Yes | Number extraction from order line rows |
| Unit of Measure (UOM) | Yes | Known UOM code matching (EA, FT, KG, etc.) |
| Ship-To ZIP Code | Yes | ZIP code pattern near shipping keywords |
| Requested Delivery Date | Yes | Date pattern near Delivery/Ship labels |
| Contract Reference | No | Pattern matching on Contract/Agreement labels |
| Delivery Instructions | No | Text after Delivery Instructions/Notes labels |

---

## Technical Notes

- **No external API required** — extraction works entirely with rule-based patterns
- **No real integrations** — customer/hierarchy/ship-to data is mocked in `mock-data/master-data.xlsx`
- **No database** — duplicate PO log stored in `data/submitted_pos.json`
- **Single user** — designed for one user at a time on local machine
- **File type restriction** — only .xlsx and .xls files accepted for upload

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
| Master data not found | Run `python create_master_data_excel.py` to (re)generate `mock-data/master-data.xlsx` |

---

## Next Steps (After POC Approval)

- Buyer authorization and product visibility check
- Product matching and UOM validation
- Regional compliance and safety data sheet validation
- Enterprise B2B pricing engine
- Budget, credit, inventory, logistics, exception handling, and final order creation
