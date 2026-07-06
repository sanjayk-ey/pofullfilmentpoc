"""
duplicate_checker.py
Detects duplicate PO submissions.
Uses a local JSON file as storage (no database needed for POC).
"""
import json, os
from datetime import datetime
from typing import Optional, Tuple

STORE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "submitted_pos.json")


def _load() -> list:
    os.makedirs(os.path.dirname(STORE_FILE), exist_ok=True)
    if not os.path.exists(STORE_FILE):
        return []
    with open(STORE_FILE, "r") as f:
        return json.load(f)


def _save(records: list):
    os.makedirs(os.path.dirname(STORE_FILE), exist_ok=True)
    with open(STORE_FILE, "w") as f:
        json.dump(records, f, indent=2)


def check(po_number: Optional[str], customer_account: Optional[str]) -> Tuple[bool, Optional[dict]]:
    """
    Returns (is_duplicate, existing_record).
    Matches on (po_number, customer_account) — both must match.
    """
    if not po_number:
        return False, None
    records = _load()
    for rec in records:
        same_po   = rec.get("po_number","").upper() == po_number.upper()
        same_cust = (not customer_account or
                     not rec.get("customer_account") or
                     rec.get("customer_account","").upper() == customer_account.upper())
        if same_po and same_cust:
            return True, rec
    return False, None


def register(po_number: str, customer_account: Optional[str], session_id: str = ""):
    """Record a new PO submission."""
    records = _load()
    records.append({
        "po_number":        po_number,
        "customer_account": customer_account or "",
        "submitted_at":     datetime.now().strftime("%d %b %Y %H:%M"),
        "status":           "SUBMITTED",
        "session_id":       session_id,
    })
    _save(records)


def reset_store():
    """Clear all submitted POs (useful for testing)."""
    _save([])
