"""
oms_system.py — Mock OMS (Order Management System).

Serves the customer's order / buying history (past order headers and lines),
from which the customer's purchasing profile is derived.
"""
from typing import Dict, List

from .base import MockSystemClient

# JSON snapshot dataset name (files live in modules/integrations/data/).
# Order history lives alongside the customer master in the reference data model.
_ORDER_HISTORY = "customer-master-data"


class OMSSystem(MockSystemClient):
    def __init__(self):
        super().__init__("OMS")

    def get_order_history(self, sheets: List[str]) -> Dict[str, List[dict]]:
        """Fetch order-history sheets (Order_History, Order_History_Lines)."""
        return self._fetch(_ORDER_HISTORY, sheets, "order-history")


OMS = OMSSystem()
