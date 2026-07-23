"""
modules.integrations
=====================
Mock enterprise-system integration layer for the Order Orchestration demo.

Instead of reading the ``mock-data/*.xlsx`` workbooks directly, every agent now
fetches and validates its data through a **mock system client** that stands in
for a real enterprise system:

    Mock ERP       — inventory / stock / ATP, credit, budget & approvals
    Mock PIM       — product catalog, attributes, UOM, substitutes, compliance
    Mock Commerce  — pricing & promotions, customer master, buyer directory
    Mock OMS       — order / buying history
    Mock Shipping  — carrier coverage, freight rating, delivery SLA

Each client exposes API-style methods, carries a system name + endpoint, and
records every call in a shared ``CALL_LOG``. The data is served from JSON
snapshots (generated from the Excel master data by ``snapshot_tool.py``) so it
is 100% identical to the previous Excel-backed path. To move to real
integrations later, only the internals of these clients change — the agents and
their validation logic stay exactly the same.
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
