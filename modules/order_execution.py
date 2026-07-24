"""
order_execution.py
Order Creation, Downstream Fulfillment, Communication, and Audit Trail.

Calls the downstream integration layer (modules/mock_integrations.py) for every
system - SMTP, ERP, OMS, WMS, TMS - and surfaces each call's explicit success
message ("ERP sales order created successfully", "Email triggered successfully",
etc.).

A downstream outage is detected when an integration returns an error; an outage
can be forced by including the word "FAIL" in the PO number, which reports an
EXECUTION_FAILURE for the affected system.

Master data: execution-master-data (Integration_Endpoints,
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
        (0.30, "🧾", "Creating ERP sales order and OMS request..."),
        (0.30, "📦", "Creating WMS pick ticket and booking TMS shipment..."),
        (0.30, "📧", "Triggering customer confirmation email..."),
        (0.25, "🗂️", "Compiling audit trail and attaching documents..."),
    ]

    def __init__(self):
        s = load_sheets("execution-master-data",
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

        # A PO number containing "FAIL" forces a downstream WMS outage
        force_fail = "FAIL" in po_no.upper()
        r.log(f"Order execution started for PO {po_no}. Connecting to downstream systems.")

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

        # Shipment tracking details (carrier tracking number + link)
        tracking_number = tms.payload.get("tracking_number", "—")
        tracking_url    = tms.payload.get("tracking_url", "")

        # ── Step 5: SMTP customer confirmation ─────────────────────────────────
        confirmation_to = clean(ctx.get("buyer_email")) or f"orders@{customer.lower()}.com"
        smtp = send_email(
            to=confirmation_to,
            subject=f"Order confirmation for PO {po_no} ({erp.record_id})",
            body=(f"Your purchase order {po_no} has been confirmed as order "
                  f"{erp.record_id}. Total: ${order_total:,.2f}. "
                  f"Carrier: {carrier}. Tracking number: {tracking_number}. "
                  f"Track your shipment: {tracking_url}. Estimated delivery: {eta}."),
            reference=po_no,
        )
        r.log(smtp.message)
        if not smtp.ok:
            return self._fail(r, smtp)

        # ── Success ────────────────────────────────────────────────────────────
        r.ok(f"Order {erp.record_id} created and confirmed. All downstream "
             f"records generated. Confirmation email triggered successfully.")

        # Per-system success table
        r.table("Downstream integration results",
                ["System", "Action",          "Record ID",     "Status", "Message"],
                [[r_.system, r_.action, r_.record_id or "—", "SUCCESS", r_.message]
                 for r_ in (erp, oms, wms, tms, smtp)])

        # ── Real-looking display values (resolve DEFAULT / blank fallbacks) ─────
        payment_terms = self._payment_terms_display(ctx)
        fulfillment_src = (warehouse if warehouse and warehouse.upper() != "DEFAULT"
                           else "Central Distribution Center (Chicago, IL)")
        carrier_disp = carrier if carrier and carrier.upper() != "DEFAULT" else "FedEx Freight"
        eta_disp = eta if eta and eta.upper() != "TBD" else \
            (clean(ctx.get("requested_delivery_date")) or "TBD")

        # Pricing bifurcation (published by the pricing stage on every path).
        subtotal   = to_num(ctx.get("pricing_subtotal"), 0) or 0.0
        surcharges = to_num(ctx.get("pricing_surcharges"), 0) or 0.0
        freight    = to_num(ctx.get("pricing_freight"), 0) or 0.0
        tax_amt    = to_num(ctx.get("pricing_tax_amt"), 0) or 0.0
        tax_pct    = to_num(ctx.get("pricing_tax_pct"), 0) or 0.0
        tax_region = clean(ctx.get("pricing_tax_region")) or "—"

        # Assemble the attached document set (generated + master-data + SDS).
        documents = self._order_documents(ctx, erp.record_id, po_no, customer)

        # Buyer & ship-to details ------------------------------------------------
        r.kv("Buyer & ship-to details", [
            ("Buyer company",          clean(ctx.get("company_name")) or customer),
            ("Buyer contact",          clean(ctx.get("contact_person")) or "—"),
            ("Buyer email",            confirmation_to),
            ("Buyer ID",               clean(ctx.get("buyer_id")) or "—"),
            ("Cost center",            clean(ctx.get("cost_center")) or "—"),
            ("Ship-to location",       clean(ctx.get("ship_to_name")) or "—"),
            ("Ship-to address",        clean(ctx.get("ship_to_address")) or "—"),
            ("Ship-to ZIP",            clean(ctx.get("ship_to_zip")) or "—"),
            ("Requested delivery date", clean(ctx.get("requested_delivery_date")) or "—"),
        ])

        r.kv("Customer order confirmation", [
            ("Confirmed order number",   erp.record_id),
            ("Purchase order number",    po_no),
            ("Customer",                 customer),
            ("Confirmation email sent to", confirmation_to),
            ("Email message ID",         smtp.record_id),
            ("Contract reference",       clean(ctx.get("contract_reference")) or "—"),
            ("Fulfillment source",       fulfillment_src),
            ("Carrier / ETA",            f"{carrier_disp} / {eta_disp}"),
            ("Tracking number",          tracking_number),
            ("Track shipment",           tracking_url or "—"),
            ("Payment terms",            payment_terms),
            ("Compliance documents",     f"{len(documents)} attached"),
        ])

        # Price breakdown (subtotal / surcharges / shipping / tax / order total) —
        price_rows = [("Subtotal (goods)", f"${subtotal:,.2f}")]
        if surcharges:
            price_rows.append(("Surcharges", f"${surcharges:,.2f}"))
        price_rows += [
            ("Shipping / freight charge", f"${freight:,.2f}"),
            (f"Sales tax ({tax_pct:g}% — {tax_region})", f"${tax_amt:,.2f}"),
            ("Final price (order total)", f"${order_total:,.2f}"),
        ]
        r.kv("Price breakdown", price_rows)

        # Attached documents table ----------------------------------------------
        if documents:
            r.table("Attached documents",
                    ["Document", "Type", "Reference"],
                    documents)

        lines = ctx.get("resolved_lines", [])
        if lines:
            r.table("Confirmed items",
                    ["SKU", "Description", "Qty", "UOM"],
                    [[l["sku"], l.get("description"),
                      f"{to_num(l.get('qty_base'), 0):g}", l.get("base_uom")]
                     for l in lines])

        r.note("All five downstream systems (ERP, OMS, WMS, TMS, SMTP) confirmed "
               "the order successfully. The customer confirmation has been sent.")

        r.data["order_number"]       = erp.record_id
        r.data["erp_record_id"]      = erp.record_id
        r.data["oms_record_id"]      = oms.record_id
        r.data["wms_record_id"]      = wms.record_id
        r.data["tms_record_id"]      = tms.record_id
        r.data["smtp_message_id"]    = smtp.record_id
        r.data["confirmation_email"] = confirmation_to
        r.data["tracking_number"]    = tracking_number
        r.data["tracking_url"]       = tracking_url
        r.log("Order execution result: PASS — order confirmed across all downstream systems.")
        return r

    # ── Display helpers ──────────────────────────────────────────────────────
    def _payment_terms_display(self, ctx) -> str:
        """Human-readable payment terms; never renders an empty '— ()'."""
        code = clean(ctx.get("payment_terms"))
        desc = clean(ctx.get("payment_terms_desc"))
        if code and desc:
            return f"{code} — {desc}"
        if code:
            return code
        if desc:
            return desc
        return "NET30 — Net 30 days from invoice date"

    def _order_documents(self, ctx, order_id, po_no, customer):
        """Assemble the attached-document set for the order: system-generated
        order documents, applicable master-data documents (terms & conditions,
        product docs), and any compliance SDS documents captured earlier in the
        pipeline. Returns rows of [document, type, reference]."""
        docs = [
            [f"Order Confirmation {order_id}", "Order Confirmation", f"OC-{order_id}.pdf"],
            ["Commercial Invoice",             "Invoice",            f"INV-{po_no}.pdf"],
            ["Packing Slip",                   "Packing Slip",       f"PS-{po_no}.pdf"],
        ]
        seen = {d[2] for d in docs}
        order_skus = {clean(l.get("sku")) for l in (ctx.get("resolved_lines") or [])
                      if clean(l.get("sku"))}
        # Master-data document repository (terms scoped ALL / customer; product docs)
        for d in self.docs:
            linked = clean(d.get("linked_to"))
            ref = clean(d.get("file_ref"))
            if not ref or ref in seen:
                continue
            if linked in ("ALL", customer) or linked in order_skus:
                label = ("Terms & Conditions" if clean(d.get("doc_type")) == "Terms"
                         else clean(d.get("doc_id")) or clean(d.get("doc_type")))
                docs.append([label, clean(d.get("doc_type")), ref])
                seen.add(ref)
        # Compliance SDS documents captured at the compliance stage.
        for att in (ctx.get("compliance_documents") or []):
            if att and att[0]:
                ref = att[1] if len(att) > 1 else ""
                if ref and ref in seen:
                    continue
                docs.append([f"Safety Data Sheet ({att[0]})", "SDS", ref or "—"])
                if ref:
                    seen.add(ref)
        return docs

    # ── Failure helper ─────────────────────────────────────────────────────────
    def _fail(self, r: StageResult, res) -> StageResult:
        r.fail("EXECUTION_FAILURE",
               f"{res.system} integration failed during {res.action}.")
        r.kv("Integration failure", [
            ("Failed system",       res.system),
            ("Action",              res.action),
            ("Endpoint",            res.endpoint),
            ("Failure message",     res.message),
            ("Retry status",        "0/3 retries attempted"),
            ("Recommended resolution",
             "Retry integration, override after manual creation, or escalate to ops"),
        ])
        r.note("Customer confirmation withheld until the failure is resolved or overridden.")
        r.log(f"{res.system} failed -> execution exception.")
        return r
