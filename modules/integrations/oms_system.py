"""
oms_system.py — Mock OMS (Order Management System).

Serves the customer's order / buying history (past order headers and lines),
from which the customer's purchasing profile is derived.
"""
from typing import Dict, List

from .base import MockSystemClient

# Order history lives alongside the customer master in the reference data model.
_ORDER_HISTORY_WB = "customer-master-data.xlsx"


class OMSSystem(MockSystemClient):
    def __init__(self):
        super().__init__("OMS")

    def get_order_history(self, sheets: List[str]) -> Dict[str, List[dict]]:
        """Fetch order-history sheets (Order_History, Order_History_Lines)."""
        return self._fetch(_ORDER_HISTORY_WB, sheets, "order-history")


OMS = OMSSystem()
