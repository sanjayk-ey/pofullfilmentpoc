"""
base.py
Shared plumbing for the mock system clients.

``MockSystemClient`` loads a system's JSON master-data snapshot from ``data/``
and returns the requested sheets as a ``{sheet_name: [row_dict, ...]}`` dict.
Every fetch is recorded in ``CALL_LOG`` so the demo can show which systems each
agent talked to. These JSON snapshots are the source of truth for all master
data (edit them directly to change the demo data).
"""
import functools
import json
import os
from typing import Dict, List

from .registry import system_meta

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# Chronological log of every mock-system call made during a run. The UI can read
# this to show endpoints/record counts; tests can assert an agent hit a system.
CALL_LOG: List[dict] = []


def reset_call_log() -> None:
    CALL_LOG.clear()


@functools.lru_cache(maxsize=None)
def _load_snapshot(dataset: str) -> Dict[str, List[dict]]:
    """Load a system's JSON snapshot ({sheet: [rows]}) by dataset name. The
    dataset name maps to ``data/<dataset>.json``. Cached per process."""
    path = os.path.join(DATA_DIR, dataset + ".json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Mock data snapshot '{os.path.basename(path)}' is missing from "
            f"{DATA_DIR}.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class MockSystemClient:
    """Base class for a single mock enterprise system (ERP / PIM / ...)."""

    def __init__(self, code: str):
        self.meta = system_meta(code)

    # ── Identity (used by the UI narration) ─────────────────────────────────
    @property
    def code(self) -> str:
        return self.meta["code"]

    @property
    def name(self) -> str:
        return self.meta["name"]

    @property
    def endpoint(self) -> str:
        return self.meta["endpoint"]

    # ── Core fetch ──────────────────────────────────────────────────────────
    def _fetch(self, dataset: str, sheets: List[str], resource: str) -> Dict[str, List[dict]]:
        """Return ``{sheet: [rows]}`` for the requested sheets from the system's
        JSON snapshot, logging the call as if it were a real API request."""
        snap = _load_snapshot(dataset)
        out = {name: list(snap.get(name, [])) for name in sheets}
        CALL_LOG.append({
            "system": self.code,
            "name": self.name,
            "endpoint": f"{self.endpoint}/{resource}",
            "resource": resource,
            "sheets": list(sheets),
            "rows": sum(len(v) for v in out.values()),
        })
        return out
