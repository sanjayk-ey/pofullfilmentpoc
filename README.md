# PO Fulfillment AI Agent — POC

A local Proof of Concept that demonstrates how an AI agent can automatically read a
Purchase Order (PO), extract its key business fields, validate them, and resolve the
correct corporate account hierarchy and ship-to location — without manual data entry.

It runs entirely on a local machine. There are **no real integrations** (ERP, CRM,
WMS, OMS, SMTP); all master data is mocked in a local Excel workbook.

## What it does

1. **Multi-channel PO intake** — paste PO text into a chat box or upload an Excel file (`.xlsx` / `.xls`).
2. **Intelligent data extraction** — pulls SKU, quantity, UOM, ship-to ZIP, requested
   delivery date, customer account, contract reference, PO number, and delivery instructions,
   each with a confidence score.
3. **Intake exceptions** — flags missing mandatory fields and detects duplicate POs.
4. **Account hierarchy & ship-to validation** — resolves the global parent, regional
   division, branch, and ship-to; applies the most-specific eligible rules; and raises
   unmatched-customer, duplicate-customer, invalid ship-to, or hierarchy-mismatch exceptions.

## Tech stack

- **Backend:** Python (rule-based extraction and validation — no external API keys required)
- **Frontend:** Streamlit (chat-style UI)
- **Mock master data:** Excel workbook (`mock-data/master-data.xlsx`)

## Quick start

```bash
pip install -r requirements.txt
python create_master_data_excel.py      # generates mock-data/master-data.xlsx
python -m streamlit run app.py
```

Then open http://localhost:8501.

## Project layout

```
po-fullfiment-poc/
├── app.py                       # Streamlit application
├── requirements.txt
├── create_sample_excel.py       # generates sample PO Excel files
├── create_master_data_excel.py  # generates the mock master-data.xlsx
├── test_validation.py           # internal test harness (extract -> validate)
├── modules/
│   ├── extractor.py             # rule-based PO field extraction
│   ├── excel_parser.py          # Excel PO reader
│   ├── duplicate_checker.py     # duplicate PO detection
│   └── account_validator.py     # account hierarchy & ship-to validation
├── mock-data/                   # mock master data (Excel) + README
└── sample-data/                 # sample POs and exception scenarios
```

See [`SETUP_GUIDE.md`](SETUP_GUIDE.md) for full setup, demo scenarios, and troubleshooting.
