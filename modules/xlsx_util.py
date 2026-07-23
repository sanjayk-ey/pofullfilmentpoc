"""
xlsx_util.py
Shared data helpers.

Value helpers (``clean`` / ``to_num`` / ``yes``) are used across every agent.

``load_sheets`` returns ``{sheet_name: [row_dict, ...]}`` from the JSON master-data
snapshots in ``modules/integrations/data/`` (the same snapshots that back the mock
enterprise-system clients). The master data no longer lives in Excel workbooks;
callers still pass the historical ``*.xlsx`` name, which is mapped to the matching
``*.json`` snapshot.
"""
import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "integrations", "data")


def clean(v):
    """Return a stripped string for non-empty values, else None."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s != "" else None


def to_num(v, default=None):
    """Best-effort numeric conversion."""
    if v is None or str(v).strip() == "":
        return default
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return default


def yes(v) -> bool:
    return str(v).strip().upper() in ("Y", "YES", "TRUE", "1")


def load_sheets(filename: str, sheet_names: list) -> dict:
    """Load several sheets from a master-data snapshot in one shot:
    ``{sheet_name: [rows...]}``. ``filename`` may be given with the historical
    ``.xlsx`` extension; the matching ``.json`` snapshot is read."""
    stem = filename[:-5] if filename.lower().endswith(".xlsx") else filename
    path = os.path.join(DATA_DIR, stem + ".json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Master-data snapshot '{os.path.basename(path)}' is missing from "
            f"{DATA_DIR}.")
    with open(path, encoding="utf-8") as f:
        snap = json.load(f)
    return {name: list(snap.get(name, [])) for name in sheet_names}
