"""
budget_approval.py
Budget, Spend Limit, and Approval Routing Validation.

Validates the order value against cost-center and branch budgets, determines
whether the buyer can self-approve, and routes to the correct approver using the
account-hierarchy approval matrix when spend thresholds are exceeded.

Master data: budget-master-data.xlsx (Budget_Master, Cost_Centers,
Approval_Matrix, Buyer_Authority).

Exception types: BUDGET_EXCEEDED, APPROVAL_REQUIRED, MISSING_APPROVER.
"""
from modules.stage_result import StageResult
from modules.xlsx_util import load_sheets, clean, to_num, yes


class BudgetApprovalValidator:
    stage_key = "budget_approval"
    title = "Approval"
    icon = "💰"
    steps = [
        (0.30, "💰", "Calculating order value against budgets..."),
        (0.30, "🏦", "Checking cost-center and branch available budget..."),
        (0.30, "🧭", "Evaluating buyer authority and approval matrix..."),
        (0.25, "🧾", "Recording budget / approval decision..."),
    ]

    def __init__(self):
        s = load_sheets("budget-master-data.xlsx",
                        ["Budget_Master", "Cost_Centers", "Approval_Matrix", "Buyer_Authority"])
        self.budget = {(clean(r.get("level_type")), clean(r.get("level_id"))): r for r in s["Budget_Master"]}
        self.cc = {clean(r.get("cost_center_id")): r for r in s["Cost_Centers"] if clean(r.get("cost_center_id"))}
        self.matrix = s["Approval_Matrix"]
        self.authority = {clean(r.get("buyer_id")): r for r in s["Buyer_Authority"] if clean(r.get("buyer_id"))}

    def _find_approver(self, amount, branch_id, regional_id, global_id):
        order = [("branch", branch_id), ("regional_division", regional_id), ("global_parent", global_id)]
        for level_type, level_id in order:
            for m in self.matrix:
                if clean(m.get("level_type")) == level_type and clean(m.get("level_id")) == level_id:
                    lo = to_num(m.get("min_amount"), 0); hi = to_num(m.get("max_amount"), 1e18)
                    if lo <= amount <= hi:
                        return m
        return None

    def validate(self, ctx) -> StageResult:
        r = StageResult(self.stage_key, self.title, self.icon)
        amount = to_num(ctx.get("order_total"), 0) or 0
        cost_center = clean(ctx.get("cost_center"))
        branch_id = clean(ctx.get("branch_id"))
        regional_id = clean(ctx.get("regional_division_id"))
        global_id = clean(ctx.get("global_parent_id"))
        buyer_id = clean(ctx.get("buyer_id"))
        r.log(f"Budget/approval started for order value ${amount:,.2f}.")

        # ── Budget availability (cost center, then branch) ──────────────────
        cc = self.cc.get(cost_center, {})
        cc_avail = to_num(cc.get("available_amount"))
        if cc_avail is not None and amount > cc_avail:
            br = self.budget.get(("branch", branch_id), {})
            br_avail = to_num(br.get("available_amount"))
            if br_avail is None or amount > br_avail:
                shortfall = amount - (cc_avail if cc_avail is not None else 0)
                approver = self._find_approver(amount, branch_id, regional_id, global_id)
                approver_name = clean((approver or {}).get("approver_name")) or "Budget Approver"
                approver_role = clean((approver or {}).get("approver_role")) or "APPROVER"
                r.fail("BUDGET_EXCEEDED",
                       f"Order value ${amount:,.2f} exceeds available budget.")
                r.kv("Budget shortfall", [
                    ("Order value", f"${amount:,.2f}"),
                    ("Cost center", f"{cost_center} (available ${cc_avail:,.2f})"),
                    ("Branch", f"{branch_id} (available ${br_avail:,.2f})" if br_avail is not None else branch_id),
                    ("Shortfall", f"${shortfall:,.2f}"),
                ])
                r.note("Routed according to the customer's approval policy.")
                r.data["approval_email_sent_to"] = approver_name
                r.data["approval_email_role"] = approver_role
                r.log("Budget exceeded -> budget exception.")
                r.log(f"Budget escalation email sent to {approver_role} ({approver_name}). Process halted pending response.")
                return r

        # ── Buyer self-approval authority ───────────────────────────────────
        auth = self.authority.get(buyer_id, {})
        self_limit = to_num(auth.get("max_order_value"),
                            to_num(ctx.get("buyer_max_order_value"), 0)) or 0
        can_self = yes(auth.get("can_self_approve")) if auth else bool(ctx.get("buyer_can_self_approve"))

        if amount <= self_limit and can_self:
            r.ok(f"Order ${amount:,.2f} is within budget and the buyer's self-approval "
                 f"limit (${self_limit:,.2f}). No approval required. Ready for credit validation.")
            r.kv("Budget & approval", [
                ("Order value", f"${amount:,.2f}"),
                ("Cost center available", f"${cc_avail:,.2f}" if cc_avail is not None else "—"),
                ("Buyer self-approval limit", f"${self_limit:,.2f}"),
                ("Approval", "Auto-approved (within authority)"),
            ])
            r.data["approval_status"] = "AUTO_APPROVED"
            r.log("Within self-approval authority -> PASS.")
            return r

        # ── Needs approval -> route to matrix approver ──────────────────────
        approver = self._find_approver(amount, branch_id, regional_id, global_id)
        if not approver:
            r.fail("MISSING_APPROVER",
                   f"Order ${amount:,.2f} exceeds the buyer's authority but no approver is "
                   f"configured for this amount in the approval matrix.")
            r.log("No approver in matrix -> missing approver exception.")
            return r

        approver_name = clean(approver.get("approver_name"))
        approver_role = clean(approver.get("approver_role"))

        # Send the approval request email to the approver
        from modules.mock_integrations import send_email
        _be = clean(ctx.get("buyer_email"))
        _domain = _be.split("@")[-1] if _be and "@" in _be else "company.com"
        approver_email = clean(approver.get("email")) or \
            f"{(approver_name or 'approver').lower().replace(' ', '.')}@{_domain}"
        smtp = send_email(
            to=approver_email,
            subject=f"Approval required for PO {clean(ctx.get('po_number'))} (${amount:,.2f})",
            body=(f"An order requires your approval. Order value ${amount:,.2f} exceeds "
                  f"the buyer's self-approval limit (${self_limit:,.2f})."),
            reference=clean(ctx.get("po_number")),
        )

        r.fail("APPROVAL_REQUIRED",
               f"Order ${amount:,.2f} exceeds the buyer's self-approval limit "
               f"(${self_limit:,.2f}). An approval task has been created and routed "
               f"to {approver_name} ({approver_role}).")
        r.kv("Approval task", [
            ("Order value",      f"${amount:,.2f}"),
            ("Approver role",    approver_role),
            ("Approver",         approver_name),
            ("Approver email",   approver_email),
            ("Approval level",   f"{clean(approver.get('level_type'))} ({clean(approver.get('level_id'))})"),
            ("Threshold range",  f"${to_num(approver.get('min_amount')):,} – "
                                 f"${to_num(approver.get('max_amount')):,}"),
            ("SLA",              f"{to_num(approver.get('sla_hours'))} hours"),
            ("Email status",     smtp.message),
            ("Email message ID", smtp.record_id or "—"),
        ])
        # UI hooks (render_stage_result picks these up to show the email/halt panel)
        r.data["approval_email_sent_to"] = approver_name
        r.data["approval_email_role"]    = approver_role
        r.data["approval_email_address"] = approver_email
        r.data["approval_email_message_id"] = smtp.record_id
        r.data["approval_status"]        = "PENDING_APPROVAL"
        r.log(f"Approval required -> routed to {approver_role} ({approver_name}).")
        r.log(smtp.message)
        return r
