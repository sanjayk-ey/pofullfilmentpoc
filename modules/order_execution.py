"""
order_execution.py
Order Creation, Downstream Fulfillment, Communication, and Audit Trail.

Creates the downstream execution records (ERP sales order, OMS request, WMS pick
ticket, shipment order), generates the customer order confirmation, attaches
required documents, and compiles the full audit trail. Raises an execution
exception when a (mock) downstream integration fails.

Master data: execution-master-data.xlsx (Integration_Endpoints,
Communication_Templates, Document_Repository).

Exception types: EXECUTION_FAILURE.
"""
from modules.stage_result import StageResult
from modules.xlsx_util import load_sheets, clean, to_num


class OrderExecution:
    stage_key = "order_execution"
    title = "Order Creation, Fulfillment & Confirmation"
    icon = "✅"
    steps = [
        (0.30, "🧾", "Creating ERP sales order and OMS request..."),
        (0.30, "📦", "Creating WMS pick ticket and shipment order..."),
        (0.30, "📧", "Generating customer order confirmation..."),
        (0.25, "🗂️", "Compiling audit trail and attaching documents..."),
    ]

    def __init__(self):
        s = load_sheets("execution-master-data.xlsx",
                        ["Integration_Endpoints", "Communication_Templates", "Document_Repository"])
        self.endpoints = s["Integration_Endpoints"]
        self.templates = s["Communication_Templates"]
        self.docs = s["Document_Repository"]

    def validate(self, ctx) -> StageResult:
        r = StageResult(self.stage_key, self.title, self.icon)
        po_no = clean(ctx.get("po_number")) or "PO-UNKNOWN"
        seed = "".join(ch for ch in po_no if ch.isdigit())[-4:] or "0001"
        force_fail = "FAIL" in po_no.upper()
        r.log(f"Execution started for PO {po_no}.")

        # ── Create downstream records (mock) ────────────────────────────────
        record_ids = {
            "ERP": f"SO-{seed}", "OMS": f"OMS-{seed}",
            "WMS": f"PICK-{seed}", "TMS": f"SHIP-{seed}", "SMTP": f"MSG-{seed}",
        }
        created_rows = []
        for ep in self.endpoints:
            system = clean(ep.get("system"))
            status = clean(ep.get("default_status")) or "SUCCESS"
            # Demo hook: a PO number containing "FAIL" simulates a WMS outage
            if force_fail and system == "WMS":
                status = "FAIL"
            if status == "FAIL":
                r.fail("EXECUTION_FAILURE",
                       f"{system} integration failed while creating "
                       f"{clean(ep.get('record_type'))}.")
                r.kv("Integration failure", [
                    ("Failed system", system),
                    ("Record type", clean(ep.get("record_type"))),
                    ("Failure message", f"{system} endpoint returned an error (mock outage)"),
                    ("Retry status", f"0/{to_num(ep.get('retry_limit'), 3)} retries"),
                    ("Recommended resolution", "Retry integration or override after manual creation"),
                ])
                r.note("Customer confirmation withheld until the failure is resolved or overridden.")
                r.log(f"{system} failed -> execution exception.")
                return r
            created_rows.append([system, clean(ep.get("record_type")),
                                 record_ids.get(system, "-"), "Created"])

        # ── Customer confirmation ───────────────────────────────────────────
        lines = ctx.get("resolved_lines", [])
        conf_lines = [[l["sku"], l.get("description"), f"{l.get('qty_base'):g}", l.get("base_uom")]
                      for l in lines]

        r.ok(f"Order {record_ids['ERP']} created and confirmed. All downstream records generated. "
             f"Confirmation sent to the customer.")
        r.table("Downstream records created",
                ["System", "Record type", "Record ID", "Status"], created_rows)
        r.kv("Customer order confirmation", [
            ("Confirmed order number", record_ids["ERP"]),
            ("Purchase order number", po_no),
            ("Customer", clean(ctx.get("customer_account"))),
            ("Final price", f"${to_num(ctx.get('order_total'), 0):,.2f}"),
            ("Contract reference", clean(ctx.get("contract_reference")) or "—"),
            ("Fulfillment source", clean(ctx.get("fulfillment_source")) or "—"),
            ("Carrier", clean(ctx.get("carrier")) or "—"),
            ("ETA", clean(ctx.get("eta")) or "—"),
            ("Payment terms", f"{clean(ctx.get('payment_terms')) or '—'} "
                              f"({clean(ctx.get('payment_terms_desc')) or ''})"),
            ("Compliance documents", str(len(ctx.get("compliance_documents") or [])) + " attached"),
        ])
        if conf_lines:
            r.table("Confirmed items", ["SKU", "Description", "Qty", "UOM"], conf_lines)
        r.data["order_number"] = record_ids["ERP"]
        r.log("Execution result: PASS -> order confirmed.")
        return r
