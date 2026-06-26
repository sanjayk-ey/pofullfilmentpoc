# PO Fulfillment AI Agent — POC

A local Proof of Concept that demonstrates how an AI agent can automatically read a
Purchase Order (PO), extract its key business fields, validate them, and resolve the
correct corporate account hierarchy and ship-to location — without manual data entry.

It runs entirely on a local machine. There are **no real integrations** (ERP, CRM,
WMS, OMS, SMTP); all master data is mocked in a local Excel workbook.

## What it does

The agent runs an order through a 12-stage orchestration pipeline. Each stage either
passes and hands off to the next, or pauses with a clearly-explained exception.

1. **Multi-channel PO intake** — paste PO text or upload an Excel file (`.xlsx` / `.xls`).
2. **Intelligent data extraction** — pulls SKU, quantity, UOM, ship-to ZIP, delivery date,
   customer account, contract reference, PO number, buyer, cost center, and instructions,
   each with a confidence score; flags missing fields and duplicate POs.
3. **Account hierarchy & ship-to validation** — global parent → division → branch → ship-to.
4. **Buyer authorization & product visibility** — role, branch, cost center, ordering rights.
5. **Product matching & UOM** — variant match, configuration, UOM conversion, substitutes.
6. **Regional compliance & SDS** — eligibility by region, SDS attachment, restricted blocks.
7. **Pricing engine** — list/contract pricing, volume tiers, rebates, promos, surcharges, freight, margin policy.
8. **Budget & approval routing** — cost-center/branch budgets, self-approval, approval matrix.
9. **Credit & payment terms** — credit limit, overdue invoices, risk, payment terms.
10. **Inventory & ATP** — plant/DC/in-transit/ATP, partial fulfillment, allocation.
11. **Logistics & SLA** — ZIP serviceability, ETA, freight rating, fulfillment optimization.
12. **Exception governance** — severity/role routing & SLA for any exception (human-in-the-loop).
13. **Order execution** — ERP/OMS/WMS/TMS records, customer confirmation, audit trail.

## Tech stack

- **Backend:** Python (rule-based extraction and validation — no external API keys required)
- **Frontend:** Streamlit (chat-style UI)
- **Mock master data:** Excel workbooks under `mock-data/` — there are **no real integrations**.

## Quick start

```bash
pip install -r requirements.txt
python create_customer_master_data_excel.py   # mock-data/customer-master-data.xlsx
python create_master_data.py                  # all other mock-data/*-master-data.xlsx
python create_sample_pos.py                   # sample-data/US-03 … US-12 PO files
python generate_story_docs.py                 # per-story manager .docx (optional)
python -m streamlit run app.py
```

Then open http://localhost:8501. Run the tests with `python test_pipeline.py` (21 cases)
and `python test_validation.py` (account validation).

## Project layout

```
po-fullfiment-poc/
├── app.py                       # Streamlit application (full 12-stage pipeline)
├── requirements.txt
├── create_sample_excel.py       # sample PO Excel files (US-01)
├── create_sample_pos.py         # per-story sample PO text files (US-03 … US-12)
├── create_customer_master_data_excel.py  # mock-data/customer-master-data.xlsx
├── create_master_data.py        # all domain master-data workbooks
├── generate_story_docs.py       # per-story manager summary .docx
├── test_validation.py           # account validation harness
├── test_pipeline.py             # end-to-end pipeline harness (21 cases)
├── modules/
│   ├── extractor.py             # rule-based PO field extraction
│   ├── excel_parser.py          # Excel PO reader
│   ├── duplicate_checker.py     # duplicate PO detection
│   ├── account_validator.py     # account hierarchy & ship-to validation
│   ├── stage_result.py          # uniform stage result object
│   ├── xlsx_util.py             # shared master-data readers
│   ├── pipeline.py              # orchestration runner + context builder
│   ├── buyer_authorization.py   # buyer auth & product visibility
│   ├── product_matcher.py       # product match, config, UOM
│   ├── compliance_validator.py  # regional compliance & SDS
│   ├── pricing_engine.py        # enterprise B2B pricing
│   ├── budget_approval.py       # budget & approval routing
│   ├── credit_validator.py      # credit & payment terms
│   ├── inventory_validator.py   # inventory & ATP
│   ├── logistics_validator.py   # logistics & SLA
│   ├── exception_governance.py  # exception routing (human-in-the-loop)
│   └── order_execution.py       # downstream creation, confirmation, audit
├── mock-data/                   # mock master data workbooks + README
└── sample-data/                 # sample POs + manager docs per story (US-01/ … US-12/)
```

See [`SETUP_GUIDE.md`](SETUP_GUIDE.md) for full setup, demo scenarios, and troubleshooting.
Each `sample-data/US-XX/` folder also contains `US-XX_Summary_for_Manager.docx`.
