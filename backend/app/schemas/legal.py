"""
Legal AI API Schemas
====================
Pydantic request / response models for the /legal/* endpoints.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class LegalQueryRequest(BaseModel):
    """Legal QA with strict grounding."""
    question: str = Field(..., min_length=3, description="Legal question to answer")
    document_ids: Optional[list[int]] = Field(
        default=None, description="Filter to specific document IDs"
    )
    clause_types: Optional[list[str]] = Field(
        default=None,
        description="Filter by clause type (e.g. ['obligation', 'penalty'])"
    )
    articles: Optional[list[str]] = Field(
        default=None, description="Filter by article (e.g. ['Article 5'])"
    )
    top_k: int = Field(default=8, ge=1, le=30, description="Top-K clauses to retrieve")
    # Phase 1 additions — legal metadata filters (used in Phase 4 routing)
    index_scope: Optional[str] = Field(
        default=None,
        description="Restrict retrieval to 'static', 'case', or None for both"
    )
    statuses: Optional[list[str]] = Field(
        default=None,
        description="Filter by legal effectiveness status (e.g. ['active', 'expired'])"
    )
    field_tags: Optional[list[str]] = Field(
        default=None,
        description="Filter by legal domain tags (e.g. ['lao_dong', 'dau_tu'])"
    )


class LegalProcessRequest(BaseModel):
    """Process a document as a legal contract."""
    document_id: int
    document_name: Optional[str] = None


class RiskAnalysisRequest(BaseModel):
    """Trigger full contract risk analysis."""
    document_id: int
    document_name: Optional[str] = ""


class IntentRouteRequest(BaseModel):
    """Route a legal consultation request to the right backend path."""
    question: str = Field(..., min_length=3)
    chat_history: list[dict] = Field(default_factory=list)


class LiveSearchRequest(BaseModel):
    """Run live legal web search over trusted domains."""
    query: str = Field(..., min_length=3)
    max_results: int = Field(default=5, ge=1, le=10)


class ValidityCheckRequest(BaseModel):
    """Check whether a legal document is still effective."""
    doc_title: str = Field(..., min_length=3)


class ConsultationRiskRequest(BaseModel):
    """Run the newer clause-level consultation risk analysis."""
    document_id: int
    document_name: Optional[str] = ""


class ClauseCompareRequest(BaseModel):
    """Compare two clauses by their IDs."""
    clause_id_a: str = Field(..., description="ID of the first clause")
    clause_id_b: str = Field(..., description="ID of the second clause")


class MissingClauseRequest(BaseModel):
    """Detect missing standard clauses in a document."""
    document_id: int


class ObligationSummaryRequest(BaseModel):
    """Summarize obligations for a party."""
    party: str = Field(..., description="Party name to summarize obligations for")
    document_id: int
    top_k: int = Field(default=30, ge=1, le=100)


# ---------------------------------------------------------------------------
# Clause response
# ---------------------------------------------------------------------------

class ClauseResponse(BaseModel):
    """A retrieved legal clause with citation."""
    clause_id: str
    reference: str            # "Contract.pdf > Article 5 > 5.2"
    text: str
    article: str
    clause: str
    clause_type: str
    score: float
    retrieval_source: str     # "vector", "bm25", "bm25+vector"
    title: str = ""
    document_type: str = ""
    issuing_authority: str = ""
    effective_date: str = ""
    status: str = ""
    index_scope: str = "case"
    canonical_citation: str = ""


class LegalSourceDocumentResponse(BaseModel):
    """Normalized legal source metadata for future static indexing."""
    document_id: int | str
    title: str
    document_type: str
    issuing_authority: str = ""
    issued_date: str = ""
    effective_date: str = ""
    expiry_date: str = ""
    status: str = ""
    field_tags: list[str] = Field(default_factory=list)
    source_url: str = ""
    document_code: str = ""
    version_label: str = ""
    index_scope: str = "static"
    is_amending_document: bool = False
    canonical_citation: str = ""


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class LegalQueryResponse(BaseModel):
    """Response to a legal QA query."""
    answer: str
    is_grounded: bool
    clauses: list[ClauseResponse]
    kg_context: str = ""
    workspace_id: int


class SmartLegalQueryResponse(LegalQueryResponse):
    domain: str = ""
    domain_confidence: float = 0.0
    clause_type_filter: list[str] | None = None
    article_filter: list[str] | None = None
    domain_signals: list[str] = Field(default_factory=list)
    field_tags_filter: list[str] | None = None
    static_doc_types_filter: list[str] | None = None
    rewritten_query: str = ""


class LegalProcessResponse(BaseModel):
    """Result of processing a legal document."""
    document_id: int
    clause_count: int
    message: str
    status: str
    source_metadata: Optional[LegalSourceDocumentResponse] = None


class ContractFieldsResponse(BaseModel):
    contract_number: str = ""
    contract_value: str = ""
    contract_value_numeric: float = 0.0
    contract_currency: str = ""
    vat_rate: str = ""
    vat_amount: str = ""
    party_a: str = ""
    party_b: str = ""
    parties: list[str] = Field(default_factory=list)
    effective_date: str = ""
    expiry_date: str = ""
    signing_date: str = ""
    payment_terms: str = ""
    payment_deadline_days: int = 0
    penalty_rate: str = ""
    late_payment_rate: str = ""
    governing_law: str = ""
    regex_extracted: list[str] = Field(default_factory=list)
    llm_extracted: list[str] = Field(default_factory=list)


class RiskItemResponse(BaseModel):
    """A single detected risk."""
    clause_id: str
    clause_reference: str
    risk_level: str           # "high" | "medium" | "low"
    risk_type: str
    description: str
    recommendation: str = ""


class RiskCountsResponse(BaseModel):
    high: int = 0
    medium: int = 0
    low: int = 0
    total: int = 0


class ReviewActionResponse(BaseModel):
    label: str
    description: str = ""
    priority: str = "medium"


class RiskAnalysisResponse(BaseModel):
    """Full contract risk analysis report."""
    document_id: int
    document_name: str
    overall_risk_level: str
    risks: list[RiskItemResponse]
    parties_identified: list[str]
    governing_law: str
    summary: str
    missing_clauses: list[str]
    risk_counts: RiskCountsResponse = Field(default_factory=RiskCountsResponse)
    top_issues: list[str] = Field(default_factory=list)
    recommended_actions: list[ReviewActionResponse] = Field(default_factory=list)


class IntentRouteResponse(BaseModel):
    intent: str
    reasoning: str
    suggested_tools: list[str]


class LiveSearchResultResponse(BaseModel):
    title: str
    url: str
    content: str = ""
    raw_content: str = ""
    domain: str = ""
    score: float = 0.0
    published_date: str = ""


class LiveSearchResponse(BaseModel):
    query: str
    results: list[LiveSearchResultResponse]


class ValidityCheckResponse(BaseModel):
    doc_title: str
    status: str
    reasoning: str
    source_url: str = ""
    source_title: str = ""
    source_domain: str = ""
    source_snippet: str = ""
    matched_keywords: list[str] = Field(default_factory=list)


class LegalBasisCitationResponse(BaseModel):
    citation: str
    excerpt: str
    source_type: str
    source_url: str = ""


class LegalAskRequest(BaseModel):
    """Intent-first ask request for the new LexGuardian ask flow."""
    question: str = Field(..., min_length=3)
    chat_history: list[dict] = Field(default_factory=list)
    document_ids: list[int] = Field(default_factory=list)
    top_k: int = Field(default=8, ge=1, le=30)


class AskEvidenceOverviewResponse(BaseModel):
    total_sources: int = 0
    statute_sources: int = 0
    case_sources: int = 0
    kg_sources: int = 0


class AskNextActionResponse(BaseModel):
    label: str
    description: str = ""


class LegalAskResponse(BaseModel):
    mode: str
    intent: str
    answer: str
    is_grounded: bool = False
    reasoning: str = ""
    suggested_tools: list[str] = Field(default_factory=list)
    evidence_overview: AskEvidenceOverviewResponse = Field(default_factory=AskEvidenceOverviewResponse)
    clauses: list[ClauseResponse] = Field(default_factory=list)
    live_results: list[LiveSearchResultResponse] = Field(default_factory=list)
    next_actions: list[AskNextActionResponse] = Field(default_factory=list)


class ConsultationFindingResponse(BaseModel):
    clause_type: str
    clause_reference: str
    clause_text: str
    status: str
    legal_basis: list[LegalBasisCitationResponse]
    revision_advice: str = ""
    reasoning: str = ""
    comparison_question: str = ""


class ConsultationRiskResponse(BaseModel):
    document_name: str
    document_type: str
    findings: list[ConsultationFindingResponse]
    summary: str
    finding_counts: RiskCountsResponse = Field(default_factory=RiskCountsResponse)
    top_issues: list[str] = Field(default_factory=list)
    recommended_actions: list[ReviewActionResponse] = Field(default_factory=list)


class ClauseCompareResponse(BaseModel):
    """Result of comparing two clauses."""
    clause_a_id: str
    clause_b_id: str
    clause_a_text: str
    clause_b_text: str
    similarities: list[str]
    differences: list[str]
    conflicts: list[str]
    recommendation: str
    analysis: str


class MissingClauseResponse(BaseModel):
    """A detected missing standard clause."""
    clause_type: str
    description: str
    risk_if_missing: str
    suggested_text: str = ""


class MissingClausesResponse(BaseModel):
    """List of missing clauses for a document."""
    document_id: int
    missing_clauses: list[MissingClauseResponse]
    total: int


class ObligationItemResponse(BaseModel):
    clause_id: str
    clause_reference: str = ""
    obligation_text: str = ""
    deadline: str = ""


class RightItemResponse(BaseModel):
    clause_id: str
    clause_reference: str = ""
    right_text: str = ""


class PenaltyItemResponse(BaseModel):
    clause_id: str
    clause_reference: str = ""
    penalty_text: str = ""


class ObligationSummaryResponse(BaseModel):
    """Structured obligation summary for a party."""
    party: str
    document_id: int
    obligations: list[ObligationItemResponse] = Field(default_factory=list)
    rights: list[RightItemResponse] = Field(default_factory=list)
    penalties: list[PenaltyItemResponse] = Field(default_factory=list)
    summary: str
