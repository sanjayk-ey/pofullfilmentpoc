"""
intake_resolver.py
Intake-time resolution and issue detection (US-01 / US-02 / US-04).

After extraction, the AI agent resolves the "soft" parts of a purchase order
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

    def __init__(self):
        p = load_sheets("product-master-data.xlsx",
                        ["Product_Master", "Substitution_Rules", "UOM_Conversions"])
        self.products = {clean(r.get("sku")): r
                         for r in p["Product_Master"] if clean(r.get("sku"))}
        self.subs = {clean(r.get("original_sku")): r
                     for r in p["Substitution_Rules"] if clean(r.get("original_sku"))}
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
        """Rank ACTIVE catalog products by similarity to a free-text description."""
        scored = []
        for sku, prod in self.products.items():
            if clean(prod.get("status")) != "ACTIVE":
                continue
            score = _similarity(description, prod.get("description"))
            if score >= self.SUGGEST_MIN:
                scored.append({
                    "sku": sku,
                    "description": clean(prod.get("description")),
                    "family": clean(prod.get("product_family")),
                    "score": round(score, 3),
                })
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:5]

    def _substitution_issue(self, ln, sku, status, product) -> IntakeIssue:
        sub = self.subs.get(sku, {})
        sub_sku = clean(sub.get("substitute_sku")) or clean(product.get("substitute_sku"))
        sub_prod = self.products.get(sub_sku, {})
        rec = {
            "original_sku": sku,
            "substitute_sku": sub_sku,
            "substitute_description": clean(sub_prod.get("description")),
            "compatibility": clean(sub.get("compatibility")) or "FUNCTIONAL",
            "price_impact_pct": sub.get("price_impact_pct") if sub else None,
            "availability_impact": clean(sub.get("availability_impact")) or "IN_STOCK",
            "rationale": clean(sub.get("rationale")) or "Approved successor product.",
        }
        return IntakeIssue(
            kind="SUBSTITUTE_SKU",
            title=f"Line {ln.line_number}: SKU {sku} is {status}",
            detail=(f"SKU '{sku}' is {status}. The AI agent identified an approved "
                    f"substitute and needs CSR approval before replacing it. The "
                    f"CSR can also type a different SKU to use instead."),
            line_number=ln.line_number,
            original=sku,
            suggestions=[rec] if sub_sku else [],
            recommended=rec if sub_sku else None,
            # Obsolete-product substitution: CSR can Approve, Modify (type a
            # different SKU), or Escalate. No "reject" — per the Product Match
            # decision layer the substitution is Approve / Modify / Escalate.
            actions=["approve", "enter", "escalate"],
            rationale=rec["rationale"],
        )

    def _uom_conversion_issue(self, ln, product) -> Optional[IntakeIssue]:
        """AC-02 — the PO line specifies its quantity in a NON-STANDARD unit of
        measure (not the product's base UOM). Convert it to the base UOM using an
        approved conversion rule and surface the conversion for CSR confirmation
        before pricing: original qty/UOM, converted qty, converted UOM, and the
        conversion logic are all shown."""
        uom = (clean(ln.uom) or "").upper()
        if not uom:
            return None
        base_uom = (clean(product.get("base_uom")) or "").upper()
        if not base_uom or uom == base_uom:
            return None                            # already in base UOM
        qty = to_num(ln.quantity)
        if not qty or qty <= 0:
            return None
        family = (clean(product.get("product_family")) or "").upper()
        # Find an approved conversion rule from the PO's UOM to the base UOM,
        # preferring a family-specific rule over a universal ("ALL") one.
        rule = None
        for r in (self.uom_rules_by_family.get(family, [])
                  + self.uom_rules_by_family.get("ALL", [])):
            if r["from_uom"] == uom and r["to_uom"] == base_uom:
                rule = r
                break
        if not rule:
            return None      # unknown/unsupported UOM — left for downstream checks
        factor = rule["factor"]
        converted = round(qty * factor, 4)

        def _disp(n):
            return int(n) if float(n) == int(n) else round(n, 2)

        qty_d, conv_d, fac_d = _disp(qty), _disp(converted), _disp(factor)
        logic = f"{qty_d} {uom} × {fac_d} {base_uom}/{uom} = {conv_d} {base_uom}"
        choice = {
            "kind": "convert",
            "original_qty": qty_d, "original_uom": uom,
            "qty_base": converted, "uom": base_uom,
            "factor": fac_d, "rule": rule.get("notes") or "",
            "logic": logic,
            "label": f"Convert {qty_d} {uom} → {conv_d} {base_uom}",
        }
        return IntakeIssue(
            kind="UOM_CONVERSION",
            title=(f"Line {ln.line_number}: quantity in a non-standard UOM "
                   f"({qty_d} {uom}) needs conversion"),
            detail=(f"The PO gave this line's quantity as **{qty_d} {uom}**, which is "
                    f"not the product's base unit of measure (**{base_uom}**). The AI "
                    f"agent converted it with an approved conversion rule and needs "
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
                    "The AI agent needs CSR confirmation before continuing."),
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
                  else f"quantity is {qty_raw}")
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
        #    description against master data (label-independent).
        candidates = self._match_by_description(desc) if desc else []

        if len(candidates) == 1 and candidates[0]["score"] >= self.AUTO_MATCH:
            top = candidates[0]
            return IntakeIssue(
                kind="UNRESOLVED_SKU" if sku else "MISSING_SKU",
                title=(f"Line {ln.line_number}: "
                       + (f"SKU '{sku}' not found in catalog"
                          if sku else "SKU missing (description + qty only)")),
                detail=("The AI agent identified the product from its description "
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
                detail=("The AI agent found several possible catalog products. "
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

        # 2) Fuzzy match on name / address against the customer's ship-tos
        query = " ".join([x for x in (name, addr) if x])
        scored = []
        for s in pool:
            hay = " ".join([clean(s.get("name")) or "", clean(s.get("address")) or "",
                            clean(s.get("city")) or "", clean(s.get("state")) or ""])
            score = max(_similarity(query, hay),
                        _similarity(name, s.get("name")) if name else 0.0)
            if score >= self.SUGGEST_MIN:
                scored.append({
                    "ship_to_id": clean(s.get("ship_to_id")),
                    "name": clean(s.get("name")),
                    "address": clean(s.get("address")),
                    "zip": clean(s.get("zip")),
                    "score": round(score, 3),
                })
        scored.sort(key=lambda x: x["score"], reverse=True)

        # Strong single match -> recommend, CSR confirms
        if len(scored) >= 1 and scored[0]["score"] >= self.AUTO_MATCH and (
                len(scored) == 1 or scored[0]["score"] - scored[1]["score"] >= 0.15):
            top = scored[0]
            # If a valid ZIP was already given and matches, no issue
            if zip_ and top["zip"] == zip_:
                return None
            return IntakeIssue(
                kind="PARTIAL_SHIP_TO",
                title="Ship-to needs confirmation",
                detail=("Only a partial ship-to was provided. The AI agent matched it "
                        "to a registered location and needs CSR confirmation."),
                original=query or zip_ or "",
                suggestions=scored[:5],
                recommended=top,
                actions=["approve", "reject", "escalate", "enter"],
                rationale=(f"Best ship-to match {top['name']} (ZIP {top['zip']}) "
                           f"at {int(top['score']*100)}% confidence."),
            )

        if scored:
            return IntakeIssue(
                kind="PARTIAL_SHIP_TO",
                title="Ship-to is ambiguous",
                detail=("The AI agent found several possible ship-to locations. "
                        "CSR to pick the correct one, type a corrected address, or escalate."),
                original=query or zip_ or "",
                suggestions=scored[:5],
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
                    "in the Buyer Profiles master. The AI listed the buyers "
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
        # Buyer first — downstream authorization depends on it.
        buyer_issue = self._resolve_buyer(po)
        if buyer_issue:
            issues.append(buyer_issue)
        for ln in po.order_lines:
            issue = self._resolve_line(ln)
            if issue:
                issues.append(issue)
        st_issue = self._resolve_ship_to(po)
        if st_issue:
            issues.append(st_issue)
        return issues
