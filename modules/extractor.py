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
    # Header fields (mandatory set)
    po_number:            Optional[str]  = None
    customer_account:     Optional[str]  = None
    contract_reference:   Optional[str]  = None
    ship_to_zip:          Optional[str]  = None
    requested_delivery_date: Optional[str] = None
    delivery_instructions: Optional[str] = None

    # Buyer context (used by downstream authorization / approval stages)
    buyer_id:             Optional[str]  = None
    cost_center:          Optional[str]  = None

    # Order lines
    order_lines: List[OrderLine] = field(default_factory=list)

    # Confidence per field (0-100)
    confidence_scores: dict = field(default_factory=dict)

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
}

# ── Regex patterns ─────────────────────────────────────────────────────────────
class Patterns:
    PO_NUMBER = [
        r'P\.?O\.?\s*(?:No\.?|Number|#|Num\.?|Ref\.?)?\s*[:\-]\s*([A-Z0-9][\w\-\/\.]{2,24})',
        r'Purchase\s+Order\s+(?:No\.?|Number|#)?\s*[:\-]\s*([A-Z0-9][\w\-\/\.]{2,24})',
        r'Order\s+(?:No\.?|Number|#|Num\.?)?\s*[:\-]\s*([A-Z0-9][\w\-\/\.]{2,24})',
        r'\b(PO[\-\/]?\d{4,}[\-\/]?[\w\-]*)\b',
    ]
    CUSTOMER = [
        r'Customer\s*(?:ID|No\.?|Number|Account|Code)?\s*[:\-]\s*([A-Z0-9][\w\-\.]{2,24})',
        r'Account\s*(?:ID|No\.?|Number|Code)?\s*[:\-]\s*([A-Z0-9][\w\-\.]{2,24})',
        r'(?:Sold\s+To|Bill\s+To|Buyer\s+ID)\s*[:\-]\s*([A-Z0-9][\w\-\.]{2,24})',
        r'(?:Client|Company)\s*(?:ID|Code)?\s*[:\-]\s*([A-Z0-9][\w\-\.]{2,24})',
    ]
    CONTRACT = [
        r'Contract\s*(?:No\.?|Number|Reference|Ref\.?|#|ID)?\s*[:\-]\s*([A-Z0-9][\w\-\/\.]{3,30})',
        r'Agreement\s*(?:No\.?|Number|Ref\.?|#)?\s*[:\-]\s*([A-Z0-9][\w\-\/\.]{3,30})',
        r'(?:MSA|SLA|Frame\s+Contract)\s*(?:No\.?|Ref\.?)?\s*[:\-]\s*([A-Z0-9][\w\-\/\.]{3,30})',
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

    MANDATORY_FIELDS = [
        ("po_number",               "PO Number"),
        ("customer_account",        "Customer Account"),
        ("ship_to_zip",             "Ship-To ZIP Code"),
        ("requested_delivery_date", "Requested Delivery Date"),
    ]
    MANDATORY_LINE_FIELDS = [
        ("sku",      "SKU"),
        ("quantity", "Quantity"),
        ("uom",      "Unit of Measure"),
    ]

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
                   "PALLETS":"PALLET","TONS":"TON","SETS":"SET","KITS":"KIT"}
        return aliases.get(u, u)

    def _find_zip_near_keyword(self, text: str) -> Tuple[Optional[str], float]:
        """Find ZIP that appears near shipping keywords."""
        ship_sections = re.findall(
            r'(?:Ship\s+To|Deliver\s+To|Delivery\s+Address|Ship\s*To\s*:).{0,400}',
            text, re.IGNORECASE | re.DOTALL)
        for section in ship_sections:
            m = re.search(r'\b(\d{5}(?:[\-]\d{4})?)\b', section)
            if m:
                # Valid 5-digit ZIP found inside the ship-to block — fully confident
                return m.group(1), 1.0
        # Fallback: any ZIP in text (still a valid ZIP, just not next to a ship-to label)
        zips = re.findall(r'\b(\d{5}(?:[\-]\d{4})?)\b', text)
        # Filter out years and common non-ZIP 5-digit numbers
        valid = [z for z in zips if not (1900 <= int(z[:4]) <= 2100 and len(z) == 4)]
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
                if sku or (qty and uom):
                    return OrderLine(line_number=line_num, sku=sku, description=desc,
                                     quantity=qty, uom=uom, unit_price=price, confidence=0.80)
        return None

    # ── Public API ─────────────────────────────────────────────────────────────
    def extract_from_text(self, text: str) -> ExtractedPO:
        po = ExtractedPO(source_type="TEXT")
        scores = {}

        # PO Number
        po.po_number, scores["po_number"] = self._first_match(text, Patterns.PO_NUMBER)

        # Customer Account
        po.customer_account, scores["customer_account"] = self._first_match(text, Patterns.CUSTOMER)

        # Contract Reference (optional field — full confidence when present)
        po.contract_reference, scores["contract_reference"] = self._first_match(text, Patterns.CONTRACT)

        # Buyer context (optional at intake; used by downstream authorization)
        po.buyer_id, _    = self._first_match(text, Patterns.BUYER)
        po.cost_center, _ = self._first_match(text, Patterns.COST_CENTER)

        # Ship-to ZIP — 100% when a valid ZIP is found, 0% when missing
        po.ship_to_zip, scores["ship_to_zip"] = self._find_zip_near_keyword(text)

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
        # (SKU + Quantity + UOM). A fully complete line is 100% confident.
        for ln in po.order_lines:
            present = sum(1 for v in (ln.sku, ln.quantity, ln.uom) if v not in (None, ""))
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
        weights = {"po_number":2.0, "customer_account":2.0, "ship_to_zip":1.5,
                   "requested_delivery_date":1.5, "order_lines":2.0,
                   "contract_reference":0.5, "delivery_instructions":0.5}
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
        # Line-level mandatory fields (deduplicated)
        for line in po.order_lines:
            for attr, label in self.MANDATORY_LINE_FIELDS:
                if not getattr(line, attr):
                    full = f"{label} (on one or more order lines)"
                    if full not in seen:
                        missing.append(full)
                        seen.add(full)
        # No order lines at all
        if not po.order_lines:
            missing.append("Order Lines (SKU / Quantity / UOM)")
        po.missing_fields = missing
