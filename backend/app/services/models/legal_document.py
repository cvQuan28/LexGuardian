"""
Legal Document Data Models
===========================

Dataclasses for the Legal AI pipeline:
  - LegalClause: a discrete clause with hierarchy metadata
  - LegalParseResult: full structured output from LegalDocumentParser
  - LegalRetrievalResult: retrieval result enriched with legal context
  - RiskItem: a detected risk from a clause
  - MissingClause: a detected missing standard clause
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Phase 4 — Retrieval routing mode
# ---------------------------------------------------------------------------

class RetrievalMode(str, Enum):
    """Routing mode that controls which index pools are queried.

    Per Spec 02 / 07:
      static_only    — statutory lookup only (no case docs)
      case_only      — workspace-scoped case docs only
      mixed          — both; required for contract risk analysis
    """
    STATIC_ONLY = "static_only"
    CASE_ONLY = "case_only"
    MIXED = "mixed"


# ---------------------------------------------------------------------------
# Clause hierarchy
# ---------------------------------------------------------------------------

@dataclass
class LegalClause:
    """
    A single legal clause extracted from a document.

    Hierarchy: Document → Article → Clause → Point

    Example:
        clause_id   = "art5_cl2_pt1"
        article     = "Article 5"
        clause      = "5.2"
        point       = "5.2.1"
        text        = "The Seller shall deliver goods within 30 days..."
        page        = 4
    """
    clause_id: str
    document_id: int
    source_file: str
    text: str
    article: str = ""          # e.g. "Article 5", "Điều 5"
    clause: str = ""           # e.g. "5.2", "Khoản 2"
    point: str = ""            # e.g. "5.2.1", "Điểm a"
    page: int = 0
    clause_type: str = ""      # e.g. "obligation", "right", "penalty", "definition"
    parties_mentioned: list[str] = field(default_factory=list)
    chunk_index: int = 0
    title: str = ""
    document_type: str = ""
    issuing_authority: str = ""
    issued_date: str = ""
    effective_date: str = ""
    expiry_date: str = ""
    status: str = ""
    field_tags: list[str] = field(default_factory=list)
    summary_text: str = ""
    index_scope: str = "case"   # "case" | "static"
    canonical_citation: str = ""
    # Phase 1 additions — per spec 03 chunk metadata
    section_path: str = ""     # breadcrumb: "Chapter I > Article 5 > Clause 2"
    chunk_kind: str = "clause" # "clause" | "summary" | "header"

    def format_reference(self) -> str:
        """Return a human-readable reference string."""
        parts = [self.canonical_citation or self.title or self.source_file]
        if self.article:
            parts.append(self.article)
        if self.clause:
            parts.append(self.clause)
        if self.point:
            parts.append(self.point)
        if self.page > 0:
            parts.append(f"p.{self.page}")
        return " > ".join(parts)

    def to_chunk_text(self) -> str:
        """Return text representation for embedding."""
        lines: list[str] = []
        if self.title:
            lines.append(f"[Title] {self.title}")
        if self.document_type:
            lines.append(f"[Document Type] {self.document_type}")
        if self.issuing_authority:
            lines.append(f"[Authority] {self.issuing_authority}")
        if self.status:
            lines.append(f"[Status] {self.status}")
        if self.effective_date:
            lines.append(f"[Effective Date] {self.effective_date}")
        if self.field_tags:
            lines.append(f"[Field Tags] {', '.join(self.field_tags)}")

        header = " ".join(filter(None, [self.article, self.clause, self.point]))
        if header:
            lines.append(f"[Reference] {header}")
        if self.section_path:
            lines.append(f"[Section Path] {self.section_path}")

        if self.summary_text:
            lines.append("")
            lines.append("[Summary]")
            lines.append(self.summary_text)

        lines.append("")
        lines.append("[Raw Text]")
        lines.append(self.text)
        return "\n".join(lines).strip()

    def to_metadata(self) -> dict:
        """Return ChromaDB-compatible metadata dict (no nested types)."""
        return {
            "clause_id": self.clause_id,
            "document_id": self.document_id,
            "source": self.source_file,
            "article": self.article,
            "clause": self.clause,
            "point": self.point,
            "page_no": self.page,
            "clause_type": self.clause_type,
            "parties_mentioned": "|".join(self.parties_mentioned),
            "chunk_index": self.chunk_index,
            "title": self.title,
            "document_type": self.document_type,
            "issuing_authority": self.issuing_authority,
            "issued_date": self.issued_date,
            "effective_date": self.effective_date,
            "expiry_date": self.expiry_date,
            "status": self.status,
            "field_tags": "|".join(self.field_tags),
            "summary_text": self.summary_text,
            "index_scope": self.index_scope,
            "canonical_citation": self.canonical_citation,
            # Phase 1 additions
            "section_path": self.section_path,
            "chunk_kind": self.chunk_kind,
            # For compatibility with the existing EnrichedChunk-based retriever
            "heading_path": self.section_path or " > ".join(filter(None, [self.article, self.clause, self.point])),
            "has_table": False,
            "has_code": False,
            "image_ids": "",
            "table_ids": "",
            "image_urls": "",
        }


@dataclass
class LegalDocumentMetadata:
    """Document-level metadata for static laws and case documents."""
    document_id: int | str
    title: str
    document_type: str
    issuing_authority: str = ""
    issued_date: str = ""
    effective_date: str = ""
    expiry_date: str = ""
    status: str = ""
    field_tags: list[str] = field(default_factory=list)
    source_url: str = ""
    document_code: str = ""
    version_label: str = ""
    index_scope: str = "static"
    is_amending_document: bool = False
    canonical_citation: str = ""
    replaces_documents: list[str] = field(default_factory=list)
    guides_documents: list[str] = field(default_factory=list)


@dataclass
class LegalParseResult:
    """Result of parsing a legal document with LegalDocumentParser."""
    document_id: int
    original_filename: str
    clauses: list[LegalClause]
    markdown: str = ""
    page_count: int = 0
    parties: list[str] = field(default_factory=list)
    governing_law: str = ""
    document_type: str = ""   # "contract", "agreement", "amendment", etc.
    metadata: Optional[LegalDocumentMetadata] = None


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

@dataclass
class LegalCitedClause:
    """A retrieved clause with its citation reference and weighted score."""
    clause: LegalClause
    score: float = 0.0
    retrieval_source: str = "vector"   # "vector", "bm25", "kg", "static_vector"

    def weighted_score(
        self,
        w_vector: float = 0.5,
        w_bm25: float = 0.3,
        w_reranker: float = 0.2,
    ) -> float:
        """Compute weighted final score per Spec 07 formula.

        Bonuses applied automatically from clause metadata:
          +0.15  active status
          -0.30  expired status
          +0.05  law > decree > circular priority
          (field/authority bonuses are applied upstream in the retriever)
        """
        base = self.score
        bonus = 0.0

        # Active status bonus / expired penalty
        status = (self.clause.status or "").lower()
        if status == "active":
            bonus += 0.15
        elif status == "expired":
            bonus -= 0.30
        elif status == "superseded":
            bonus -= 0.20

        # Document-type priority bonus (Laws > Decrees > Circulars)
        dtype = (self.clause.document_type or "").lower()
        if dtype in {"law", "code"}:
            bonus += 0.05
        elif dtype == "decree":
            bonus += 0.02

        return max(0.0, base + bonus)


@dataclass
class LegalRetrievalResult:
    """Result of legal hybrid retrieval."""
    query: str
    clauses: list[LegalCitedClause]
    static_clauses: list[LegalCitedClause] = field(default_factory=list)  # Phase 4
    kg_context: str = ""
    mode: str = "hybrid"  # mirrors RetrievalMode value

    def format_context(self) -> str:
        """Assemble structured context string for LLM."""
        parts = []
        if self.kg_context:
            parts.append("## Knowledge Graph — Legal Entities & Relations")
            parts.append(self.kg_context)
            parts.append("")

        if self.clauses:
            parts.append("## Retrieved Clauses")
            for i, cited in enumerate(self.clauses):
                c = cited.clause
                ref = c.format_reference()
                parts.append(f"### [{i + 1}] {ref} (clause_id: {c.clause_id})")
                meta_bits = []
                if c.document_type:
                    meta_bits.append(f"type={c.document_type}")
                if c.issuing_authority:
                    meta_bits.append(f"authority={c.issuing_authority}")
                if c.status:
                    meta_bits.append(f"status={c.status}")
                if c.effective_date:
                    meta_bits.append(f"effective_date={c.effective_date}")
                if c.field_tags:
                    meta_bits.append(f"field_tags={', '.join(c.field_tags)}")
                if meta_bits:
                    parts.append("Metadata: " + " | ".join(meta_bits))
                parts.append(c.text)
                parts.append("")

        if not parts:
            return "No relevant clauses found."

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Phase 4 — Claim-level grounding evidence (Spec 07)
# ---------------------------------------------------------------------------

@dataclass
class LegalFindingEvidence:
    """Per-finding evidence structure required by Spec 07 grounding policy."""
    case_clause_id: str                  # id of the contract clause being assessed
    statutory_clause_ids: list[str]      # supporting statutory clause ids
    statutory_statuses: list[str]        # parallel list: status of each statutory clause
    support_level: str                   # "strong" | "partial" | "inferred" | "none"
    audit_passed: bool                   # True only when active statutory support exists
    fallback_used: bool = False          # True when only inactive statutes were available
    fallback_note: str = ""              # explanation if fallback_used


# ---------------------------------------------------------------------------
# Analysis results
# ---------------------------------------------------------------------------


@dataclass
class RiskItem:
    """A detected risk in a contract."""
    clause_id: str
    clause_reference: str   # human-readable: "Article 5 > 5.2"
    risk_level: str         # "high", "medium", "low"
    risk_type: str          # "missing_penalty", "ambiguous_obligation", "unlimited_liability", etc.
    description: str        # plain-language explanation
    recommendation: str = ""


@dataclass
class ContractRiskReport:
    """Output of analyze_contract_risk()."""
    document_id: int
    document_name: str
    overall_risk_level: str          # "high", "medium", "low"
    risks: list[RiskItem]
    parties_identified: list[str]
    governing_law: str
    summary: str                     # LLM-generated summary
    missing_clauses: list[str] = field(default_factory=list)


@dataclass
class ClauseComparison:
    """Output of compare_clauses()."""
    clause_a_id: str
    clause_b_id: str
    clause_a_text: str
    clause_b_text: str
    similarities: list[str]
    differences: list[str]
    conflicts: list[str]
    recommendation: str
    analysis: str                    # LLM full analysis


@dataclass
class MissingClause:
    """A standard clause that is missing from the contract."""
    clause_type: str          # "termination", "force_majeure", "governing_law", etc.
    description: str          # what this clause normally covers
    risk_if_missing: str      # consequence of missing it
    suggested_text: str = ""  # optional suggested placeholder text


@dataclass
class ObligationSummary:
    """Output of summarize_obligations()."""
    party: str
    document_id: int
    obligations: list[dict]   # [{clause_id, clause_ref, obligation_text, deadline}]
    rights: list[dict]        # [{clause_id, clause_ref, right_text}]
    penalties: list[dict]     # [{clause_id, clause_ref, penalty_text}]
    summary: str
