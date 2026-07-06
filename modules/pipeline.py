"""
pipeline.py
Orchestration pipeline that runs every decision stage in order, threading a
shared context dictionary through them. Used by both the Streamlit app (with
per-stage animation) and the headless test harness.

Stage order:
  Buyer Authorization -> Product Match -> Compliance -> Pricing -> Budget/Approval
  -> Credit -> Inventory -> Logistics  (these pause on the first exception)
  -> Exception Governance (always)  -> Order Execution (only if nothing paused)
"""
from modules.buyer_authorization import BuyerAuthorizationValidator
from modules.product_matcher import ProductMatchValidator
from modules.compliance_validator import ComplianceValidator
from modules.pricing_engine import PricingEngine
from modules.budget_approval import BudgetApprovalValidator
from modules.credit_validator import CreditValidator
from modules.inventory_validator import InventoryValidator
from modules.logistics_validator import LogisticsValidator
from modules.exception_governance import ExceptionGovernance
from modules.order_execution import OrderExecution
from modules.account_validator import AccountValidator

# Singleton account validator used to resolve fulfillment rule profiles from the
# fulfillment_rule ID stored in applied_rules.
_ACCOUNT_VALIDATOR = AccountValidator()

# Singletons (each loads its master-data workbook once)
SEQUENTIAL_STAGES = [
    BuyerAuthorizationValidator(),
    ProductMatchValidator(),
    ComplianceValidator(),
    PricingEngine(),
    BudgetApprovalValidator(),
    CreditValidator(),
    InventoryValidator(),
    LogisticsValidator(),
]
GOVERNANCE = ExceptionGovernance()
EXECUTION = OrderExecution()

# Minimal ZIP -> region (state) resolver for compliance checks
_REGION_PREFIX = {"606": "IL", "600": "IL", "601": "IL", "100": "NY", "104": "NY",
                  "482": "MI", "481": "MI", "900": "CA", "901": "CA", "902": "CA",
                  "752": "TX", "750": "TX", "751": "TX",
                  "E14": "UK", "E1": "UK"}


def region_for_zip(zip_code):
    z = (str(zip_code or "")).strip()
    return _REGION_PREFIX.get(z[:3], "IL")


def build_context(po, av):
    """Assemble the shared pipeline context from extraction + account validation."""
    ctx = {
        "po_number": po.po_number,
        "customer_account": po.customer_account,
        "contract_reference": po.contract_reference,
        "ship_to_zip": po.ship_to_zip,
        "ship_to_name": getattr(po, "ship_to_name", None),
        "ship_to_address": getattr(po, "ship_to_address", None),
        "delivery_instructions": getattr(po, "delivery_instructions", None),
        "requested_delivery_date": po.requested_delivery_date,
        "company_name": getattr(po, "company_name", None),
        "contact_person": getattr(po, "contact_person", None),
        "buyer_email": getattr(po, "buyer_email", None),
        "buyer_id": getattr(po, "buyer_id", None),
        "cost_center": getattr(po, "cost_center", None),
        "region": region_for_zip(po.ship_to_zip),
        "order_lines": [
            {"line_number": l.line_number, "sku": l.sku, "quantity": l.quantity,
             "uom": l.uom, "description": l.description}
            for l in po.order_lines
        ],
    }
    if av is not None and not av.is_exception:
        ctx["branch_id"] = (av.branch or {}).get("id")
        ctx["regional_division_id"] = (av.regional_division or {}).get("id")
        ctx["global_parent_id"] = (av.global_parent or {}).get("id")
        ctx["applied_rules"] = dict(av.applied_rules or {})
        # Customer standing + buying history for the Customer Validation and
        # Product Match decision layers.
        ctx["customer_tier"] = (av.customer or {}).get("customer_tier")
        ctx["customer_class"] = (av.customer or {}).get("customer_class")
        ctx["buying_history"] = av.buying_history
        # Resolve the fulfillment_rule profile (preferred WH, split/backorder flags,
        # restricted DCs, MOQ, SLA, allocation priority) so US-09 and US-10 can apply it.
        rule_id = (av.applied_rules or {}).get("fulfillment_rule")
        profile = _ACCOUNT_VALIDATOR.get_fulfillment_rule(rule_id) if rule_id else None
        if profile:
            ctx["fulfillment_profile"] = profile
    return ctx


def run_orchestration(ctx):
    """Headless run of the full pipeline. Returns the ordered list of StageResults."""
    results = []
    paused = False
    for stage in SEQUENTIAL_STAGES:
        res = stage.validate(ctx)
        results.append(res)
        ctx.update(res.data or {})
        if res.is_exception:
            paused = True
            break

    gov = GOVERNANCE.route(results, ctx)
    results.append(gov)

    if not paused:
        ex = EXECUTION.validate(ctx)
        ctx.update(ex.data or {})
        results.append(ex)

    return results
