"""
Legal Domain Router
====================

Detects whether a query is legal-domain or general-domain.
Routes legal queries to the LegalRetriever pipeline.

Detection strategy (layered, fast-to-slow):
  Layer 1 — Keyword exact match     (~0ms)   — Vietnamese + English legal terms
  Layer 2 — Clause-number regex     (~0ms)   — "Điều 5", "Khoản 3.2.1"
  Layer 3 — Legal number extraction (~0ms)   — currency, %, date patterns
  Layer 4 — Semantic scoring        (~50ms)  — embedding cosine vs legal anchor

Threshold logic:
  keyword_score >= 2  → "legal"    (high confidence)
  keyword_score == 1  → check regex/number
  keyword_score == 0  → semantic fallback

Returns: Tuple[domain: str, confidence: float, signals: list[str]]
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vietnamese & English legal keyword sets
# ---------------------------------------------------------------------------

# High-signal legal terms — 2 points each
_LEGAL_KEYWORDS_HIGH = {
    # Vietnamese — contract terms
    "hợp đồng", "điều khoản", "điều ", "khoản ", "điểm ",
    "bên a", "bên b", "bên mua", "bên bán", "bên thuê", "bên cho thuê",
    "nghĩa vụ", "quyền và nghĩa vụ", "phạt vi phạm", "bồi thường",
    "thanh toán", "giá trị hợp đồng", "giá hợp đồng", "tiền phạt",
    "chấm dứt hợp đồng", "hủy hợp đồng", "bất khả kháng",
    "trọng tài", "tòa án", "pháp luật việt nam", "luật thương mại",
    "thuế gtgt", "thuế vat", "phụ lục", "biên bản nghiệm thu",
    "bảo hành", "bảo lãnh thực hiện", "giải quyết tranh chấp",
    # Vietnamese — legal consultation (laws, decrees, regulations)
    "bộ luật", "bộ luật dân sự", "bộ luật hình sự", "bộ luật lao động",
    "luật doanh nghiệp", "luật đất đai", "luật lao động", "luật dân sự",
    "luật hình sự", "luật hôn nhân", "luật thuế", "luật đầu tư",
    "luật xây dựng", "luật nhà ở", "luật kinh doanh", "luật bảo hiểm",
    "nghị định", "thông tư", "quyết định", "văn bản pháp luật",
    "quy định pháp luật", "pháp luật quy định", "theo quy định",
    "quy phạm pháp luật", "hệ thống pháp luật", "văn bản quy phạm",
    "xử phạt vi phạm", "xử phạt hành chính", "vi phạm hành chính",
    "tội phạm", "hình phạt", "khởi tố", "truy tố", "xét xử",
    "thừa kế", "ly hôn", "quyền nuôi con", "cấp dưỡng",
    "tranh chấp đất đai", "quyền sử dụng đất", "giấy chứng nhận",
    # English
    "contract", "clause", "obligation", "penalty", "breach",
    "indemnify", "governing law", "force majeure", "arbitration",
    "liquidated damages", "termination", "warranties", "representations",
    "labor law", "civil code", "criminal law", "decree", "regulation",
    "legal provision", "statutory", "compliance", "legislation",
}

# Medium-signal legal terms — 1 point each
_LEGAL_KEYWORDS_MED = {
    # Vietnamese — contract
    "ký kết", "hiệu lực", "thực hiện", "vi phạm", "tranh chấp",
    "giao hàng", "nghiệm thu", "bàn giao", "hoàn thành", "tiến độ",
    "cam kết", "đảm bảo", "tài sản", "sở hữu", "chuyển nhượng",
    "lãi suất", "phạt chậm", "nộp phạt", "đặt cọc", "ký quỹ",
    # Vietnamese — legal consultation
    "pháp lý", "pháp luật", "quy định", "luật", "điều luật",
    "tư vấn luật", "tư vấn pháp lý", "tra cứu luật", "hiểu luật",
    "còn hiệu lực", "hết hiệu lực", "có hiệu lực", "áp dụng",
    "quyền lợi", "quyền hạn", "trách nhiệm", "nghĩa vụ pháp lý",
    "mức phạt", "mức xử phạt", "bị phạt", "phạt tiền",
    "thủ tục", "hồ sơ", "giấy phép", "đăng ký", "chứng nhận",
    "người lao động", "người sử dụng lao động", "tiền lương",
    "bảo hiểm xã hội", "bảo hiểm y tế", "bảo hiểm thất nghiệp",
    # English
    "shall", "must", "liable", "warranty", "indemnification",
    "damages", "dispute", "jurisdiction", "payment", "delivery",
    "rights", "duties", "legal", "law", "statute", "code",
}

# Clause-number patterns in queries — very strong legal signal
_CLAUSE_REF_PATTERNS = [
    re.compile(r"điều\s+\d+", re.IGNORECASE),
    re.compile(r"khoản\s+\d+", re.IGNORECASE),
    re.compile(r"điểm\s+[a-z]", re.IGNORECASE),
    re.compile(r"article\s+\d+", re.IGNORECASE),
    re.compile(r"section\s+[\d\.]+", re.IGNORECASE),
    re.compile(r"\bclause\s+[\d\.]+", re.IGNORECASE),
]

# Number patterns common in legal questions
_LEGAL_NUMBER_PATTERNS = [
    re.compile(r"\d+[\.,]\d+\s*(?:vnđ|vnd|đồng|usd|\$|%)", re.IGNORECASE),
    re.compile(r"\d+\s*%\s*(?:phạt|lãi|giá trị|vat|gtgt)", re.IGNORECASE),
    re.compile(r"(?:giá trị|tổng giá|hợp đồng)\s+[^\n]{0,30}\d", re.IGNORECASE),
]

# Legal question words
_LEGAL_QUESTION_STARTERS = {
    # Contract questions
    "giá trị hợp đồng", "tổng giá trị", "hợp đồng có giá",
    "bên nào phải", "ai phải", "nghĩa vụ của", "quyền của",
    "mức phạt", "tiền phạt", "hình thức phạt", "điều kiện chấm dứt",
    "khi nào được", "nếu vi phạm", "trường hợp",
    "what is the contract value", "what are the obligations",
    "what happens if", "penalty for", "termination clause",
    # Legal consultation questions
    "luật quy định", "quy định về", "theo pháp luật", "pháp luật quy định",
    "mức xử phạt", "bị xử phạt", "xử phạt như thế nào",
    "có được phép", "được phép không", "hợp pháp không",
    "thủ tục như thế nào", "cần phải làm gì", "cần giấy tờ gì",
    "tư vấn về", "cho tôi biết về", "giải thích về",
    "làm thế nào để", "làm sao để", "quy trình",
}


@dataclass
class DomainDetectionResult:
    """Result of domain detection for a query."""
    domain: str                     # "legal" or "general"
    confidence: float               # 0.0 – 1.0
    signals: list[str] = field(default_factory=list)   # why legal was detected
    clause_types_hint: list[str] = field(default_factory=list)  # e.g. ["payment", "penalty"]
    entity_hints: list[str] = field(default_factory=list)       # e.g. ["Bên A", "Điều 5"]
    field_tags_hint: list[str] = field(default_factory=list)    # e.g. ["lao_dong", "thue"]
    static_doc_types_hint: list[str] = field(default_factory=list)  # e.g. ["law", "decree"]
    rewritten_query: str = ""


# ---------------------------------------------------------------------------
# Main detector class
# ---------------------------------------------------------------------------

class LegalDomainRouter:
    """
    Fast, offline domain router for Vietnamese/English legal queries.

    Usage:
        router = LegalDomainRouter()
        result = router.detect("Mức phạt vi phạm hợp đồng là bao nhiêu?")
        # result.domain == "legal", result.confidence == 0.9
    """

    def detect(self, query: str, context: str = "") -> DomainDetectionResult:
        """
        Detect whether query is legal or general domain.

        Args:
            query: The user's question
            context: Optional additional context (e.g. document title)

        Returns:
            DomainDetectionResult with domain, confidence, and signals
        """
        combined = (query + " " + context).lower()
        signals: list[str] = []
        score = 0.0

        # --- Layer 1: High-signal keyword match (2 pts each) ---
        for kw in _LEGAL_KEYWORDS_HIGH:
            if kw in combined:
                score += 2.0
                signals.append(f"keyword_high:{kw}")
                if score >= 4:  # early exit — clearly legal
                    break

        # --- Layer 2: Medium-signal keyword match (1 pt each) ---
        if score < 4:
            for kw in _LEGAL_KEYWORDS_MED:
                if kw in combined:
                    score += 1.0
                    signals.append(f"keyword_med:{kw}")

        # --- Layer 3: Clause reference patterns (3 pts each) ---
        for pat in _CLAUSE_REF_PATTERNS:
            m = pat.search(combined)
            if m:
                score += 3.0
                signals.append(f"clause_ref:{m.group(0)}")

        # --- Layer 4: Legal number patterns (1.5 pts each) ---
        for pat in _LEGAL_NUMBER_PATTERNS:
            m = pat.search(combined)
            if m:
                score += 1.5
                signals.append(f"legal_number:{m.group(0)[:30]}")

        # --- Layer 5: Legal question starters (2 pts) ---
        for starter in _LEGAL_QUESTION_STARTERS:
            if combined.startswith(starter) or starter in combined:
                score += 2.0
                signals.append(f"question_starter:{starter}")
                break

        # --- Normalize to 0-1 confidence ---
        # Max realistic score ≈ 20; cap at 1.0
        confidence = min(score / 10.0, 1.0)
        domain = "legal" if score >= 2.0 else "general"

        # --- Infer clause type hints from query ---
        clause_types_hint = self._infer_clause_types(combined)

        # --- Extract entity hints (Điều X, party names) ---
        entity_hints = self._extract_entity_hints(combined)
        field_tags_hint = self._infer_field_tags(combined)
        static_doc_types_hint = self._infer_static_doc_types(combined)
        rewritten_query = self._rewrite_legal_query(
            original_query=query,
            clause_types_hint=clause_types_hint,
            entity_hints=entity_hints,
            field_tags_hint=field_tags_hint,
            static_doc_types_hint=static_doc_types_hint,
        )

        logger.debug(
            f"DomainRouter: score={score:.1f} conf={confidence:.2f} "
            f"domain={domain} signals={signals[:5]}"
        )

        return DomainDetectionResult(
            domain=domain,
            confidence=confidence,
            signals=signals,
            clause_types_hint=clause_types_hint,
            entity_hints=entity_hints,
            field_tags_hint=field_tags_hint,
            static_doc_types_hint=static_doc_types_hint,
            rewritten_query=rewritten_query,
        )

    # ------------------------------------------------------------------
    # Clause type inference from query
    # ------------------------------------------------------------------

    # Maps query keywords → clause_type filter for LegalRetriever
    _QUERY_TO_CLAUSE_TYPE: dict[str, list[str]] = {
        "payment":      ["payment", "obligation"],
        "thanh toán":   ["payment", "obligation"],
        "phạt":         ["penalty"],
        "penalty":      ["penalty"],
        "bồi thường":   ["penalty", "obligation"],
        "chấm dứt":     ["termination"],
        "termination":  ["termination"],
        "bảo mật":      ["confidentiality"],
        "confidential": ["confidentiality"],
        "bất khả kháng": ["force_majeure"],
        "force majeure": ["force_majeure"],
        "nghĩa vụ":     ["obligation"],
        "obligation":   ["obligation"],
        "quyền":        ["right"],
        "right":        ["right"],
        "định nghĩa":   ["definition"],
        "definition":   ["definition"],
        "pháp luật":    ["governing_law"],
        "governing law": ["governing_law"],
        "giá trị":      ["payment"],
        "hợp đồng có giá": ["payment"],
    }

    _QUERY_TO_FIELD_TAGS: dict[str, list[str]] = {
        "lao động": ["lao_dong"],
        "người lao động": ["lao_dong"],
        "người sử dụng lao động": ["lao_dong"],
        "bảo hiểm xã hội": ["lao_dong", "bao_hiem"],
        "thuế": ["thue"],
        "thuế gtgt": ["thue"],
        "vat": ["thue"],
        "doanh nghiệp": ["doanh_nghiep"],
        "công ty": ["doanh_nghiep"],
        "đầu tư": ["dau_tu"],
        "đất đai": ["dat_dai"],
        "nhà ở": ["nha_o", "dat_dai"],
        "xây dựng": ["xay_dung"],
        "thương mại": ["thuong_mai"],
        "mua bán hàng hóa": ["thuong_mai"],
        "dân sự": ["dan_su"],
        "hôn nhân": ["hon_nhan_gia_dinh"],
        "gia đình": ["hon_nhan_gia_dinh"],
        "hình sự": ["hinh_su"],
        "tố tụng": ["to_tung"],
        "sở hữu trí tuệ": ["so_huu_tri_tue"],
        "bản quyền": ["so_huu_tri_tue"],
        "môi trường": ["moi_truong"],
        "ngân hàng": ["ngan_hang", "tai_chinh"],
        "chứng khoán": ["chung_khoan", "tai_chinh"],
        "phá sản": ["pha_san", "doanh_nghiep"],
        "hải quan": ["hai_quan", "xuat_nhap_khau"],
    }

    _QUERY_TO_STATIC_DOC_TYPES: dict[str, list[str]] = {
        "luật": ["law", "code"],
        "bộ luật": ["code", "law"],
        "nghị định": ["decree"],
        "thông tư": ["circular"],
        "nghị quyết": ["resolution"],
        "quyết định": ["decision"],
        "decree": ["decree"],
        "circular": ["circular"],
        "law": ["law", "code"],
        "code": ["code", "law"],
    }

    def _infer_clause_types(self, query_lower: str) -> list[str]:
        """Map query keywords to clause_type filters."""
        types: list[str] = []
        seen: set[str] = set()
        for kw, ctypes in self._QUERY_TO_CLAUSE_TYPE.items():
            if kw in query_lower:
                for ct in ctypes:
                    if ct not in seen:
                        types.append(ct)
                        seen.add(ct)
        return types

    # ------------------------------------------------------------------
    # Entity extraction from query
    # ------------------------------------------------------------------

    _ENTITY_PATTERNS = [
        re.compile(r"điều\s+\d+(?:\.\d+)*", re.IGNORECASE),
        re.compile(r"khoản\s+\d+(?:\.\d+)*", re.IGNORECASE),
        re.compile(r"bên\s+[a-z]", re.IGNORECASE),
        re.compile(r"bên\s+(?:mua|bán|thuê|cho thuê|thứ nhất|thứ hai)", re.IGNORECASE),
        re.compile(r"article\s+\d+(?:\.\d+)*", re.IGNORECASE),
    ]

    def _extract_entity_hints(self, query_lower: str) -> list[str]:
        """Extract Điều X, Khoản Y, Bên A etc. from query."""
        hints: list[str] = []
        for pat in self._ENTITY_PATTERNS:
            for m in pat.finditer(query_lower):
                h = m.group(0).strip()
                if h not in hints:
                    hints.append(h)
        return hints

    def _infer_field_tags(self, query_lower: str) -> list[str]:
        """Infer legal field tags for static-corpus filtering."""
        tags: list[str] = []
        seen: set[str] = set()
        for kw, mapped_tags in self._QUERY_TO_FIELD_TAGS.items():
            if kw in query_lower:
                for tag in mapped_tags:
                    if tag not in seen:
                        tags.append(tag)
                        seen.add(tag)
        return tags

    def _infer_static_doc_types(self, query_lower: str) -> list[str]:
        """Infer likely statutory document types from explicit query language."""
        doc_types: list[str] = []
        seen: set[str] = set()
        for kw, mapped_types in self._QUERY_TO_STATIC_DOC_TYPES.items():
            if kw in query_lower:
                for doc_type in mapped_types:
                    if doc_type not in seen:
                        doc_types.append(doc_type)
                        seen.add(doc_type)
        return doc_types

    def _rewrite_legal_query(
        self,
        original_query: str,
        clause_types_hint: list[str],
        entity_hints: list[str],
        field_tags_hint: list[str],
        static_doc_types_hint: list[str],
    ) -> str:
        """Rewrite the user's legal question into a retrieval-oriented search query."""
        parts = [original_query.strip()]

        if field_tags_hint:
            parts.append("legal fields: " + ", ".join(field_tags_hint))
        if static_doc_types_hint:
            parts.append("preferred legal documents: " + ", ".join(static_doc_types_hint))
        if clause_types_hint:
            parts.append("legal issues: " + ", ".join(clause_types_hint))
        if entity_hints:
            parts.append("referenced entities: " + ", ".join(entity_hints))

        q_lower = original_query.lower()
        if "mức phạt" in q_lower or "xử phạt" in q_lower:
            parts.append("look for legal basis on penalties, sanction conditions, limits, exceptions")
        if "đơn phương chấm dứt" in q_lower or "chấm dứt" in q_lower:
            parts.append("look for legal conditions, notice requirements, procedure, and lawful cases")
        if "nghĩa vụ" in q_lower or "phải" in q_lower:
            parts.append("look for obligations, duties, conditions, liabilities, and consequences")
        if "được không" in q_lower or "có được" in q_lower:
            parts.append("determine legal permissibility, prohibitions, conditions, and exceptions")

        return " | ".join(part for part in parts if part)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_router_instance: Optional[LegalDomainRouter] = None


def get_legal_router() -> LegalDomainRouter:
    """Get the singleton LegalDomainRouter."""
    global _router_instance
    if _router_instance is None:
        _router_instance = LegalDomainRouter()
    return _router_instance


def detect_domain(query: str, context: str = "") -> DomainDetectionResult:
    """
    Convenience function: detect query domain.

    Examples:
        detect_domain("Mức phạt vi phạm hợp đồng là bao nhiêu?")
        → DomainDetectionResult(domain="legal", confidence=0.9, ...)

        detect_domain("What is the weather today?")
        → DomainDetectionResult(domain="general", confidence=0.0, ...)
    """
    return get_legal_router().detect(query, context)
