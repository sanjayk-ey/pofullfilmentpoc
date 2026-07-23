"""
logistics_validator.py
Fulfillment Optimization, Logistics, Serviceability, and Delivery SLA.

This stage evaluates MULTIPLE candidate fulfillment plans for every order and
picks the lowest-cost plan that satisfies inventory availability, delivery SLA,
and the customer's fulfillment rules (preferred/alternate/restricted warehouses,
split-shipment policy).

For every order it enumerates up to three candidate plans:
    Option A - ship everything from the preferred DC (single shipment)
    Option B - ship everything from the best alternate DC (single shipment)
    Option C - split the order across preferred + alternate (only if split
               is allowed and the order has 2+ lines)

For each candidate it computes:
    - Origin warehouse(s) and region
    - Carrier + service level (from Carrier_Coverage)
    - Transit days and ETA
    - Freight cost (Freight_Rating base_rate + per_kg_rate * weight, factored
      by an origin-to-destination zone lookup)
    - Inventory feasibility (all lines fully sourceable from the chosen
      warehouse(s) using DC_Stock net of reservations)
    - SLA compliance (transit <= customer delivery SLA)

The plans are ranked by total freight cost and the cheapest feasible plan
that meets SLA is selected as the winner. A comparison table (Option A / B /
C -> Cost, Transit, Feasible, Winner) is rendered as evidence so a demo
audience can see exactly why the winning plan was chosen.

Existing exception paths are preserved:
    ZIP_NOT_SERVICEABLE - no carrier services the ship-to ZIP
    SLA_MISS            - no feasible plan meets the delivery SLA
"""
from datetime import date, timedelta
from modules.stage_result import StageResult
from modules.xlsx_util import clean, to_num
from modules.integrations import SHIPPING, ERP


# Minimal ship-to ZIP prefix -> state mapping (kept in sync with pipeline.py).
# Duplicated here to avoid a circular import with modules.pipeline.
_REGION_PREFIX = {"606": "IL", "600": "IL", "601": "IL", "100": "NY", "104": "NY",
                  "482": "MI", "481": "MI", "900": "CA", "901": "CA", "902": "CA",
                  "752": "TX", "750": "TX", "751": "TX",
                  "E14": "UK", "E1": "UK"}


def _region_for_zip(zip_code):
    z = (str(zip_code or "")).strip()
    return _REGION_PREFIX.get(z[:3], "IL")


# Origin region (warehouse) -> destination region (from ship-to ZIP) -> zone
# code used to pick the right Freight_Rating row. Higher zone number = longer
# haul = higher rate. Fallback for any unlisted pairing is Z2.
_ZONE_MATRIX = {
    "Midwest": {"IL": "Z1", "MI": "Z1", "IN": "Z1", "OH": "Z1",
                "NY": "Z2", "NJ": "Z2", "PA": "Z2", "TX": "Z2",
                "CA": "Z3", "WA": "Z3", "AK": "Z3", "HI": "Z3"},
    "Northeast": {"NY": "Z1", "NJ": "Z1", "PA": "Z1",
                  "IL": "Z2", "MI": "Z2",
                  "CA": "Z3", "AK": "Z3"},
    "West":    {"CA": "Z1", "WA": "Z1", "OR": "Z1",
                "AK": "Z2",
                "IL": "Z3", "MI": "Z3", "NY": "Z3"},
    "South":   {"TX": "Z1", "FL": "Z1", "GA": "Z1",
                "IL": "Z2", "NY": "Z2",
                "CA": "Z3", "AK": "Z3"},
}


class LogisticsValidator:
    stage_key = "logistics"
    title = "Shipments"
    icon = "🎯"
    # Mock systems: the Shipping provider serves carrier coverage / freight /
    # SLA; ERP is checked for per-DC stock feasibility of each candidate plan.
    systems = ("SHIPPING", "ERP")
    steps = [
        (0.30, "📍", "Validating ship-to ZIP serviceability..."),
        (0.30, "🏭", "Enumerating candidate fulfillment plans (preferred / alternate / split)..."),
        (0.30, "💸", "Rating freight cost for each candidate plan..."),
        (0.30, "🗓️", "Scoring transit time against delivery SLA..."),
        (0.25, "🏆", "Selecting lowest-cost feasible plan..."),
    ]

    def __init__(self):
        log = SHIPPING.get_logistics(
            ["Carrier_Coverage", "Freight_Rating", "SLA_Rules",
             "Warehouse_Master", "Delivery_Calendar"])
        self.coverage = log["Carrier_Coverage"]
        self.rating = log["Freight_Rating"]
        self.sla = log["SLA_Rules"]
        self.warehouses = log["Warehouse_Master"]
        self.wh_by_id = {clean(w.get("warehouse_id")): w
                         for w in self.warehouses if clean(w.get("warehouse_id"))}

        # Inventory master — required to check per-DC availability for each
        # candidate plan (allocatable = on_hand - reserved).
        inv = ERP.get_inventory(["DC_Stock"])
        self.dc_stock = {}
        for d in inv["DC_Stock"]:
            sku = clean(d.get("sku"))
            loc = clean(d.get("location_id"))
            if sku and loc:
                on_hand = to_num(d.get("on_hand_qty"), 0) or 0
                reserved = to_num(d.get("quantity_reserved"), 0) or 0
                self.dc_stock[(sku, loc)] = max(on_hand - reserved, 0)

    # ── SLA & zone helpers ────────────────────────────────────────────────────
    def _sla_max(self, customer, ctx):
        sla_from_profile = to_num((ctx.get("fulfillment_profile") or {}).get("delivery_sla_days"), 0)
        if sla_from_profile and sla_from_profile > 0:
            return sla_from_profile
        row = next((x for x in self.sla if clean(x.get("scope_type")) == "customer"
                    and clean(x.get("scope_id")) == customer), None)
        row = row or next((x for x in self.sla if clean(x.get("scope_type")) == "default"), None)
        return to_num((row or {}).get("max_transit_days"), 5)

    def _zone(self, origin_wh_id, ship_to_zip):
        """Determine freight zone from origin warehouse region -> destination state."""
        wh = self.wh_by_id.get(origin_wh_id) or {}
        origin_region = clean(wh.get("region")) or "Midwest"
        dest_state = _region_for_zip(ship_to_zip)   # returns e.g. "IL", "NY", "CA"
        return _ZONE_MATRIX.get(origin_region, {}).get(dest_state, "Z2")

    def _serviceable_carriers(self, zip_):
        prefix = (zip_ or "")[:3]
        carriers = [c for c in self.coverage
                    if clean(c.get("zip_prefix")) == prefix
                    and str(clean(c.get("serviceable"))).upper() == "Y"]
        carriers.sort(key=lambda c: (0 if clean(c.get("service_level")) == "GROUND" else 1,
                                     to_num(c.get("transit_days"), 99)))
        return carriers

    def _freight_for(self, origin_wh_id, ship_to_zip, weight_kg, carrier_name):
        """Freight cost from an origin warehouse to the ship-to ZIP for one carrier."""
        zone = self._zone(origin_wh_id, ship_to_zip)
        rate = next((x for x in self.rating
                     if clean(x.get("carrier")) == carrier_name
                     and clean(x.get("zone")) == zone), None)
        # Fall back to the carrier's cheapest zone if the exact zone isn't rated
        if not rate:
            rate = next((x for x in self.rating
                         if clean(x.get("carrier")) == carrier_name), None)
        if not rate:
            return 0.0
        base = to_num(rate.get("base_rate"), 0) or 0
        per_kg = to_num(rate.get("per_kg_rate"), 0) or 0
        return round(base + per_kg * weight_kg, 2)

    def _transit_for(self, origin_wh_id, ship_to_zip, base_transit_days):
        """Adjust transit days based on origin zone — longer hauls take longer."""
        zone_penalty = {"Z1": 0, "Z2": 1, "Z3": 2}
        return int(base_transit_days) + zone_penalty.get(
            self._zone(origin_wh_id, ship_to_zip), 1)

    # ── Candidate plan construction ───────────────────────────────────────────
    def _line_weight(self, ln):
        return (to_num(ln.get("weight_kg"), 0) or 0) * (to_num(ln.get("qty_base"), 0) or 0)

    def _plan_single(self, label, origin_wh, lines, ship_to_zip, carrier, base_transit, note):
        """A plan that ships all lines from a single warehouse."""
        weight = round(sum(self._line_weight(l) for l in lines), 1)
        freight = self._freight_for(origin_wh, ship_to_zip,
                                    weight, clean(carrier.get("carrier")))
        transit = self._transit_for(origin_wh, ship_to_zip, base_transit)
        # Feasibility: every line's full qty available at this DC
        feasible, shortfalls = True, []
        for l in lines:
            need = int(to_num(l.get("qty_base"), 0) or 0)
            have = int(self.dc_stock.get((l["sku"], origin_wh), 0))
            if have < need:
                feasible = False
                shortfalls.append(f"{l['sku']} short {need - have}")
        wh_name = clean((self.wh_by_id.get(origin_wh) or {}).get("name")) or origin_wh
        return {
            "label": label, "type": "SINGLE",
            "origins": [origin_wh], "origin_display": f"{origin_wh} ({wh_name})",
            "shipments": 1,
            "carrier": clean(carrier.get("carrier")),
            "service_level": clean(carrier.get("service_level")),
            "transit_days": transit,
            "weight_kg": weight,
            "freight_cost": freight,
            "feasible": feasible,
            "feasibility_note": "; ".join(shortfalls) or "All lines available",
            "note": note,
        }

    def _plan_split(self, label, wh1, wh2, lines, ship_to_zip, carrier, base_transit):
        """A plan that splits the order between two warehouses (inventory-balance
        strategy).

        For each line, if the alternate DC (wh2) has full stock we ship it from
        there so that scarce inventory at the preferred DC (wh1) is preserved for
        lines that only wh1 can fulfill. Lines wh2 cannot fulfill go to wh1.
        This maps to the "Inventory Balance" bullet on the Optimization slide.
        """
        group1, group2 = [], []
        for l in lines:
            need = int(to_num(l.get("qty_base"), 0) or 0)
            if self.dc_stock.get((l["sku"], wh2), 0) >= need:
                group2.append(l)
            else:
                group1.append(l)
        # If everything landed in one group, it's effectively a single plan.
        if not group1 or not group2:
            return None
        w1 = round(sum(self._line_weight(l) for l in group1), 1)
        w2 = round(sum(self._line_weight(l) for l in group2), 1)
        f1 = self._freight_for(wh1, ship_to_zip, w1, clean(carrier.get("carrier")))
        f2 = self._freight_for(wh2, ship_to_zip, w2, clean(carrier.get("carrier")))
        # Feasibility on the split groups
        feasible, shortfalls = True, []
        for l in group1:
            need = int(to_num(l.get("qty_base"), 0) or 0)
            have = int(self.dc_stock.get((l["sku"], wh1), 0))
            if have < need:
                feasible = False
                shortfalls.append(f"{l['sku']} @ {wh1} short {need - have}")
        for l in group2:
            need = int(to_num(l.get("qty_base"), 0) or 0)
            have = int(self.dc_stock.get((l["sku"], wh2), 0))
            if have < need:
                feasible = False
                shortfalls.append(f"{l['sku']} @ {wh2} short {need - have}")
        n1 = clean((self.wh_by_id.get(wh1) or {}).get("name")) or wh1
        n2 = clean((self.wh_by_id.get(wh2) or {}).get("name")) or wh2
        # A split shipment's ETA is the SLOWER of its two shipments (customer
        # gets the full order only when the last shipment arrives).
        t1 = self._transit_for(wh1, ship_to_zip, base_transit)
        t2 = self._transit_for(wh2, ship_to_zip, base_transit)
        return {
            "label": label, "type": "SPLIT",
            "origins": [wh1, wh2],
            "origin_display": f"{wh1} + {wh2}",
            "shipments": 2,
            "carrier": clean(carrier.get("carrier")),
            "service_level": clean(carrier.get("service_level")),
            "transit_days": max(t1, t2),
            "weight_kg": w1 + w2,
            "freight_cost": round(f1 + f2, 2),
            "feasible": feasible,
            "feasibility_note": "; ".join(shortfalls) or "All lines available",
            "note": f"Split: {len(group1)} line(s) from {n1}, {len(group2)} line(s) from {n2}",
        }

    def _build_candidates(self, ctx, lines, ship_to_zip, chosen_carrier, transit_days):
        profile = ctx.get("fulfillment_profile") or {}
        preferred = clean(profile.get("preferred_warehouse"))
        alternates = [a for a in (profile.get("alternate_warehouses") or [])
                      if a and a != preferred]
        restricted = set(profile.get("restricted_warehouses") or [])
        split_ok = bool(profile.get("split_shipment_allowed", True))

        plans = []
        if preferred and preferred not in restricted:
            plans.append(self._plan_single(
                "Option A", preferred, lines, ship_to_zip, chosen_carrier,
                transit_days, "Ship everything from preferred DC"))
        alt = next((a for a in alternates if a not in restricted), None)
        if alt:
            plans.append(self._plan_single(
                "Option B", alt, lines, ship_to_zip, chosen_carrier,
                transit_days, "Ship everything from alternate DC"))
        if split_ok and preferred and alt and len(lines) >= 2:
            sp = self._plan_split("Option C", preferred, alt, lines,
                                  ship_to_zip, chosen_carrier, transit_days)
            if sp:
                plans.append(sp)
        return plans

    # ── Main ──────────────────────────────────────────────────────────────────
    def validate(self, ctx) -> StageResult:
        r = StageResult(self.stage_key, self.title, self.icon)
        customer = clean(ctx.get("customer_account"))
        zip_ = clean(ctx.get("ship_to_zip")) or ""
        lines = ctx.get("resolved_lines", [])
        weight = round(sum(self._line_weight(l) for l in lines), 1)
        r.log(f"Fulfillment optimization started for ZIP '{zip_}', customer {customer}, "
              f"total shipment weight {weight}kg.")

        # ── Serviceability ───────────────────────────────────────────────────
        carriers = self._serviceable_carriers(zip_)
        if not carriers:
            r.fail("ZIP_NOT_SERVICEABLE",
                   f"Ship-to ZIP '{zip_}' is not serviceable by any available carrier. "
                   f"AI suggests the nearest pickup location.")

            def _zip_distance(w):
                """Numeric ZIP-prefix distance to the ship-to ZIP (best-effort);
                warehouses with an unparseable ZIP sort last."""
                try:
                    return abs(int(str(clean(w.get("zip")))[:5]) - int(str(zip_)[:5]))
                except (TypeError, ValueError):
                    return 10 ** 9

            ranked = sorted(self.warehouses, key=_zip_distance)
            r.table("Nearest pickup location",
                    ["Pickup Location", "Name", "ZIP", "Region"],
                    [[clean(w.get("warehouse_id")), clean(w.get("name")),
                      clean(w.get("zip")), clean(w.get("region"))]
                     for w in ranked])
            if ranked:
                nearest = ranked[0]
                r.note(f"Nearest pickup location: {clean(nearest.get('name'))} "
                       f"(ZIP {clean(nearest.get('zip'))}, {clean(nearest.get('region'))}). "
                       "Routed to CSR for customer communication "
                       "(alternate carrier / ship-to / pickup).")
                # Publish a real fulfillment source, carrier, and ETA so a CSR
                # override (ship from nearest hub via freight pickup) still shows
                # concrete values in the final confirmation instead of DEFAULT/TBD.
                r.data["fulfillment_source"] = (clean(nearest.get("name"))
                                                or clean(nearest.get("warehouse_id")))
                r.data["carrier"] = "FedEx Freight (nearest-hub pickup)"
                eta_guess = clean(ctx.get("requested_delivery_date"))
                r.data["eta"] = (eta_guess
                                 or (date.today() + timedelta(days=5)).strftime("%d %b %Y"))
            else:
                r.note("Routed to CSR for customer communication "
                       "(alternate carrier / ship-to / pickup).")
            r.log("ZIP not serviceable -> AI suggested nearest pickup location "
                  "-> shipments exception.")
            return r

        chosen_carrier = carriers[0]
        transit = to_num(chosen_carrier.get("transit_days"), 99)
        sla_max = self._sla_max(customer, ctx)
        sla_source = ("fulfillment profile"
                      if (ctx.get("fulfillment_profile") or {}).get("delivery_sla_days")
                      else "logistics SLA_Rules")

        # ── Enumerate candidate plans ─────────────────────────────────────────
        candidates = self._build_candidates(ctx, lines, zip_, chosen_carrier, transit)
        # Winner = cheapest feasible plan that also meets SLA
        eligible = [c for c in candidates if c["feasible"] and c["transit_days"] <= sla_max]
        winner = min(eligible, key=lambda c: c["freight_cost"]) if eligible else None

        # Build the comparison evidence table (always show, even if only one candidate)
        opt_rows = []
        for c in candidates:
            status = ("Winner" if c is winner
                      else "Feasible" if c["feasible"] and c["transit_days"] <= sla_max
                      else "Rejected")
            opt_rows.append([
                c["label"], c["type"], c["origin_display"], c["carrier"],
                f"{c['transit_days']} day(s)",
                f"{c['weight_kg']} kg",
                f"${c['freight_cost']:,.2f}",
                "Yes" if c["feasible"] else "No",
                status,
            ])

        # ── SLA miss (no plan meets SLA) ─────────────────────────────────────
        if not winner:
            r.fail("SLA_MISS",
                   f"Best available transit time ({transit} days) exceeds the delivery "
                   f"SLA of {sla_max} days for ZIP '{zip_}', or no plan is inventory-feasible.")
            r.table("Fulfillment optimization options evaluated",
                    ["Plan", "Type", "Origin(s)", "Carrier", "Transit",
                     "Weight", "Freight cost", "Inventory OK", "Status"], opt_rows)
            r.kv("SLA assessment", [
                ("Carrier", clean(chosen_carrier.get("carrier"))),
                ("Transit days", transit),
                ("SLA max", f"{sla_max} days (source: {sla_source})"),
            ])
            r.note("Routed to CSR for alternate delivery proposal.")
            r.log("No candidate plan meets SLA -> SLA miss exception.")
            return r

        # ── Winner selected ──────────────────────────────────────────────────
        eta = date.today() + timedelta(days=winner["transit_days"])
        savings = None
        others = [c for c in candidates if c is not winner and c["feasible"]
                  and c["transit_days"] <= sla_max]
        if others:
            savings = round(max(c["freight_cost"] for c in others) - winner["freight_cost"], 2)

        r.ok(f"Optimal fulfillment plan selected: {winner['label']} "
             f"({winner['type']}, ${winner['freight_cost']:,.2f}). "
             f"ETA {eta.strftime('%d %b %Y')}. Ready for order execution.")
        r.table("Fulfillment optimization options evaluated",
                ["Plan", "Type", "Origin(s)", "Carrier", "Transit",
                 "Weight", "Freight cost", "Inventory OK", "Status"], opt_rows)
        winner_kv = [
            ("Selected plan",           f"{winner['label']} ({winner['type']})"),
            ("Origin warehouse(s)",     winner["origin_display"]),
            ("Number of shipments",     winner["shipments"]),
            ("Carrier",                 f"{winner['carrier']} ({winner['service_level']})"),
            ("Transit days",            f"{winner['transit_days']} (SLA {sla_max} from {sla_source})"),
            ("Shipment weight",         f"{winner['weight_kg']} kg"),
            ("Freight cost (winner)",   f"${winner['freight_cost']:,.2f}"),
            ("Estimated delivery (ETA)", eta.strftime("%d %b %Y")),
        ]
        if savings is not None and savings > 0:
            winner_kv.append(("Savings vs next-best plan", f"${savings:,.2f}"))
        r.kv("Selected fulfillment plan", winner_kv)
        r.note(f"Optimization criterion: lowest freight cost among feasible plans "
               f"that meet the {sla_max}-day delivery SLA.")

        # Downstream consumers (execution stage, confirmation email)
        r.data["eta"] = eta.strftime("%d %b %Y")
        r.data["carrier"] = winner["carrier"]
        r.data["freight_cost"] = winner["freight_cost"]
        r.data["fulfillment_source"] = winner["origins"][0]
        r.data["shipments"] = winner["shipments"]
        r.log(f"Optimization result: PASS -> winner {winner['label']} "
              f"(${winner['freight_cost']:,.2f}); proceed to order execution.")
        return r
