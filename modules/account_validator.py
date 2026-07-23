"""
account_validator.py
Corporate Account Hierarchy and Ship-To Validation.

Reads MOCK master data (no real ERP / CRM / WMS / OMS / SMTP) from a single
Excel workbook:  mock-data/customer-master-data.xlsx  with sheets:
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

from modules.integrations import COMMERCE, OMS

MOCK_DIR             = os.path.join(os.path.dirname(__file__), "..", "mock-data")
CUSTOMER_MASTER_XLSX = os.path.join(MOCK_DIR, "customer-master-data.xlsx")

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

    # Customer standing (Customer Validation decision layer)
    buying_history:      Optional[dict] = None

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
    def __init__(self, master_path: str = CUSTOMER_MASTER_XLSX):
        # Customer identity, corporate hierarchy, ship-to master, hierarchy rules
        # and fulfillment-rule profiles are fetched from the Mock Commerce
        # platform. (``master_path`` is retained for backward compatibility but
        # the data now flows through the mock system clients.)
        c = COMMERCE.get_customer(
            ["Customer_Master", "Account_Hierarchy", "Ship_To_Master",
             "Hierarchy_Rules", "Fulfillment_Rules"])
        self._customer_rows  = c["Customer_Master"]
        self._hierarchy_rows = c["Account_Hierarchy"]
        self._shipto_rows    = c["Ship_To_Master"]
        self._rule_rows      = c["Hierarchy_Rules"]
        # Fulfillment rule profiles: preferred warehouse, alternates, restricted
        # DCs, split-shipment / backorder flags, MOQ, delivery SLA, allocation
        # priority. Hierarchy_Rules.fulfillment_rule stores the rule_id.
        self._fulfillment_rule_rows = c["Fulfillment_Rules"]
        # Buying history is stored as transactional past orders (header + lines)
        # in the Mock OMS. The per-customer buying-history summary used by
        # Customer Validation + Product Match is DERIVED from these transactions
        # at load time (see _build_indexes / _build_buying_history).
        o = OMS.get_order_history(["Order_History", "Order_History_Lines"])
        self._order_history_rows = o["Order_History"]
        self._order_history_line_rows = o["Order_History_Lines"]
        self._build_indexes()
        self._build_fulfillment_rule_index()

    def _build_fulfillment_rule_index(self):
        self.fulfillment_rule_profiles: Dict[str, dict] = {}
        for r in self._fulfillment_rule_rows:
            rid = _clean(r.get("rule_id"))
            if not rid:
                continue
            self.fulfillment_rule_profiles[rid] = {
                "rule_id":                rid,
                "rule_name":              _clean(r.get("rule_name")) or rid,
                "preferred_warehouse":    _clean(r.get("preferred_warehouse")) or "",
                "alternate_warehouses":   [w.strip() for w in
                    (str(r.get("alternate_warehouses") or "").split(",")) if w.strip()],
                "restricted_warehouses":  [w.strip() for w in
                    (str(r.get("restricted_warehouses") or "").split(",")) if w.strip()],
                "split_shipment_allowed": (_clean(r.get("split_shipment_allowed")) or "Y").upper() == "Y",
                "backorder_allowed":      (_clean(r.get("backorder_allowed")) or "Y").upper() == "Y",
                "max_backorder_days":     int(float(r.get("max_backorder_days") or 0)),
                "min_order_qty":          int(float(r.get("min_order_qty") or 0)),
                "delivery_sla_days":      int(float(r.get("delivery_sla_days") or 0)),
                "allocation_priority":    _clean(r.get("allocation_priority")) or "SILVER",
                "description":            _clean(r.get("description")) or "",
            }

    def get_fulfillment_rule(self, rule_id: Optional[str]) -> Optional[dict]:
        """Resolve a fulfillment rule ID (from applied_rules) to its full profile."""
        if not rule_id:
            return None
        return self.fulfillment_rule_profiles.get(str(rule_id).strip())

    # ── Buying history derived from transactional order history ─────────────────
    def _build_buying_history(self):
        """Derive a per-customer buying-history summary from past orders.

        Buying history is not stored pre-aggregated; it is computed from the
        transactional Order_History (header) + Order_History_Lines (detail)
        tables, exactly as an ERP would report a customer's purchasing profile.
        Exposed per customer:
          customer_since, total_orders, lifetime_value, avg_order_value,
          last_order_date, frequent_families, frequent_skus, recent_orders.
        """
        # Index line items by order_id
        lines_by_order: Dict[str, list] = {}
        for r in self._order_history_line_rows:
            oid = _clean(r.get("order_id"))
            if not oid:
                continue
            try:
                qty = float(r.get("quantity") or 0)
            except (TypeError, ValueError):
                qty = 0.0
            lines_by_order.setdefault(oid, []).append({
                "sku":       (_clean(r.get("sku")) or "").upper(),
                "family":    (_clean(r.get("product_family")) or "").upper(),
                "quantity":  qty,
                "uom":       _clean(r.get("uom")) or "",
                "unit_price": _clean(r.get("unit_price")) or "",
                "line_total": _clean(r.get("line_total")) or "",
            })

        # Group order headers by customer account
        orders_by_acct: Dict[str, list] = {}
        for r in self._order_history_rows:
            acct = _clean(r.get("customer_account"))
            oid = _clean(r.get("order_id"))
            if not acct or not oid:
                continue
            try:
                total = float(r.get("order_total") or 0)
            except (TypeError, ValueError):
                total = 0.0
            orders_by_acct.setdefault(acct.upper(), []).append({
                "order_id":     oid,
                "po_number":    _clean(r.get("po_number")) or "",
                "order_date":   _clean(r.get("order_date")) or "",
                "order_status": _clean(r.get("order_status")) or "",
                "order_total":  total,
                "currency":     _clean(r.get("currency")) or "",
                "lines":        lines_by_order.get(oid, []),
            })

        self.order_history: Dict[str, list] = orders_by_acct
        self.buying_history: Dict[str, dict] = {}
        for acct, orders in orders_by_acct.items():
            if not orders:
                continue
            orders_sorted = sorted(orders, key=lambda o: o["order_date"])
            total_orders = len(orders_sorted)
            lifetime_value = round(sum(o["order_total"] for o in orders_sorted), 2)
            avg_order_value = round(lifetime_value / total_orders, 2) if total_orders else 0.0
            dates = [o["order_date"] for o in orders_sorted if o["order_date"]]
            customer_since = dates[0][:4] if dates else ""
            last_order_date = dates[-1] if dates else ""

            # Rank families / SKUs by cumulative quantity across all order lines.
            fam_qty: Dict[str, float] = {}
            sku_qty: Dict[str, float] = {}
            for o in orders_sorted:
                for ln in o["lines"]:
                    if ln["family"]:
                        fam_qty[ln["family"]] = fam_qty.get(ln["family"], 0.0) + ln["quantity"]
                    if ln["sku"]:
                        sku_qty[ln["sku"]] = sku_qty.get(ln["sku"], 0.0) + ln["quantity"]
            frequent_families = [f for f, _ in
                                 sorted(fam_qty.items(), key=lambda kv: kv[1], reverse=True)]
            frequent_skus = [s for s, _ in
                             sorted(sku_qty.items(), key=lambda kv: kv[1], reverse=True)[:5]]

            self.buying_history[acct] = {
                "customer_since":    customer_since,
                "total_orders":      total_orders,
                "lifetime_value":    lifetime_value,
                "avg_order_value":   avg_order_value,
                "last_order_date":   last_order_date,
                "frequent_families": frequent_families,
                "frequent_skus":     frequent_skus,
                "recent_orders":     list(reversed(orders_sorted))[:3],
            }

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
                # Customer Validation attributes (shown in Resolved Account
                # Hierarchy and used by the Customer Validation layer).
                "customer_tier":              _clean(r.get("customer_tier")) or "",
                "payment_terms":              _clean(r.get("payment_terms")) or "",
                "customer_class":             _clean(r.get("customer_class")) or "",
                "distributor_authorization":  _clean(r.get("distributor_authorization")) or "",
            })

        # Buying history: derive a per-customer summary from the transactional
        # order history (Order_History + Order_History_Lines).
        self._build_buying_history()

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
                 ship_to_zip: Optional[str],
                 company_name: Optional[str] = None) -> AccountValidationResult:
        r = AccountValidationResult()
        who = customer_account or company_name
        r.audit_trail.append(
            f"Account validation started for customer='{who}', "
            f"ship-to ZIP='{ship_to_zip}'."
        )

        # ── Resolve customer identity ──────────────────────────────────────────
        matches = [c for c in self.customers
                   if customer_account and
                   c["customer_account"].upper() == customer_account.upper()]

        if len(matches) == 0:
            ident = (f"Customer account '{customer_account}'" if customer_account
                     else f"Company '{company_name}'" if company_name
                     else "The customer")
            r.status = "EXCEPTION"
            r.exception_type = "UNMATCHED_CUSTOMER"
            r.message = (f"{ident} was not found in the "
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

        # ── Customer standing: tier, class, distributor status, terms ─────────
        r.audit_trail.append(
            f"Customer standing: tier={customer.get('customer_tier') or 'n/a'}, "
            f"class={customer.get('customer_class') or 'n/a'}, "
            f"distributor status={customer.get('distributor_authorization') or 'n/a'}, "
            f"payment terms={customer.get('payment_terms') or 'n/a'}.")

        # ── Buying-history validation (Customer Validation decision layer) ─────
        bh = self.buying_history.get((customer["customer_account"] or "").upper())
        r.buying_history = bh
        if bh:
            lv = bh.get("lifetime_value")
            lv_disp = f"${lv:,.0f}" if isinstance(lv, (int, float)) else str(lv)
            r.audit_trail.append(
                f"Buying history verified from {bh.get('total_orders')} past order(s): "
                f"customer since {bh.get('customer_since')}, "
                f"lifetime value {lv_disp}, "
                f"last order {bh.get('last_order_date')}, "
                f"frequent families {', '.join(bh.get('frequent_families') or []) or 'n/a'}.")
        else:
            r.audit_trail.append(
                "Buying history: no prior purchase history on file (new customer).")

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
