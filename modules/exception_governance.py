"""
exception_governance.py
Exception-Based CSR Intervention and Governance (Human-in-the-Loop).

Cross-cutting governance layer. It inspects the results of every prior stage,
surfaces only the exceptions that require human intervention, classifies their
severity, routes them to the correct role with full decision context, and
attaches the resolution / escalation SLA. Routine orders pass through with no
intervention.

Master data: exception-governance-master-data (Severity_Matrix,
Role_Routing, SLA_Thresholds).
"""
from modules.stage_result import StageResult
from modules.xlsx_util import load_sheets, clean, to_num


class ExceptionGovernance:
    stage_key = "exception_governance"
    title = "Exception Governance & Human-in-the-Loop"
    icon = "🧑‍⚖️"
    steps = [
        (0.30, "🔎", "Scanning all stages for exceptions..."),
        (0.30, "🏷️", "Classifying severity and category..."),
        (0.30, "📨", "Routing to the responsible role with decision context..."),
        (0.25, "⏱️", "Attaching resolution / escalation SLA..."),
    ]

    def __init__(self):
        s = load_sheets("exception-governance-master-data",
                        ["Severity_Matrix", "Role_Routing", "SLA_Thresholds"])
        self.severity = {clean(r.get("exception_type")): r for r in s["Severity_Matrix"] if clean(r.get("exception_type"))}
        self.routing = {clean(r.get("category")): r for r in s["Role_Routing"] if clean(r.get("category"))}
        self.sla = {clean(r.get("severity")): r for r in s["SLA_Thresholds"] if clean(r.get("severity"))}

    def route(self, results, ctx) -> StageResult:
        r = StageResult(self.stage_key, self.title, self.icon)
        exceptions = [res for res in results if getattr(res, "is_exception", False)]

        if not exceptions:
            r.ok("No human intervention required. All validations passed — the order was "
                 "processed autonomously and is ready for execution.")
            r.kv("Governance summary", [
                ("Exceptions detected", "0"),
                ("Mode", "Autonomous (straight-through processing)"),
                ("Action", "None — proceed to order execution"),
            ])
            r.log("Governance: no exceptions -> straight-through processing.")
            return r

        rows = []
        for res in exceptions:
            etype = res.exception_type or "UNKNOWN"
            sev = self.severity.get(etype, {})
            severity = clean(sev.get("severity")) or "MEDIUM"
            category = clean(sev.get("category")) or res.stage_key.upper()
            route = self.routing.get(category, {})
            sla = self.sla.get(severity, {})
            rows.append([
                res.title, etype, severity,
                clean(route.get("role")) or clean(sev.get("default_role")) or "CSR",
                clean(route.get("escalation_role")) or "SUPERVISOR",
                f"{to_num(sla.get('sla_hours'), '—')}h / esc {to_num(sla.get('escalation_hours'), '—')}h",
                clean(route.get("queue")) or "Q-GENERAL",
            ])

        primary = exceptions[0]
        r.ok(f"{len(exceptions)} exception(s) surfaced for human intervention. "
             f"Automated progression paused until resolved.")
        r.table("Routed exceptions",
                ["Stage", "Exception", "Severity", "Assigned role", "Escalation", "SLA", "Queue"],
                rows)
        r.kv("Primary exception — decision context", [
            ("Stage", primary.title),
            ("Exception type", primary.exception_type),
            ("Reason / AI recommendation", primary.headline),
            ("Required action", "Approve, modify, reject, or escalate"),
        ])
        r.note("CSR/approver may approve, modify, reject, or escalate. Orchestration resumes "
               "once the exception is resolved; unresolved items escalate per SLA.")
        r.log(f"Governance: routed {len(exceptions)} exception(s); primary={primary.exception_type}.")
        r.data["governance_routed"] = len(exceptions)
        return r
