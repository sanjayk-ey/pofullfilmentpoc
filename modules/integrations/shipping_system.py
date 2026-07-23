"""
shipping_system.py — Mock Shipping Service Provider.

Serves carrier coverage, freight rating, delivery SLA rules, warehouse origins
and the delivery calendar used to plan and rate shipments.
"""
from typing import Dict, List

from .base import MockSystemClient

_LOGISTICS_WB = "logistics-master-data.xlsx"


class ShippingSystem(MockSystemClient):
    def __init__(self):
        super().__init__("SHIPPING")

    def get_logistics(self, sheets: List[str]) -> Dict[str, List[dict]]:
        """Fetch logistics sheets (Carrier_Coverage, Freight_Rating, SLA_Rules,
        Warehouse_Master, Delivery_Calendar)."""
        return self._fetch(_LOGISTICS_WB, sheets, "logistics")


SHIPPING = ShippingSystem()
