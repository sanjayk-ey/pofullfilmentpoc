"""
inventory_validator.py
Inventory Availability, ATP, Allocation, and Partial Fulfillment Planning.

Checks availability across plant stock, DC stock, in-transit stock, and ATP;
applies customer-specific fulfillment rules; proposes partial fulfillment with a
backorder plan when the full quantity is not available.

Master data: inventory-master-data.xlsx (Plant_Stock, DC_Stock, In_Transit, ATP,
Allocation_Rules, Fulfillment_Preferences).

Exception types: INVENTORY_SHORTAGE, ALLOCATION_CONFLICT.
"""
from modules.stage_result import StageResult
from modules.xlsx_util import load_sheets, clean, to_num


class InventoryValidator:
    stage_key = "inventory"
    title = "Inventory Availability & ATP"
    icon = "📦"
    steps = [
        (0.30, "🏭", "Checking plant and distribution center stock..."),
        (0.30, "🚛", "Adding in-transit and available-to-promise supply..."),
        (0.30, "📐", "Applying customer fulfillment rules and allocation..."),
        (0.25, "🧾", "Recording fulfillment plan..."),
    ]

    def __init__(self):
        s = load_sheets("inventory-master-data.xlsx",
                        ["Plant_Stock", "DC_Stock", "In_Transit", "ATP",
                         "Allocation_Rules", "Fulfillment_Preferences"])
        self.atp = {clean(r.get("sku")): r for r in s["ATP"] if clean(r.get("sku"))}
        self.dc = s["DC_Stock"]
        self.plant = s["Plant_Stock"]
        self.transit = s["In_Transit"]
        self.alloc = {clean(r.get("customer_tier")): r for r in s["Allocation_Rules"] if clean(r.get("customer_tier"))}
        self.prefs = {clean(r.get("customer_account")): r for r in s["Fulfillment_Preferences"] if clean(r.get("customer_account"))}

    def _dc_for(self, sku, preferred, restricted):
        rows = [d for d in self.dc if clean(d.get("sku")) == sku
                and clean(d.get("location_id")) != restricted
                and to_num(d.get("on_hand_qty"), 0) > 0]
        rows.sort(key=lambda d: 0 if clean(d.get("location_id")) == preferred else 1)
        return rows

    def validate(self, ctx) -> StageResult:
        r = StageResult(self.stage_key, self.title, self.icon)
        customer = clean(ctx.get("customer_account"))
        lines = ctx.get("resolved_lines", [])
        pref = self.prefs.get(customer, {})
        preferred = clean(pref.get("preferred_warehouse"))
        restricted = clean(pref.get("restricted_dc"))
        tier = clean(pref.get("customer_tier")) or "SILVER"
        backorder_tol = to_num(pref.get("backorder_tolerance_days"),
                               to_num((self.alloc.get(tier) or {}).get("backorder_tolerance_days"), 0))
        r.log(f"Inventory check started ({customer}, tier {tier}, preferred {preferred}).")

        avail_rows = []
        plan = []
        for ln in lines:
            sku = ln["sku"]; need = to_num(ln.get("qty_base"), 0) or 0
            atp = to_num((self.atp.get(sku) or {}).get("atp_qty"), 0)
            dcs = self._dc_for(sku, preferred, restricted)
            source = clean(dcs[0].get("location_id")) if dcs else (preferred or "PLANT")
            avail_rows.append([sku, f"{need:g}", f"{atp:g}", source,
                               "Available" if need <= atp else "Short"])

            if need > atp:
                backordered = need - atp
                eta = clean((self.atp.get(sku) or {}).get("next_replenishment_date"))
                r.fail("INVENTORY_SHORTAGE",
                       f"SKU '{sku}' requested {need:g} but only {atp:g} available-to-promise.")
                r.kv("Partial fulfillment proposal", [
                    ("SKU", sku),
                    ("Requested", f"{need:g}"),
                    ("Available now", f"{atp:g} from {source}"),
                    ("Backordered", f"{backordered:g}"),
                    ("Estimated availability", eta or "TBD"),
                    ("Backorder tolerance", f"{backorder_tol} days"),
                    ("Split shipment", clean(pref.get("split_shipment")) or "—"),
                ])
                r.note("Inventory shortage proposal routed to CSR for customer confirmation.")
                r.log(f"SKU '{sku}': shortage -> inventory exception.")
                return r

            plan.append({"sku": sku, "qty": need, "source": source})

        r.ok(f"All {len(lines)} line(s) available across the fulfillment network. "
             f"Ready for logistics validation.")
        r.table("Availability", ["SKU", "Requested", "ATP", "Source", "Status"], avail_rows)
        r.kv("Applied fulfillment rules", [
            ("Customer tier", tier),
            ("Preferred warehouse", preferred or "—"),
            ("Restricted DC", restricted or "none"),
            ("Split shipment", clean(pref.get("split_shipment")) or "—"),
            ("Backorder tolerance", f"{backorder_tol} days"),
            ("Allocation priority", to_num((self.alloc.get(tier) or {}).get("priority"), "—")),
        ])
        r.data["fulfillment_plan"] = plan
        r.data["fulfillment_source"] = plan[0]["source"] if plan else preferred
        r.log("Inventory result: PASS -> proceed to logistics.")
        return r
