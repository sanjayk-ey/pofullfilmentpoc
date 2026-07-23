"""
pim_system.py — Mock PIM (Product Information Management).

Serves the product catalog (SKUs, attributes, UOM conversions, substitution
rules) and product compliance data (regional eligibility, SDS documents).
"""
from typing import Dict, List

from .base import MockSystemClient

_PRODUCT_WB = "product-master-data.xlsx"
_COMPLIANCE_WB = "compliance-master-data.xlsx"


class PIMSystem(MockSystemClient):
    def __init__(self):
        super().__init__("PIM")

    def get_product_catalog(self, sheets: List[str]) -> Dict[str, List[dict]]:
        """Fetch product-catalog sheets (Product_Master, Product_Attributes,
        UOM_Conversions, Substitution_Rules, Compatibility_Rules)."""
        return self._fetch(_PRODUCT_WB, sheets, "product-catalog")

    def get_compliance(self, sheets: List[str]) -> Dict[str, List[dict]]:
        """Fetch compliance sheets (Compliance_Rules, Regional_Restrictions,
        SDS_Repository, Product_Eligibility)."""
        return self._fetch(_COMPLIANCE_WB, sheets, "product-compliance")


PIM = PIMSystem()
