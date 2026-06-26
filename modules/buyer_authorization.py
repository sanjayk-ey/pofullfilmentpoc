"""
buyer_authorization.py
Buyer Authorization, Product Visibility, and Ordering Rights.

Validates that the buyer is authorized to purchase the requested products for the
specified branch / cost center, that requested products are visible/orderable at
the buyer's level, and that the cost center is active and within scope.

Master data: buyer-master-data.xlsx (Buyer_Profiles, User_Permissions,
Cost_Centers, Product_Visibility_Rules) + product-master-data.xlsx (sku->family).

Exception types: UNAUTHORIZED_BUYER, RESTRICTED_PRODUCT, INVALID_COST_CENTER.
"""
from modules.stage_result import StageResult
from modules.xlsx_util import load_sheets, clean, yes

ROLE_RANK = {"JUNIOR_BUYER": 1, "BUYER": 2, "SENIOR_BUYER": 3, "ACCOUNT_MANAGER": 4}


def _csv_set(v):
    return {x.strip().upper() for x in str(v or "").split(",") if x.strip()}


class BuyerAuthorizationValidator:
    stage_key = "buyer_authorization"
    title = "Buyer Authorization & Product Visibility"
    icon = "🔐"
    steps = [
        (0.30, "🔐", "Validating buyer profile, role, and status..."),
        (0.30, "🏢", "Confirming branch and cost center assignment..."),
        (0.30, "👁️", "Checking product visibility and ordering rights..."),
        (0.25, "🧾", "Recording authorization decision..."),
    ]

    def __init__(self):
        s = load_sheets("buyer-master-data.xlsx",
                        ["Buyer_Profiles", "User_Permissions", "Cost_Centers",
                         "Product_Visibility_Rules"])
        self.profiles = {clean(r.get("buyer_id")): r for r in s["Buyer_Profiles"] if clean(r.get("buyer_id"))}
        self.perms = {clean(r.get("buyer_id")): r for r in s["User_Permissions"] if clean(r.get("buyer_id"))}
        self.cost_centers = {clean(r.get("cost_center_id")): r for r in s["Cost_Centers"] if clean(r.get("cost_center_id"))}
        self.visibility = s["Product_Visibility_Rules"]
        prod = load_sheets("product-master-data.xlsx", ["Product_Master"])["Product_Master"]
        self.sku_family = {clean(r.get("sku")): clean(r.get("product_family")) for r in prod if clean(r.get("sku"))}

    def validate(self, ctx) -> StageResult:
        r = StageResult(self.stage_key, self.title, self.icon)
        buyer_id = clean(ctx.get("buyer_id"))
        cost_center = clean(ctx.get("cost_center"))
        branch_id = clean(ctx.get("branch_id"))
        skus = [clean(l.get("sku")) for l in ctx.get("order_lines", []) if clean(l.get("sku"))]
        r.log(f"Authorization started for buyer='{buyer_id}', cost_center='{cost_center}', branch='{branch_id}'.")

        # ── Buyer identity & status ─────────────────────────────────────────
        profile = self.profiles.get(buyer_id) if buyer_id else None
        if not profile:
            return r.fail("UNAUTHORIZED_BUYER",
                          f"Buyer '{buyer_id or '(none)'}' was not found in the buyer master. "
                          f"The order cannot be authorized.").log("Buyer lookup: NO MATCH.")
        status = clean(profile.get("status"))
        role = clean(profile.get("role"))
        if status != "ACTIVE":
            return r.fail("UNAUTHORIZED_BUYER",
                          f"Buyer '{buyer_id}' ({clean(profile.get('buyer_name'))}) is "
                          f"{status}. Active buyer status is required.").log(f"Buyer status={status}.")
        if clean(profile.get("customer_account")) != ctx.get("customer_account"):
            return r.fail("UNAUTHORIZED_BUYER",
                          f"Buyer '{buyer_id}' is not registered to customer "
                          f"'{ctx.get('customer_account')}'.").log("Buyer/customer mismatch.")
        r.log(f"Buyer resolved: {clean(profile.get('buyer_name'))} (role {role}).")

        perm = self.perms.get(buyer_id, {})
        permitted_branches = _csv_set(perm.get("permitted_branches"))
        permitted_ccs = _csv_set(perm.get("permitted_cost_centers"))
        denied_families = _csv_set(perm.get("denied_product_families"))

        # ── Cost center validation ──────────────────────────────────────────
        cc = self.cost_centers.get(cost_center) if cost_center else None
        if not cc:
            return r.fail("INVALID_COST_CENTER",
                          f"Cost center '{cost_center or '(none)'}' does not exist.").log("Cost center not found.")
        if clean(cc.get("status")) != "ACTIVE":
            return r.fail("INVALID_COST_CENTER",
                          f"Cost center '{cost_center}' is {clean(cc.get('status'))}.").log("Cost center inactive.")
        if clean(cc.get("branch_id")) != branch_id:
            return r.fail("INVALID_COST_CENTER",
                          f"Cost center '{cost_center}' belongs to branch "
                          f"'{clean(cc.get('branch_id'))}', not the order branch '{branch_id}'.").log("Cost center branch mismatch.")
        if permitted_ccs and cost_center.upper() not in permitted_ccs:
            return r.fail("INVALID_COST_CENTER",
                          f"Buyer '{buyer_id}' is not permitted to order against cost center "
                          f"'{cost_center}'.").log("Cost center outside buyer scope.")
        if permitted_branches and branch_id and branch_id.upper() not in permitted_branches:
            return r.fail("UNAUTHORIZED_BUYER",
                          f"Buyer '{buyer_id}' is not permitted to order for branch '{branch_id}'.").log("Branch outside buyer scope.")
        r.log(f"Cost center {cost_center} active and in scope (branch {branch_id}).")

        # ── Product visibility / ordering rights ────────────────────────────
        restricted = []
        for sku in skus:
            family = (self.sku_family.get(sku) or "").upper()
            if family and family in denied_families:
                restricted.append((sku, family, f"Denied for buyer role {role}", "buyer permission"))
                continue
            for rule in self.visibility:
                rfam = clean(rule.get("product_family"))
                rsku = clean(rule.get("sku"))
                scope_id = clean(rule.get("scope_id"))
                vis = clean(rule.get("visibility"))
                min_role = clean(rule.get("min_role"))
                applies = ((rsku and rsku == sku) or
                           (rfam and rfam.upper() == family and not rsku))
                if not applies:
                    continue
                if vis == "HIDDEN" and clean(rule.get("scope_type")) == "cost_center" and scope_id == cost_center:
                    restricted.append((sku, family, f"Hidden for cost center {cost_center}", clean(rule.get("scope_type"))))
                elif vis == "RESTRICTED" and ROLE_RANK.get(role, 0) < ROLE_RANK.get(min_role, 99):
                    restricted.append((sku, family, f"Requires role {min_role}+ (buyer is {role})", clean(rule.get("scope_type"))))

        if restricted:
            r.fail("RESTRICTED_PRODUCT",
                   f"{len(restricted)} requested product(s) are not orderable for this buyer.")
            r.table("Restricted products", ["SKU", "Family", "Reason", "Rule level"],
                    [list(x) for x in restricted])
            r.log(f"Restricted products: {[x[0] for x in restricted]}.")
            return r

        # ── PASS ────────────────────────────────────────────────────────────
        r.ok(f"Buyer authorized. {len(skus)} product(s) visible and orderable. "
             f"Ready for product validation.")
        r.kv("Buyer authorization", [
            ("Buyer", f"{clean(profile.get('buyer_name'))} ({buyer_id})"),
            ("Role", role),
            ("Branch", branch_id),
            ("Cost center", f"{cost_center} — {clean(cc.get('name'))}"),
            ("Self-approval limit", f"${profile.get('max_order_value'):,} {clean(profile.get('currency')) or ''}"
                if profile.get("max_order_value") else "—"),
        ])
        r.data["buyer_max_order_value"] = profile.get("max_order_value")
        r.data["buyer_can_self_approve"] = yes(profile.get("can_self_approve"))
        r.log("Authorization result: PASS -> proceed to product validation.")
        return r
