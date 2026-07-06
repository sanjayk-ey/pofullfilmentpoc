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
    title = "Pricing and Promo"
    icon = "💲"
    steps = [
        (0.30, "📋", "Loading price list and negotiated contracts..."),
        (0.30, "📅", "Applying date-bound contract pricing..."),
        (0.30, "📊", "Applying volume tiers, promotions, and rebates..."),
        (0.25, "🚚", "Adding location surcharges and freight terms..."),
        (0.25, "💵", "Calculating sales tax for the ship-to state..."),
        (0.25, "🧮", "Checking margin / discount policy..."),
    ]

    def __init__(self):
        s = load_sheets("pricing-master-data.xlsx",
                        ["Price_List", "Contracts", "Volume_Tiers", "Rebates",
                         "Promotions", "Surcharges", "Freight_Terms", "Margin_Policy",
                         "Raw_Material_Index", "Tax_Rates"])
        self.price_list = {clean(r.get("sku")): r for r in s["Price_List"] if clean(r.get("sku"))}
        self.contracts = s["Contracts"]
        self.tiers = s["Volume_Tiers"]
        self.rebates = s["Rebates"]
        self.promos = s["Promotions"]
        self.surcharges = s["Surcharges"]
        self.freight = s["Freight_Terms"]
        self.margin = {clean(r.get("product_family")): r for r in s["Margin_Policy"] if clean(r.get("product_family"))}
        # Tax rates keyed by state / region code (with ALL as the fallback).
        self.tax_rates = {}
        for r in s["Tax_Rates"]:
            code = (clean(r.get("region_code")) or "").upper()
            if code:
                self.tax_rates[code] = {
                    "region_name": clean(r.get("region_name")),
                    "tax_type": clean(r.get("tax_type")) or "SALES_TAX",
                    "tax_pct": to_num(r.get("tax_pct"), 0),
                    "notes": clean(r.get("notes")),
                }

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
        waterfall = []          # price_waterfall_lines (business reference schema)
        subtotal = 0.0
        # First policy breach (if any). We no longer early-return on a breach:
        # the whole order is still priced so the order total, surcharges, freight
        # and tax are always available downstream (e.g. after a CSR override the
        # customer confirmation still shows the correct total). The breach is
        # raised as a PRICING_EXCEPTION at the end.
        breach = None
        for li, ln in enumerate(lines, 1):
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

            # ── Build the price waterfall for this line (cumulative build-up) ──
            order_line_id = f"OL-{li:05d}"
            seq = 0

            def _wf(ctype, label, amount, resulting):
                nonlocal seq
                seq += 1
                waterfall.append({
                    "waterfall_id": f"WF-{li:03d}-{seq:02d}",
                    "order_line_id": order_line_id,
                    "component_sequence": seq,
                    "component_type": ctype,
                    "component_label": label,
                    "amount_or_pct": round(amount, 4),
                    "resulting_unit_price": round(resulting, 4),
                })

            _wf("list", "List price", list_price, list_price)
            if contract:
                _wf("contract", f"Contract price ({contract[2]})", base, base)
            cum = 0.0
            if tier_pct:
                cum += tier_pct
                _wf("volume", f"Volume tier discount ({tier_id})", tier_pct, base * (1 - cum / 100.0))
            if promo_pct:
                cum += promo_pct
                _wf("promo", f"Promotional discount ({promo_id})", promo_pct, base * (1 - cum / 100.0))
            if rebate_pct:
                cum += rebate_pct
                _wf("rebate", "Customer rebate accrual", rebate_pct, base * (1 - cum / 100.0))
            _wf("net", "Net unit price", unit_net, unit_net)

            margin_row = self.margin.get(family) or {}
            max_disc = to_num(margin_row.get("max_discount_pct"), 100)
            min_margin = to_num(margin_row.get("min_margin_pct"), 0)
            if eff_from_list > max_disc and breach is None:
                approver_role = clean(margin_row.get("approver_role")) or "PRICING_APPROVER"
                # Margin impact = the dollar value of the discount granted
                # BEYOND policy on this line (what approving the exception costs).
                excess_pct = round(eff_from_list - max_disc, 2)
                margin_impact = round((excess_pct / 100.0) * list_price * (qty or 0), 2)
                breach = {
                    "sku": sku, "family": family, "list_price": list_price,
                    "base": base, "base_src": base_src, "disc": disc,
                    "tier_pct": tier_pct, "promo_pct": promo_pct, "rebate_pct": rebate_pct,
                    "unit_net": unit_net, "eff_from_list": eff_from_list,
                    "max_disc": max_disc, "min_margin": min_margin,
                    "margin_impact": margin_impact, "approver_role": approver_role,
                }

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

        # Freight / shipping terms
        freight_amt = 0.0; incoterm = "-"; freight_source = "—"
        cust_freight = next((f for f in self.freight if clean(f.get("scope_type")) == "customer"
                             and clean(f.get("scope_id")) == customer), None)
        ft = cust_freight or next((f for f in self.freight if clean(f.get("scope_type")) == "default"), None)
        if ft:
            base_freight = to_num(ft.get("base_freight"), 0) or 0
            min_freight  = to_num(ft.get("min_freight"),  0) or 0
            per_kg       = to_num(ft.get("per_kg_rate"), 0) or 0
            weight_lookup = ctx.get("resolved_lines") or []
            total_weight = sum(to_num(l.get("weight_kg"), 0) or 0
                               for l in weight_lookup) if weight_lookup else 0
            calc = base_freight + (per_kg * total_weight)
            freight_amt = round(max(calc, min_freight), 2)
            incoterm = clean(ft.get("incoterm"))
            freight_source = (f"{clean(ft.get('scope_type'))} "
                              f"{clean(ft.get('scope_id')) or ''}").strip()

        # Sales tax (state-level) — applied to (subtotal + surcharges); freight
        # is typically non-taxable so we exclude it from the tax base.
        region = (ctx.get("region") or "ALL").upper()
        tax_row = self.tax_rates.get(region) or self.tax_rates.get("ALL", {})
        tax_pct = to_num(tax_row.get("tax_pct"), 0) or 0
        tax_base = round(subtotal + surcharge_total, 2)
        tax_amt = round(tax_base * tax_pct / 100.0, 2)
        tax_label = f"{tax_row.get('tax_type') or 'SALES_TAX'} — {tax_row.get('region_name') or region}"

        order_total = round(subtotal + surcharge_total + freight_amt + tax_amt, 2)

        # ── Totals are ALWAYS published to ctx (even on a policy breach) so a CSR
        #    override still yields a correct order total downstream. ──────────────
        r.data["order_total"] = order_total
        r.data["pricing_subtotal"] = round(subtotal, 2)
        r.data["pricing_surcharges"] = round(surcharge_total, 2)
        r.data["pricing_freight"]  = freight_amt
        r.data["pricing_incoterm"] = incoterm
        r.data["pricing_tax_pct"]  = tax_pct
        r.data["pricing_tax_amt"]  = tax_amt
        r.data["pricing_tax_region"] = region
        r.data["price_waterfall_lines"] = waterfall

        def _emit_common_tables():
            r.table("Line pricing breakdown",
                    ["SKU", "List", "Base source", "Base", "Disc% (tier/promo/rebate)", "Net unit", "Qty", "Line total"],
                    breakdown)
            r.table("Price waterfall (per-line build-up)",
                    ["Order line", "Seq", "Component", "Label", "Amount / %", "Resulting unit price"],
                    [[w["order_line_id"], w["component_sequence"], w["component_type"],
                      w["component_label"], f'{w["amount_or_pct"]:g}',
                      f'${w["resulting_unit_price"]:,.4f}'] for w in waterfall])
            if surcharge_rows:
                r.table("Surcharges", ["Type", "Rate", "Amount", "Reason"], surcharge_rows)
            # Explicit tax & shipping breakdown (always shown per business feedback).
            r.table("Tax & shipping (AI-calculated)",
                    ["Charge", "Basis", "Rate / Terms", "Amount"],
                    [
                        ["Freight (shipping)", f"{freight_source or '—'}",
                         f"{incoterm}  ·  base ${to_num(ft.get('base_freight'), 0) if ft else 0:,.2f}"
                         f"  ·  +${to_num(ft.get('per_kg_rate'), 0) if ft else 0:,.2f}/kg",
                         f"${freight_amt:,.2f}"],
                        ["Sales tax", tax_label,
                         f"{tax_pct:g}% on subtotal + surcharges (${tax_base:,.2f})",
                         f"${tax_amt:,.2f}"],
                    ])
            r.kv("Order totals", [
                ("Subtotal", f"${subtotal:,.2f}"),
                ("Surcharges", f"${surcharge_total:,.2f}"),
                ("Freight / shipping", f"${freight_amt:,.2f} ({incoterm})"),
                (f"Sales tax ({tax_pct:g}% — {tax_row.get('region_name') or region})",
                 f"${tax_amt:,.2f}"),
                ("Order total", f"${order_total:,.2f}"),
            ])

        # ── Policy breach -> interactive CSR gate (human-in-the-loop) ────────────
        # Phrased like the decision-layer prompt: "Requested discount exceeds
        # policy. Margin impact = $X. Approve exception?" The CSR chooses
        # Approve / Reject / Escalate on the paused stage card. The full order is
        # already priced so the totals above remain valid after an override.
        if breach is not None:
            b = breach
            r.fail("PRICING_EXCEPTION",
                   f"Requested discount {b['eff_from_list']}% on SKU '{b['sku']}' exceeds the "
                   f"{b['family']} policy limit of {b['max_disc']}%. "
                   f"Margin impact ≈ ${b['margin_impact']:,.0f}. Approve exception?")
            r.kv("Pricing exception — CSR approval required", [
                ("SKU", b["sku"]), ("List price", f"${b['list_price']:,.2f}"),
                ("Base price", f"${b['base']:,.2f} ({b['base_src']})"),
                ("Total discount", f"{b['disc']}% (tier {b['tier_pct']}% + promo {b['promo_pct']}% + rebate {b['rebate_pct']}%)"),
                ("Net unit price", f"${b['unit_net']:,.2f}"),
                ("Effective discount vs list", f"{b['eff_from_list']}%"),
                ("Policy max discount", f"{b['max_disc']}%"),
                ("Policy min margin", f"{b['min_margin']}%"),
                ("Margin impact (excess discount × qty)", f"${b['margin_impact']:,.2f}"),
                ("Order total (if approved)", f"${order_total:,.2f}"),
                ("Escalation target", b["approver_role"]),
            ])
            _emit_common_tables()
            r.data["pricing_margin_impact"] = b["margin_impact"]
            r.data["pricing_approver_role"] = b["approver_role"]
            r.log(f"SKU '{b['sku']}' discount {b['eff_from_list']}%>{b['max_disc']}% -> pricing exception "
                  f"(margin impact ${b['margin_impact']:,.2f}). Paused for CSR approval "
                  f"(Approve exception / Reject / Escalate to {b['approver_role']}). "
                  f"Order total ${order_total:,.2f} preserved for downstream stages.")
            return r

        r.ok(f"Final price calculated. Subtotal ${subtotal:,.2f} + surcharges "
             f"${surcharge_total:,.2f} + freight ${freight_amt:,.2f} + tax "
             f"${tax_amt:,.2f} = order total ${order_total:,.2f}. "
             "Ready for budget and approval validation.")
        _emit_common_tables()
        if notes:
            for n in notes:
                r.note(n)
                r.log(n)
        r.log(f"Pricing result: PASS -> subtotal ${subtotal:,.2f}, freight "
              f"${freight_amt:,.2f} ({incoterm}), tax ${tax_amt:,.2f} "
              f"({tax_pct:g}% {region}), order total ${order_total:,.2f}.")
        return r
