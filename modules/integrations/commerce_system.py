"""
commerce_system.py — Mock Commerce Platform.

Serves pricing & promotions, the customer master (accounts, corporate
hierarchy, ship-to locations, hierarchy rules, fulfillment rules) and the buyer
directory (profiles, permissions, cost centers, product-visibility rules).
"""
from typing import Dict, List

from .base import MockSystemClient

_PRICING_WB = "pricing-master-data.xlsx"
_CUSTOMER_WB = "customer-master-data.xlsx"
_BUYER_WB = "buyer-master-data.xlsx"


class CommerceSystem(MockSystemClient):
    def __init__(self):
        super().__init__("COMMERCE")

    def get_pricing(self, sheets: List[str]) -> Dict[str, List[dict]]:
        """Fetch pricing sheets (Price_List, Contracts, Volume_Tiers, Rebates,
        Promotions, Surcharges, Freight_Terms, Margin_Policy, Raw_Material_Index,
        Tax_Rates)."""
        return self._fetch(_PRICING_WB, sheets, "pricing")

    def get_customer(self, sheets: List[str]) -> Dict[str, List[dict]]:
        """Fetch customer-master sheets (Customer_Master, Account_Hierarchy,
        Ship_To_Master, Hierarchy_Rules, Fulfillment_Rules)."""
        return self._fetch(_CUSTOMER_WB, sheets, "customer")

    def get_buyer(self, sheets: List[str]) -> Dict[str, List[dict]]:
        """Fetch buyer-directory sheets (Buyer_Profiles, User_Permissions,
        Cost_Centers, Product_Visibility_Rules)."""
        return self._fetch(_BUYER_WB, sheets, "buyer")


COMMERCE = CommerceSystem()
