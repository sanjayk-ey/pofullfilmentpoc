"""
extractor.py
Rule-based PO field extractor with confidence scoring.
No external API required — works entirely offline.
"""
import re
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from dateutil import parser as dateparser


# ── Data structures ────────────────────────────────────────────────────────────
@dataclass
class OrderLine:
    line_number: int
    sku:         Optional[str]   = None
    description: Optional[str]  = None
    quantity:    Optional[float] = None
    uom:         Optional[str]   = None
    unit_price:  Optional[float] = None
    confidence:  float           = 0.0


@dataclass
class ExtractedPO:
    # Header fields
    po_number:            Optional[str]  = None
    po_date:              Optional[str]  = None
    customer_account:     Optional[str]  = None
    contract_reference:   Optional[str]  = None
    # Ship-to can be provided as a full address, a partial address, a ZIP, or
    # just a factory / company name. Any one of these satisfies intake; the
    # exact registered ship-to is resolved against master data (with CSR
    # confirmation when only a partial/ambiguous value is given).
    ship_to_zip:          Optional[str]  = None
    ship_to_name:         Optional[str]  = None
    ship_to_address:      Optional[str]  = None
    requested_delivery_date: Optional[str] = None
    delivery_instructions: Optional[str] = None

    # Human-readable buyer identity (standard on a US PO). The internal
    # customer account / buyer id / cost center are resolved from these against
    # master data (see modules/resolver.py).
    company_name:         Optional[str]  = None
    contact_person:       Optional[str]  = None
    buyer_email:          Optional[str]  = None

    # Buyer context (used by downstream authorization / approval stages)
    buyer_id:             Optional[str]  = None
    cost_center:          Optional[str]  = None

    # Order lines
    order_lines: List[OrderLine] = field(default_factory=list)

    # Confidence per field (0-100)
    confidence_scores: dict = field(default_factory=dict)

    # Where each optional header field came from — either the PO document
    # ("PO") or the master data fallback ("MASTER"). Missing keys mean the
    # field is either mandatory or truly not available. Used by the UI to
    # display a small "(from master data)" badge instead of "— not found —".
    field_source: dict = field(default_factory=dict)

    # Overall
    overall_confidence: float       = 0.0
    missing_fields:     List[str]   = field(default_factory=list)
    warnings:           List[str]   = field(default_factory=list)
    source_type:        str         = "TEXT"   # TEXT or EXCEL

    # Computed convenience props
    @property
    def all_skus(self):
        return [l.sku for l in self.order_lines if l.sku]

    @property
    def all_quantities(self):
        return [l.quantity for l in self.order_lines if l.quantity]

    @property
    def all_uoms(self):
        return [l.uom for l in self.order_lines if l.uom]


# ── Known UOMs ─────────────────────────────────────────────────────────────────
KNOWN_UOMS = {
    "EA","EACH","PC","PCS","PIECE","PIECES",
    "FT","FEET","FOOT","M","METER","METERS",
    "KG","KILOGRAM","KGS","LB","LBS","POUND","POUNDS",
    "GAL","GALLON","GALLONS","L","LITRE","LITER",
    "BOX","BOXES","KIT","KITS","SET","SETS",
    "ROLL","ROLLS","PALLET","PALLETS","MT","TON","TONS",
    "IN","INCH","INCHES","CM","MM",
    "CASE","CASES","CS","PR","PAIR","PAIRS","DOZ","DOZEN","DZ",
}

# ── Regex patterns ─────────────────────────────────────────────────────────────
class Patterns:
    PO_NUMBER = [
        r'P\.?O\.?\s*(?:No\.?|Number|#|Num\.?|Ref\.?)?\s*[:\-]\s*([A-Z0-9][\w\-\/\.]{2,24})',
        r'Purchase\s+Order\s+(?:No\.?|Number|#)?\s*[:\-]\s*([A-Z0-9][\w\-\/\.]{2,24})',
        r'Order\s+(?:No\.?|Number|#|Num\.?)?\s*[:\-]\s*([A-Z0-9][\w\-\/\.]{2,24})',
        r'\b(PO[\-\/]?\d{4,}[\-\/]?[\w\-]*)\b',
    ]
    # Explicit customer ACCOUNT NUMBER (a code like CUST-1001). Kept strict so a
    # free-text company name is never mistaken for an account code.
    CUSTOMER_ID = [
        r'Customer\s*(?:Account\s*)?(?:ID|No\.?|Number|Account|Code)\s*[:\-]\s*([A-Z]{2,}\-[A-Z0-9\-]{2,})',
        r'Account\s*(?:ID|No\.?|Number|Code)\s*[:\-]\s*([A-Z]{2,}\-[A-Z0-9\-]{2,})',
    ]
    # Buying company name (free text) from the buyer / bill-to block.
    COMPANY = [
        r'Company\s*(?:Name)?\s*[:\-]\s*(.+)',
        r'(?:Buyer|Bill[\-\s]*To|Sold[\-\s]*To|Customer)\s*(?:Name|Company)\s*[:\-]\s*(.+)',
    ]
    # Contact person / requisitioner (a human name) from the buyer block.
    CONTACT = [
        r'Contact\s*Person\s*[:\-]\s*(.+)',
        r'(?:Attn\.?|Attention|Ordered\s*By|Requisitioner|Buyer\s*Contact|Contact)\s*[:\-]\s*(.+)',
    ]
    CONTRACT = [
        r'Contract\s*(?:No\.?|Number|Reference|Ref\.?|#|ID)?\s*[:\-]\s*([A-Z0-9][\w\-\/\.]{3,30})',
        r'Agreement\s*(?:No\.?|Number|Ref\.?|#)?\s*[:\-]\s*([A-Z0-9][\w\-\/\.]{3,30})',
        r'(?:MSA|SLA|Frame\s+Contract)\s*(?:No\.?|Ref\.?)?\s*[:\-]\s*([A-Z0-9][\w\-\/\.]{3,30})',
    ]
    # PO issue date (distinct from the requested delivery date).
    PO_DATE = [
        r'(?:PO|P\.O\.|Purchase\s+Order|Order)\s*Date\s*[:\-]\s*'
        r'(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})',
        r'(?:PO|P\.O\.|Purchase\s+Order|Order)\s*Date\s*[:\-]\s*'
        r'(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2})',
        r'(?:PO|P\.O\.|Purchase\s+Order|Order)\s*Date\s*[:\-]\s*'
        r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4})',
        r'(?:PO|P\.O\.|Purchase\s+Order|Order)\s*Date\s*[:\-]\s*'
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+\d{4})',
    ]
    # Buyer email address (from the buyer / bill-to block).
    EMAIL = [
        r'(?:Buyer\s*)?E[\-\s]?mail\s*(?:ID|Address)?\s*[:\-]\s*'
        r'([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})',
        r'\b([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b',
    ]
    # Ship-to free-text: the block after a SHIP TO / DELIVER TO label. Captured
    # so a partial address or a factory/company name can be resolved later.
    SHIP_TO_BLOCK = [
        r'(?:Ship[\-\s]*To|Deliver[\-\s]*To|Delivery\s+Address|Ship\s+To\s+Address)'
        r'\s*[:\-]?\s*\n?((?:.+\n?){1,5})',
    ]
    ZIP = [
        r'\b([0-9]{5}(?:[\-][0-9]{4})?)\b',
    ]
    DATE = [
        r'(?:Delivery|Requested|Ship|Required|Due|Need\s+By)\s*(?:Date|By|On|Before)?\s*[:\-]\s*'
        r'(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})',
        r'(?:Delivery|Requested|Ship|Required|Due)\s*(?:Date)?\s*[:\-]\s*'
        r'(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2})',
        r'(?:Delivery|Ship|Due)\s*(?:Date)?\s*[:\-]\s*'
        r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4})',
        r'(?:Delivery|Ship|Due)\s*(?:Date)?\s*[:\-]\s*'
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+\d{4})',
    ]
    DELIVERY_INSTR = [
        r'(?:Delivery|Shipping)\s+Instructions?\s*[:\-]\s*(.+?)(?:\n\n|\Z)',
        r'Special\s+Instructions?\s*[:\-]\s*(.+?)(?:\n\n|\Z)',
        r'Notes?\s*[:\-]\s*(.+?)(?:\n\n|\Z)',
        r'Comments?\s*[:\-]\s*(.+?)(?:\n\n|\Z)',
        r'Remarks?\s*[:\-]\s*(.+?)(?:\n\n|\Z)',
    ]
    SKU = [
        r'(?:SKU|Part\s*(?:No\.?|Number|#|Code)|Item\s*(?:No\.?|Code)|Material\s*(?:No\.?|Code)?)\s*[:\-]?\s*([A-Z0-9][\w\-\.]{3,24})',
        r'\b(SKU[\-][A-Z0-9\-]{3,20})\b',
    ]
    PAYMENT_TERMS = [
        r'Payment\s+Terms?\s*[:\-]\s*(.+?)(?:\n|$)',
    ]
    BUYER = [
        r'Buyer\s*(?:ID|No\.?|Number|Code)\s*[:\-]\s*([A-Z0-9][\w\-]{2,20})',
    ]
    COST_CENTER = [
        r'Cost\s*Cent(?:er|re)\s*(?:ID|No\.?|Code)?\s*[:\-]\s*([A-Z0-9][\w\-]{2,20})',
    ]


# ── Main extractor class ───────────────────────────────────────────────────────
class POExtractor:
    """
    Extracts PO fields from free-form text using regex pattern matching.
    Returns confidence scores and flags missing mandatory fields.
    """

    # Per business feedback, only the following are MANDATORY at intake. Every
    # other field is optional — if present it is used, otherwise it is resolved
    # from master data (or defaulted).
    #   - PO Number, PO Date
    #   - Buyer: Company Name + Buyer Email
    #   - Ship-To: any form (full/partial address, ZIP, or factory/company name)
    #   - Requested Delivery Date
    #   - Order line: SKU, Description, Quantity  (UOM is optional)
    # Ship-to and customer identity are checked with custom logic below.
    MANDATORY_FIELDS = [
        ("po_number",               "PO Number"),
        ("po_date",                 "PO Date"),
        ("company_name",            "Buyer Company Name"),
        ("buyer_email",             "Buyer Email"),
        ("requested_delivery_date", "Requested Delivery Date"),
    ]
    MANDATORY_LINE_FIELDS = [
        ("sku",         "SKU"),
        ("description", "Description"),
        ("quantity",    "Quantity"),
    ]

    def __init__(self):
        # Entity resolver maps company/contact names to internal ids. Guarded so
        # the extractor still works offline if master data is unavailable.
        try:
            from modules.resolver import EntityResolver
            self.resolver = EntityResolver()
        except Exception:
            self.resolver = None

    # ── Internal helpers ───────────────────────────────────────────────────────
    def _first_match(self, text: str, patterns: list, flags=re.IGNORECASE|re.MULTILINE) -> Tuple[Optional[str], float]:
        """
        Try patterns in order, return (value, confidence).
        Confidence model: a field that is found and non-empty is fully confident (1.0).
        Confidence drops below 1.0 only when a field is missing/empty/invalid — which is
        handled by the callers and the missing-field validation.
        """
        for pat in patterns:
            m = re.search(pat, text, flags)
            if m:
                val = m.group(1).strip()
                if val:
                    return val, 1.0
        return None, 0.0

    def _parse_date(self, raw: str) -> Tuple[Optional[str], bool]:
        """Return (formatted_date, parsed_ok). parsed_ok indicates a valid calendar date."""
        try:
            return dateparser.parse(raw, dayfirst=False).strftime("%d %b %Y"), True
        except Exception:
            return raw.strip(), False

    def _normalize_uom(self, raw: str) -> str:
        u = raw.upper().strip()
        aliases = {"EACH":"EA","PIECE":"PC","PIECES":"PCS","FEET":"FT","FOOT":"FT",
                   "METER":"M","METERS":"M","KILOGRAM":"KG","POUND":"LB","POUNDS":"LB",
                   "GALLON":"GAL","GALLONS":"GAL","LITRE":"L","LITER":"L",
                   "INCH":"IN","INCHES":"IN","BOXES":"BOX","ROLLS":"ROLL",
                   "PALLETS":"PALLET","TONS":"TON","SETS":"SET","KITS":"KIT",
                   "CASES":"CASE","CS":"CASE","PAIR":"PR","PAIRS":"PR",
                   "DOZEN":"DOZ","DZ":"DOZ"}
        return aliases.get(u, u)

    def _resolve_identity(self, po: "ExtractedPO"):
        """
        Resolve the internal customer account, buyer id and cost center from the
        human-readable company / contact names on the PO. Explicit codes on the
        PO always win; resolution only fills in what is not explicitly given.
        Also backfills the OPTIONAL header fields (contact_person, contract
        reference, delivery instructions) from master data when the PO omits
        them, tagging each in ``po.field_source`` as "PO" or "MASTER".
        """
        # Clean captured free-text names
        if po.company_name:
            po.company_name = po.company_name.strip().rstrip(".,").strip()
        if po.contact_person:
            po.contact_person = po.contact_person.strip().rstrip(".,").strip()

        # Record where each optional field originally came from.
        po.field_source["contact_person"]        = "PO" if po.contact_person else None
        po.field_source["contract_reference"]    = "PO" if po.contract_reference else None
        po.field_source["delivery_instructions"] = "PO" if po.delivery_instructions else None

        if self.resolver is None:
            return

        # Customer account from company name (when not given explicitly)
        if not po.customer_account and po.company_name:
            po.customer_account = self.resolver.resolve_company(po.company_name)

        # Buyer id + default cost center. Resolve from the contact person when
        # present; otherwise fall back to the buyer email (only Company Name +
        # Buyer Email are mandatory, so the buyer is normally resolved by email).
        buyer = None
        if po.contact_person:
            buyer = self.resolver.resolve_buyer(po.contact_person)
        if not buyer and po.buyer_email:
            buyer = self.resolver.resolve_buyer_by_email(po.buyer_email)
        if buyer:
            if not po.buyer_id:
                po.buyer_id = buyer.get("buyer_id")
            if not po.cost_center:
                po.cost_center = buyer.get("default_cost_center")
            if not po.customer_account:
                po.customer_account = buyer.get("customer_account")

        # ── Master-data fallback for optional header fields ───────────────
        # Contact person: buyer_name registered against this email. When we
        # backfill from master data we treat the value as fully-known (100%
        # confidence) because it came straight from the trusted master.
        if not po.contact_person:
            fallback = self.resolver.default_contact_person(po.buyer_email)
            if fallback:
                po.contact_person = fallback
                po.field_source["contact_person"] = "MASTER"
                po.confidence_scores["contact_person"] = 100

        # Contract reference: customer's ACTIVE contract on file.
        if not po.contract_reference and po.customer_account:
            fallback = self.resolver.default_contract_reference(po.customer_account)
            if fallback:
                po.contract_reference = fallback
                po.field_source["contract_reference"] = "MASTER"
                po.confidence_scores["contract_reference"] = 100

        # NOTE: Delivery instructions are intentionally NOT backfilled from
        # master data — they belong to a specific PO transaction (dock hours
        # for that delivery, special notes for that shipment) and should be
        # shown only when the customer explicitly provides them on this PO.

    def _extract_buyer_email(self, text: str) -> Optional[str]:
        """Extract the buyer's email, scoped to the BUYER / BILL-TO block so the
        vendor/seller email is not mistakenly used."""
        email_re = r'([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})'
        # 1) Email inside the BUYER / BILL-TO / SOLD-TO block (until the next
        #    ALL-CAPS section header or a blank line).
        block = re.search(
            r'(?:BUYER|BILL[\-\s]*TO|SOLD[\-\s]*TO|CUSTOMER)\b.*?'
            r'(?=\n[A-Z][A-Z \(\)/]{4,}\n|\n\s*\n|\Z)',
            text, re.IGNORECASE | re.DOTALL)
        if block:
            m = re.search(r'E[\-\s]?mail\s*(?:ID|Address)?\s*[:\-]\s*' + email_re,
                          block.group(0), re.IGNORECASE) \
                or re.search(email_re, block.group(0))
            if m:
                return m.group(1)
        # 2) An explicitly "Buyer Email" labelled field anywhere.
        m = re.search(r'Buyer\s*E[\-\s]?mail\s*(?:ID|Address)?\s*[:\-]\s*' + email_re,
                      text, re.IGNORECASE)
        if m:
            return m.group(1)
        # 3) Last resort: first email in the document.
        m = re.search(email_re, text)
        return m.group(1) if m else None

    def _extract_ship_to(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """Return (ship_to_name, ship_to_address) from the SHIP TO block.

        The first non-empty line after the SHIP TO label is treated as the
        location / factory / company name; the remaining lines (if any) are the
        address. Either may be partial — resolution against master data (and CSR
        confirmation) happens downstream.
        """
        m = re.search(
            r'(?:Ship[\-\s]*To|Deliver[\-\s]*To|Delivery\s+Address)\s*[:\-]?\s*\n?'
            r'((?:[^\n]*\n?){1,6})',
            text, re.IGNORECASE)
        if not m:
            return None, None
        block = m.group(1)
        raw_lines = block.splitlines()
        cleaned = []
        for ln in raw_lines:
            s = ln.strip()
            if not s:
                # Blank line ends the ship-to block
                break
            # Stop at a separator row like "===" or "----"
            if re.fullmatch(r'[=\-_*]{3,}', s):
                break
            # Stop when we hit another labeled header field (contains ":") or
            # the start of the order-lines table (starts with "Line" / "Item"
            # / "#" and contains "|").
            if re.match(r'^(Line|Item|#|No\.?)\b.*\|', s, re.I):
                break
            if s.upper() in ("USA", "US", "U.S.A.", "UNITED STATES"):
                continue
            # Skip any other clearly-labeled header field embedded in the block
            # (e.g. "Requested Delivery Date: 24 Jul 2026"), but keep the
            # explicit ZIP: xxxxx line since it belongs to the ship-to.
            if ":" in s and not re.match(r'^ZIP\s*:', s, re.I):
                break
            cleaned.append(s)
        if not cleaned:
            return None, None
        # Drop trailing "ZIP: xxxxx" line — it feeds ship_to_zip separately.
        cleaned = [ln for ln in cleaned if not re.match(r'^ZIP\s*:', ln, re.I)]
        if not cleaned:
            return None, None
        name = cleaned[0]
        address = ", ".join(cleaned[1:]) if len(cleaned) > 1 else None
        # If the first line already looks like a street address (starts with a
        # number), treat the whole block as address with no distinct name.
        if re.match(r'^\d', name):
            return None, ", ".join(cleaned)
        return name, address

    def _find_zip_near_keyword(self, text: str) -> Tuple[Optional[str], float]:
        """Find ZIP, preferring an explicitly labeled field, then a ship-to block."""
        # Highest priority: an explicit ZIP / postal-code label (e.g. "Ship-To ZIP: 60639").
        # This avoids mistaking a 5-digit run inside a PO number for a ZIP code.
        m = re.search(
            r'(?:Ship[\-\s]*To\s*)?(?:ZIP|Zip\s*Code|Postal\s*Code)\s*[:\-]\s*(\d{5}(?:[\-]\d{4})?)\b',
            text, re.IGNORECASE)
        if m:
            return m.group(1), 1.0

        ship_sections = re.findall(
            r'(?:Ship\s+To|Deliver\s+To|Delivery\s+Address|Ship\s*To\s*:).{0,400}',
            text, re.IGNORECASE | re.DOTALL)
        # Prefer a ZIP that follows the standard USPS "City, ST ZIP" pattern
        # (e.g. "Malibu, CA 90265") so we don't accidentally match a 5-digit
        # street number like "22200 Pacific Coast Hwy".
        for section in ship_sections:
            m = re.search(
                r'\b[A-Z]{2}\s+(\d{5}(?:[\-]\d{4})?)\b', section)
            if m:
                return m.group(1), 1.0
        for section in ship_sections:
            m = re.search(r'\b(\d{5}(?:[\-]\d{4})?)\b', section)
            if m:
                return m.group(1), 1.0
        # Fallback: any ZIP in text (still a valid ZIP, just not next to a
        # ship-to label). We exclude 5-digit runs that are actually part of a
        # composite identifier such as a PO number "PO-2026-20002" (preceded
        # by a hyphen or slash and letters) so we don't hand a PO's suffix
        # back to the account validator as a ship-to ZIP.
        candidates = re.findall(
            r'(?<![A-Za-z0-9\-\/])(\d{5}(?:[\-]\d{4})?)(?![A-Za-z0-9\-\/])',
            text)
        # Filter out years and common non-ZIP 5-digit numbers
        valid = [z for z in candidates
                 if not (1900 <= int(z[:4]) <= 2100 and len(z) == 5)]
        if valid:
            return valid[0], 1.0
        return None, 0.0

    def _extract_order_lines(self, text: str) -> List[OrderLine]:
        """
        Detect table-like sections and extract order line items.
        Handles both vertical lists and horizontal table formats.
        """
        lines = []

        # Ensure text ends with newline so the last table row is captured
        text_nl = text if text.endswith('\n') else text + '\n'

        # Strategy 1: Look for line table with headers (Line|SKU|Qty|UOM pattern)
        table_match = re.search(
            r'(?:Line|#|No\.?)[|\t, ]+(?:SKU|Part|Item|Material|Product)[|\t, ]+.+?\n((?:.+\n)+)',
            text_nl, re.IGNORECASE)
        if table_match:
            rows = table_match.group(1).strip().split('\n')
            for row in rows:
                line = self._parse_table_row(row, len(lines)+1)
                if line:
                    lines.append(line)

        # Strategy 2: Look for numbered line items (1. SKU-xxx  100 EA)
        if not lines:
            item_pattern = re.compile(
                r'^\s*(\d{1,3})[\.|\)|\s]\s+'           # line number
                r'([A-Z0-9][\w\-\.]{3,24})\s+'          # SKU
                r'(.+?)\s+'                              # description (optional)
                r'(\d+(?:\.\d+)?)\s+'                   # quantity
                r'([A-Z]{1,8})',                         # UOM
                re.IGNORECASE | re.MULTILINE)
            for m in item_pattern.finditer(text_nl):
                lines.append(OrderLine(
                    line_number=int(m.group(1)),
                    sku=m.group(2).upper(),
                    description=m.group(3).strip() if len(m.group(3).strip()) > 3 else None,
                    quantity=float(m.group(4)),
                    uom=self._normalize_uom(m.group(5)),
                    confidence=0.85
                ))

        # Strategy 3: Single-line SKU blocks (SKU: xxx\nQty: 100\nUOM: EA)
        if not lines:
            blocks = re.split(r'\n(?=\s*(?:SKU|Part|Item|Material)\s*[:\-])', text_nl, flags=re.IGNORECASE)
            for i, block in enumerate(blocks[1:], 1):
                sku_m = re.search(r'(?:SKU|Part\s*(?:No\.?|Number|#|Code)|Item)\s*[:\-]\s*([A-Z0-9][\w\-\.]{3,24})', block, re.I)
                qty_m = re.search(r'(?:Qty|Quantity|Amount)\s*[:\-]\s*(\d+(?:\.\d+)?)', block, re.I)
                uom_m = re.search(r'(?:UOM|Unit\s*(?:of\s*Measure)?)\s*[:\-]\s*([A-Z]{1,8})', block, re.I)
                desc_m= re.search(r'(?:Description|Desc|Name)\s*[:\-]\s*(.+?)(?:\n|$)', block, re.I)
                if sku_m:
                    lines.append(OrderLine(
                        line_number=i,
                        sku=sku_m.group(1).upper(),
                        description=desc_m.group(1).strip() if desc_m else None,
                        quantity=float(qty_m.group(1)) if qty_m else None,
                        uom=self._normalize_uom(uom_m.group(1)) if uom_m else None,
                        confidence=0.80
                    ))

        return lines

    def _parse_table_row(self, row: str, line_num: int) -> Optional[OrderLine]:
        """Parse a single delimited table row."""
        # NOTE: pipe must be escaped as r'\|' — bare '|' is the regex OR operator
        for sep in [r'\|', '\t', r'\s{2,}']:
            parts = re.split(sep, row.strip())
            parts = [p.strip() for p in parts if p.strip()]
            if len(parts) >= 3:
                sku, qty, uom, desc, price = None, None, None, None, None
                for idx, part in enumerate(parts):
                    # First column is almost always a line/row number — skip it for data
                    if idx == 0 and re.match(r'^\d{1,3}$', part):
                        continue
                    if re.match(r'^[A-Z]{2,}[\-][A-Z0-9\-\.]{2,}$', part, re.I) and not sku:
                        sku = part.upper()
                    elif re.match(r'^\d+(?:\.\d+)?$', part) and not qty:
                        try: qty = float(part)
                        except: pass
                    elif part.upper() in KNOWN_UOMS and not uom:
                        uom = self._normalize_uom(part)
                    elif re.match(r'^\$?[\d,]+\.\d{2}$', part) and not price:
                        try: price = float(part.replace('$', '').replace(',', ''))
                        except: pass
                    elif len(part) > 5 and not desc and not re.match(r'^\d', part):
                        desc = part
                # UOM is optional; a row is a valid order line if it has
                # (SKU) OR (description + quantity) OR (quantity + UOM).
                if sku or (desc and qty is not None) or (qty is not None and uom):
                    return OrderLine(line_number=line_num, sku=sku, description=desc,
                                     quantity=qty, uom=uom, unit_price=price, confidence=0.80)
        return None

    # ── Public API ─────────────────────────────────────────────────────────────
    def extract_from_text(self, text: str) -> ExtractedPO:
        po = ExtractedPO(source_type="TEXT")
        scores = {}

        # PO Number
        po.po_number, scores["po_number"] = self._first_match(text, Patterns.PO_NUMBER)

        # PO Date — 100% when it parses into a valid calendar date
        raw_po_date, _ = self._first_match(text, Patterns.PO_DATE)
        if raw_po_date:
            formatted, parsed_ok = self._parse_date(raw_po_date)
            po.po_date = formatted
            scores["po_date"] = 1.0 if parsed_ok else 0.6
        else:
            scores["po_date"] = 0.0

        # Customer identity: explicit account code (if present) + company name +
        # contact person. Internal ids are resolved from names below.
        po.customer_account, _ = self._first_match(text, Patterns.CUSTOMER_ID)
        po.company_name, _     = self._first_match(text, Patterns.COMPANY)
        po.contact_person, _   = self._first_match(text, Patterns.CONTACT)

        # Buyer email (mandatory). Scoped to the BUYER / BILL-TO block so the
        # vendor/seller email (which usually appears first) is not picked up.
        po.buyer_email = self._extract_buyer_email(text)

        # Contract Reference (optional field — full confidence when present)
        po.contract_reference, scores["contract_reference"] = self._first_match(text, Patterns.CONTRACT)

        # Buyer context (optional at intake; used by downstream authorization)
        po.buyer_id, _    = self._first_match(text, Patterns.BUYER)
        po.cost_center, _ = self._first_match(text, Patterns.COST_CENTER)

        # Resolve internal ids from the human-readable names against master data.
        self._resolve_identity(po)
        scores["customer_account"] = 1.0 if po.customer_account else 0.0
        scores["company_name"]     = 1.0 if po.company_name else 0.0
        scores["contact_person"]   = 1.0 if po.contact_person else 0.0
        scores["buyer_email"]      = 1.0 if po.buyer_email else 0.0
        # If _resolve_identity backfilled a value from master data, that value
        # comes from a trusted source so we treat it as fully known (100%).
        # (The regex-driven score above is left at 0 for fields that were not
        # in the PO text.)
        if po.field_source.get("contract_reference") == "MASTER":
            scores["contract_reference"] = 1.0
        if po.field_source.get("contact_person") == "MASTER":
            scores["contact_person"] = 1.0

        # Ship-to — accept ANY form: ZIP, free-text block (partial address), or a
        # factory / company name. The registered ship-to is resolved against
        # master data downstream (with CSR confirmation for partial matches).
        po.ship_to_zip, _ = self._find_zip_near_keyword(text)
        po.ship_to_name, po.ship_to_address = self._extract_ship_to(text)
        scores["ship_to"] = 1.0 if (po.ship_to_zip or po.ship_to_name or po.ship_to_address) else 0.0

        # Delivery Date — 100% when it parses into a valid calendar date (any text format),
        # reduced only when found but unparseable, 0% when not found.
        raw_date, _ = self._first_match(text, Patterns.DATE)
        if raw_date:
            formatted, parsed_ok = self._parse_date(raw_date)
            po.requested_delivery_date = formatted
            scores["requested_delivery_date"] = 1.0 if parsed_ok else 0.6
        else:
            scores["requested_delivery_date"] = 0.0

        # Delivery Instructions
        raw_instr, conf_instr = self._first_match(text, Patterns.DELIVERY_INSTR, re.IGNORECASE|re.DOTALL)
        if raw_instr:
            po.delivery_instructions = raw_instr.strip()[:300]
            scores["delivery_instructions"] = conf_instr

        # Order lines
        po.order_lines = self._extract_order_lines(text)

        # Recompute each line's confidence by completeness of mandatory fields
        # (SKU + Description + Quantity). UOM is optional — it defaults to the
        # product's base UOM from master data during product matching.
        for ln in po.order_lines:
            present = sum(1 for v in (ln.sku, ln.description, ln.quantity) if v not in (None, ""))
            ln.confidence = present / 3.0

        # Aggregate line-level confidence into scores
        if po.order_lines:
            avg_line_conf = sum(l.confidence for l in po.order_lines) / len(po.order_lines)
            scores["order_lines"] = avg_line_conf
        else:
            scores["order_lines"] = 0.0

        po.confidence_scores = {k: round(v*100) for k, v in scores.items()}
        self._compute_overall_confidence(po)
        self._flag_missing_fields(po)
        return po

    def _compute_overall_confidence(self, po: ExtractedPO):
        weights = {"po_number":2.0, "po_date":1.0, "company_name":1.5,
                   "buyer_email":1.5, "ship_to":1.5, "requested_delivery_date":1.5,
                   "order_lines":2.0, "contract_reference":0.5,
                   "delivery_instructions":0.5}
        total_w = sum(weights.values())
        weighted_sum = sum(po.confidence_scores.get(k,0)*w for k,w in weights.items())
        po.overall_confidence = round(weighted_sum / total_w)

    def _flag_missing_fields(self, po: ExtractedPO):
        missing = []
        seen = set()
        # Header mandatory fields
        for attr, label in self.MANDATORY_FIELDS:
            if not getattr(po, attr):
                missing.append(label)
                seen.add(label)
        # Ship-to is satisfied by ANY form: ZIP, free-text address, or a
        # factory / company name.
        if not (po.ship_to_zip or po.ship_to_name or po.ship_to_address):
            missing.append("Ship-To (address, ZIP, or location name)")
            seen.add("Ship-To")
        # Line-level fields (SKU, description, quantity) are NEVER hard-gated
        # here. Missing / incorrect SKU, missing description AND missing OR
        # zero quantity are all handled interactively by the intake resolver
        # against master data — each one becomes a CSR decision (US-01 AC-02 /
        # US-04) instead of a hard "intake blocked" wall.
        if not po.order_lines:
            missing.append("Order Lines (SKU / Description / Quantity)")
        po.missing_fields = missing
