"""
intake_resolver.py
Intake-time resolution and issue detection (US-01 / US-02 / US-04).

After extraction, the Order assistant resolves the "soft" parts of a purchase order
against master data BEFORE the decision pipeline runs, and surfaces anything it
cannot resolve confidently as an interactive issue for the CSR to
approve / reject / escalate / correct:

  - Label-independent SKU identification: the SKU is identified from master data
    regardless of the column label or code the customer used. A code that
    matches a known SKU is accepted; otherwise the product description is
    matched against the catalog. A missing SKU (description + qty only) is
    resolved the same way.

  - Obsolete / inactive SKU substitution (US-04 AC-04): a recommended substitute
    is proposed with compatibility, price impact and availability impact, and
    requires CSR approval before it replaces the requested SKU.

  - Ship-to resolution (US-02): a partial address or a factory / company name is
    resolved to a registered ship-to location. An ambiguous or unmatched
    ship-to is surfaced for the CSR to pick a suggestion or type a correction.

The resolver never mutates the PO destructively without a confident, unambiguous
match; anything less becomes an IntakeIssue the UI renders with action buttons.
"""
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import List, Optional, Dict, Any

from modules.xlsx_util import load_sheets, clean, to_num


def _norm(s) -> str:
    if not s:
        return ""
    s = str(s).strip().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokens(s) -> set:
    return set(_norm(s).split())


def _fmt_qty(v) -> str:
    """Render a quantity for display, dropping a trailing '.0' on whole numbers
    (e.g. 0.0 -> '0', 2.0 -> '2', 2.5 -> '2.5')."""
    n = to_num(v)
    if n is None:
        return str(v)
    return str(int(n)) if float(n).is_integer() else str(n)


def _similarity(a, b) -> float:
    """Blend of token overlap (Jaccard) and character ratio, with a containment
    bonus — robust for short industrial product descriptions where the PO text
    is often a clean subset of the fuller catalog description."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    ta, tb = set(na.split()), set(nb.split())
    union = ta | tb
    jacc = len(ta & tb) / len(union) if union else 0.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    base = 0.6 * jacc + 0.4 * ratio
    # Containment: if every token of the shorter description appears in the
    # longer one (e.g. "pop-up drain assembly" ⊂ "pop-up drain assembly,
    # brushed nickel"), treat it as a strong match.
    smaller, larger = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if smaller and smaller <= larger:
        containment = len(smaller) / len(larger)
        base = max(base, 0.80 + 0.20 * containment)
    return base


@dataclass
class IntakeIssue:
    kind: str                       # UNRESOLVED_SKU | MISSING_SKU | SUBSTITUTE_SKU |
                                    # UOM_AMBIGUOUS | PARTIAL_SHIP_TO | UNRESOLVED_SHIP_TO |
                                    # UNRESOLVED_BUYER | INVALID_QUANTITY
    title: str
    detail: str
    line_number: Optional[int] = None
    original: str = ""
    suggestions: List[Dict[str, Any]] = field(default_factory=list)
    recommended: Optional[Dict[str, Any]] = None
    actions: List[str] = field(default_factory=list)   # approve|reject|escalate|pick|enter
    rationale: str = ""

    @property
    def issue_id(self) -> str:
        base = f"{self.kind}-{self.line_number if self.line_number is not None else 'H'}"
        return base


class IntakeResolver:
    # Confidence bands for description-based SKU identification
    AUTO_MATCH = 0.82     # single strong match -> AI recommends, CSR just approves
    SUGGEST_MIN = 0.45    # show as a suggestion to pick from
    MAX_SHIPTO_OPTIONS = 10   # cap on ship-to locations offered in the CSR picker

    def __init__(self):
        p = load_sheets("product-master-data.xlsx",
                        ["Product_Master", "Substitution_Rules", "UOM_Conversions",
                         "Product_Attributes"])
        self.products = {clean(r.get("sku")): r
                         for r in p["Product_Master"] if clean(r.get("sku"))}
        # First approved substitute per original SKU (kept for backward compat)…
        self.subs = {clean(r.get("original_sku")): r
                     for r in p["Substitution_Rules"] if clean(r.get("original_sku"))}
        # …plus every approved substitute row per original SKU (there may be
        # several — the CSR should be offered all of them, not just one).
        self.sub_rules_by_orig = {}
        for r in p["Substitution_Rules"]:
            o = clean(r.get("original_sku"))
            if o:
                self.sub_rules_by_orig.setdefault(o, []).append(r)
        # Configuration attributes (finish, control type, …) keyed by SKU, used
        # to explain a suggestion in plain language.
        self.attrs_by_sku = {}
        for r in p.get("Product_Attributes", []):
            s = clean(r.get("sku"))
            nm = clean(r.get("attribute_name"))
            vl = clean(r.get("attribute_value"))
            if s and nm and vl:
                self.attrs_by_sku.setdefault(s, {})[nm] = vl
        # UOM conversions from pack UOM -> base UOM, keyed by (from_uom, family).
        # Used to advertise the pack unit name (e.g. CARTRIDGE family: CASE -> EA
        # x 24) when the PO omits UOM and qty is ambiguous vs the pack size.
        self.uom_rules_by_family = {}
        for r in p["UOM_Conversions"]:
            fam  = (clean(r.get("product_family")) or "").upper()
            frm  = (clean(r.get("from_uom")) or "").upper()
            to   = (clean(r.get("to_uom")) or "").upper()
            fac  = to_num(r.get("factor"))
            note = clean(r.get("notes"))
            if fam and frm and to and fac:
                self.uom_rules_by_family.setdefault(fam, []).append(
                    {"from_uom": frm, "to_uom": to, "factor": fac, "notes": note}
                )

        c = load_sheets("customer-master-data.xlsx", ["Ship_To_Master"])
        self.shiptos = [r for r in c["Ship_To_Master"] if clean(r.get("ship_to_id"))]

        # Buyer directory — used to detect UNRESOLVED_BUYER (the PO's buyer
        # email is not in Buyer_Profiles, or company + email cannot be linked
        # to any registered buyer).
        try:
            b = load_sheets("buyer-master-data.xlsx", ["Buyer_Profiles"])
            self.buyers = [r for r in b["Buyer_Profiles"] if clean(r.get("buyer_id"))]
        except Exception:
            self.buyers = []

    def _pack_uom_for(self, product) -> Optional[Dict[str, Any]]:
        """Return the (pack_uom, base_uom, factor) applicable when a customer
        might have written the qty in packs. Prefers an explicit family rule of
        the form pack_uom -> base_uom (e.g. CASE -> EA x 24 for CARTRIDGE)."""
        base_uom = (clean(product.get("base_uom")) or "").upper()
        family   = (clean(product.get("product_family")) or "").upper()
        pack_sz  = to_num(product.get("pack_size"), 1) or 1
        if not base_uom or pack_sz <= 1:
            return None
        for rule in self.uom_rules_by_family.get(family, []):
            if rule["to_uom"] == base_uom and rule["from_uom"] != base_uom \
                    and rule["factor"] and rule["factor"] > 1:
                return {"pack_uom": rule["from_uom"], "base_uom": base_uom,
                        "factor": rule["factor"], "notes": rule.get("notes") or ""}
        # Fall back to a generic "CASE" label when the family has a pack_size but
        # no explicit rule row.
        return {"pack_uom": "CASE", "base_uom": base_uom, "factor": pack_sz,
                "notes": f"1 case = {int(pack_sz)} {base_uom.lower()}"}

    # ── SKU identification ────────────────────────────────────────────────────
    def _match_by_description(self, description) -> List[Dict[str, Any]]:
        """Rank ACTIVE catalog products by similarity to a free-text description.

        Returns multiple options so the CSR always has alternatives to choose
        from: confident matches (>= SUGGEST_MIN) are preferred, but when only
        one clears the bar the next-best active products are added (up to three
        total) so the pick-list is never a single forced choice."""
        scored = []
        for sku, prod in self.products.items():
            if clean(prod.get("status")) != "ACTIVE":
                continue
            score = _similarity(description, prod.get("description"))
            scored.append({
                "sku": sku,
                "description": clean(prod.get("description")),
                "family": clean(prod.get("product_family")),
                "score": round(score, 3),
            })
        scored.sort(key=lambda x: x["score"], reverse=True)
        strong = [c for c in scored if c["score"] >= self.SUGGEST_MIN]
        if len(strong) >= 2:
            return strong[:5]
        # Top up with the next-best plausible products so multiple options show.
        result = list(strong)
        for c in scored:
            if len(result) >= 3:
                break
            if c not in result and c["score"] > 0.1:
                result.append(c)
        return result[:5]

    # ── Price / attribute helpers (used to enrich CSR suggestions) ────────────
    def _price(self, sku):
        return to_num((self.products.get(sku) or {}).get("list_price"))

    def _currency(self, sku):
        return clean((self.products.get(sku) or {}).get("currency")) or "USD"

    def _attrs(self, sku) -> Dict[str, str]:
        """Human-facing attribute map for a SKU, blending Product_Master fields
        with the Product_Attributes sheet (finish, control type, …)."""
        p = self.products.get(sku) or {}
        a = {
            "family": clean(p.get("product_family")),
            "material": clean(p.get("material")),
            "grade": clean(p.get("grade")),
            "size": clean(p.get("size")),
            "base_uom": clean(p.get("base_uom")),
            "manufacturer": clean(p.get("manufacturer")),
        }
        for k, v in (self.attrs_by_sku.get(sku) or {}).items():
            a.setdefault(k, v)
        return {k: v for k, v in a.items() if v}

    @staticmethod
    def _money(cur, amount):
        return f"{cur} {amount:,.2f}" if amount is not None else "n/a"

    @staticmethod
    def _join(items):
        items = [i for i in items if i]
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        return ", ".join(items[:-1]) + " and " + items[-1]

    # Attribute -> friendly label used when describing a product in words.
    _ATTR_LABELS = [
        ("family", "product family"), ("grade", "configuration"),
        ("control_type", "control type"), ("material", "material"),
        ("size", "size"), ("finish", "finish"), ("base_uom", "unit of measure"),
    ]

    def _price_fields(self, orig_sku, cand_sku) -> Dict[str, Any]:
        """price / original_price / difference block for a candidate SKU."""
        op = self._price(orig_sku) if orig_sku else None
        cp = self._price(cand_sku)
        cur = self._currency(cand_sku) or (self._currency(orig_sku) if orig_sku else "USD")
        out = {"price": cp, "currency": cur}
        if op is not None:
            out["original_price"] = op
            if cp is not None:
                diff = round(cp - op, 2)
                out["price_diff"] = diff
                out["price_diff_pct"] = round(diff / op * 100, 1) if op else None
        return out

    def _substitution_reason(self, orig_sku, cand_sku) -> str:
        """Plain-language explanation of why cand_sku is offered for orig_sku,
        mapping the two products' attributes and comparing their prices."""
        oa, ca = self._attrs(orig_sku), self._attrs(cand_sku)
        od = clean((self.products.get(orig_sku) or {}).get("description")) or orig_sku
        cd = clean((self.products.get(cand_sku) or {}).get("description")) or cand_sku
        shared, diffs = [], []
        for k, lab in self._ATTR_LABELS:
            ov, cv = oa.get(k), ca.get(k)
            if ov and cv:
                if _norm(ov) == _norm(cv):
                    shared.append(f"{lab} ({cv})")
                else:
                    diffs.append(f"{lab} ({ov} → {cv})")
        parts = [f"{cand_sku} ({cd}) is an active replacement for the "
                 f"discontinued {orig_sku} ({od})."]
        if shared:
            parts.append(f"It keeps the same {self._join(shared)}.")
        if diffs:
            parts.append(f"It differs on {self._join(diffs)}.")
        op, cp = self._price(orig_sku), self._price(cand_sku)
        cur = self._currency(cand_sku)
        if op is not None and cp is not None:
            diff = round(cp - op, 2)
            pct = round(diff / op * 100, 1) if op else 0
            if diff == 0:
                parts.append(f"Both list at {self._money(cur, cp)}.")
            else:
                direction = "more" if diff > 0 else "less"
                parts.append(f"It lists at {self._money(cur, cp)} versus "
                             f"{self._money(cur, op)} — about {self._money(cur, abs(diff))} "
                             f"({abs(pct)}%) {direction}.")
        return " ".join(parts)

    def _match_reason(self, cand_sku, from_desc) -> str:
        """Plain-language explanation of a description-matched candidate,
        describing its attributes and price (no confidence score)."""
        ca = self._attrs(cand_sku)
        cd = clean((self.products.get(cand_sku) or {}).get("description")) or cand_sku
        cp = self._price(cand_sku)
        cur = self._currency(cand_sku)
        bits = [f"{lab} {ca[k]}" for k, lab in self._ATTR_LABELS if ca.get(k)]
        parts = []
        if from_desc:
            parts.append(f"Identified from the description “{from_desc}”.")
        parts.append(f"{cand_sku} ({cd})"
                     + (f" is a product with {self._join(bits)}." if bits else "."))
        if cp is not None:
            parts.append(f"It lists at {self._money(cur, cp)}.")
        return " ".join(parts)

    def _enrich_candidate(self, cand, orig_sku=None, from_desc=None, substitute=False):
        """Attach price, attributes and a conversational reason to a candidate
        suggestion dict (mutates and returns it)."""
        sku = cand.get("sku")
        cand.update(self._price_fields(orig_sku, sku))
        cand["attrs"] = self._attrs(sku)
        cand["original_sku"] = orig_sku
        if substitute:
            cand["reason"] = self._substitution_reason(orig_sku, sku)
        else:
            cand["reason"] = self._match_reason(sku, from_desc)
        return cand

    def _substitution_issue(self, ln, sku, status, product) -> IntakeIssue:
        # Build the full list of approved substitutes for this obsolete SKU.
        # The Product_Master successor (substitute_sku) is the primary
        # recommendation; every Substitution_Rules row adds a further option so
        # the CSR can choose between multiple valid replacements.
        primary_sku = clean(product.get("substitute_sku"))
        ordered_subs = []                    # (substitute_sku, rule_row)
        seen = set()
        if primary_sku:
            rule = next((r for r in self.sub_rules_by_orig.get(sku, [])
                         if clean(r.get("substitute_sku")) == primary_sku), {})
            ordered_subs.append((primary_sku, rule)); seen.add(primary_sku)
        for r in self.sub_rules_by_orig.get(sku, []):
            ss = clean(r.get("substitute_sku"))
            if ss and ss not in seen and ss in self.products:
                ordered_subs.append((ss, r)); seen.add(ss)
        # Fallback: other ACTIVE products in the same family, if no rule exists.
        if not ordered_subs:
            fam = (clean(product.get("product_family")) or "").upper()
            for cs, cp in self.products.items():
                if cs != sku and clean(cp.get("status")) == "ACTIVE" \
                        and (clean(cp.get("product_family")) or "").upper() == fam:
                    ordered_subs.append((cs, {})); seen.add(cs)

        options = []
        for ss, rule in ordered_subs:
            sub_prod = self.products.get(ss, {})
            opt = {
                "sku": ss,
                "description": clean(sub_prod.get("description")),
                "family": clean(sub_prod.get("product_family")),
                # keep substitute_* keys so the apply/render paths stay compatible
                "substitute_sku": ss,
                "substitute_description": clean(sub_prod.get("description")),
                "compatibility": clean(rule.get("compatibility")) or "FUNCTIONAL",
                "price_impact_pct": rule.get("price_impact_pct") if rule else None,
                "availability_impact": clean(rule.get("availability_impact")) or "IN_STOCK",
                "rationale": clean(rule.get("rationale")) or "Approved successor product.",
            }
            self._enrich_candidate(opt, orig_sku=sku, substitute=True)
            options.append(opt)

        rec = options[0] if options else None
        return IntakeIssue(
            kind="SUBSTITUTE_SKU",
            title=f"Line {ln.line_number}: SKU {sku} is {status}",
            detail=(f"SKU '{sku}' is {status}. The Order assistant identified "
                    f"{'approved substitutes' if len(options) > 1 else 'an approved substitute'} "
                    f"and needs CSR approval before replacing it. The CSR can pick a "
                    f"replacement below or type a different SKU to use instead."),
            line_number=ln.line_number,
            original=sku,
            suggestions=options,
            recommended=rec,
            # Obsolete-product substitution: CSR can Approve, Modify (type a
            # different SKU), or Escalate. No "reject" — per the Product Match
            # decision layer the substitution is Approve / Modify / Escalate.
            actions=["approve", "enter", "escalate"],
            rationale=(rec.get("rationale") if rec else "Approved successor product."),
        )

    def _uom_conversion_issue(self, ln, product) -> Optional[IntakeIssue]:
        """AC-02 — the PO line specifies its quantity in a NON-STANDARD unit of
        measure (not the product's base UOM).

        When the converted quantity is a whole number the issue is a straight
        confirmation (single option). When it is NOT a whole number (e.g. 52 EA
        ordered but 1 KIT = 10 EA → 5.2 KIT) the CSR is offered two options:
        round DOWN (5 KIT / 50 EA) and round UP (6 KIT / 60 EA), each with
        price impact and a plain-language reason."""
        uom = (clean(ln.uom) or "").upper()
        if not uom:
            return None
        base_uom = (clean(product.get("base_uom")) or "").upper()
        if not base_uom or uom == base_uom:
            return None
        qty = to_num(ln.quantity)
        if not qty or qty <= 0:
            return None
        family = (clean(product.get("product_family")) or "").upper()
        rule = None
        for r in (self.uom_rules_by_family.get(family, [])
                  + self.uom_rules_by_family.get("ALL", [])):
            if r["from_uom"] == uom and r["to_uom"] == base_uom:
                rule = r
                break
        if not rule:
            return None
        factor = rule["factor"]
        converted = round(qty * factor, 4)

        def _disp(n):
            return int(n) if float(n) == int(n) else round(n, 2)

        qty_d = _disp(qty)
        price_per_kit = to_num(product.get("list_price")) or 0
        currency = (clean(product.get("currency")) or "USD").upper()

        # Determine how many base-UOM units are in one pack (inverse of factor).
        ea_per_kit = round(1 / factor) if factor and factor > 0 else 1

        # When conversion yields a non-whole number, offer round-down / round-up.
        if float(converted) != int(converted):
            lo_kits = int(converted)           # round down
            hi_kits = lo_kits + 1              # round up
            lo_ea = lo_kits * ea_per_kit
            hi_ea = hi_kits * ea_per_kit
            lo_total = round(lo_kits * price_per_kit, 2)
            hi_total = round(hi_kits * price_per_kit, 2)
            orig_ea_cost = round(qty * (price_per_kit / ea_per_kit), 2) if ea_per_kit else 0
            lo_diff = round(lo_total - orig_ea_cost, 2)
            hi_diff = round(hi_total - orig_ea_cost, 2)
            lo_ea_short = int(qty) - lo_ea

            option_lo = {
                "kind": "round_down", "kits": lo_kits,
                "ea_equivalent": lo_ea, "total_price": lo_total,
                "price_diff": lo_diff, "currency": currency,
                "original_qty": qty_d, "original_uom": uom,
                "qty_base": lo_kits, "uom": base_uom,
                "factor": _disp(factor),
                "rule": rule.get("notes") or "",
                "logic": f"{lo_kits} {base_uom} × {ea_per_kit} {uom}/{base_uom} = {lo_ea} {uom}",
                "label": f"Order {lo_kits} {base_uom} ({lo_ea} {uom})",
                "reason": (f"Round down to {lo_kits} {base_uom} ({lo_ea} {uom}). "
                           f"This is {lo_ea_short} {uom} less than the {qty_d} {uom} "
                           f"requested on the PO. Total cost: {currency} {lo_total:,.2f}."),
            }
            option_hi = {
                "kind": "round_up", "kits": hi_kits,
                "ea_equivalent": hi_ea, "total_price": hi_total,
                "price_diff": hi_diff, "currency": currency,
                "original_qty": qty_d, "original_uom": uom,
                "qty_base": hi_kits, "uom": base_uom,
                "factor": _disp(factor),
                "rule": rule.get("notes") or "",
                "logic": f"{hi_kits} {base_uom} × {ea_per_kit} {uom}/{base_uom} = {hi_ea} {uom}",
                "label": f"Order {hi_kits} {base_uom} ({hi_ea} {uom})",
                "reason": (f"Round up to {hi_kits} {base_uom} ({hi_ea} {uom}). "
                           f"This is {hi_ea - int(qty)} {uom} more than the {qty_d} "
                           f"{uom} requested on the PO. Total cost: {currency} {hi_total:,.2f}."),
            }
            return IntakeIssue(
                kind="UOM_CONVERSION",
                title=(f"Line {ln.line_number}: {qty_d} {uom} ordered but product "
                       f"sells in {base_uom} (1 {base_uom} = {ea_per_kit} {uom})"),
                detail=(f"The PO requests **{qty_d} {uom}** but this product is sold "
                        f"in **{base_uom}** (1 {base_uom} = {ea_per_kit} {uom}). "
                        f"{qty_d} {uom} does not convert to a whole number of "
                        f"{base_uom} ({_disp(converted)} {base_uom}). "
                        f"CSR to choose the appropriate quantity."),
                line_number=ln.line_number,
                original=f"{qty_d} {uom}",
                suggestions=[option_lo, option_hi],
                recommended=option_hi,
                actions=["pick", "reject", "escalate"],
                rationale=(f"1 {base_uom} = {ea_per_kit} {uom}. "
                           f"{qty_d} ÷ {ea_per_kit} = {_disp(converted)} (not whole)."),
            )

        # Exact conversion — single option, straight confirmation.
        conv_d, fac_d = _disp(converted), _disp(factor)
        logic = f"{qty_d} {uom} × {fac_d} {base_uom}/{uom} = {conv_d} {base_uom}"
        choice = {
            "kind": "convert",
            "original_qty": qty_d, "original_uom": uom,
            "qty_base": conv_d, "uom": base_uom,
            "factor": fac_d, "rule": rule.get("notes") or "",
            "logic": logic,
            "label": f"Convert {qty_d} {uom} → {conv_d} {base_uom}",
        }
        return IntakeIssue(
            kind="UOM_CONVERSION",
            title=(f"Line {ln.line_number}: quantity in a non-standard UOM "
                   f"({qty_d} {uom}) needs conversion"),
            detail=(f"The PO gave this line's quantity as **{qty_d} {uom}**, which is "
                    f"not the product's base unit of measure (**{base_uom}**). The Order "
                    f"assistant converted it with an approved conversion rule and needs "
                    f"CSR confirmation before it proceeds to pricing."),
            line_number=ln.line_number,
            original=f"{qty_d} {uom}",
            suggestions=[choice],
            recommended=choice,
            actions=["approve", "reject", "escalate"],
            rationale=(f"Approved conversion rule: 1 {uom} = {fac_d} {base_uom} "
                       f"({choice['rule'] or 'catalog UOM conversion'}). {logic}."),
        )

    def _uom_ambiguity_issue(self, ln, product) -> Optional[IntakeIssue]:
        """When the PO omits UOM and the qty is small enough to be plausibly
        interpreted as packs instead of individual units, ask the CSR to
        confirm. This is the interactive AC-02 (UOM conversion) demo moment."""
        if clean(ln.uom):
            return None                           # PO gave an explicit UOM
        qty = to_num(ln.quantity)
        if not qty or qty <= 0:
            return None
        pack = self._pack_uom_for(product)
        if not pack:
            return None
        pack_sz = pack["factor"]
        # Ambiguous only when qty is a small integer AND less than one full pack.
        if qty >= pack_sz or qty > 12:
            return None

        base_uom = pack["base_uom"]
        pack_uom = pack["pack_uom"]
        as_base  = {"kind": "base", "uom": base_uom, "qty": qty,
                    "qty_base": qty, "label": f"{int(qty)} {base_uom} (individual pieces)"}
        as_pack  = {"kind": "pack", "uom": pack_uom, "qty": qty,
                    "qty_base": round(qty * pack_sz, 2),
                    "label": (f"{int(qty)} {pack_uom} = {int(qty*pack_sz)} {base_uom} "
                              f"(1 {pack_uom.lower()} = {int(pack_sz)} {base_uom.lower()})")}
        return IntakeIssue(
            kind="UOM_AMBIGUOUS",
            title=(f"Line {ln.line_number}: UOM not specified for "
                   f"{clean(product.get('sku'))} (pack of {int(pack_sz)})"),
            detail=("The PO did not include a unit of measure and the quantity is "
                    f"small enough that it could reasonably be either individual "
                    f"{base_uom.lower()} pieces or full {pack_uom.lower()}s. "
                    "The Order assistant needs CSR confirmation before continuing."),
            line_number=ln.line_number,
            original=f"qty={qty}, uom=<missing>",
            suggestions=[as_base, as_pack],
            recommended=as_base,          # safest default: individual pieces
            actions=["approve", "pick", "reject", "escalate"],
            rationale=(f"Product Master: base UOM {base_uom}, pack size {int(pack_sz)} "
                       f"{base_uom.lower()} per {pack_uom.lower()}. Approved conversion "
                       f"rule: {int(pack_sz)} {base_uom} = 1 {pack_uom} "
                       f"({pack.get('notes') or 'family pack size'})."),
        )

    def _invalid_quantity_issue(self, ln, product=None) -> IntakeIssue:
        """Quantity is missing or zero. Ask CSR to enter the correct qty
        before the pipeline can continue."""
        qty_raw = ln.quantity
        reason = ("no quantity was provided" if qty_raw in (None, "")
                  else f"quantity is {_fmt_qty(qty_raw)}")
        sku_disp = clean(ln.sku) or (clean(ln.description) or "this line")
        detail = (f"Line {ln.line_number} for **{sku_disp}** cannot be processed "
                  f"because {reason}. CSR to enter the correct quantity, reject "
                  "the order, or escalate.")
        rationale = ("Quantity is a mandatory field on every order line; the "
                     "AI cannot infer it from master data.")
        return IntakeIssue(
            kind="INVALID_QUANTITY",
            title=f"Line {ln.line_number}: quantity invalid ({reason})",
            detail=detail,
            line_number=ln.line_number,
            original=str(qty_raw),
            suggestions=[],
            recommended={"line_label": sku_disp, "qty_raw": qty_raw},
            actions=["enter", "reject", "escalate"],
            rationale=rationale,
        )

    def _resolve_line(self, ln) -> Optional[IntakeIssue]:
        sku = clean(ln.sku)
        desc = clean(ln.description)
        qty = to_num(ln.quantity)

        # 0) Quantity must be a positive number. Missing or zero quantity is
        #    an interactive issue — the CSR types the correct qty.
        if ln.quantity in (None, "") or (qty is not None and qty <= 0):
            # Still resolve the SKU / description so the CSR knows which
            # product the qty is for; the returned issue only asks for qty.
            product = self.products.get(sku) if sku else None
            return self._invalid_quantity_issue(ln, product)

        # 1) Code matches a known SKU exactly
        if sku and sku in self.products:
            product = self.products[sku]
            status = (clean(product.get("status")) or "").upper()
            # Fill missing description from master (optional field)
            if not desc:
                ln.description = clean(product.get("description"))
            if status in ("OBSOLETE", "INACTIVE"):
                return self._substitution_issue(ln, sku, status, product)
            # Active SKU: an explicit NON-STANDARD UOM is converted to the base
            # UOM and confirmed by the CSR (the interactive UOM-conversion demo).
            conv_issue = self._uom_conversion_issue(ln, product)
            if conv_issue:
                return conv_issue
            # Otherwise, a MISSING UOM with an ambiguous small qty is confirmed.
            uom_issue = self._uom_ambiguity_issue(ln, product)
            if uom_issue:
                return uom_issue
            return None   # active, resolved

        # 2) Code not a known SKU (wrong label / typo / missing) -> identify by
        #    description against master data (label-independent). Each candidate
        #    is enriched with its price, attributes and a plain-language reason.
        candidates = self._match_by_description(desc) if desc else []
        for cand in candidates:
            self._enrich_candidate(cand, orig_sku=(sku or None), from_desc=desc)

        if len(candidates) == 1 and candidates[0]["score"] >= self.AUTO_MATCH:
            top = candidates[0]
            return IntakeIssue(
                kind="UNRESOLVED_SKU" if sku else "MISSING_SKU",
                title=(f"Line {ln.line_number}: "
                       + (f"SKU '{sku}' not found in catalog"
                          if sku else "SKU missing (description + qty only)")),
                detail=("The Order assistant identified the product from its description "
                        "against the catalog and recommends confirming the SKU."),
                line_number=ln.line_number,
                original=sku or (desc or ""),
                suggestions=candidates,
                recommended=top,
                actions=["approve", "reject", "escalate", "enter"],
                rationale=(f"Best description match {top['sku']} "
                           f"({top['description']}) at {int(top['score']*100)}% confidence."),
            )

        if candidates:
            return IntakeIssue(
                kind="UNRESOLVED_SKU" if sku else "MISSING_SKU",
                title=(f"Line {ln.line_number}: "
                       + (f"SKU '{sku}' not found — multiple possible matches"
                          if sku else "SKU missing — multiple possible matches")),
                detail=("The Order assistant found several possible catalog products. "
                        "CSR to pick the correct SKU, type the correct SKU, or escalate."),
                line_number=ln.line_number,
                original=sku or (desc or ""),
                suggestions=candidates,
                recommended=None,
                actions=["pick", "enter", "escalate"],
                rationale="Multiple candidate products above the match threshold.",
            )

        # 3) Nothing to go on
        return IntakeIssue(
            kind="MISSING_SKU" if not sku else "UNRESOLVED_SKU",
            title=f"Line {ln.line_number}: SKU could not be identified",
            detail=("No catalog match was found from the SKU code or description. "
                    "CSR to enter the correct SKU or escalate."),
            line_number=ln.line_number,
            original=sku or (desc or ""),
            suggestions=[],
            recommended=None,
            actions=["enter", "escalate"],
            rationale="No confident catalog match from code or description.",
        )

    # ── Ship-to resolution ────────────────────────────────────────────────────
    def _shipto_for_account(self, customer_account):
        acct = clean(customer_account)
        rows = [s for s in self.shiptos if clean(s.get("customer_account")) == acct] if acct else []
        return rows or self.shiptos

    def _resolve_ship_to(self, po) -> Optional[IntakeIssue]:
        zip_ = clean(po.ship_to_zip)
        name = clean(po.ship_to_name)
        addr = clean(po.ship_to_address)
        pool = self._shipto_for_account(po.customer_account)

        # 1) Exact ZIP match within the customer's ship-to locations -> resolved
        if zip_:
            exact = [s for s in pool if clean(s.get("zip")) == zip_]
            if exact:
                if not name:
                    po.ship_to_name = clean(exact[0].get("name"))
                return None

        # 2) Fuzzy match on name / address against the customer's ship-tos.
        #    Every registered ship-to for the account is scored and offered to
        #    the CSR (ranked by confidence) so the full set of valid locations
        #    is always selectable — not just those above the suggestion
        #    threshold. SUGGEST_MIN is only used to decide whether the match is
        #    confident enough to skip the CSR gate or to flag it as ambiguous.
        query = " ".join([x for x in (name, addr) if x])
        scored = []
        for s in pool:
            hay = " ".join([clean(s.get("name")) or "", clean(s.get("address")) or "",
                            clean(s.get("city")) or "", clean(s.get("state")) or ""])
            score = max(_similarity(query, hay),
                        _similarity(name, s.get("name")) if name else 0.0)
            scored.append({
                "ship_to_id": clean(s.get("ship_to_id")),
                "name": clean(s.get("name")),
                "address": clean(s.get("address")),
                "zip": clean(s.get("zip")),
                "score": round(score, 3),
            })
        scored.sort(key=lambda x: x["score"], reverse=True)
        # All registered ship-tos for the account, ranked best-match first.
        options = scored[:self.MAX_SHIPTO_OPTIONS]
        above = [x for x in scored if x["score"] >= self.SUGGEST_MIN]

        # Strong single match -> recommend, CSR confirms (all locations still
        # selectable in case the CSR wants a different one).
        if scored and scored[0]["score"] >= self.AUTO_MATCH and (
                len(scored) == 1 or scored[0]["score"] - scored[1]["score"] >= 0.15):
            top = scored[0]
            # If a valid ZIP was already given and matches, no issue
            if zip_ and top["zip"] == zip_:
                return None
            return IntakeIssue(
                kind="PARTIAL_SHIP_TO",
                title="Ship-to needs confirmation",
                detail=("Only a partial ship-to was provided. The Order assistant matched it "
                        "to a registered location and needs CSR confirmation. All "
                        "ship-to locations registered for this customer are listed so "
                        "the CSR can confirm the best match or choose another."),
                original=query or zip_ or "",
                suggestions=options,
                recommended=top,
                actions=["approve", "reject", "escalate", "enter"],
                rationale=(f"Best ship-to match {top['name']} (ZIP {top['zip']}) "
                           f"at {int(top['score']*100)}% confidence."),
            )

        if above:
            return IntakeIssue(
                kind="PARTIAL_SHIP_TO",
                title="Ship-to is ambiguous",
                detail=("The Order assistant could not confidently match the ship-to. All "
                        "ship-to locations registered for this customer are listed "
                        "(ranked by match confidence). CSR to pick the correct one, "
                        "type a corrected address, or escalate."),
                original=query or zip_ or "",
                suggestions=options,
                recommended=None,
                actions=["pick", "enter", "escalate"],
                rationale="Multiple candidate ship-to locations.",
            )

        # If a valid ZIP was given but not in the customer's pool, let the
        # account validator raise the formal exception downstream.
        if zip_:
            return None

        return IntakeIssue(
            kind="UNRESOLVED_SHIP_TO",
            title="Ship-to could not be resolved",
            detail=("The provided ship-to could not be matched to any registered "
                    "location. CSR to type the correct ship-to address or escalate."),
            original=query or "",
            suggestions=[{"ship_to_id": clean(s.get("ship_to_id")),
                          "name": clean(s.get("name")), "address": clean(s.get("address")),
                          "zip": clean(s.get("zip"))} for s in pool[:5]],
            recommended=None,
            actions=["enter", "escalate"],
            rationale="No ship-to match from ZIP, name, or address.",
        )

    # ── Buyer resolution ──────────────────────────────────────────────────────
    def _resolve_buyer(self, po) -> Optional[IntakeIssue]:
        """When the PO's buyer email does not resolve to any Buyer_Profiles
        row, raise UNRESOLVED_BUYER with the buyers registered against the
        same customer account (or all active buyers) as suggestions. The CSR
        can pick the correct buyer or type a corrected buyer name / email.

        No issue is raised when:
          - `_resolve_identity` already resolved the buyer (buyer_id set), or
          - the PO gave no buyer email at all (that's handled as a missing
            mandatory field before the resolver runs)."""
        if getattr(po, "buyer_id", None):
            return None
        if not clean(po.buyer_email):
            return None
        cust = clean(po.customer_account)
        # Prefer buyers on the same customer account; fall back to all active
        # buyers when the customer is not yet known.
        pool = [b for b in self.buyers
                if clean(b.get("customer_account")) == cust
                and (clean(b.get("status")) or "").upper() == "ACTIVE"] if cust else []
        if not pool:
            pool = [b for b in self.buyers
                    if (clean(b.get("status")) or "").upper() == "ACTIVE"]
        suggestions = [{
            "buyer_id": clean(b.get("buyer_id")),
            "buyer_name": clean(b.get("buyer_name")),
            "email": clean(b.get("email")),
            "role": clean(b.get("role")),
            "customer_account": clean(b.get("customer_account")),
            "default_cost_center": clean(b.get("default_cost_center")),
        } for b in pool[:6]]
        return IntakeIssue(
            kind="UNRESOLVED_BUYER",
            title=f"Buyer '{po.buyer_email}' is not in the buyer directory",
            detail=("The PO's buyer email does not match any registered buyer "
                    "in the Buyer Profiles master. The Order agent listed the buyers "
                    "registered against this customer — CSR to pick the correct "
                    "buyer, type the correct buyer name, or escalate before the "
                    "authorization stage runs."),
            original=po.buyer_email or "",
            suggestions=suggestions,
            recommended=None,
            actions=["pick", "enter", "escalate"],
            rationale=("No Buyer_Profiles row was found for the PO's email. "
                       f"Showing {len(suggestions)} candidate buyer(s) from "
                       "master data."),
        )

    # ── Public API ────────────────────────────────────────────────────────────
    def resolve(self, po) -> List[IntakeIssue]:
        """Resolve the PO against master data and return any issues needing CSR
        input. Confident, unambiguous matches are applied in place silently."""
        issues: List[IntakeIssue] = []
        # CSR-approval order: order items first, then buyer, then ship-to.
        # 1) Order items (line-level product / quantity / UOM issues).
        for ln in po.order_lines:
            issue = self._resolve_line(ln)
            if issue:
                issues.append(issue)
        # 2) Buyer resolution / authorization.
        buyer_issue = self._resolve_buyer(po)
        if buyer_issue:
            issues.append(buyer_issue)
        # 3) Ship-to details.
        st_issue = self._resolve_ship_to(po)
        if st_issue:
            issues.append(st_issue)
        return issues
