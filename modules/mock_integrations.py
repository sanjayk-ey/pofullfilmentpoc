"""
mock_integrations.py
=====================
Centralised MOCK functions for every external system this POC pretends to call:

    SMTP / Email   -> send_email(...)
    ERP            -> create_erp_sales_order(...)
    OMS            -> create_oms_request(...)
    WMS            -> create_wms_pick_ticket(...)
    TMS            -> create_tms_shipment(...)

There is **no network I/O** in this file. Every function builds a deterministic
mock record ID, returns a structured ``MockResult`` with a clear human-readable
success message ("Email triggered successfully", "ERP sales order created
successfully", etc.), and (optionally) prints to stdout so a developer can see
the simulated call in the terminal.

For demo purposes a failure can be forced by passing ``force_fail=True``; the
function returns a ``MockResult`` with ``ok=False`` and an error message so the
caller can raise an EXECUTION_FAILURE exception.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict


@dataclass
class MockResult:
    """Uniform return value from every mock integration call."""
    ok:         bool              = True
    system:     str               = ""   # ERP / OMS / WMS / TMS / SMTP
    action:     str               = ""   # e.g. "Sales Order created"
    record_id:  Optional[str]     = None
    message:    str               = ""   # human-readable success / failure text
    endpoint:   str               = ""   # mock URL the call "went to"
    timestamp:  str               = ""
    payload:    Dict              = field(default_factory=dict)


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


def _seed(reference: Optional[str]) -> str:
    """Generate a short deterministic suffix from a reference (PO number, etc.)."""
    digits = "".join(ch for ch in (reference or "") if ch.isdigit())
    return (digits[-4:] or "0001").rjust(4, "0")


# ────────────────────────────────────────────────────────────────────────────────
# SMTP / Email
# ────────────────────────────────────────────────────────────────────────────────
def send_email(to: str,
               subject: str,
               body: str = "",
               reference: Optional[str] = None,
               force_fail: bool = False) -> MockResult:
    """Mock SMTP send. No network call. Returns 'Email triggered successfully'."""
    record_id = f"MSG-{_seed(reference)}"
    endpoint  = "mock://smtp/send"
    if force_fail:
        return MockResult(
            ok=False, system="SMTP", action="Email send",
            record_id=None,
            message=f"Email triggered FAILED (mock outage at {endpoint}).",
            endpoint=endpoint, timestamp=_now(),
            payload={"to": to, "subject": subject},
        )
    return MockResult(
        ok=True, system="SMTP", action="Email triggered",
        record_id=record_id,
        message=f"Email triggered successfully to {to} (message id {record_id}).",
        endpoint=endpoint, timestamp=_now(),
        payload={"to": to, "subject": subject, "body_preview": (body or "")[:100]},
    )


# ────────────────────────────────────────────────────────────────────────────────
# ERP — Sales Order
# ────────────────────────────────────────────────────────────────────────────────
def create_erp_sales_order(customer_account: str,
                           po_number: str,
                           order_total: float = 0.0,
                           force_fail: bool = False) -> MockResult:
    """Mock ERP call. Returns 'ERP sales order created successfully'."""
    record_id = f"SO-{_seed(po_number)}"
    endpoint  = "mock://erp/salesorder"
    if force_fail:
        return MockResult(
            ok=False, system="ERP", action="Sales Order",
            message=f"ERP sales order creation FAILED (mock outage at {endpoint}).",
            endpoint=endpoint, timestamp=_now(),
            payload={"customer": customer_account, "po_number": po_number},
        )
    return MockResult(
        ok=True, system="ERP", action="Sales Order created",
        record_id=record_id,
        message=f"ERP sales order created successfully ({record_id}) for customer "
                f"{customer_account}, PO {po_number}.",
        endpoint=endpoint, timestamp=_now(),
        payload={"customer": customer_account, "po_number": po_number,
                 "order_total": order_total},
    )


# ────────────────────────────────────────────────────────────────────────────────
# OMS — Order Request
# ────────────────────────────────────────────────────────────────────────────────
def create_oms_request(po_number: str, force_fail: bool = False) -> MockResult:
    """Mock OMS call. Returns 'OMS request created successfully'."""
    record_id = f"OMS-{_seed(po_number)}"
    endpoint  = "mock://oms/order"
    if force_fail:
        return MockResult(
            ok=False, system="OMS", action="Order Request",
            message=f"OMS order request FAILED (mock outage at {endpoint}).",
            endpoint=endpoint, timestamp=_now(),
        )
    return MockResult(
        ok=True, system="OMS", action="Order Request created",
        record_id=record_id,
        message=f"OMS order request created successfully ({record_id}).",
        endpoint=endpoint, timestamp=_now(),
        payload={"po_number": po_number},
    )


# ────────────────────────────────────────────────────────────────────────────────
# WMS — Pick Ticket
# ────────────────────────────────────────────────────────────────────────────────
def create_wms_pick_ticket(po_number: str,
                           warehouse: str = "",
                           force_fail: bool = False) -> MockResult:
    """Mock WMS call. Returns 'WMS pick ticket created successfully'."""
    record_id = f"PICK-{_seed(po_number)}"
    endpoint  = "mock://wms/pick"
    if force_fail:
        return MockResult(
            ok=False, system="WMS", action="Pick Ticket",
            message=f"WMS pick ticket creation FAILED (mock outage at {endpoint}).",
            endpoint=endpoint, timestamp=_now(),
        )
    return MockResult(
        ok=True, system="WMS", action="Pick Ticket created",
        record_id=record_id,
        message=f"WMS pick ticket created successfully ({record_id}) at "
                f"warehouse {warehouse or 'DEFAULT'}.",
        endpoint=endpoint, timestamp=_now(),
        payload={"po_number": po_number, "warehouse": warehouse},
    )


# ────────────────────────────────────────────────────────────────────────────────
# TMS — Shipment Order
# ────────────────────────────────────────────────────────────────────────────────
def create_tms_shipment(po_number: str,
                        carrier: str = "",
                        eta: str = "",
                        force_fail: bool = False) -> MockResult:
    """Mock TMS call. Returns 'TMS shipment booked successfully'."""
    record_id = f"SHIP-{_seed(po_number)}"
    endpoint  = "mock://tms/shipment"
    if force_fail:
        return MockResult(
            ok=False, system="TMS", action="Shipment Order",
            message=f"TMS shipment booking FAILED (mock outage at {endpoint}).",
            endpoint=endpoint, timestamp=_now(),
        )
    return MockResult(
        ok=True, system="TMS", action="Shipment booked",
        record_id=record_id,
        message=f"TMS shipment booked successfully ({record_id}) with carrier "
                f"{carrier or 'DEFAULT'}, ETA {eta or 'TBD'}.",
        endpoint=endpoint, timestamp=_now(),
        payload={"po_number": po_number, "carrier": carrier, "eta": eta},
    )
