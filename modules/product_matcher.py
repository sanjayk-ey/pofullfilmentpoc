"""
product_matcher.py
Complex Product Matching, Configuration, Variant, and UOM Validation.

Matches each requested SKU to a catalog variant, validates it is orderable,
converts non-standard units of measure using approved conversion rules,
recommends an approved substitute when a SKU is obsolete or inactive, and
validates STOCK AVAILABILITY: the requested quantity (in base UOM) is checked
against unreserved stock across all distribution centers. If the PO quantity
cannot be met, the order is stopped here and never advances downstream.

Master data: product-master-data.xlsx (Product_Master, Product_Attributes,
UOM_Conversions, Substitution_Rules, Compatibility_Rules) and
inventory-master-data.xlsx (DC_Stock) for availability.

Exception types: PRODUCT_CONFIG_EXCEPTION, OBSOLETE_SKU, INVALID_UOM,
                 OUT_OF_STOCK (requested quantity not available — order stopped).
"""
from modules.stage_result import StageResult
from modules.xlsx_util import clean, to_num
from modules.integrations import PIM, ERP


class ProductMatchValidator:
    stage_key = "product_match"
    title = "Product Match"
    icon = "📦"
    # Mock systems this agent fetches & validates against (PIM = catalog / UOM /
    # substitutes, ERP = warehouse stock availability).
    systems = ("PIM", "ERP")
    steps = [
        (0.30, "🔎", "Matching requested SKUs to catalog variants..."),
        (0.30, "🧩", "Validating required configuration attributes..."),
        (0.30, "🔁", "Converting and validating units of measure..."),
        (0.25, "♻️", "Checking for obsolete / inactive SKUs and substitutes..."),
        (0.25, "📚", "Cross-checking against customer buying history..."),
    ]

    def __init__(self):
        s = PIM.get_product_catalog(
            ["Product_Master", "Product_Attributes", "UOM_Conversions",
             "Substitution_Rules", "Compatibility_Rules"])
        self.products = {clean(r.get("sku")): r for r in s["Product_Master"] if clean(r.get("sku"))}
        self.attributes = s["Product_Attributes"]
        self.subs = {clean(r.get("original_sku")): r for r in s["Substitution_Rules"] if clean(r.get("original_sku"))}

        # Stock availability per SKU across ALL distribution centers, using the
        # UNRESERVED on-hand quantity (on_hand − reserved) that can actually be
        # promised to this order. Availability is validated HERE, during product
        # match: if the requested quantity cannot be met from warehouse stock,
        # the order is stopped and never advances to pricing / credit / approval.
        #   self.dc_available[sku]  -> total unreserved units across all DCs
        #   self.dc_breakdown[sku]  -> [(dc_id, unreserved_qty), ...] for display
        self.dc_available = {}
        self.dc_breakdown = {}
        try:
            inv = ERP.get_inventory(["DC_Stock"])
            for d in inv.get("DC_Stock", []):
                sku = clean(d.get("sku"))
                loc = clean(d.get("location_id"))
                if not sku:
                    continue
                on_hand = to_num(d.get("on_hand_qty"), 0) or 0
                reserved = to_num(d.get("quantity_reserved"), 0) or 0
                avail = max(0, on_hand - reserved)
                self.dc_available[sku] = self.dc_available.get(sku, 0) + avail
                if loc:
                    self.dc_breakdown.setdefault(sku, []).append((loc, avail))
        except Exception:
            # If inventory master is unavailable, skip the availability gate
            # rather than blocking product matching.
            self.dc_available = {}
            self.dc_breakdown = {}
        # UOM conversions keyed by (family, from_uom, to_uom). A family value of
        # "ALL" is the universal fallback (e.g. KG->LB, DOZ->EA). Family-scoped
        # rules always take priority over ALL when they exist.
        self.conv = {}
        for r in s["UOM_Conversions"]:
            f  = clean(r.get("from_uom"))
            t  = clean(r.get("to_uom"))
            fam = (clean(r.get("product_family")) or "ALL").upper()
            if f and t:
                self.conv[(fam, f.upper(), t.upper())] = to_num(r.get("factor"))

    def _lookup_conv(self, family, from_uom, to_uom):
        """Prefer a family-specific rule; fall back to ALL."""
        fam = (family or "").upper()
        return (self.conv.get((fam, from_uom, to_uom))
                or self.conv.get(("ALL", from_uom, to_uom)))

    def _possible_matches(self, description):
        desc = (description or "").upper()
        hits = []
        for sku, p in self.products.items():
            fam = (clean(p.get("product_family")) or "").upper()
            if fam and fam in desc and clean(p.get("status")) == "ACTIVE":
                hits.append((sku, clean(p.get("description"))))
        return hits[:4]

    def validate(self, ctx) -> StageResult:
        r = StageResult(self.stage_key, self.title, self.icon)
        lines = ctx.get("order_lines", [])
        r.log(f"Product validation started for {len(lines)} order line(s).")

        resolved = []
        display_rows = []
        for ln in lines:
            sku = clean(ln.get("sku"))
            qty = to_num(ln.get("quantity"))
            req_uom = (clean(ln.get("uom")) or "").upper()
            product = self.products.get(sku)

            if not product:
                r.fail("PRODUCT_CONFIG_EXCEPTION",
                       f"SKU '{sku}' could not be matched to an orderable catalog variant.")
                pm = self._possible_matches(ln.get("description"))
                if pm:
                    r.table("Possible matches", ["SKU", "Description"], [list(x) for x in pm])
                r.note("Please confirm, modify, or escalate the product match.")
                r.log(f"SKU '{sku}': no catalog match -> product configuration exception.")
                return r

            status = clean(product.get("status"))
            if status in ("OBSOLETE", "INACTIVE"):
                sub = self.subs.get(sku, {})
                r.fail("OBSOLETE_SKU",
                       f"SKU '{sku}' is {status}. An approved substitute is recommended (CSR approval required).")
                r.table("Substitution recommendation",
                        ["Original SKU", "Substitute SKU", "Compatibility", "Price impact %", "Availability", "Rationale"],
                        [[sku, clean(sub.get("substitute_sku")) or clean(product.get("substitute_sku")),
                          clean(sub.get("compatibility")) or "—",
                          sub.get("price_impact_pct") if sub else "—",
                          clean(sub.get("availability_impact")) or "—",
                          clean(sub.get("rationale")) or "—"]])
                r.log(f"SKU '{sku}' {status} -> substitution recommendation.")
                return r

            base_uom = (clean(product.get("base_uom")) or "").upper()
            family = clean(product.get("product_family"))
            list_price = to_num(product.get("list_price"))
            weight = to_num(product.get("weight_kg"), 0) or 0

            # UOM conversion (AC-02). Three cases:
            #  a) PO omits UOM → assume the qty is already in the product's
            #     base UOM (per Product Master). Show that explicitly.
            #  b) PO UOM equals base UOM → no conversion needed.
            #  c) PO UOM differs → apply the approved conversion rule.
            converted = False
            qty_base = qty
            if not req_uom:
                effective_uom = base_uom
                conv_note = f"UOM inferred from Product Master → {base_uom}"
                # Also record inference in the audit trail so it stays visible
                # even when the Matched-products table hides the conversion
                # columns (which it does when no numeric conversion happened).
                r.log(f"SKU '{sku}': PO omitted UOM, "
                      f"inferred from Product Master → {base_uom}.")
            elif req_uom == base_uom:
                effective_uom = req_uom
                conv_note = "no conversion needed"
            else:
                factor = self._lookup_conv(family, req_uom, base_uom)
                if factor is None:
                    r.fail("INVALID_UOM",
                           f"Requested UOM '{req_uom}' for SKU '{sku}' cannot be converted to the "
                           f"base UOM '{base_uom}'. No approved conversion rule exists.")
                    r.log(f"SKU '{sku}': no conversion {req_uom}->{base_uom} -> invalid UOM.")
                    return r
                qty_base = round((qty or 0) * factor, 2)
                converted = True
                effective_uom = req_uom
                conv_note = f"{qty} {req_uom} × {factor} = {qty_base} {base_uom} (approved rule)"

            # ── Stock availability validation (during product match) ────────────
            # Validate the requested quantity (in base UOM) against the UNRESERVED
            # stock available across all distribution centers. If the PO quantity
            # cannot be met from warehouse stock, the order is STOPPED here and
            # never advances to pricing / credit / inventory / approval. (An order
            # that is fully available but only by splitting across warehouses does
            # pass this gate — the split itself is confirmed later in Inventory.)
            need = qty_base or 0
            avail = self.dc_available.get(sku)
            if avail is not None and need > 0 and avail < need:
                loc_txt = (", ".join(f"{loc}: {a:g}" for loc, a in self.dc_breakdown.get(sku, []))
                           or "none")
                zero = avail <= 0
                headline = (f"SKU '{sku}' has no available stock in any warehouse."
                            if zero else
                            f"SKU '{sku}' is short: {avail:g} available vs {need:g} requested "
                            f"across all warehouses.")
                r.fail("OUT_OF_STOCK",
                       f"{headline} The requested quantity cannot be fulfilled, so the order "
                       f"is stopped and will not be processed.")
                r.kv("Stock availability check (all warehouses)", [
                    ("SKU", sku),
                    ("Description", clean(product.get("description"))),
                    ("Requested quantity", f"{need:g} {base_uom}"),
                    ("Available (unreserved, all DCs)", f"{avail:g} {base_uom}"),
                    ("Shortfall", f"{need - avail:g} {base_uom}"),
                    ("Availability by warehouse", loc_txt),
                    ("Decision", "STOP — requested quantity is not available"),
                    ("Recommended action",
                     "Escalate to Procurement / Planning for replenishment, or reject the line"),
                ])
                r.log(f"SKU '{sku}': need {need:g} > available {avail:g} "
                      f"-> OUT_OF_STOCK (order stopped at product match).")
                return r

            resolved.append({
                "line": ln.get("line_number"), "sku": sku, "description": clean(product.get("description")),
                "family": family, "requested_qty": qty, "requested_uom": effective_uom,
                "base_uom": base_uom, "qty_base": qty_base, "converted": converted,
                "list_price": list_price, "weight_kg": weight, "hazardous": clean(product.get("hazardous")),
            })
            # Store the row along with its "converted" flag so we can decide
            # whether to show the Converted / Conversion-logic columns below.
            display_rows.append({
                "converted": converted,
                "cells": [sku, clean(product.get("description")), family,
                          f"{qty} {effective_uom}",
                          f"{qty_base} {base_uom}" if converted else "—",
                          conv_note],
            })

        # ── Buying-history consistency check (Product Match decision layer) ──
        # Confirm the ordered product families are consistent with what this
        # customer normally buys; flag any first-time family purchase for
        # awareness (informational — does not stop the order).
        bh = ctx.get("buying_history") or {}
        freq_families = set(bh.get("frequent_families") or [])
        history_rows = []
        if bh:
            for item in resolved:
                fam = (item.get("family") or "").upper()
                if not fam:
                    continue
                if fam in freq_families:
                    verdict = "Consistent — regularly ordered"
                else:
                    verdict = "First-time family for this customer"
                history_rows.append([item.get("sku"), fam, verdict])
                r.log(f"Buying-history check: SKU '{item.get('sku')}' family {fam} → {verdict}.")
        else:
            r.log("Buying-history check: no prior history on file (new customer).")

        r.ok(f"All {len(resolved)} product(s) matched, configured, and unit-validated. Ready for compliance validation.")

        # Only include the "Converted" and "Conversion logic" columns when
        # at least one line actually required a UOM conversion. Otherwise the
        # matched-products table is a clean SKU / Description / Family /
        # Requested view.
        any_converted = any(row["converted"] for row in display_rows)
        if any_converted:
            headers = ["SKU", "Description", "Family", "Requested",
                       "Converted", "Conversion logic"]
            rows_out = [row["cells"] for row in display_rows]
        else:
            headers = ["SKU", "Description", "Family", "Requested"]
            rows_out = [row["cells"][:4] for row in display_rows]

        r.table("Matched products", headers, rows_out)
        if history_rows:
            r.table("Buying-history check (customer purchase consistency)",
                    ["SKU", "Family", "Verdict"], history_rows)
        r.data["resolved_lines"] = resolved
        r.log("Product validation result: PASS -> proceed to compliance validation.")
        return r
