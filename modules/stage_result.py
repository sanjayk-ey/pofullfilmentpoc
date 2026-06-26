"""
stage_result.py
A uniform result object returned by every orchestration stage so the UI and the
test harness can render any stage consistently.

A stage returns PASS or EXCEPTION, a short headline, any number of display
sections (key/value blocks, tables, or notes), an audit trail, and a `data`
dict whose values are merged into the shared pipeline context for later stages.
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class StageResult:
    stage_key:      str
    title:          str
    icon:           str = "⚙️"
    status:         str = "PASS"            # PASS | EXCEPTION
    exception_type: Optional[str] = None
    headline:       str = ""
    sections:       List[dict] = field(default_factory=list)
    audit_trail:    List[str] = field(default_factory=list)
    data:           Dict[str, Any] = field(default_factory=dict)

    @property
    def is_exception(self) -> bool:
        return self.status == "EXCEPTION"

    # ── builder helpers ─────────────────────────────────────────────────────
    def fail(self, exception_type: str, headline: str):
        self.status = "EXCEPTION"
        self.exception_type = exception_type
        self.headline = headline
        return self

    def ok(self, headline: str):
        self.status = "PASS"
        self.headline = headline
        return self

    def kv(self, title: str, rows: List[tuple]):
        """rows = [(label, value), ...]"""
        self.sections.append({"type": "kv", "title": title, "rows": rows})
        return self

    def table(self, title: str, headers: List[str], rows: List[list]):
        self.sections.append({"type": "table", "title": title,
                              "headers": headers, "rows": rows})
        return self

    def note(self, text: str):
        self.sections.append({"type": "note", "text": text})
        return self

    def log(self, msg: str):
        self.audit_trail.append(msg)
        return self
