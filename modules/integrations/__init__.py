"""
modules.integrations
=====================
Mock enterprise-system integration layer for the Order Orchestration demo.

Every agent fetches and validates its data through a **mock system client** that
stands in for a real enterprise system:

    Mock ERP       — inventory / stock / ATP, credit, budget & approvals
    Mock PIM       — product catalog, attributes, UOM, substitutes, compliance
    Mock Commerce  — pricing & promotions, customer master, buyer directory
    Mock OMS       — order / buying history
    Mock Shipping  — carrier coverage, freight rating, delivery SLA

Each client exposes API-style methods, carries a system name + endpoint, and
records every call in a shared ``CALL_LOG``. The data is served from the JSON
master-data snapshots in ``data/`` (the single source of truth for demo data).
To move to real integrations later, only the internals of these clients change —
the agents and their validation logic stay exactly the same.
"""
from .registry import SYSTEMS, system_meta, system_name, describe_systems
from .base import CALL_LOG, reset_call_log
from .erp_system import ERP
from .pim_system import PIM
from .commerce_system import COMMERCE
from .oms_system import OMS
from .shipping_system import SHIPPING

__all__ = [
    "SYSTEMS", "system_meta", "system_name", "describe_systems",
    "CALL_LOG", "reset_call_log",
    "ERP", "PIM", "COMMERCE", "OMS", "SHIPPING",
]
