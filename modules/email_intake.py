"""
email_intake.py
Read Purchase-Order emails directly from an Outlook / Microsoft 365 mailbox via
the Microsoft Graph API.

Design goals for the POC
------------------------
* No client secret on disk. We use MSAL **device-code flow** (a public client),
  so the user signs in interactively as themselves and we only ever hold a
  short-lived, delegated access token. The refresh token is cached locally so
  the sign-in prompt appears only once (until it expires / is revoked).
* Reads the **Inbox**, matches PO emails **by subject keyword**, and returns the
  **plain-text body** ready to be fed into ``POExtractor.extract_from_text``.

Required configuration (environment variables, e.g. via a local .env)
---------------------------------------------------------------------
    GRAPH_CLIENT_ID    Application (client) ID of an Entra app registration
                       configured as a *public client* with the delegated
                       ``Mail.Read`` permission granted/consented.
    GRAPH_TENANT_ID    Directory (tenant) ID of your organisation.
    PO_SUBJECT_KEYWORD Subject keyword used to identify PO emails
                       (default: "purchase order").

These three values are the ONLY things this code needs from IT/Azure. Everything
else (auth, token refresh, fetching, HTML->text) is handled here.
"""
from __future__ import annotations

import os
import re
import html
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read"]

# Where the MSAL refresh-token cache is stored (kept out of the repo).
_TOKEN_CACHE_PATH = os.path.join(
    os.path.dirname(__file__), "..", ".graph_token_cache.json"
)


class EmailIntakeError(RuntimeError):
    """Raised for any configuration / auth / fetch problem, with a readable message."""


@dataclass
class POEmail:
    """One PO email reduced to what the extractor / UI needs."""
    message_id: str
    subject: str
    sender: str
    received: Optional[datetime]
    body_text: str

    @property
    def received_label(self) -> str:
        return self.received.strftime("%d %b %Y %H:%M") if self.received else "—"


# ── Configuration ───────────────────────────────────────────────────────────
def load_dotenv(path: Optional[str] = None) -> None:
    """Minimal .env loader (no external dependency).

    Reads KEY=VALUE lines from a project-root ``.env`` into ``os.environ``
    without overwriting values already set in the real environment.
    """
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception:
        pass


# Load .env as soon as this module is imported.
load_dotenv()


def get_config() -> dict:
    """Read Graph configuration from the environment. Does not validate."""
    return {
        "client_id": os.environ.get("GRAPH_CLIENT_ID", "").strip(),
        "tenant_id": os.environ.get("GRAPH_TENANT_ID", "").strip(),
        "subject_keyword": os.environ.get("PO_SUBJECT_KEYWORD", "purchase order").strip(),
    }


def is_configured() -> bool:
    cfg = get_config()
    return bool(cfg["client_id"] and cfg["tenant_id"])


# ── HTML → text ─────────────────────────────────────────────────────────────
def html_to_text(raw_html: str) -> str:
    """Best-effort HTML → plain text so the rule-based extractor can read it.

    Uses BeautifulSoup when available; otherwise falls back to a tag-stripping
    regex. Email bodies frequently arrive as HTML, and the extractor expects the
    same kind of plain text a user would paste.
    """
    try:
        from bs4 import BeautifulSoup  # optional dependency
        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        # <br> and block elements become line breaks so tables/labels survive.
        for br in soup.find_all(["br"]):
            br.replace_with("\n")
        for block in soup.find_all(["p", "div", "tr", "li", "table", "h1", "h2", "h3"]):
            block.append("\n")
        text = soup.get_text()
    except Exception:
        text = re.sub(r"(?i)<br\s*/?>", "\n", raw_html)
        text = re.sub(r"(?i)</(p|div|tr|li|table|h[1-6])>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)

    # Collapse excessive blank lines / trailing spaces.
    lines = [ln.rstrip() for ln in text.splitlines()]
    out, blanks = [], 0
    for ln in lines:
        if ln.strip() == "":
            blanks += 1
            if blanks <= 1:
                out.append("")
        else:
            blanks = 0
            out.append(ln)
    return "\n".join(out).strip()


# ── Authentication (MSAL device-code flow) ──────────────────────────────────
def _build_msal_app(client_id: str, tenant_id: str):
    try:
        import msal
    except ImportError as e:
        raise EmailIntakeError(
            "The 'msal' package is not installed. Run:  pip install msal requests beautifulsoup4"
        ) from e

    cache = msal.SerializableTokenCache()
    if os.path.exists(_TOKEN_CACHE_PATH):
        try:
            cache.deserialize(open(_TOKEN_CACHE_PATH, "r", encoding="utf-8").read())
        except Exception:
            pass

    app = msal.PublicClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        token_cache=cache,
    )
    return app, cache


def _persist_cache(cache) -> None:
    if cache.has_state_changed:
        try:
            with open(_TOKEN_CACHE_PATH, "w", encoding="utf-8") as f:
                f.write(cache.serialize())
        except Exception:
            pass


def acquire_token_silent(client_id: str, tenant_id: str) -> Optional[str]:
    """Return a cached access token without prompting, or None if unavailable."""
    app, cache = _build_msal_app(client_id, tenant_id)
    accounts = app.get_accounts()
    if not accounts:
        return None
    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    _persist_cache(cache)
    if result and "access_token" in result:
        return result["access_token"]
    return None


def begin_device_flow(client_id: str, tenant_id: str) -> dict:
    """Start a device-code sign-in. Returns the flow dict (has 'message',
    'user_code', 'verification_uri'). Call ``complete_device_flow`` afterwards.
    """
    app, _cache = _build_msal_app(client_id, tenant_id)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise EmailIntakeError(
            "Failed to start device-code sign-in: "
            + flow.get("error_description", str(flow))
        )
    return flow


def complete_device_flow(client_id: str, tenant_id: str, flow: dict) -> str:
    """Block until the user finishes the device-code sign-in; return access token."""
    app, cache = _build_msal_app(client_id, tenant_id)
    result = app.acquire_token_by_device_flow(flow)  # blocks until done/timeout
    _persist_cache(cache)
    if "access_token" not in result:
        raise EmailIntakeError(
            "Sign-in did not complete: " + result.get("error_description", str(result))
        )
    return result["access_token"]


# ── Fetching PO emails ──────────────────────────────────────────────────────
def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def fetch_po_emails(
    access_token: str,
    subject_keyword: Optional[str] = None,
    top: int = 25,
) -> List[POEmail]:
    """Fetch Inbox messages whose subject contains ``subject_keyword``.

    Uses Graph ``$search`` (which can't be combined with ``$orderby``), then
    sorts newest-first client-side. Returns a list of ``POEmail`` with the body
    already converted to plain text.
    """
    try:
        import requests
    except ImportError as e:
        raise EmailIntakeError(
            "The 'requests' package is not installed. Run:  pip install msal requests beautifulsoup4"
        ) from e

    if subject_keyword is None:
        subject_keyword = get_config()["subject_keyword"]

    url = f"{GRAPH_BASE}/me/mailFolders/inbox/messages"
    params = {
        "$search": f'"subject:{subject_keyword}"',
        "$select": "id,subject,from,receivedDateTime,body,bodyPreview",
        "$top": str(top),
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        # $search on messages requires the 'eventual' consistency level.
        "ConsistencyLevel": "eventual",
    }
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code == 401:
        raise EmailIntakeError("Access token rejected (401). Please sign in again.")
    if resp.status_code == 403:
        raise EmailIntakeError(
            "Permission denied (403). The app needs delegated 'Mail.Read' with "
            "admin/user consent granted in your tenant."
        )
    if resp.status_code >= 400:
        raise EmailIntakeError(
            f"Graph request failed ({resp.status_code}): {resp.text[:500]}"
        )

    items = resp.json().get("value", [])
    emails: List[POEmail] = []
    for m in items:
        body = m.get("body", {}) or {}
        content = body.get("content", "") or m.get("bodyPreview", "")
        if (body.get("contentType", "text") or "text").lower() == "html":
            content = html_to_text(content)
        else:
            content = html.unescape(content)
        sender = ""
        frm = (m.get("from") or {}).get("emailAddress") or {}
        sender = frm.get("address") or frm.get("name") or ""
        emails.append(POEmail(
            message_id=m.get("id", ""),
            subject=m.get("subject", "") or "(no subject)",
            sender=sender,
            received=_parse_dt(m.get("receivedDateTime")),
            body_text=content,
        ))

    emails.sort(key=lambda e: e.received or datetime.min, reverse=True)
    return emails
