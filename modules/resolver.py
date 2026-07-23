"""
resolver.py
Entity resolver — maps the human-readable identifiers that appear on a real
purchase order (buying company name, contact person name) to the internal
master-data identifiers the orchestration stages work with:

    company name     -> customer account   (Customer_Master.company_name)
    contact person   -> buyer id + default cost center + customer account
                        (Buyer_Profiles.buyer_name)

This mirrors how a production order-management platform performs entity
resolution against ERP / CRM master data: a customer sends a standard PO with
their company name and a contact person, and the system resolves the internal
account and buyer records behind the scenes.
"""
import re
from modules.xlsx_util import clean
from modules.integrations import COMMERCE


def normalize(name: str) -> str:
    """Normalize a name for tolerant matching (case, spacing, punctuation)."""
    if not name:
        return ""
    s = str(name).strip().lower()
    s = re.sub(r"\(.*?\)", " ", s)          # drop parentheticals e.g. "(legacy)"
    s = re.sub(r"[^a-z0-9&]+", " ", s)       # punctuation -> space (keep &)
    s = re.sub(r"\s+", " ", s).strip()
    return s


class EntityResolver:
    def __init__(self):
        self.company_to_account = {}   # normalized company name -> customer_account
        self.buyer_by_name = {}        # normalized buyer name  -> {ids}
        self.buyer_by_email = {}       # lowercased email       -> {ids}
        # Default header-field lookups used when a PO omits an optional field:
        self.contract_by_customer = {}   # customer_account -> active contract_reference
        self.instr_by_zip = {}            # ship-to ZIP     -> default delivery instructions
        self.instr_by_customer = {}       # customer_account -> default delivery instructions
                                          # (used when the ship-to has no per-location value)
        self._load_customers()
        self._load_buyers()
        self._load_contracts()
        self._load_shipto_instructions()

    def _load_customers(self):
        try:
            rows = COMMERCE.get_customer(["Customer_Master"])["Customer_Master"]
        except Exception:
            rows = []
        for r in rows:
            account = clean(r.get("customer_account"))
            company = clean(r.get("company_name"))
            if account and company:
                self.company_to_account.setdefault(normalize(company), account)

    def _load_buyers(self):
        try:
            rows = COMMERCE.get_buyer(["Buyer_Profiles"])["Buyer_Profiles"]
        except Exception:
            rows = []
        for r in rows:
            bid = clean(r.get("buyer_id"))
            name = clean(r.get("buyer_name"))
            email = clean(r.get("email"))
            info = {
                "buyer_id": bid,
                "buyer_name": name,
                "customer_account": clean(r.get("customer_account")),
                "default_cost_center": clean(r.get("default_cost_center")),
                "status": clean(r.get("status")),
            }
            if bid and name:
                self.buyer_by_name.setdefault(normalize(name), info)
            if bid and email:
                self.buyer_by_email.setdefault(email.strip().lower(), info)

    def _load_contracts(self):
        """Index each customer's ACTIVE contract reference so we can supply it
        as the default when a PO omits the contract number."""
        try:
            rows = COMMERCE.get_pricing(["Contracts"])["Contracts"]
        except Exception:
            rows = []
        for r in rows:
            cust = clean(r.get("customer_account"))
            ref  = clean(r.get("contract_reference"))
            status = (clean(r.get("status")) or "").upper()
            if cust and ref and status == "ACTIVE":
                # first ACTIVE contract wins (rows are order-of-priority in the sheet)
                self.contract_by_customer.setdefault(cust, ref)

    def _load_shipto_instructions(self):
        """Index each ship-to location's default delivery instructions, keyed by
        both ZIP and by customer account (so we can fall back one level up)."""
        try:
            rows = COMMERCE.get_customer(["Ship_To_Master"])["Ship_To_Master"]
        except Exception:
            rows = []
        for r in rows:
            instr = clean(r.get("default_delivery_instructions"))
            if not instr:
                continue
            zip_ = clean(r.get("zip"))
            cust = clean(r.get("customer_account"))
            if zip_:
                self.instr_by_zip.setdefault(zip_, instr)
            if cust:
                self.instr_by_customer.setdefault(cust, instr)

    # ── Public API ───────────────────────────────────────────────────────────
    def resolve_company(self, company_name):
        """Return the customer account for a company name, or None."""
        return self.company_to_account.get(normalize(company_name))

    def resolve_buyer(self, contact_person):
        """Return {buyer_id, customer_account, default_cost_center} or None."""
        return self.buyer_by_name.get(normalize(contact_person))

    def resolve_buyer_by_email(self, email):
        """Return {buyer_id, customer_account, default_cost_center} or None."""
        if not email:
            return None
        return self.buyer_by_email.get(str(email).strip().lower())

    # ── Default header-field lookups (used when the PO omits these) ─────────
    def default_contact_person(self, email):
        """Return the buyer_name registered against this email in Buyer_Profiles."""
        b = self.resolve_buyer_by_email(email)
        return (b or {}).get("buyer_name")

    def default_contract_reference(self, customer_account):
        """Return the customer's current ACTIVE contract reference."""
        return self.contract_by_customer.get(clean(customer_account) or "")

    def default_delivery_instructions(self, zip_=None, customer_account=None):
        """Return the ship-to's default delivery instructions (by ZIP first,
        then by customer account)."""
        if zip_ and clean(zip_) in self.instr_by_zip:
            return self.instr_by_zip[clean(zip_)]
        if customer_account and clean(customer_account) in self.instr_by_customer:
            return self.instr_by_customer[clean(customer_account)]
        return None
