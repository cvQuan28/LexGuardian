"""
Legal Structured Information Extractor
========================================

Extracts structured fields from Vietnamese/English contracts WITHOUT an LLM call.
Uses a tiered approach:
  1. Regex extraction (instant, deterministic)
  2. LLM fallback only for fields regex cannot find

Fields extracted:
  - contract_value     : total value (e.g. 500,000,000 VNĐ)
  - vat_rate           : VAT percentage
  - vat_amount         : VAT amount if stated
  - party_a            : first contracting party
  - party_b            : second contracting party
  - payment_terms      : payment schedule
  - payment_deadline   : deadline (days, date)
  - effective_date     : contract start date
  - expiry_date        : contract end date
  - penalty_rate       : penalty % or amount
  - late_payment_rate  : late payment penalty
  - contract_number    : document identifier
  - signing_date       : signing date

Returns a ContractFields dataclass + a plain dict for JSON serialization.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)


# ===========================================================================
# Data model
# ===========================================================================

@dataclass
class ContractFields:
    """Structured fields extracted from a contract."""
    contract_number: str = ""
    contract_value: str = ""           # raw string: "500,000,000 VNĐ"
    contract_value_numeric: float = 0.0
    contract_currency: str = ""        # "VND" | "USD" | "EUR"
    vat_rate: str = ""                 # "10%"
    vat_amount: str = ""               # "50,000,000 VNĐ"
    party_a: str = ""
    party_b: str = ""
    parties: list[str] = field(default_factory=list)
    effective_date: str = ""
    expiry_date: str = ""
    signing_date: str = ""
    payment_terms: str = ""
    payment_deadline_days: int = 0
    penalty_rate: str = ""
    late_payment_rate: str = ""
    governing_law: str = ""
    # Confidence: which fields came from regex vs LLM
    regex_extracted: list[str] = field(default_factory=list)
    llm_extracted: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ===========================================================================
# Regex patterns
# ===========================================================================

# --- Contract value ---
# Matches: "500.000.000 đồng", "500,000,000 VNĐ", "1.5 tỷ đồng", "$50,000 USD"
_VALUE_PATTERNS = [
    # Full number with currency
    re.compile(
        r"(?:giá trị hợp đồng|tổng giá trị|trị giá|giá hợp đồng|"
        r"total value|contract value|tổng cộng|tổng số tiền)"
        r"[^0-9\n]{0,40}"
        r"([\d\.,]+)\s*(tỷ|triệu|nghìn|ngàn)?\s*"
        r"(vnđ|vnd|đồng|usd|\$|eur|€)?",
        re.IGNORECASE,
    ),
    # Standalone large amounts on a line
    re.compile(
        r"^[^\d\n]{0,30}([\d\.,]{5,})\s*(tỷ|triệu|nghìn|ngàn)?\s*(vnđ|vnd|đồng|usd|\$)\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
]

_MULTIPLIERS = {"tỷ": 1_000_000_000, "triệu": 1_000_000, "nghìn": 1_000, "ngàn": 1_000}

# --- VAT ---
_VAT_PATTERNS = [
    re.compile(r"(?:thuế\s*gtgt|thuế\s*vat|vat|gtgt)[^0-9\n]{0,20}(\d+(?:[.,]\d+)?)\s*%", re.IGNORECASE),
    re.compile(r"(\d+)\s*%\s*(?:thuế|vat|gtgt)", re.IGNORECASE),
]
_VAT_AMOUNT_PATTERNS = [
    re.compile(
        r"(?:thuế\s*gtgt|vat)[^0-9\n]{0,30}([\d\.,]+)\s*(tỷ|triệu)?\s*(vnđ|vnd|đồng)?",
        re.IGNORECASE,
    ),
]

# --- Parties ---
_PARTY_A_PATTERNS = [
    re.compile(r"bên\s*(?:a|thứ nhất|1)[:\-–]\s*([^\n,;]{5,100})", re.IGNORECASE),
    re.compile(r"party\s*a[:\-–]\s*([^\n,;]{5,100})", re.IGNORECASE),
    re.compile(r"bên\s*bán[:\-–]\s*([^\n,;]{5,100})", re.IGNORECASE),
    re.compile(r"bên\s*cho\s*thuê[:\-–]\s*([^\n,;]{5,100})", re.IGNORECASE),
]
_PARTY_B_PATTERNS = [
    re.compile(r"bên\s*(?:b|thứ hai|2)[:\-–]\s*([^\n,;]{5,100})", re.IGNORECASE),
    re.compile(r"party\s*b[:\-–]\s*([^\n,;]{5,100})", re.IGNORECASE),
    re.compile(r"bên\s*mua[:\-–]\s*([^\n,;]{5,100})", re.IGNORECASE),
    re.compile(r"bên\s*thuê[:\-–]\s*([^\n,;]{5,100})", re.IGNORECASE),
]

# --- Date patterns ---
_DATE_PATTERNS = [
    re.compile(r"\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}"),           # 15/03/2024
    re.compile(r"ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4}"),  # ngày 15 tháng 3 năm 2024
    re.compile(r"\d{1,2}\s+(?:january|february|march|april|may|june|july|"
               r"august|september|october|november|december)\s+\d{4}", re.IGNORECASE),
]

_EFFECTIVE_DATE_PATTERNS = [
    re.compile(r"(?:có hiệu lực|kể từ ngày|hiệu lực từ|effective date)[^\n\d]{0,30}" +
               r"(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})", re.IGNORECASE),
    re.compile(r"(?:có hiệu lực|kể từ ngày)(.*?ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4})",
               re.IGNORECASE),
]
_SIGNING_DATE_PATTERNS = [
    re.compile(r"(?:ký kết|ký ngày|signed on|ngày ký)[^\n\d]{0,20}"
               r"(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})", re.IGNORECASE),
    re.compile(r"(?:ký kết|ký ngày)(.*?ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4})",
               re.IGNORECASE),
]

# --- Payment terms ---
_PAYMENT_PATTERNS = [
    re.compile(r"(?:thanh toán|payment)[^\n]{0,200}", re.IGNORECASE),
    re.compile(r"(?:đợt\s+\d+|lần\s+\d+)[^\n]{0,200}", re.IGNORECASE),
]
_PAYMENT_DAYS_PATTERN = re.compile(
    r"(?:trong vòng|within|không quá|no later than|sau)\s+(\d+)\s+(?:ngày|days)",
    re.IGNORECASE,
)

# --- Penalty ---
_PENALTY_PATTERNS = [
    re.compile(r"(?:phạt vi phạm|tiền phạt|mức phạt|penalty)[^\n\d]{0,30}"
               r"([\d\.,]+)\s*%", re.IGNORECASE),
    re.compile(r"(\d+(?:[.,]\d+)?)\s*%\s*(?:giá trị|hợp đồng|tổng)\s*"
               r"(?:vi phạm|phạt|chậm)", re.IGNORECASE),
]
_LATE_PAYMENT_PATTERN = re.compile(
    r"(?:chậm thanh toán|late payment|lãi suất chậm)[^\n\d]{0,30}"
    r"([\d\.,]+)\s*%(?:\s*/\s*(?:ngày|tháng|năm|day|month|year))?",
    re.IGNORECASE,
)

# --- Contract number ---
_CONTRACT_NUMBER_PATTERNS = [
    re.compile(r"(?:số hợp đồng|contract no\.?|số:)\s*([A-Z0-9\/\-\.]{3,30})", re.IGNORECASE),
    re.compile(r"HĐ[\/\-]([A-Z0-9\/\-\.]{2,20})", re.IGNORECASE),
]

# --- Governing law ---
_GOVERNING_LAW_PATTERN = re.compile(
    r"(?:pháp luật|luật điều chỉnh|governing law)[^\n]{0,50}"
    r"(?:việt nam|cộng hòa xã hội|vietnam|singapore|england|new york)",
    re.IGNORECASE,
)


# ===========================================================================
# Extractor class
# ===========================================================================

class ContractFieldExtractor:
    """
    Extracts structured fields from contract text using regex.
    All methods return (value, source) where source="regex" or "llm".

    Usage:
        extractor = ContractFieldExtractor()
        fields = extractor.extract(text)
        print(fields.contract_value)         # "500,000,000 VNĐ"
        print(fields.contract_value_numeric) # 500000000.0
        print(fields.party_a)                # "Công ty TNHH ABC"
    """

    def extract(self, text: str) -> ContractFields:
        """Extract all structured fields from contract text."""
        fields = ContractFields()

        self._extract_contract_number(text, fields)
        self._extract_value(text, fields)
        self._extract_vat(text, fields)
        self._extract_parties(text, fields)
        self._extract_dates(text, fields)
        self._extract_payment_terms(text, fields)
        self._extract_penalties(text, fields)
        self._extract_governing_law(text, fields)

        return fields

    # ------------------------------------------------------------------
    def _extract_contract_number(self, text: str, f: ContractFields) -> None:
        for pat in _CONTRACT_NUMBER_PATTERNS:
            m = pat.search(text[:2000])
            if m:
                f.contract_number = m.group(1).strip()
                f.regex_extracted.append("contract_number")
                return

    def _extract_value(self, text: str, f: ContractFields) -> None:
        for pat in _VALUE_PATTERNS:
            m = pat.search(text)
            if m:
                raw_num = m.group(1).replace(",", "").replace(".", "")
                multiplier_str = m.group(2).lower() if m.group(2) else ""
                currency_str = m.group(3) if m.group(3) else ""
                try:
                    amount = float(raw_num)
                except ValueError:
                    continue

                multiplier = _MULTIPLIERS.get(multiplier_str, 1)
                amount *= multiplier

                currency = "VND"
                if currency_str and ("usd" in currency_str.lower() or "$" in currency_str):
                    currency = "USD"
                elif currency_str and "eur" in currency_str.lower():
                    currency = "EUR"

                f.contract_value_numeric = amount
                f.contract_currency = currency
                f.contract_value = f"{amount:,.0f} {currency}"
                f.regex_extracted.append("contract_value")
                return

    def _extract_vat(self, text: str, f: ContractFields) -> None:
        for pat in _VAT_PATTERNS:
            m = pat.search(text)
            if m:
                f.vat_rate = f"{m.group(1).strip()}%"
                f.regex_extracted.append("vat_rate")
                break

        for pat in _VAT_AMOUNT_PATTERNS:
            m = pat.search(text)
            if m:
                f.vat_amount = m.group(0)[:60].strip()
                f.regex_extracted.append("vat_amount")
                break

    def _extract_parties(self, text: str, f: ContractFields) -> None:
        # Only search in first 3000 chars — parties are at the top
        header = text[:3000]

        for pat in _PARTY_A_PATTERNS:
            m = pat.search(header)
            if m:
                f.party_a = self._clean_party_name(m.group(1))
                if f.party_a:
                    f.regex_extracted.append("party_a")
                    break

        for pat in _PARTY_B_PATTERNS:
            m = pat.search(header)
            if m:
                f.party_b = self._clean_party_name(m.group(1))
                if f.party_b:
                    f.regex_extracted.append("party_b")
                    break

        f.parties = [p for p in [f.party_a, f.party_b] if p]

    def _extract_dates(self, text: str, f: ContractFields) -> None:
        for pat in _EFFECTIVE_DATE_PATTERNS:
            m = pat.search(text)
            if m:
                f.effective_date = m.group(1).strip()
                f.regex_extracted.append("effective_date")
                break

        for pat in _SIGNING_DATE_PATTERNS:
            m = pat.search(text[:2000])
            if m:
                f.signing_date = m.group(1).strip()
                f.regex_extracted.append("signing_date")
                break

    def _extract_payment_terms(self, text: str, f: ContractFields) -> None:
        for pat in _PAYMENT_PATTERNS:
            m = pat.search(text)
            if m:
                snippet = m.group(0)[:200].strip()
                f.payment_terms = snippet
                f.regex_extracted.append("payment_terms")
                break

        m = _PAYMENT_DAYS_PATTERN.search(text)
        if m:
            try:
                f.payment_deadline_days = int(m.group(1))
                f.regex_extracted.append("payment_deadline_days")
            except ValueError:
                pass

    def _extract_penalties(self, text: str, f: ContractFields) -> None:
        for pat in _PENALTY_PATTERNS:
            m = pat.search(text)
            if m:
                f.penalty_rate = m.group(0)[:80].strip()
                f.regex_extracted.append("penalty_rate")
                break

        m = _LATE_PAYMENT_PATTERN.search(text)
        if m:
            f.late_payment_rate = m.group(0)[:80].strip()
            f.regex_extracted.append("late_payment_rate")

    def _extract_governing_law(self, text: str, f: ContractFields) -> None:
        m = _GOVERNING_LAW_PATTERN.search(text)
        if m:
            f.governing_law = m.group(0)[:120].strip()
            f.regex_extracted.append("governing_law")

    @staticmethod
    def _clean_party_name(raw: str) -> str:
        """Strip trailing noise from party name."""
        raw = raw.strip()
        # Remove trailing parenthetical qualifiers like "(sau đây gọi là...)"
        raw = re.sub(r'\s*\(sau đây.*', '', raw, flags=re.IGNORECASE)
        raw = re.sub(r'\s*\(hereinafter.*', '', raw, flags=re.IGNORECASE)
        raw = re.sub(r'\s*\(gọi.*', '', raw, flags=re.IGNORECASE)
        raw = re.sub(r'[,;]+$', '', raw)
        return raw.strip()[:100]


# ===========================================================================
# LLM-augmented extractor (fallback for undetected fields)
# ===========================================================================

_LLM_EXTRACT_PROMPT = """Extract the following fields from this Vietnamese/English contract text.
Return ONLY a JSON object with these exact keys (use null for missing fields):

{{
  "contract_value": "e.g. 500,000,000 VNĐ or null",
  "vat_rate": "e.g. 10% or null",
  "party_a": "Full name of Party A / Bên A or null",
  "party_b": "Full name of Party B / Bên B or null",
  "payment_deadline_days": 30,
  "penalty_rate": "e.g. 5% of contract value or null",
  "effective_date": "e.g. 01/01/2024 or null",
  "governing_law": "e.g. Vietnamese law or null"
}}

CONTRACT TEXT (first 3000 characters):
{text}

Return ONLY the JSON object."""


async def extract_with_llm_fallback(
    text: str,
    regex_result: ContractFields,
    llm_provider,
    fields_to_fill: Optional[list[str]] = None,
) -> ContractFields:
    """
    Fill in fields that regex missed using an LLM call.

    Args:
        text: Contract text
        regex_result: Already-extracted fields from regex
        llm_provider: LLM provider instance
        fields_to_fill: Which fields to try filling (None = all missing)

    Returns:
        Updated ContractFields with LLM-filled gaps
    """
    import json
    from app.services.llm.types import LLMMessage

    # Determine which fields are still empty
    missing = []
    r = regex_result
    checks = {
        "contract_value": not r.contract_value,
        "vat_rate": not r.vat_rate,
        "party_a": not r.party_a,
        "party_b": not r.party_b,
        "payment_deadline_days": r.payment_deadline_days == 0,
        "penalty_rate": not r.penalty_rate,
        "effective_date": not r.effective_date,
        "governing_law": not r.governing_law,
    }

    if fields_to_fill:
        missing = [f for f in fields_to_fill if checks.get(f, False)]
    else:
        missing = [f for f, is_missing in checks.items() if is_missing]

    if not missing:
        return regex_result  # Nothing to fill

    try:
        prompt = _LLM_EXTRACT_PROMPT.format(text=text[:3000])
        messages = [LLMMessage(role="user", content=prompt)]
        raw = await llm_provider.acomplete(messages, temperature=0.0, max_tokens=512)

        # Strip markdown fences if any
        raw = raw.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:-1])

        data = json.loads(raw)

        # Fill only missing fields
        if "contract_value" in missing and data.get("contract_value"):
            regex_result.contract_value = data["contract_value"]
            regex_result.llm_extracted.append("contract_value")
        if "vat_rate" in missing and data.get("vat_rate"):
            regex_result.vat_rate = data["vat_rate"]
            regex_result.llm_extracted.append("vat_rate")
        if "party_a" in missing and data.get("party_a"):
            regex_result.party_a = data["party_a"]
            regex_result.llm_extracted.append("party_a")
        if "party_b" in missing and data.get("party_b"):
            regex_result.party_b = data["party_b"]
            regex_result.llm_extracted.append("party_b")
        if "payment_deadline_days" in missing and data.get("payment_deadline_days"):
            try:
                regex_result.payment_deadline_days = int(data["payment_deadline_days"])
                regex_result.llm_extracted.append("payment_deadline_days")
            except (ValueError, TypeError):
                pass
        if "penalty_rate" in missing and data.get("penalty_rate"):
            regex_result.penalty_rate = data["penalty_rate"]
            regex_result.llm_extracted.append("penalty_rate")
        if "effective_date" in missing and data.get("effective_date"):
            regex_result.effective_date = data["effective_date"]
            regex_result.llm_extracted.append("effective_date")
        if "governing_law" in missing and data.get("governing_law"):
            regex_result.governing_law = data["governing_law"]
            regex_result.llm_extracted.append("governing_law")

        # Update parties list
        regex_result.parties = [p for p in [regex_result.party_a, regex_result.party_b] if p]

    except Exception as e:
        logger.warning(f"LLM extraction fallback failed: {e}")

    return regex_result


# ===========================================================================
# Module-level convenience function
# ===========================================================================

def extract_contract_fields(text: str) -> ContractFields:
    """
    Fast regex-only extraction. No LLM call.
    For LLM fallback, use extract_with_llm_fallback().

    Example:
        fields = extract_contract_fields(contract_text)
        print(f"Value: {fields.contract_value}")     # "500,000,000 VND"
        print(f"Bên A: {fields.party_a}")            # "Công ty ABC"
        print(f"VAT: {fields.vat_rate}")             # "10%"
        print(f"Penalty: {fields.penalty_rate}")     # "5% giá trị hợp đồng"
    """
    return ContractFieldExtractor().extract(text)
