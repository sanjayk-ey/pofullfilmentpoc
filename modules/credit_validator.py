"""
credit_validator.py
Credit, Payment Terms, and Financial Risk Validation.

Validates customer credit limit, available credit, open/overdue invoices,
payment terms, and risk indicators; releases the order when within policy or
places it on credit hold otherwise.

Master data: credit-master-data.xlsx (Credit_Master, Invoice_Aging,
Payment_History, Payment_Terms, Risk_Signals).

Exception types: CREDIT_HOLD.
"""
from modules.stage_result import StageResult
from modules.xlsx_util import load_sheets, clean, to_num, yes


class CreditValidator:
    stage_key = "credit"
    title = "Credit, Payment Terms & Financial Risk"
    icon = "🏦"
    steps = [
        (0.30, "🏦", "Checking credit limit and available credit..."),
        (0.30, "📄", "Reviewing open and overdue invoices..."),
        (0.30, "⚠️", "Evaluating payment risk and fraud signals..."),
        (0.25, "🧾", "Applying payment terms and recording decision..."),
    ]

    def __init__(self):
        s = load_sheets("credit-master-data.xlsx",
                        ["Credit_Master", "Invoice_Aging", "Payment_History",
                         "Payment_Terms", "Risk_Signals"])
        self.credit = {clean(r.get("customer_account")): r for r in s["Credit_Master"] if clean(r.get("customer_account"))}
        self.aging = s["Invoice_Aging"]
        self.terms = {clean(r.get("terms_code")): r for r in s["Payment_Terms"] if clean(r.get("terms_code"))}
        self.risk = {clean(r.get("customer_account")): r for r in s["Risk_Signals"] if clean(r.get("customer_account"))}

    def validate(self, ctx) -> StageResult:
        r = StageResult(self.stage_key, self.title, self.icon)
        customer = clean(ctx.get("customer_account"))
        amount = to_num(ctx.get("order_total"), 0) or 0
        r.log(f"Credit validation started for {customer}, order value ${amount:,.2f}.")

        cm = self.credit.get(customer)
        if not cm:
            r.fail("CREDIT_HOLD", f"No credit record found for customer '{customer}'.")
            r.log("No credit master record -> credit hold.")
            return r

        limit = to_num(cm.get("credit_limit"), 0)
        available = to_num(cm.get("available_credit"), 0)
        status = clean(cm.get("credit_status"))
        terms_code = clean(cm.get("payment_terms"))
        terms = self.terms.get(terms_code, {})
        overdue = [i for i in self.aging if clean(i.get("customer_account")) == customer
                   and to_num(i.get("days_overdue"), 0) > 0]
        overdue_amt = sum(to_num(i.get("amount"), 0) for i in overdue)
        risk = self.risk.get(customer, {})

        reasons = []
        if status == "HOLD":
            reasons.append(f"account credit status is {status}")
        if amount > available:
            reasons.append(f"order value ${amount:,.2f} exceeds available credit ${available:,.2f}")
        if overdue_amt > 0:
            reasons.append(f"overdue invoices total ${overdue_amt:,.2f}")
        if yes(risk.get("fraud_flag")) or yes(risk.get("watchlist")):
            reasons.append("flagged on the fraud/risk watchlist")

        if reasons:
            r.fail("CREDIT_HOLD", "Order placed on credit hold: " + "; ".join(reasons) + ".")
            r.kv("Credit assessment", [
                ("Credit limit", f"${limit:,.2f}"),
                ("Available credit", f"${available:,.2f}"),
                ("Order value", f"${amount:,.2f}"),
                ("Overdue invoices", f"${overdue_amt:,.2f}"),
                ("Payment terms", f"{terms_code} - {clean(terms.get('description'))}"),
                ("Risk rating", clean(cm.get("risk_rating"))),
                ("Recommended action", "Route to finance for review / payment / override"),
            ])
            if overdue:
                r.table("Overdue invoices", ["Invoice", "Amount", "Due date", "Days overdue"],
                        [[clean(i.get("invoice_no")), f"${to_num(i.get('amount')):,.2f}",
                          clean(i.get("due_date")), to_num(i.get("days_overdue"))] for i in overdue])
            r.log("Credit hold -> credit exception.")
            return r

        r.ok(f"Credit check passed. Customer within policy. Payment terms {terms_code}. "
             f"Ready for inventory validation.")
        r.kv("Credit assessment", [
            ("Credit limit", f"${limit:,.2f}"),
            ("Available credit", f"${available:,.2f}"),
            ("Order value", f"${amount:,.2f}"),
            ("Credit status", status),
            ("Payment terms", f"{terms_code} - {clean(terms.get('description'))}"),
            ("Risk rating", clean(cm.get("risk_rating"))),
        ])
        r.data["payment_terms"] = terms_code
        r.data["payment_terms_desc"] = clean(terms.get("description"))
        r.log("Credit result: PASS -> proceed to inventory.")
        return r
