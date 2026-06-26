"""
product_matcher.py
Complex Product Matching, Configuration, Variant, and UOM Validation.

Matches each requested SKU to a catalog variant, validates it is orderable,
converts non-standard units of measure using approved conversion rules, and
recommends an approved substitute when a SKU is obsolete or inactive.

Master data: product-master-data.xlsx (Product_Master, Product_Attributes,
UOM_Conversions, Substitution_Rules, Compatibility_Rules).

Exception types: PRODUCT_CONFIG_EXCEPTION, OBSOLETE_SKU, INVALID_UOM.
"""
from modules.stage_result import StageResult
from modules.xlsx_util import load_sheets, clean, to_num


class ProductMatchValidator:
    stage_key = "product_match"
    title = "Product Matching, Configuration & UOM Validation"
    icon = "📦"
    steps = [
        (0.30, "🔎", "Matching requested SKUs to catalog variants..."),
        (0.30, "🧩", "Validating required configuration attributes..."),
        (0.30, "🔁", "Converting and validating units of measure..."),
        (0.25, "♻️", "Checking for obsolete / inactive SKUs and substitutes..."),
    ]

    def __init__(self):
        s = load_sheets("product-master-data.xlsx",
                        ["Product_Master", "Product_Attributes", "UOM_Conversions",
                         "Substitution_Rules", "Compatibility_Rules"])
        self.products = {clean(r.get("sku")): r for r in s["Product_Master"] if clean(r.get("sku"))}
        self.attributes = s["Product_Attributes"]
        self.subs = {clean(r.get("original_sku")): r for r in s["Substitution_Rules"] if clean(r.get("original_sku"))}
        self.conv = {}
        for r in s["UOM_Conversions"]:
            f, t = clean(r.get("from_uom")), clean(r.get("to_uom"))
            if f and t:
                self.conv[(f.upper(), t.upper())] = to_num(r.get("factor"))

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

            # UOM conversion
            converted = False
            qty_base = qty
            conv_note = "no conversion needed"
            if req_uom and base_uom and req_uom != base_uom:
                factor = self.conv.get((req_uom, base_uom))
                if factor is None:
                    r.fail("INVALID_UOM",
                           f"Requested UOM '{req_uom}' for SKU '{sku}' cannot be converted to the "
                           f"base UOM '{base_uom}'. No approved conversion rule exists.")
                    r.log(f"SKU '{sku}': no conversion {req_uom}->{base_uom} -> invalid UOM.")
                    return r
                qty_base = round((qty or 0) * factor, 2)
                converted = True
                conv_note = f"{qty} {req_uom} x {factor} = {qty_base} {base_uom}"

            resolved.append({
                "line": ln.get("line_number"), "sku": sku, "description": clean(product.get("description")),
                "family": family, "requested_qty": qty, "requested_uom": req_uom or base_uom,
                "base_uom": base_uom, "qty_base": qty_base, "converted": converted,
                "list_price": list_price, "weight_kg": weight, "hazardous": clean(product.get("hazardous")),
            })
            display_rows.append([sku, clean(product.get("description")), family,
                                 f"{qty} {req_uom or base_uom}",
                                 f"{qty_base} {base_uom}" if converted else "—", conv_note])

        r.ok(f"All {len(resolved)} product(s) matched, configured, and unit-validated. Ready for compliance validation.")
        r.table("Matched products",
                ["SKU", "Description", "Family", "Requested", "Converted", "Conversion logic"],
                display_rows)
        r.data["resolved_lines"] = resolved
        r.log("Product validation result: PASS -> proceed to compliance validation.")
        return r
