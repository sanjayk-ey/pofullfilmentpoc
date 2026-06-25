"""
account_validator.py
Corporate Account Hierarchy and Ship-To Validation.

Reads MOCK master data (no real ERP / CRM / WMS / OMS / SMTP) from a single
Excel workbook:  mock-data/master-data.xlsx  with sheets:
    Customer_Master    - customer accounts + ERP customer records + CRM/account records
    Account_Hierarchy  - branch -> regional division -> global parent
    Ship_To_Master     - ship-to locations matched by ZIP
    Hierarchy_Rules    - rules defined at each hierarchy level

Responsibilities:
  - Identify the account hierarchy (global parent, regional division, branch,
    ship-to) and determine the applicable hierarchy-level rules.
  - Escalate an invalid ship-to that is not associated with the customer
    account hierarchy.
  - Apply the most specific eligible rules (ship-to > branch > regional >
    global parent) and log the applied hierarchy level in the audit trail.

Exception types covered:
  UNMATCHED_CUSTOMER, DUPLICATE_CUSTOMER, INVALID_SHIP_TO, HIERARCHY_MISMATCH
"""
import os
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple

import openpyxl

MOCK_DIR     = os.path.join(os.path.dirname(__file__), "..", "mock-data")
MASTER_XLSX  = os.path.join(MOCK_DIR, "master-data.xlsx")

# Rule levels ordered from most specific to least specific
RULE_LEVELS = ["ship_to", "branch", "regional_division", "global_parent"]

# All rule keys that may appear at any level
RULE_KEYS = [
    "pricing_tier",
    "product_visibility",
    "budget_limit",
    "approval_routing",
    "fulfillment_rule",
]


# ── Result structure ───────────────────────────────────────────────────────────
@dataclass
class AccountValidationResult:
    status:          str            = "PASS"        # PASS | EXCEPTION
    exception_type:  Optional[str]  = None          # see exception types above
    message:         str            = ""

    # Resolved hierarchy
    customer:            Optional[dict] = None
    global_parent:       Optional[dict] = None
    regional_division:   Optional[dict] = None
    branch:              Optional[dict] = None
    ship_to:             Optional[dict] = None

    # Applied rules
    applied_rules:        Dict[str, str] = field(default_factory=dict)
    applied_rule_sources: Dict[str, str] = field(default_factory=dict)
    applied_level:        Optional[str]  = None

    # Exception support detail
    candidates:        List[dict] = field(default_factory=list)  # duplicate customer records
    possible_ship_tos: List[dict] = field(default_factory=list)  # for invalid / mismatch

    # Audit trail
    audit_trail: List[str] = field(default_factory=list)

    @property
    def is_exception(self) -> bool:
        return self.status == "EXCEPTION"


# ── Excel loader ─────────────────────────────────────────────────────────────
def _read_sheet(wb, sheet_name: str) -> List[dict]:
    """Read a worksheet into a list of row-dicts. Row 1 = title, row 2 = headers."""
    ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        return []
    headers = [str(h).strip() if h is not None else "" for h in rows[1]]
    out = []
    for raw in rows[2:]:
        if raw is None or all(v is None or str(v).strip() == "" for v in raw):
            continue
        record = {}
        for h, v in zip(headers, raw):
            if not h:
                continue
            record[h] = v
        out.append(record)
    return out


def _clean(v):
    """Return a stripped string for non-empty values, else None."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s != "" else None


class AccountValidator:
    def __init__(self, master_path: str = MASTER_XLSX):
        wb = openpyxl.load_workbook(master_path, data_only=True)
        self._customer_rows  = _read_sheet(wb, "Customer_Master")
        self._hierarchy_rows = _read_sheet(wb, "Account_Hierarchy")
        self._shipto_rows    = _read_sheet(wb, "Ship_To_Master")
        self._rule_rows      = _read_sheet(wb, "Hierarchy_Rules")
        wb.close()
        self._build_indexes()

    # ── Build lookup indexes from the flat Excel tables ─────────────────────────
    def _build_indexes(self):
        # Rules keyed by level_id
        self._rules_by_id: Dict[str, dict] = {}
        for r in self._rule_rows:
            level_id = _clean(r.get("level_id"))
            if not level_id:
                continue
            rules = {}
            for col in RULE_KEYS:
                val = r.get(col)
                if val is None or str(val).strip() == "":
                    continue
                if col == "budget_limit":
                    try:
                        val = int(float(val))
                    except (TypeError, ValueError):
                        pass
                else:
                    val = str(val).strip()
                rules[col] = val
            self._rules_by_id[level_id] = rules

        # Customers
        self.customers = []
        for r in self._customer_rows:
            self.customers.append({
                "customer_account": _clean(r.get("customer_account")) or "",
                "company_name":     _clean(r.get("company_name")) or "",
                "status":           _clean(r.get("status")) or "",
                "branch_id":        _clean(r.get("branch_id")) or "",
                "erp_customer_id":  _clean(r.get("erp_customer_id")) or "",
                "crm_account_id":   _clean(r.get("crm_account_id")) or "",
            })

        # Branch -> {branch, regional_division, global_parent} (each node carries rules)
        self.branch_index: Dict[str, dict] = {}
        for r in self._hierarchy_rows:
            bid = _clean(r.get("branch_id"))
            if not bid:
                continue
            rid = _clean(r.get("regional_division_id")) or ""
            gid = _clean(r.get("global_parent_id")) or ""
            self.branch_index[bid] = {
                "branch": {
                    "id": bid,
                    "name": _clean(r.get("branch_name")) or bid,
                    "rules": self._rules_by_id.get(bid, {}),
                },
                "regional_division": {
                    "id": rid,
                    "name": _clean(r.get("regional_division_name")) or rid,
                    "rules": self._rules_by_id.get(rid, {}),
                },
                "global_parent": {
                    "id": gid,
                    "name": _clean(r.get("global_parent_name")) or gid,
                    "rules": self._rules_by_id.get(gid, {}),
                },
            }

        # Ship-to locations (each carries its own rules)
        self.ship_tos = []
        for r in self._shipto_rows:
            sid = _clean(r.get("ship_to_id"))
            if not sid:
                continue
            self.ship_tos.append({
                "ship_to_id": sid,
                "name":       _clean(r.get("name")) or sid,
                "address":    _clean(r.get("address")) or "",
                "zip":        _clean(r.get("zip")) or "",
                "branch_id":  _clean(r.get("branch_id")) or "",
                "status":     _clean(r.get("status")) or "",
                "rules":      self._rules_by_id.get(sid, {}),
            })

        self.shipto_index = {st["ship_to_id"]: st for st in self.ship_tos}
        self.shipto_by_zip: Dict[str, list] = {}
        for st in self.ship_tos:
            self.shipto_by_zip.setdefault(st["zip"].upper(), []).append(st)

    # ── Public API ──────────────────────────────────────────────────────────────
    def validate(self, customer_account: Optional[str],
                 ship_to_zip: Optional[str]) -> AccountValidationResult:
        r = AccountValidationResult()
        r.audit_trail.append(
            f"Account validation started for customer='{customer_account}', "
            f"ship-to ZIP='{ship_to_zip}'."
        )

        # ── Resolve customer identity ──────────────────────────────────────────
        matches = [c for c in self.customers
                   if customer_account and
                   c["customer_account"].upper() == customer_account.upper()]

        if len(matches) == 0:
            r.status = "EXCEPTION"
            r.exception_type = "UNMATCHED_CUSTOMER"
            r.message = (f"Customer account '{customer_account}' was not found in the "
                         f"customer master. Cannot determine account hierarchy.")
            r.audit_trail.append("Customer lookup: NO MATCH -> Unmatched customer exception.")
            return r

        if len(matches) > 1:
            r.status = "EXCEPTION"
            r.exception_type = "DUPLICATE_CUSTOMER"
            r.message = (f"Customer account '{customer_account}' matches "
                         f"{len(matches)} master records. A unique customer identity "
                         f"is required before processing.")
            r.candidates = matches
            r.audit_trail.append(
                f"Customer lookup: {len(matches)} matches -> Duplicate customer exception.")
            return r

        customer = matches[0]
        r.customer = customer
        r.audit_trail.append(
            f"Customer resolved: {customer['company_name']} "
            f"(ERP {customer['erp_customer_id']}, CRM {customer['crm_account_id']}).")

        # ── Resolve hierarchy from customer's branch ───────────────────────────
        branch_info = self.branch_index.get(customer["branch_id"])
        if not branch_info:
            r.status = "EXCEPTION"
            r.exception_type = "HIERARCHY_MISMATCH"
            r.message = (f"Customer '{customer['company_name']}' is mapped to branch "
                         f"'{customer['branch_id']}' which does not exist in the account "
                         f"hierarchy.")
            r.audit_trail.append("Branch lookup: NOT FOUND -> Hierarchy mismatch exception.")
            return r

        r.branch            = branch_info["branch"]
        r.regional_division = branch_info["regional_division"]
        r.global_parent     = branch_info["global_parent"]
        r.audit_trail.append(
            f"Hierarchy resolved: {r.global_parent['name']} > "
            f"{r.regional_division['name']} > {r.branch['name']}.")

        # ── Validate ship-to by ZIP ────────────────────────────────────────────
        if not ship_to_zip:
            r.status = "EXCEPTION"
            r.exception_type = "INVALID_SHIP_TO"
            r.message = "No ship-to ZIP was provided on the order; cannot validate ship-to."
            r.possible_ship_tos = self._ship_tos_for_branch(customer["branch_id"])
            r.audit_trail.append("Ship-to ZIP missing -> Invalid ship-to exception.")
            return r

        zip_matches = self.shipto_by_zip.get(ship_to_zip.upper(), [])

        if not zip_matches:
            # ZIP is nowhere in the ship-to master
            r.status = "EXCEPTION"
            r.exception_type = "INVALID_SHIP_TO"
            r.message = (f"Ship-to ZIP '{ship_to_zip}' is not registered to any ship-to "
                         f"location in the system.")
            r.possible_ship_tos = self._ship_tos_for_branch(customer["branch_id"])
            r.audit_trail.append(
                f"Ship-to ZIP '{ship_to_zip}': no master record -> Invalid ship-to exception.")
            return r

        # ZIP exists — check it belongs to the customer's hierarchy
        ship_to = zip_matches[0]
        st_branch_info = self.branch_index.get(ship_to["branch_id"], {})
        st_parent = st_branch_info.get("global_parent", {})

        if st_parent.get("id") != r.global_parent["id"]:
            # ZIP belongs to a DIFFERENT corporate parent -> hierarchy mismatch
            r.status = "EXCEPTION"
            r.exception_type = "HIERARCHY_MISMATCH"
            r.message = (f"Ship-to ZIP '{ship_to_zip}' ({ship_to['name']}) belongs to "
                         f"'{st_parent.get('name','another company')}', which is not part "
                         f"of '{r.global_parent['name']}' - the customer's account "
                         f"hierarchy.")
            r.ship_to = ship_to
            r.possible_ship_tos = self._ship_tos_for_branch(customer["branch_id"])
            r.audit_trail.append(
                f"Ship-to '{ship_to['ship_to_id']}' under {st_parent.get('id')} != "
                f"customer parent {r.global_parent['id']} -> Hierarchy mismatch exception.")
            return r

        # Ship-to is under the same global parent — valid
        r.ship_to = ship_to
        r.audit_trail.append(
            f"Ship-to validated: {ship_to['name']} (ZIP {ship_to['zip']}) under "
            f"{r.global_parent['name']} hierarchy.")

        # ── Apply hierarchy-specific rules, most specific first ─────────────────
        self._apply_rules(r)

        r.status = "PASS"
        r.message = (f"Account hierarchy identified and ship-to validated. "
                     f"Order ready to proceed to buyer authorization validation.")
        r.audit_trail.append("Account validation result: PASS -> proceed to buyer authorization.")
        return r

    # ── Rule resolution ─────────────────────────────────────────────────────────
    def _apply_rules(self, r: AccountValidationResult):
        """
        Merge rules from least specific to most specific so that the most specific
        level wins. Record which level each applied rule came from (audit).
        """
        level_rules = {
            "global_parent":     (r.global_parent or {}).get("rules", {}),
            "regional_division": (r.regional_division or {}).get("rules", {}),
            "branch":            (r.branch or {}).get("rules", {}),
            "ship_to":           (r.ship_to or {}).get("rules", {}),
        }

        applied = {}
        sources = {}
        # Apply from least specific -> most specific (later overrides earlier)
        for level in reversed(RULE_LEVELS):          # global_parent ... ship_to
            for key, val in level_rules.get(level, {}).items():
                applied[key] = val
                sources[key] = level

        r.applied_rules = {k: applied[k] for k in RULE_KEYS if k in applied}
        r.applied_rule_sources = {k: sources[k] for k in r.applied_rules}

        # Most specific level that actually contributed a rule
        for level in RULE_LEVELS:
            if any(src == level for src in sources.values()):
                r.applied_level = level
                break

        level_label = {
            "ship_to": "ship-to", "branch": "branch",
            "regional_division": "regional division", "global_parent": "global parent",
        }.get(r.applied_level, r.applied_level)
        r.audit_trail.append(
            f"Applied hierarchy rules (most specific level: {level_label}). "
            f"Rule sources: " +
            ", ".join(f"{k}={level_label_short(v)}" for k, v in r.applied_rule_sources.items())
            + ".")

    # ── Helpers ─────────────────────────────────────────────────────────────────
    def _ship_tos_for_branch(self, branch_id: str) -> List[dict]:
        """Return the candidate ship-to locations belonging to the customer's branch."""
        return [st for st in self.ship_tos if st["branch_id"] == branch_id]


def level_label_short(level: str) -> str:
    return {
        "ship_to": "ship-to",
        "branch": "branch",
        "regional_division": "regional",
        "global_parent": "global",
    }.get(level, level)
