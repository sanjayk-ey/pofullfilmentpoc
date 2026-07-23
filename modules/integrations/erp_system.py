"""
erp_system.py — Mock ERP (Enterprise Resource Planning).

Serves inventory / stock / ATP, customer credit & financial risk, and the
budget / approval-matrix data used for spend authorisation.
"""
from typing import Dict, List

from .base import MockSystemClient

_INVENTORY_WB = "inventory-master-data.xlsx"
_CREDIT_WB = "credit-master-data.xlsx"
_BUDGET_WB = "budget-master-data.xlsx"


class ERPSystem(MockSystemClient):
    def __init__(self):
        super().__init__("ERP")

    def get_inventory(self, sheets: List[str]) -> Dict[str, List[dict]]:
        """Fetch inventory sheets (Plant_Stock, DC_Stock, In_Transit, ATP,
        Allocation_Rules, Fulfillment_Preferences)."""
        return self._fetch(_INVENTORY_WB, sheets, "inventory")

    def get_credit(self, sheets: List[str]) -> Dict[str, List[dict]]:
        """Fetch credit sheets (Credit_Master, Invoice_Aging, Payment_History,
        Payment_Terms, Risk_Signals)."""
        return self._fetch(_CREDIT_WB, sheets, "credit")

    def get_budget(self, sheets: List[str]) -> Dict[str, List[dict]]:
        """Fetch budget / approval sheets (Budget_Master, Cost_Centers,
        Approval_Matrix, Buyer_Authority)."""
        return self._fetch(_BUDGET_WB, sheets, "budget-approvals")


ERP = ERPSystem()
