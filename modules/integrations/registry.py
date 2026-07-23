"""
registry.py
Metadata for every mock enterprise system: a stable code, a short display name,
the full name, a (mock) API endpoint, and an icon. Used both by the clients (to
tag their calls) and by the UI (to narrate "connecting to Mock ERP / PIM ...").
"""
from typing import Dict, List

SYSTEMS: Dict[str, dict] = {
    "ERP": {
        "code": "ERP",
        "name": "Mock ERP",
        "full": "Mock ERP (Enterprise Resource Planning)",
        "endpoint": "https://erp.mock.internal/api/v1",
        "icon": "🏭",
    },
    "PIM": {
        "code": "PIM",
        "name": "Mock PIM",
        "full": "Mock PIM (Product Information Management)",
        "endpoint": "https://pim.mock.internal/api/v1",
        "icon": "🧬",
    },
    "COMMERCE": {
        "code": "COMMERCE",
        "name": "Mock Commerce",
        "full": "Mock Commerce Platform",
        "endpoint": "https://commerce.mock.internal/api/v1",
        "icon": "🛒",
    },
    "OMS": {
        "code": "OMS",
        "name": "Mock OMS",
        "full": "Mock OMS (Order Management System)",
        "endpoint": "https://oms.mock.internal/api/v1",
        "icon": "🗂️",
    },
    "SHIPPING": {
        "code": "SHIPPING",
        "name": "Mock Shipping",
        "full": "Mock Shipping Service Provider",
        "endpoint": "https://ship.mock.carrier-network.com/api/v1",
        "icon": "🚚",
    },
}


def system_meta(code: str) -> dict:
    return SYSTEMS.get(code, {"code": code, "name": code, "full": code,
                              "endpoint": "", "icon": "🔌"})


def system_name(code: str) -> str:
    return system_meta(code)["name"]


def describe_systems(codes: List[str]) -> str:
    """Human-readable list of system names, e.g. 'Mock PIM and Mock ERP'."""
    names = [system_name(c) for c in codes]
    names = [n for n in names if n]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]
