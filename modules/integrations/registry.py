"""
registry.py
Metadata for every enterprise system: a stable code, a short display name,
the full name, an API endpoint, and an icon. Used both by the clients (to tag
their calls) and by the UI (to narrate "connecting to ERP / PIM ...").
"""
from typing import Dict, List

SYSTEMS: Dict[str, dict] = {
    "ERP": {
        "code": "ERP",
        "name": "ERP",
        "full": "ERP (Enterprise Resource Planning)",
        "endpoint": "https://erp.internal/api/v1",
        "icon": "🏭",
    },
    "PIM": {
        "code": "PIM",
        "name": "PIM",
        "full": "PIM (Product Information Management)",
        "endpoint": "https://pim.internal/api/v1",
        "icon": "🧬",
    },
    "COMMERCE": {
        "code": "COMMERCE",
        "name": "Commerce",
        "full": "Commerce Platform",
        "endpoint": "https://commerce.internal/api/v1",
        "icon": "🛒",
    },
    "OMS": {
        "code": "OMS",
        "name": "OMS",
        "full": "OMS (Order Management System)",
        "endpoint": "https://oms.internal/api/v1",
        "icon": "🗂️",
    },
    "SHIPPING": {
        "code": "SHIPPING",
        "name": "Shipping",
        "full": "Shipping Service Provider",
        "endpoint": "https://ship.carrier-network.com/api/v1",
        "icon": "🚚",
    },
}


def system_meta(code: str) -> dict:
    return SYSTEMS.get(code, {"code": code, "name": code, "full": code,
                              "endpoint": "", "icon": "🔌"})


def system_name(code: str) -> str:
    return system_meta(code)["name"]


def describe_systems(codes: List[str]) -> str:
    """Human-readable list of system names, e.g. 'PIM and ERP'."""
    names = [system_name(c) for c in codes]
    names = [n for n in names if n]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]
