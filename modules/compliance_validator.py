"""
compliance_validator.py
Regional Compliance, Product Eligibility, and SDS Validation.

Validates that each product is eligible for sale/shipment to the ship-to region,
attaches required SDS / compliance documentation, and blocks restricted
product-region combinations.

Master data: compliance-master-data.xlsx (Compliance_Rules, Regional_Restrictions,
SDS_Repository, Product_Eligibility).

Exception types: COMPLIANCE_RESTRICTION, MISSING_SDS.
"""
from modules.stage_result import StageResult
from modules.xlsx_util import load_sheets, clean, yes


class ComplianceValidator:
    stage_key = "compliance"
    title = "Regional Compliance & SDS Validation"
    icon = "🛡️"
    steps = [
        (0.30, "🌍", "Validating regional product eligibility..."),
        (0.30, "📑", "Checking compliance restrictions for ship-to region..."),
        (0.30, "🧪", "Identifying and attaching required SDS documents..."),
        (0.25, "🧾", "Logging compliance validation result..."),
    ]

    def __init__(self):
        s = load_sheets("compliance-master-data.xlsx",
                        ["Compliance_Rules", "Regional_Restrictions",
                         "SDS_Repository", "Product_Eligibility"])
        self.rules = s["Compliance_Rules"]
        self.regional = {clean(r.get("region_code")): r for r in s["Regional_Restrictions"] if clean(r.get("region_code"))}
        self.sds = {clean(r.get("sku")): r for r in s["SDS_Repository"] if clean(r.get("sku"))}
        self.elig = {}
        for r in s["Product_Eligibility"]:
            sku = clean(r.get("sku"))
            if sku:
                self.elig.setdefault(sku, []).append(r)

    def _eligible(self, sku, region):
        rows = self.elig.get(sku, [])
        if not rows:
            return True, None
        for row in rows:
            if (clean(row.get("region")) or "").upper() == region.upper():
                return yes(row.get("eligible")), clean(row.get("conditions"))
        for row in rows:
            if (clean(row.get("region")) or "").upper() == "ALL":
                return yes(row.get("eligible")), clean(row.get("conditions"))
        return True, None

    def validate(self, ctx) -> StageResult:
        r = StageResult(self.stage_key, self.title, self.icon)
        region = clean(ctx.get("region")) or "ALL"
        region_name = clean((self.regional.get(region) or {}).get("region_name")) or region
        lines = ctx.get("resolved_lines", [])
        r.log(f"Compliance validation started for region '{region}' ({region_name}).")

        attachments = []
        elig_rows = []
        for ln in lines:
            sku = ln["sku"]; family = (ln.get("family") or "").upper()
            ok, cond = self._eligible(sku, region)

            # Family-level regional restriction
            restricted_families = {x.strip().upper() for x in
                                   str((self.regional.get(region) or {}).get("restricted_families") or "").split(",") if x.strip()}
            if family in restricted_families:
                ok = False
                cond = cond or f"{family} restricted in {region_name}"

            if not ok:
                r.fail("COMPLIANCE_RESTRICTION",
                       f"SKU '{sku}' is not eligible for shipment to {region_name} ({region}).")
                r.kv("Restricted product", [("SKU", sku), ("Family", family),
                                            ("Ship-to region", f"{region_name} ({region})"),
                                            ("Reason", cond or "Regional restriction")])
                r.note("Order line blocked from fulfillment. Routed to compliance approver.")
                r.data["approval_email_sent_to"] = "Compliance Approver"
                r.data["approval_email_role"] = "COMPLIANCE_APPROVER"
                r.log(f"SKU '{sku}' restricted in {region} -> compliance exception.")
                r.log("Mock email notification triggered to compliance approver. Process halted pending response.")
                return r

            elig_rows.append([sku, family, f"{region_name} ({region})", "Eligible", cond or "None"])

            # SDS requirement for hazardous goods
            if yes(ln.get("hazardous")):
                doc = self.sds.get(sku)
                if not doc:
                    r.fail("MISSING_SDS",
                           f"SKU '{sku}' is hazardous and requires a Safety Data Sheet, "
                           f"but no SDS document is available.")
                    r.data["approval_email_sent_to"] = "Compliance Approver"
                    r.data["approval_email_role"] = "COMPLIANCE_APPROVER"
                    r.log(f"SKU '{sku}' hazardous, SDS missing -> compliance exception.")
                    r.log("Mock email notification triggered to compliance approver. Process halted pending response.")
                    return r
                attachments.append([sku, clean(doc.get("sds_document_id")),
                                    clean(doc.get("sds_version")), clean(doc.get("hazard_class")),
                                    clean(doc.get("expiry_date"))])

        r.ok("All products eligible for the ship-to region. Compliance documentation attached. "
             "Ready for pricing.")
        r.table("Regional eligibility",
                ["SKU", "Family", "Region", "Status", "Conditions"], elig_rows)
        if attachments:
            r.table("Attached SDS / compliance documents",
                    ["SKU", "SDS Document", "Version", "Hazard class", "Expiry"], attachments)
        r.data["compliance_documents"] = attachments
        r.log("Compliance result: PASS -> proceed to pricing.")
        return r
