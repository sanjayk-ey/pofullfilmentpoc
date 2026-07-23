"""
inventory_validator.py
Inventory Availability, ATP, Allocation, and Partial Fulfillment Planning.

This stage now applies the FULFILLMENT RULE PROFILE resolved by the account
validator (from customer-master-data.xlsx -> Fulfillment_Rules sheet) and
makes every decision visible in the StageResult output:

  - min_order_qty           order rejected if total qty below the MOQ
  - restricted_warehouses   never sourced from these DCs (audit/contract rules)
  - preferred_warehouse     first DC tried for each line
  - alternate_warehouses    fallback DCs in declared order
  - split_shipment_allowed  if N and a line needs >1 DC, raise an exception
  - backorder_allowed       if N and a line cannot be fully sourced, raise
  - max_backorder_days      acceptable backorder window
  - allocation_priority     used when stock is constrained

A customer-level row in inventory-master-data.xlsx -> Fulfillment_Preferences
still acts as an override for legacy compatibility.

Exception types: INVENTORY_SHORTAGE, ALLOCATION_CONFLICT, SPLIT_NOT_ALLOWED,
                 SPLIT_SHIPMENT, MIN_ORDER_QTY_NOT_MET, RESTRICTED_WAREHOUSE.
"""
from modules.stage_result import StageResult
from modules.xlsx_util import clean, to_num
from modules.integrations import ERP


class InventoryValidator:
    stage_key = "inventory"
    title = "Inventory Checks"
    icon = "📦"
    # Mock system: ERP serves plant / DC stock, ATP and allocation.
    systems = ("ERP",)
    steps = [
        (0.30, "🏭", "Checking plant and distribution center stock..."),
        (0.30, "🚛", "Adding in-transit and available-to-promise supply..."),
        (0.30, "📐", "Applying customer fulfillment rules and allocation..."),
        (0.25, "🧾", "Recording fulfillment plan..."),
    ]

    def __init__(self):
        s = ERP.get_inventory(
            ["Plant_Stock", "DC_Stock", "In_Transit", "ATP",
             "Allocation_Rules", "Fulfillment_Preferences"])
        self.atp = {clean(r.get("sku")): r for r in s["ATP"] if clean(r.get("sku"))}
        # DC stock indexed (sku, location) -> qty.  We track on-hand and the
        # quantity already reserved/committed to other demand, so unreserved
        # (allocatable) stock = on_hand - reserved.
        self.dc_stock = {}
        self.dc_reserved = {}
        for d in s["DC_Stock"]:
            sku = clean(d.get("sku"))
            loc = clean(d.get("location_id"))
            if sku and loc:
                self.dc_stock[(sku, loc)] = to_num(d.get("on_hand_qty"), 0) or 0
                self.dc_reserved[(sku, loc)] = to_num(d.get("quantity_reserved"), 0) or 0
        self.alloc = {clean(r.get("customer_tier")): r for r in s["Allocation_Rules"]
                      if clean(r.get("customer_tier"))}
        self.prefs = {clean(r.get("customer_account")): r for r in s["Fulfillment_Preferences"]
                      if clean(r.get("customer_account"))}

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _resolve_profile(self, ctx):
        """Merge hierarchy profile (primary) with customer-level override (legacy)."""
        prof = dict(ctx.get("fulfillment_profile") or {})
        cust = self.prefs.get(clean(ctx.get("customer_account"))) or {}
        # Customer-level override (only if set) overrides specific fields
        if clean(cust.get("preferred_warehouse")):
            prof["preferred_warehouse"] = clean(cust.get("preferred_warehouse"))
        if clean(cust.get("restricted_dc")):
            r = prof.get("restricted_warehouses") or []
            extra = clean(cust.get("restricted_dc"))
            if extra and extra not in r:
                prof["restricted_warehouses"] = r + [extra]
        # Sensible defaults if no profile was resolved at all
        prof.setdefault("preferred_warehouse", "")
        prof.setdefault("alternate_warehouses", [])
        prof.setdefault("restricted_warehouses", [])
        prof.setdefault("split_shipment_allowed", True)
        prof.setdefault("backorder_allowed", True)
        prof.setdefault("max_backorder_days", 0)
        prof.setdefault("min_order_qty", 0)
        prof.setdefault("delivery_sla_days", 0)
        prof.setdefault("allocation_priority", "SILVER")
        prof.setdefault("rule_id", "DEFAULT")
        prof.setdefault("rule_name", "Default")
        return prof

    def _allowed_dcs_for_sku(self, sku, profile):
        """Ordered list of (dc_id, qty) for this SKU honoring preferred -> alternates,
        excluding restricted DCs."""
        restricted = set(profile.get("restricted_warehouses") or [])
        order = []
        pref = profile.get("preferred_warehouse")
        if pref and pref not in restricted:
            order.append(pref)
        for alt in (profile.get("alternate_warehouses") or []):
            if alt and alt not in restricted and alt not in order:
                order.append(alt)
        # Add any other DCs in the master as a final fallback (still excluding restricted)
        for (s, loc) in self.dc_stock:
            if s == sku and loc not in restricted and loc not in order:
                order.append(loc)
        return [(loc, self.dc_stock.get((sku, loc), 0)) for loc in order]

    # ── Main ───────────────────────────────────────────────────────────────────
    def validate(self, ctx) -> StageResult:
        r = StageResult(self.stage_key, self.title, self.icon)
        customer = clean(ctx.get("customer_account"))
        lines = ctx.get("resolved_lines", [])
        profile = self._resolve_profile(ctx)

        r.log(f"Inventory check started ({customer}). "
              f"Applying fulfillment profile '{profile.get('rule_id')}' "
              f"({profile.get('rule_name')}).")

        # Show the resolved fulfillment profile up front so the applied rules are clear
        r.kv("Applied fulfillment rules (profile)", [
            ("Rule ID",                   profile.get("rule_id")),
            ("Rule name",                 profile.get("rule_name")),
            ("Preferred warehouse",       profile.get("preferred_warehouse") or "—"),
            ("Alternate warehouses",      ", ".join(profile.get("alternate_warehouses") or []) or "—"),
            ("Restricted warehouses",     ", ".join(profile.get("restricted_warehouses") or []) or "none"),
            ("Split shipment allowed",    "Yes" if profile.get("split_shipment_allowed") else "No"),
            ("Backorder allowed",         "Yes" if profile.get("backorder_allowed") else "No"),
            ("Max backorder days",        profile.get("max_backorder_days")),
            ("Minimum order quantity",    profile.get("min_order_qty")),
            ("Target delivery SLA",       f"{profile.get('delivery_sla_days')} days"),
            ("Allocation priority",       profile.get("allocation_priority")),
        ])
        if profile.get("description"):
            r.note(profile["description"])

        # Publish the preferred warehouse as the fulfillment source up-front so
        # that even if this stage raises a shortage/allocation exception that a
        # CSR later overrides, the final confirmation still shows a real DC
        # instead of "DEFAULT". The success path refines this to the actual DC.
        r.data["fulfillment_source"] = clean(profile.get("preferred_warehouse")) or ""

        # ── Min order quantity check ──────────────────────────────────────────
        moq = int(profile.get("min_order_qty") or 0)
        if moq > 0:
            total_qty = sum(int(to_num(ln.get("qty_base"), 0) or 0) for ln in lines)
            if total_qty < moq:
                r.fail("MIN_ORDER_QTY_NOT_MET",
                       f"Total order quantity {total_qty} is below the customer's "
                       f"minimum order quantity of {moq}.")
                r.kv("MOQ check", [
                    ("Total order quantity",   total_qty),
                    ("Required minimum",       moq),
                    ("Shortfall",              moq - total_qty),
                    ("Recommended action",     "CSR to confirm with customer or add lines"),
                ])
                r.log(f"MOQ {moq} not met (got {total_qty}) -> inventory exception.")
                return r

        # ── Per-line sourcing ──────────────────────────────────────────────────
        avail_rows = []
        plan = []
        any_split = False

        for ln in lines:
            sku = ln["sku"]
            need = int(to_num(ln.get("qty_base"), 0) or 0)
            atp_qty = int(to_num((self.atp.get(sku) or {}).get("atp_qty"), 0) or 0)

            allowed = self._allowed_dcs_for_sku(sku, profile)
            sources_used = []
            remaining = need
            for dc_id, qty_here in allowed:
                if remaining <= 0:
                    break
                if qty_here <= 0:
                    continue
                take = min(remaining, qty_here)
                sources_used.append((dc_id, take))
                remaining -= take

            sourced_qty = need - remaining

            # SPLIT-SHIPMENT rule: if split is forbidden, try to re-source from a single DC
            if len(sources_used) > 1 and not profile.get("split_shipment_allowed"):
                single = next(((dc, q) for dc, q in allowed if q >= need), None)
                if single:
                    sources_used = [(single[0], need)]
                    remaining = 0
                    r.log(f"SKU '{sku}': split disallowed -> re-sourced fully from {single[0]}.")
                else:
                    r.fail("SPLIT_NOT_ALLOWED",
                           f"SKU '{sku}' needs {need:g}, but no single DC has enough stock and "
                           f"the customer's profile forbids split shipments.")
                    r.kv("Split shipment violation", [
                        ("SKU", sku),
                        ("Requested", need),
                        ("Largest single DC stock", max((q for _, q in allowed), default=0)),
                        ("Allowed DC stocks",
                         ", ".join(f"{dc}:{q:g}" for dc, q in allowed) or "none"),
                        ("Would have split across",
                         ", ".join(f"{dc}:{q:g}" for dc, q in sources_used) or "none"),
                        ("Rule",  "split_shipment_allowed = N (single-shipment customer)"),
                        ("Recommended action",
                         "CSR to confirm: allow split this time, or raise customer override"),
                    ])
                    r.log(f"SKU '{sku}': split required but not allowed -> SPLIT_NOT_ALLOWED.")
                    return r

            # ── ALLOCATION PRIORITY (US-09 AC-04) ───────────────────────────────
            # On-hand can cover the line, but part of that stock is already
            # reserved/committed to higher-priority demand. If the unreserved
            # (allocatable) quantity cannot satisfy this order, raise an
            # allocation conflict rather than touching reserved stock.
            if remaining <= 0:
                total_onhand = sum(q for _, q in allowed)
                total_unreserved = sum(
                    max(0, self.dc_stock.get((sku, dc), 0) - self.dc_reserved.get((sku, dc), 0))
                    for dc, _ in allowed)
                if need > total_unreserved and total_onhand >= need:
                    reserved_total = total_onhand - total_unreserved
                    r.fail("ALLOCATION_CONFLICT",
                           f"SKU '{sku}': {need:g} requested, but only {total_unreserved:g} "
                           f"unreserved units are allocatable ({reserved_total:g} reserved for "
                           f"higher-priority demand).")
                    r.kv("Allocation conflict", [
                        ("SKU", sku),
                        ("Requested", need),
                        ("On-hand (all allowed DCs)", total_onhand),
                        ("Reserved / committed", reserved_total),
                        ("Unreserved (allocatable)", total_unreserved),
                        ("Allocation shortfall", need - total_unreserved),
                        ("This order's allocation priority", profile.get("allocation_priority")),
                        ("Reserved by DC",
                         ", ".join(f"{dc}:{self.dc_reserved.get((sku, dc), 0):g}"
                                   for dc, _ in allowed) or "none"),
                        ("Recommended action",
                         "CSR / planner to re-prioritise allocation or confirm backorder"),
                    ])
                    r.log(f"SKU '{sku}': need {need} > unreserved {total_unreserved} "
                          f"-> ALLOCATION_CONFLICT.")
                    return r

            # ── SPLIT-SHIPMENT APPROVAL (multi-warehouse delivery) ──────────────
            # The line is fully available, but only by pulling stock from more
            # than one warehouse (e.g. 8 from DC-CHI-01 + 2 from DC-DET-02 for a
            # qty of 10). Split shipments mean multiple deliveries / staggered
            # ETAs, so — even when the customer's profile permits splitting — a
            # CSR must confirm the split delivery before the order proceeds.
            if remaining <= 0 and len(sources_used) > 1 and profile.get("split_shipment_allowed"):
                any_split = True
                split_txt = " + ".join(f"{q:g} from {dc}" for dc, q in sources_used)
                r.fail("SPLIT_SHIPMENT",
                       f"SKU '{sku}' (qty {need:g}) can be fully delivered only by splitting the "
                       f"shipment across {len(sources_used)} warehouses ({split_txt}). "
                       f"CSR approval required for the split delivery.")
                r.kv("Split-shipment approval required", [
                    ("SKU", sku),
                    ("Requested quantity", need),
                    ("Warehouse split",
                     ", ".join(f"{dc} → {q:g} unit(s)" for dc, q in sources_used)),
                    ("Single-warehouse fulfillment possible?",
                     "No — no single warehouse holds the full quantity"),
                    ("Split shipment rule",
                     "Allowed (Y) — but split delivery needs CSR confirmation"),
                    ("Delivery impact",
                     "Multiple shipments / potentially staggered ETAs"),
                    ("Allocation priority", profile.get("allocation_priority")),
                    ("Recommended action",
                     "CSR to approve the split delivery, or consolidate to a single warehouse"),
                ])
                r.note("Split-delivery proposal routed to CSR for confirmation.")
                # Publish the planned split so downstream stages and the final
                # confirmation stay correct once the CSR approves the override.
                plan.append({"sku": sku, "qty": need,
                             "sources": [{"dc": dc, "qty": q} for dc, q in sources_used]})
                r.data["fulfillment_plan"] = plan
                r.data["fulfillment_source"] = sources_used[0][0]
                r.data["fulfillment_profile"] = profile
                r.data["delivery_sla_days"] = profile.get("delivery_sla_days")
                r.log(f"SKU '{sku}': fully sourced via split ({split_txt}) -> SPLIT_SHIPMENT approval.")
                return r

            if len(sources_used) > 1:
                any_split = True

            # BACKORDER rule
            if remaining > 0:
                if not profile.get("backorder_allowed"):
                    r.fail("INVENTORY_SHORTAGE",
                           f"SKU '{sku}' short by {remaining:g} and the customer's profile "
                           f"does not allow backorders.")
                    r.kv("Inventory shortage (no backorder allowed)", [
                        ("SKU", sku),
                        ("Requested", need),
                        ("Sourced from allowed DCs", sourced_qty),
                        ("Shortfall", remaining),
                        ("ATP (global)", atp_qty),
                        ("Rule", "backorder_allowed = N"),
                        ("Recommended action", "CSR to contact customer / propose substitute"),
                    ])
                    r.log(f"SKU '{sku}': shortfall {remaining}, backorder disallowed -> exception.")
                    return r

                # Backorder allowed — propose partial plan
                eta = clean((self.atp.get(sku) or {}).get("next_replenishment_date"))
                r.fail("INVENTORY_SHORTAGE",
                       f"SKU '{sku}': sourcing {sourced_qty:g} now, backordering {remaining:g}.")
                r.kv("Partial fulfillment proposal", [
                    ("SKU", sku),
                    ("Requested", need),
                    ("Available now",
                     ", ".join(f"{dc} ({q:g})" for dc, q in sources_used) or "none"),
                    ("Backordered", remaining),
                    ("Estimated availability", eta or "TBD"),
                    ("Max backorder window",
                     f"{profile.get('max_backorder_days')} days (customer policy)"),
                    ("Allocation priority", profile.get("allocation_priority")),
                ])
                r.note("Backorder proposal routed to CSR for customer confirmation.")
                r.log(f"SKU '{sku}': partial plan {sourced_qty}/{need} -> inventory exception.")
                return r

            avail_rows.append([sku, f"{need:g}", f"{atp_qty:g}",
                               ", ".join(f"{dc} ({q:g})" for dc, q in sources_used),
                               "Available"])
            plan.append({"sku": sku, "qty": need,
                         "sources": [{"dc": dc, "qty": q} for dc, q in sources_used]})

        # ── Success ────────────────────────────────────────────────────────────
        r.ok(f"All {len(lines)} line(s) available across the fulfillment network. "
             f"Ready for logistics validation.")
        r.table("Sourcing plan", ["SKU", "Requested", "ATP", "Source DC(s)", "Status"], avail_rows)
        if any_split:
            r.note(f"Order will be split across multiple DCs (allowed by rule "
                   f"'{profile.get('rule_id')}').")
        r.data["fulfillment_plan"] = plan
        primary = plan[0]["sources"][0]["dc"] if plan and plan[0]["sources"] \
                  else profile.get("preferred_warehouse")
        r.data["fulfillment_source"] = primary
        r.data["fulfillment_profile"] = profile
        r.data["delivery_sla_days"] = profile.get("delivery_sla_days")
        r.log("Inventory result: PASS -> proceed to logistics.")
        return r
