"""
manual_entry_validators.py
Inline validators for values a CSR types into an intake decision card.

The interactive orchestrator paused on an ambiguous SKU / missing SKU / zero
quantity / etc. and asked the CSR for a correction. Before the pipeline is
allowed to resume with the CSR's typed value, these validators run to make
sure the entry:

  * SKU: is a real SKU in the product master, AND is not already present on
    another line of the same PO (a duplicate would double-count the same
    product).
  * QUANTITY: is a positive number.

Each validator returns an error message string on failure, or None on
success. The UI displays the message inline and keeps the "Use my entry"
button disabled until the CSR corrects the input — the process cannot move
ahead until a valid value is supplied.
"""
from typing import Optional


def _clean_sku(s: str) -> str:
    return (s or "").strip().upper()


def validate_manual_sku(sku: str, po, current_line_number: Optional[int],
                        products: dict) -> Optional[str]:
    """Return an error message if the typed SKU is invalid (not in the
    product master) or duplicates a SKU already on another line of the same
    PO. None means the SKU is acceptable.

    Args:
        sku:                the text the CSR typed
        po:                 the ExtractedPO (has .order_lines with .sku, .line_number)
        current_line_number: the line the CSR is correcting — SKUs on THIS
                             line are allowed (the CSR may be re-typing the
                             same SKU); duplicates are checked against
                             every OTHER line
        products:           dict {sku_upper: product_row} from the product master
    """
    s = _clean_sku(sku)
    if not s:
        return "Please enter a SKU."
    if s not in products:
        return (f"'{s}' is not in the product master. Please enter a valid "
                "catalog SKU (or click Reject to stop the order).")
    for ln in getattr(po, "order_lines", []) or []:
        # Skip the line we are correcting — the CSR is allowed to re-affirm
        # its own SKU (or the AI's suggestion) on this same line.
        if ln.line_number == current_line_number:
            continue
        existing = _clean_sku(ln.sku or "")
        if existing == s:
            return (f"'{s}' is already on line {ln.line_number} of this PO. "
                    "Duplicate SKUs on the same order would double-count the "
                    "same product — please enter a different SKU.")
    return None


def validate_manual_quantity(text: str) -> Optional[str]:
    """Return an error message if the typed quantity is not a positive whole
    number. Only digits are accepted — no decimals, negatives, or letters."""
    if text is None or not str(text).strip():
        return "Please enter a positive whole number."
    raw = str(text).strip()
    if not raw.isdigit():
        return f"'{raw}' is not valid — only positive whole numbers are allowed (no decimals, letters, or negative signs)."
    q = int(raw)
    if q <= 0:
        return "Quantity must be greater than zero."
    return None
