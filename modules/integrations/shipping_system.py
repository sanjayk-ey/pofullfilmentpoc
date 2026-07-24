"""
shipping_system.py — Mock Shipping Service Provider.

Serves carrier coverage, freight rating, delivery SLA rules, warehouse origins
and the delivery calendar used to plan and rate shipments.
"""
from typing import Dict, List

from .base import MockSystemClient

# JSON snapshot dataset name (files live in modules/integrations/data/).
_LOGISTICS = "logistics-master-data"


class ShippingSystem(MockSystemClient):
    def __init__(self):
        super().__init__("SHIPPING")

    def get_logistics(self, sheets: List[str]) -> Dict[str, List[dict]]:
        """Fetch logistics sheets (Carrier_Coverage, Freight_Rating, SLA_Rules,
        Warehouse_Master, Delivery_Calendar)."""
        return self._fetch(_LOGISTICS, sheets, "logistics")


SHIPPING = ShippingSystem()
