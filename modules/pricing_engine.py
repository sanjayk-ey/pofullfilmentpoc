"""
pricing_engine.py
Enterprise B2B Pricing Engine Validation.

Calculates the final price per order line using a multi-layer rule stack:
base list price -> date-bound contract price -> volume-tier discount ->
promotions -> rebates -> location surcharge -> freight terms, and raises a
pricing exception when the effective discount breaches margin/discount policy.

Master data: pricing-master-data.xlsx (Price_List, Contracts, Volume_Tiers,
Rebates, Promotions, Surcharges, Freight_Terms, Margin_Policy, Raw_Material_Index).

Exception types: PRICING_EXCEPTION, MISSING_PRICING_RULE.
"""
from datetime import date
from dateutil import parser as dateparser

from modules.stage_result import StageResult
from modules.xlsx_util import load_sheets, clean, to_num


def _as_date(v, default=None):
    if v is None or str(v).strip() == "":
        return default
    try:
        return dateparser.parse(str(v)).date()
    except Exception:
        return default


class PricingEngine:
    stage_key = "pricing"
    title = "Enterprise B2B Pricing Engine"
    icon = "💲"
    steps = [
        (0.30, "📋", "Loading price list and negotiated contracts..."),
        (0.30, "📅", "Applying date-bound contract pricing..."),
        (0.30, "📊", "Applying volume tiers, promotions, and rebates..."),
        (0.25, "🚚", "Adding location surcharges and freight terms..."),
        (0.25, "🧮", "Checking margin / discount policy..."),
    ]

    def __init__(self):
        s = load_sheets("pricing-master-data.xlsx",
                        ["Price_List", "Contracts", "Volume_Tiers", "Rebates",
                         "Promotions", "Surcharges", "Freight_Terms", "Margin_Policy",
                         "Raw_Material_Index"])
        self.price_list = {clean(r.get("sku")): r for r in s["Price_List"] if clean(r.get("sku"))}
        self.contracts = s["Contracts"]
        self.tiers = s["Volume_Tiers"]
        self.rebates = s["Rebates"]
        self.promos = s["Promotions"]
        self.surcharges = s["Surcharges"]
        self.freight = s["Freight_Terms"]
        self.margin = {clean(r.get("product_family")): r for r in s["Margin_Policy"] if clean(r.get("product_family"))}

    def _contract_price(self, customer, sku, family, on_date, notes):
        best = None  # (specificity, price, reference)
        for c in self.contracts:
            if clean(c.get("customer_account")) != customer:
                continue
            scope_type = clean(c.get("scope_type")); scope_id = clean(c.get("scope_id"))
            matches_sku = scope_type == "sku" and scope_id == sku
            matches_fam = scope_type == "family" and scope_id == family
            if not (matches_sku or matches_fam):
                continue
            vf = _as_date(c.get("valid_from")); vt = _as_date(c.get("valid_to"))
            active = (clean(c.get("status")) == "ACTIVE" and (not vf or vf <= on_date) and (not vt or on_date <= vt))
            if not active:
                notes.append(f"Contract {clean(c.get('contract_reference'))} for "
                             f"{scope_id} not active on {on_date} - falling back to next rule.")
                continue
            spec = 2 if matches_sku else 1
            price = to_num(c.get("contract_price"))
            if best is None or spec > best[0]:
                best = (spec, price, clean(c.get("contract_reference")))
        return best

    def _tier_discount(self, family, sku, qty):
        for t in self.tiers:
            st = clean(t.get("scope_type")); sid = clean(t.get("scope_id"))
            if (st == "family" and sid == family) or (st == "sku" and sid == sku):
                lo = to_num(t.get("min_qty"), 0); hi = to_num(t.get("max_qty"), 1e18)
                if lo <= (qty or 0) <= hi:
                    d = to_num(t.get("discount_pct"), 0)
                    if d:
                        return d, clean(t.get("tier_id"))
        return 0, None

    def _promo_discount(self, family, sku, on_date):
        for p in self.promos:
            st = clean(p.get("scope_type")); sid = clean(p.get("scope_id"))
            if (st == "family" and sid == family) or (st == "sku" and sid == sku):
                vf = _as_date(p.get("valid_from")); vt = _as_date(p.get("valid_to"))
                if (not vf or vf <= on_date) and (not vt or on_date <= vt):
                    return to_num(p.get("discount_pct"), 0), clean(p.get("promo_id"))
        return 0, None

    def _rebate_pct(self, customer, family):
        total = 0
        for rb in self.rebates:
            if clean(rb.get("customer_account")) != customer:
                continue
            fam = clean(rb.get("product_family"))
            if fam in (family, "ALL"):
                total += to_num(rb.get("rebate_pct"), 0)
        return total

    def validate(self, ctx) -> StageResult:
        r = StageResult(self.stage_key, self.title, self.icon)
        customer = ctx.get("customer_account")
        zip_ = clean(ctx.get("ship_to_zip"))
        on_date = _as_date(ctx.get("requested_delivery_date"), date.today())
        lines = ctx.get("resolved_lines", [])
        notes = []
        r.log(f"Pricing started for {len(lines)} line(s), price date {on_date}.")

        breakdown = []
        subtotal = 0.0
        for ln in lines:
            sku = ln["sku"]; family = ln.get("family"); qty = ln.get("qty_base") or 0
            list_price = to_num(ln.get("list_price")) or to_num((self.price_list.get(sku) or {}).get("list_price"))
            if list_price is None:
                r.fail("MISSING_PRICING_RULE", f"No price list entry found for SKU '{sku}'.")
                r.log(f"SKU '{sku}': missing price -> pricing exception.")
                return r

            contract = self._contract_price(customer, sku, family, on_date, notes)
            base = contract[1] if contract else list_price
            base_src = f"contract {contract[2]}" if contract else "list price"

            tier_pct, tier_id = self._tier_discount(family, sku, qty)
            promo_pct, promo_id = self._promo_discount(family, sku, on_date)
            rebate_pct = self._rebate_pct(customer, family)
            disc = tier_pct + promo_pct + rebate_pct
            unit_net = round(base * (1 - disc / 100.0), 4)
            eff_from_list = round((list_price - unit_net) / list_price * 100, 1) if list_price else 0
            line_total = round(unit_net * (qty or 0), 2)
            subtotal += line_total

            max_disc = to_num((self.margin.get(family) or {}).get("max_discount_pct"), 100)
            if eff_from_list > max_disc:
                r.fail("PRICING_EXCEPTION",
                       f"Effective discount {eff_from_list}% on SKU '{sku}' exceeds the "
                       f"{family} policy limit of {max_disc}%.")
                r.kv("Pricing breach", [
                    ("SKU", sku), ("List price", f"${list_price:,.2f}"),
                    ("Base price", f"${base:,.2f} ({base_src})"),
                    ("Total discount", f"{disc}% (tier {tier_pct}% + promo {promo_pct}% + rebate {rebate_pct}%)"),
                    ("Net unit price", f"${unit_net:,.2f}"),
                    ("Effective discount vs list", f"{eff_from_list}%"),
                    ("Policy max discount", f"{max_disc}%"),
                    ("Recommended action", f"Route to {clean((self.margin.get(family) or {}).get('approver_role')) or 'pricing approver'}"),
                ])
                r.log(f"SKU '{sku}' discount {eff_from_list}%>{max_disc}% -> pricing exception.")
                return r

            breakdown.append([sku, f"${list_price:,.2f}", base_src, f"${base:,.2f}",
                              f"{tier_pct}/{promo_pct}/{rebate_pct}", f"${unit_net:,.2f}",
                              f"{qty:g}", f"${line_total:,.2f}"])

        # Order-level surcharges
        surcharge_total = 0.0
        surcharge_rows = []
        for sc in self.surcharges:
            st = clean(sc.get("scope_type")); sid = clean(sc.get("scope_id"))
            applies = (st == "ALL") or (st == "zip" and sid == zip_)
            if not applies:
                continue
            amt_type = clean(sc.get("amount_type")); amt = to_num(sc.get("amount"), 0)
            val = round(subtotal * amt / 100.0, 2) if amt_type == "PCT" else amt
            surcharge_total += val
            surcharge_rows.append([clean(sc.get("surcharge_type")),
                                   f"{amt}%" if amt_type == "PCT" else f"${amt:,.2f}",
                                   f"${val:,.2f}", clean(sc.get("reason"))])

        # Freight terms
        freight_amt = 0.0; incoterm = "-"
        cust_freight = next((f for f in self.freight if clean(f.get("scope_type")) == "customer"
                             and clean(f.get("scope_id")) == customer), None)
        ft = cust_freight or next((f for f in self.freight if clean(f.get("scope_type")) == "default"), None)
        if ft:
            freight_amt = to_num(ft.get("base_freight"), 0) or 0
            incoterm = clean(ft.get("incoterm"))

        order_total = round(subtotal + surcharge_total + freight_amt, 2)

        r.ok(f"Final price calculated. Order total ${order_total:,.2f}. Ready for budget and approval validation.")
        r.table("Line pricing breakdown",
                ["SKU", "List", "Base source", "Base", "Disc% (tier/promo/rebate)", "Net unit", "Qty", "Line total"],
                breakdown)
        if surcharge_rows:
            r.table("Surcharges", ["Type", "Rate", "Amount", "Reason"], surcharge_rows)
        r.kv("Order totals", [
            ("Subtotal", f"${subtotal:,.2f}"),
            ("Surcharges", f"${surcharge_total:,.2f}"),
            ("Freight", f"${freight_amt:,.2f} ({incoterm})"),
            ("Order total", f"${order_total:,.2f}"),
        ])
        if notes:
            for n in notes:
                r.note(n)
                r.log(n)
        r.data["order_total"] = order_total
        r.data["pricing_subtotal"] = round(subtotal, 2)
        r.log(f"Pricing result: PASS -> order total ${order_total:,.2f}.")
        return r
