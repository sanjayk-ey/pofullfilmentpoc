"""
order_execution.py
Order Creation, Downstream Fulfillment, Communication, and Audit Trail.

Calls the central MOCK integrations (modules/mock_integrations.py) for every
downstream system - SMTP, ERP, OMS, WMS, TMS - and surfaces each call's
explicit success message ("ERP sales order created successfully", "Email
triggered successfully", etc.). No real network I/O happens anywhere.

A failure can be simulated for the demo by including the word "FAIL" in the PO
number; that triggers a mock WMS outage which is reported as EXECUTION_FAILURE.

Master data: execution-master-data.xlsx (Integration_Endpoints,
Communication_Templates, Document_Repository).

Exception types: EXECUTION_FAILURE.
"""
from modules.stage_result import StageResult
from modules.xlsx_util import load_sheets, clean, to_num
from modules.mock_integrations import (
    send_email,
    create_erp_sales_order,
    create_oms_request,
    create_wms_pick_ticket,
    create_tms_shipment,
)


class OrderExecution:
    stage_key = "order_execution"
    title = "Order Creation, Fulfillment & Confirmation"
    icon = "✅"
    steps = [
        (0.30, "🧾", "Creating ERP sales order and OMS request (mock)..."),
        (0.30, "📦", "Creating WMS pick ticket and booking TMS shipment (mock)..."),
        (0.30, "📧", "Triggering customer confirmation email (mock SMTP)..."),
        (0.25, "🗂️", "Compiling audit trail and attaching documents..."),
    ]

    def __init__(self):
        s = load_sheets("execution-master-data.xlsx",
                        ["Integration_Endpoints", "Communication_Templates",
                         "Document_Repository"])
        self.endpoints = s["Integration_Endpoints"]
        self.templates = s["Communication_Templates"]
        self.docs = s["Document_Repository"]

    def validate(self, ctx) -> StageResult:
        r = StageResult(self.stage_key, self.title, self.icon)
        po_no = clean(ctx.get("po_number")) or "PO-UNKNOWN"
        customer = clean(ctx.get("customer_account")) or "UNKNOWN"
        order_total = to_num(ctx.get("order_total"), 0) or 0.0
        warehouse = clean(ctx.get("fulfillment_source")) or "DEFAULT"
        carrier = clean(ctx.get("carrier")) or "DEFAULT"
        eta = clean(ctx.get("eta")) or "TBD"

        # Demo hook: PO numbers containing "FAIL" simulate a WMS outage
        force_fail = "FAIL" in po_no.upper()
        r.log(f"Execution started for PO {po_no} (all integrations are MOCKED).")

        # ── Step 1: ERP sales order ─────────────────────────────────────────────
        erp = create_erp_sales_order(customer, po_no, order_total)
        r.log(erp.message)
        if not erp.ok:
            return self._fail(r, erp)

        # ── Step 2: OMS order request ──────────────────────────────────────────
        oms = create_oms_request(po_no)
        r.log(oms.message)
        if not oms.ok:
            return self._fail(r, oms)

        # ── Step 3: WMS pick ticket ────────────────────────────────────────────
        wms = create_wms_pick_ticket(po_no, warehouse, force_fail=force_fail)
        r.log(wms.message)
        if not wms.ok:
            return self._fail(r, wms)

        # ── Step 4: TMS shipment ───────────────────────────────────────────────
        tms = create_tms_shipment(po_no, carrier, eta)
        r.log(tms.message)
        if not tms.ok:
            return self._fail(r, tms)

        # ── Step 5: SMTP customer confirmation ─────────────────────────────────
        confirmation_to = f"orders@{customer.lower()}.example.com"
        smtp = send_email(
            to=confirmation_to,
            subject=f"Order confirmation for PO {po_no} ({erp.record_id})",
            body=(f"Your purchase order {po_no} has been confirmed as order "
                  f"{erp.record_id}. Total: ${order_total:,.2f}. ETA: {eta}."),
            reference=po_no,
        )
        r.log(smtp.message)
        if not smtp.ok:
            return self._fail(r, smtp)

        # ── Success ────────────────────────────────────────────────────────────
        r.ok(f"Order {erp.record_id} created and confirmed. All downstream "
             f"records generated. Confirmation email triggered successfully.")

        # Per-system success table — exactly what the user requested
        r.table("Mock integration results",
                ["System", "Action",          "Record ID",     "Status", "Message"],
                [[r_.system, r_.action, r_.record_id or "—", "SUCCESS", r_.message]
                 for r_ in (erp, oms, wms, tms, smtp)])

        r.kv("Customer order confirmation", [
            ("Confirmed order number",   erp.record_id),
            ("Purchase order number",    po_no),
            ("Customer",                 customer),
            ("Confirmation email sent to", confirmation_to),
            ("Email message ID",         smtp.record_id),
            ("Final price",              f"${order_total:,.2f}"),
            ("Contract reference",       clean(ctx.get("contract_reference")) or "—"),
            ("Fulfillment source",       warehouse),
            ("Carrier / ETA",            f"{carrier} / {eta}"),
            ("Payment terms",            f"{clean(ctx.get('payment_terms')) or '—'} "
                                         f"({clean(ctx.get('payment_terms_desc')) or ''})"),
            ("Compliance documents",     f"{len(ctx.get('compliance_documents') or [])} attached"),
        ])

        lines = ctx.get("resolved_lines", [])
        if lines:
            r.table("Confirmed items",
                    ["SKU", "Description", "Qty", "UOM"],
                    [[l["sku"], l.get("description"),
                      f"{to_num(l.get('qty_base'), 0):g}", l.get("base_uom")]
                     for l in lines])

        r.note("All five downstream integrations (ERP, OMS, WMS, TMS, SMTP) are "
               "MOCKED for this POC - no real network calls were made.")

        r.data["order_number"]       = erp.record_id
        r.data["erp_record_id"]      = erp.record_id
        r.data["oms_record_id"]      = oms.record_id
        r.data["wms_record_id"]      = wms.record_id
        r.data["tms_record_id"]      = tms.record_id
        r.data["smtp_message_id"]    = smtp.record_id
        r.data["confirmation_email"] = confirmation_to
        r.log("Execution result: PASS — order confirmed (all integrations mocked).")
        return r

    # ── Failure helper ─────────────────────────────────────────────────────────
    def _fail(self, r: StageResult, mock_res) -> StageResult:
        r.fail("EXECUTION_FAILURE",
               f"{mock_res.system} integration failed during {mock_res.action}.")
        r.kv("Integration failure", [
            ("Failed system",       mock_res.system),
            ("Action",              mock_res.action),
            ("Mock endpoint",       mock_res.endpoint),
            ("Failure message",     mock_res.message),
            ("Retry status",        "0/3 retries (mock)"),
            ("Recommended resolution",
             "Retry integration, override after manual creation, or escalate to ops"),
        ])
        r.note("Customer confirmation withheld until the failure is resolved or overridden.")
        r.log(f"{mock_res.system} failed -> execution exception.")
        return r
