"""
logistics_validator.py
Logistics, ZIP Serviceability, Delivery SLA, and Fulfillment Optimization.

Validates carrier serviceability for the ship-to ZIP, calculates ETA against the
delivery SLA, rates freight, and recommends the optimal cost-service fulfillment
option; raises an exception when the ZIP is not serviceable or the SLA is missed.

Master data: logistics-master-data.xlsx (Carrier_Coverage, Freight_Rating,
SLA_Rules, Warehouse_Master, Delivery_Calendar).

Exception types: ZIP_NOT_SERVICEABLE, SLA_MISS.
"""
from datetime import date, timedelta
from modules.stage_result import StageResult
from modules.xlsx_util import load_sheets, clean, to_num


class LogisticsValidator:
    stage_key = "logistics"
    title = "Logistics, Serviceability & Delivery SLA"
    icon = "🚚"
    steps = [
        (0.30, "📍", "Validating ship-to ZIP serviceability..."),
        (0.30, "🗓️", "Calculating ETA against delivery SLA..."),
        (0.30, "💸", "Rating freight and optimizing warehouse/carrier..."),
        (0.25, "🧾", "Recording fulfillment optimization decision..."),
    ]

    def __init__(self):
        s = load_sheets("logistics-master-data.xlsx",
                        ["Carrier_Coverage", "Freight_Rating", "SLA_Rules",
                         "Warehouse_Master", "Delivery_Calendar"])
        self.coverage = s["Carrier_Coverage"]
        self.rating = s["Freight_Rating"]
        self.sla = s["SLA_Rules"]
        self.warehouses = s["Warehouse_Master"]

    def _sla_max(self, customer):
        row = next((x for x in self.sla if clean(x.get("scope_type")) == "customer"
                    and clean(x.get("scope_id")) == customer), None)
        row = row or next((x for x in self.sla if clean(x.get("scope_type")) == "default"), None)
        return to_num((row or {}).get("max_transit_days"), 5)

    def validate(self, ctx) -> StageResult:
        r = StageResult(self.stage_key, self.title, self.icon)
        customer = clean(ctx.get("customer_account"))
        zip_ = clean(ctx.get("ship_to_zip")) or ""
        prefix = zip_[:3]
        source = clean(ctx.get("fulfillment_source")) or "DC-CHI-01"
        lines = ctx.get("resolved_lines", [])
        weight = round(sum((to_num(l.get("weight_kg"), 0) or 0) * (to_num(l.get("qty_base"), 0) or 0) for l in lines), 1)
        r.log(f"Logistics started for ZIP '{zip_}' (prefix {prefix}), source {source}, weight {weight}kg.")

        carriers = [c for c in self.coverage if clean(c.get("zip_prefix")) == prefix
                    and str(clean(c.get("serviceable"))).upper() == "Y"]
        if not carriers:
            r.fail("ZIP_NOT_SERVICEABLE",
                   f"Ship-to ZIP '{zip_}' is not serviceable by any available carrier.")
            r.table("Suggested alternatives (pickup locations)",
                    ["Warehouse", "Name", "ZIP", "Region"],
                    [[clean(w.get("warehouse_id")), clean(w.get("name")), clean(w.get("zip")),
                      clean(w.get("region"))] for w in self.warehouses])
            r.note("Routed to CSR for customer communication (alternate carrier / ship-to / pickup).")
            r.log("ZIP not serviceable -> logistics exception.")
            return r

        # Prefer GROUND service, then fastest transit
        carriers.sort(key=lambda c: (0 if clean(c.get("service_level")) == "GROUND" else 1,
                                     to_num(c.get("transit_days"), 99)))
        chosen = carriers[0]
        transit = to_num(chosen.get("transit_days"), 99)
        sla_max = self._sla_max(customer)

        # Freight rating (use first matching carrier zone)
        rate = next((x for x in self.rating if clean(x.get("carrier")) == clean(chosen.get("carrier"))), None)
        freight = 0.0
        if rate:
            freight = round(to_num(rate.get("base_rate"), 0) + to_num(rate.get("per_kg_rate"), 0) * weight, 2)
        eta = date.today() + timedelta(days=transit)

        if transit > sla_max:
            r.fail("SLA_MISS",
                   f"Best available transit time ({transit} days) exceeds the delivery SLA "
                   f"of {sla_max} days for ZIP '{zip_}'.")
            r.kv("SLA assessment", [
                ("Carrier", clean(chosen.get("carrier"))),
                ("Transit days", transit), ("SLA max", sla_max),
                ("Estimated delivery", eta.strftime("%d %b %Y")),
            ])
            r.note("Routed to CSR for alternate delivery proposal.")
            r.log("Transit exceeds SLA -> SLA miss exception.")
            return r

        r.ok(f"ZIP serviceable. Optimal fulfillment selected. ETA {eta.strftime('%d %b %Y')}. "
             f"Ready for order execution.")
        r.kv("Fulfillment optimization", [
            ("Ship-to ZIP", zip_),
            ("Selected warehouse", source),
            ("Carrier", f"{clean(chosen.get('carrier'))} ({clean(chosen.get('service_level'))})"),
            ("Transit days", f"{transit} (SLA {sla_max})"),
            ("Shipment weight", f"{weight} kg"),
            ("Freight cost", f"${freight:,.2f}"),
            ("Estimated delivery (ETA)", eta.strftime("%d %b %Y")),
            ("Plan", "Single shipment (best cost-service outcome)"),
        ])
        r.data["eta"] = eta.strftime("%d %b %Y")
        r.data["carrier"] = clean(chosen.get("carrier"))
        r.data["freight_cost"] = freight
        r.log("Logistics result: PASS -> proceed to order execution.")
        return r
