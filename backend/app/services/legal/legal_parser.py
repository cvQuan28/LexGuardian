"""
Legal Document Parser
======================

Extends Docling-based parsing with legal structure detection:
  - Detects Articles, Clauses, and Points from Vietnamese and English contracts
  - Preserves Document → Article → Clause → Point hierarchy
  - Returns structured LegalClause list instead of generic chunks

Numbering patterns supported:
  Vietnamese: Điều 1, Khoản 1, Điểm a
  English:    Article 1, Section 1, Clause 1.2, Point 1.2.1
  Generic:    1., 1.1, 1.1.1, (a), (i)
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.services.models.legal_document import (
    LegalClause,
    LegalDocumentMetadata,
    LegalParseResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compiled regex patterns for legal numbering detection
# ---------------------------------------------------------------------------

# Vietnamese and English article-level markers (highest hierarchy)
_ARTICLE_PATTERNS = [
    re.compile(r"^(Điều\s+\d+[\.\s].*)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^(Article\s+\d+[\.\s:]*.*)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^(ARTICLE\s+[IVXLCDM]+[\.\s:]*.*)", re.MULTILINE),
    re.compile(r"^(Chapter\s+\d+[\.\s:]*.*)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^(Chương\s+\d+[\.\s:]*.*)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^(\d+\.\s+[A-ZĐẮẰẶẨẤẦẬ].+)", re.MULTILINE),     # "1. DEFINITIONS"
]

# Clause-level markers (medium hierarchy)
_CLAUSE_PATTERNS = [
    re.compile(r"^(Khoản\s+\d+[\.\s:]*.*)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^(Section\s+\d+[\.\d]*[\.\s:]*.*)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^(Clause\s+[\d\.]+[\.\s:]*.*)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^(\d+\.\d+[\.\s:]+\S.*)", re.MULTILINE),    # "1.2 Obligations..."
]

# Point-level markers (lowest hierarchy)
_POINT_PATTERNS = [
    re.compile(r"^(Điểm\s+[a-zA-Z][\.\s:]*.*)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^(\([a-z]\)\s+.*)", re.MULTILINE),           # "(a) The Seller..."
    re.compile(r"^(\([ivxlcdm]+\)\s+.*)", re.MULTILINE),      # "(i) ..."
    re.compile(r"^(\d+\.\d+\.\d+[\.\s:]+\S.*)", re.MULTILINE), # "1.2.3 ..."
]

# Party extraction patterns
_PARTY_PATTERNS = [
    re.compile(r'"([^"]{2,60})"(?:\s*\((?:the\s+)?"([^"]{2,40})"\))?', re.IGNORECASE),
    re.compile(r'(?:bên\s+\w+|party\s+\w+)\s*[:\-]\s*([^\n,;]{5,80})', re.IGNORECASE),
    # Match "called the 'PartyName'" with either straight or curly single quotes
    re.compile(r"(?:called\s+the\s+)['\u2018]([^'\u2019]+)['\u2019]", re.IGNORECASE),
]

# Document type detection
_DOC_TYPE_PATTERNS = {
    "contract": re.compile(r'\b(contract|hợp đồng)\b', re.IGNORECASE),
    "agreement": re.compile(r'\b(agreement|thỏa thuận)\b', re.IGNORECASE),
    "amendment": re.compile(r'\b(amendment|phụ lục|addendum)\b', re.IGNORECASE),
    "nda": re.compile(r'\b(non.disclosure|bảo mật|NDA)\b', re.IGNORECASE),
    "mou": re.compile(r'\b(memorandum|biên bản ghi nhớ|MOU)\b', re.IGNORECASE),
}

# Clause type classification keywords
_CLAUSE_TYPE_KEYWORDS = {
    "obligation": [
        "shall", "must", "phải", "có nghĩa vụ", "obligated", "required to",
        "agrees to", "undertakes to", "sẽ thực hiện",
    ],
    "right": [
        "may", "có quyền", "entitled to", "has the right", "is permitted",
        "can", "được phép", "is allowed",
    ],
    "penalty": [
        "penalty", "phạt", "liquidated damages", "damages", "bồi thường",
        "indemnify", "liability", "breach", "vi phạm", "sanction",
    ],
    "definition": [
        "means", "defined as", "refers to", "nghĩa là", "được định nghĩa",
        '"', "hereinafter", "definition",
    ],
    "termination": [
        "termination", "chấm dứt", "expire", "hết hạn", "cancel", "hủy bỏ",
        "terminate",
    ],
    "governing_law": [
        "governing law", "pháp luật", "jurisdiction", "thẩm quyền", "dispute",
        "tranh chấp", "arbitration", "trọng tài",
    ],
    "force_majeure": [
        "force majeure", "bất khả kháng", "acts of god", "beyond control",
        "unforeseeable",
    ],
    "payment": [
        "payment", "thanh toán", "invoice", "hóa đơn", "fee", "phí",
        "price", "giá", "consideration",
    ],
    "confidentiality": [
        "confidential", "bí mật", "non-disclosure", "proprietary",
        "secret",
    ],
}

MIN_CLAUSE_LENGTH = 50   # chars — ignore noise lines shorter than this


class LegalDocumentParser:
    """
    Parses legal documents and extracts clause-level structure.

    Priority:
      1. Uses Docling markdown output as the raw text
      2. Applies regex-based hierarchical clause detection
      3. Falls back to paragraph-level chunking for unstructured text

    Returns LegalParseResult with a flat list of LegalClause objects,
    each carrying article/clause/point hierarchy metadata.
    """

    def __init__(self, workspace_id: int, output_dir: Optional[Path] = None):
        self.workspace_id = workspace_id
        self.output_dir = output_dir or (
            settings.BASE_DIR / "data" / "docling" / f"kb_{workspace_id}"
        )
        self._docling_converter = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(
        self,
        file_path: str | Path,
        document_id: int,
        original_filename: str,
    ) -> LegalParseResult:
        """
        Parse a legal document and return structured clauses.

        Args:
            file_path: Path to the document
            document_id: Database document ID
            original_filename: Filename for citations

        Returns:
            LegalParseResult with a list of LegalClause objects
        """
        path = Path(file_path)
        start = time.time()

        # Step 1: Get raw text and page count from Docling
        markdown, page_count = self._extract_markdown(path, document_id)

        # Step 2: Detect document metadata
        document_type = self._detect_document_type(markdown)
        parties = self._extract_parties(markdown)
        governing_law = self._extract_governing_law(markdown)
        doc_metadata = LegalDocumentMetadata(
            document_id=document_id,
            title=original_filename,
            document_type=document_type,
            index_scope="case",
            canonical_citation=original_filename,
        )

        # Step 3: Extract clauses with hierarchy
        clauses = self._extract_clauses(
            markdown=markdown,
            document_id=document_id,
            source_file=original_filename,
        )
        for clause in clauses:
            clause.title = original_filename
            clause.document_type = document_type
            clause.index_scope = "case"
            clause.canonical_citation = original_filename

        elapsed = int((time.time() - start) * 1000)
        logger.info(
            f"LegalParser: doc={document_id} ({original_filename}) "
            f"clauses={len(clauses)} pages={page_count} in {elapsed}ms"
        )

        return LegalParseResult(
            document_id=document_id,
            original_filename=original_filename,
            clauses=clauses,
            markdown=markdown,
            page_count=page_count,
            parties=parties,
            governing_law=governing_law,
            document_type=document_type,
            metadata=doc_metadata,
        )

    # ------------------------------------------------------------------
    # Step 1: Text extraction via Docling
    # ------------------------------------------------------------------

    def _extract_markdown(self, path: Path, document_id: int) -> tuple[str, int]:
        """Extract raw markdown and page count using Docling."""
        suffix = path.suffix.lower()
        docling_exts = {".pdf", ".docx", ".pptx", ".html"}

        if suffix in docling_exts:
            return self._extract_with_docling(path)
        elif suffix in {".txt", ".md"}:
            return self._extract_plain_text(path)
        else:
            raise ValueError(f"Unsupported format for legal parsing: {suffix}")

    def _extract_with_docling(self, path: Path) -> tuple[str, int]:
        """Use Docling to convert document to clean markdown."""
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions

        if self._docling_converter is None:
            pipeline_options = PdfPipelineOptions()
            pipeline_options.generate_picture_images = False  # no images for legal
            pipeline_options.do_formula_enrichment = False
            self._docling_converter = DocumentConverter(
                format_options={
                    "pdf": PdfFormatOption(pipeline_options=pipeline_options),
                }
            )

        conv_result = self._docling_converter.convert(str(path))
        doc = conv_result.document

        try:
            markdown = doc.export_to_markdown(page_break_placeholder="\n\n---PAGE---\n\n")
        except TypeError:
            markdown = doc.export_to_markdown()

        page_count = len(doc.pages) if hasattr(doc, "pages") and doc.pages else 0
        return markdown, page_count

    def _extract_plain_text(self, path: Path) -> tuple[str, int]:
        """Plain text fallback."""
        text = path.read_text(encoding="utf-8", errors="replace")
        return text, 0

    # ------------------------------------------------------------------
    # Step 2: Document metadata
    # ------------------------------------------------------------------

    def _detect_document_type(self, text: str) -> str:
        first_500 = text[:500].lower()
        for dtype, pattern in _DOC_TYPE_PATTERNS.items():
            if pattern.search(first_500):
                return dtype
        return "contract"

    def _extract_parties(self, text: str) -> list[str]:
        """Extract party names from the first 2000 characters."""
        parties: list[str] = []
        header = text[:2000]
        for pat in _PARTY_PATTERNS:
            for m in pat.finditer(header):
                name = m.group(1).strip()
                if len(name) > 3 and name not in parties:
                    parties.append(name)
        return parties[:10]  # cap at 10

    def _extract_governing_law(self, text: str) -> str:
        """Extract governing law jurisdiction."""
        pattern = re.compile(
            r'(?:governing law|pháp luật\s+(?:của\s+)?|luật\s+(?:áp dụng\s+)?(?:là\s+)?)'
            r'([^\n,;\.]{5,80})',
            re.IGNORECASE,
        )
        m = pattern.search(text)
        return m.group(1).strip() if m else ""

    # ------------------------------------------------------------------
    # Step 3: Clause extraction
    # ------------------------------------------------------------------

    def _extract_clauses(
        self,
        markdown: str,
        document_id: int,
        source_file: str,
    ) -> list[LegalClause]:
        """
        Main clause extraction logic.

        Strategy:
          1. Split text into lines
          2. Walk lines, detecting article/clause/point headers
          3. Accumulate text under each header
          4. On next header, flush accumulated text as a LegalClause
        """
        lines = markdown.split("\n")
        clauses: list[LegalClause] = []

        current_article = ""
        current_clause = ""
        current_point = ""
        current_page = 1
        current_lines: list[str] = []
        chunk_index = 0

        def flush_clause():
            nonlocal chunk_index
            text = "\n".join(current_lines).strip()
            if len(text) < MIN_CLAUSE_LENGTH:
                return

            clause_id = str(uuid.uuid4())[:12]
            clause_type = self._classify_clause_type(text)
            parties = self._extract_parties_from_text(text)
            # Build breadcrumb section path
            section_path = " > ".join(filter(None, [current_article, current_clause, current_point]))

            clauses.append(LegalClause(
                clause_id=clause_id,
                document_id=document_id,
                source_file=source_file,
                text=text,
                article=current_article,
                clause=current_clause,
                point=current_point,
                page=current_page,
                clause_type=clause_type,
                parties_mentioned=parties,
                chunk_index=chunk_index,
                section_path=section_path,
                chunk_kind="clause",
            ))
            chunk_index += 1

        for line in lines:
            stripped = line.strip()

            # Page marker from Docling
            if "---PAGE---" in stripped:
                current_page += 1
                continue

            # Detect article
            article_match = self._match_article(stripped)
            if article_match:
                flush_clause()
                current_article = article_match
                current_clause = ""
                current_point = ""
                current_lines = [line]
                continue

            # Detect clause
            clause_match = self._match_clause(stripped)
            if clause_match:
                flush_clause()
                current_clause = clause_match
                current_point = ""
                current_lines = [line]
                continue

            # Detect point
            point_match = self._match_point(stripped)
            if point_match:
                flush_clause()
                current_point = point_match
                current_lines = [line]
                continue

            # Normal content line
            current_lines.append(line)

        # Flush last clause
        flush_clause()

        # If nothing was detected (unstructured document), fallback to paragraphs
        if not clauses:
            logger.warning(
                f"No legal structure detected in {source_file}. "
                f"Falling back to paragraph chunking."
            )
            clauses = self._paragraph_fallback(markdown, document_id, source_file)

        return clauses

    # ------------------------------------------------------------------
    # Pattern matchers
    # ------------------------------------------------------------------

    def _match_article(self, line: str) -> str:
        """Return article label if line is an article header, else empty."""
        for pat in _ARTICLE_PATTERNS:
            m = pat.match(line)
            if m:
                return m.group(1)[:80].strip()
        return ""

    def _match_clause(self, line: str) -> str:
        """Return clause label if line is a clause header, else empty."""
        for pat in _CLAUSE_PATTERNS:
            m = pat.match(line)
            if m:
                return m.group(1)[:80].strip()
        return ""

    def _match_point(self, line: str) -> str:
        """Return point label if line is a point header, else empty."""
        for pat in _POINT_PATTERNS:
            m = pat.match(line)
            if m:
                return m.group(1)[:80].strip()
        return ""

    # ------------------------------------------------------------------
    # Clause enrichment
    # ------------------------------------------------------------------

    def _classify_clause_type(self, text: str) -> str:
        """
        Classify a clause based on keyword matching.
        Returns the type with the most keyword hits.
        """
        text_lower = text.lower()
        scores: dict[str, int] = {}
        for ctype, keywords in _CLAUSE_TYPE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw.lower() in text_lower)
            if score > 0:
                scores[ctype] = score

        if not scores:
            return "general"
        return max(scores, key=lambda k: scores[k])

    def _extract_parties_from_text(self, text: str) -> list[str]:
        """Extract party names from a single clause."""
        parties: list[str] = []
        for pat in _PARTY_PATTERNS:
            for m in pat.finditer(text[:500]):
                name = m.group(1).strip()
                if 3 < len(name) < 80 and name not in parties:
                    parties.append(name)
        return parties[:5]

    # ------------------------------------------------------------------
    # Fallback: paragraph chunking
    # ------------------------------------------------------------------

    def _paragraph_fallback(
        self,
        text: str,
        document_id: int,
        source_file: str,
    ) -> list[LegalClause]:
        """
        Fallback for unstructured text: split by double newline into paragraphs.
        Each paragraph becomes a 'general' clause.
        """
        paragraphs = re.split(r'\n{2,}', text)
        clauses = []
        for i, para in enumerate(paragraphs):
            para = para.strip()
            if len(para) < MIN_CLAUSE_LENGTH:
                continue
            clause_id = str(uuid.uuid4())[:12]
            clauses.append(LegalClause(
                clause_id=clause_id,
                document_id=document_id,
                source_file=source_file,
                text=para,
                article="",
                clause="",
                point="",
                page=0,
                clause_type=self._classify_clause_type(para),
                parties_mentioned=self._extract_parties_from_text(para),
                chunk_index=i,
                section_path="",
                chunk_kind="clause",
            ))
        return clauses
