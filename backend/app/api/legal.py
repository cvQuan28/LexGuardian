"""
Legal AI API Endpoints
=======================

All endpoints are scoped to a workspace_id and require the workspace to exist.

Routes:
  POST /legal/process/{workspace_id}           — Process a document as legal contract
  POST /legal/route-intent/{workspace_id}      — Intent routing for legal consultation
  POST /legal/live-search/{workspace_id}       — Trusted live legal web search
  POST /legal/check-validity/{workspace_id}    — Check whether a legal document is still effective
  POST /legal/query/{workspace_id}             — Legal QA with strict grounding
  POST /legal/analyze-risk/{workspace_id}      — Full contract risk analysis
  POST /legal/consult-risk/{workspace_id}      — Clause-level consultation risk report
  POST /legal/compare-clauses/{workspace_id}   — Compare two clauses
  POST /legal/missing-clauses/{workspace_id}   — Detect missing standard clauses
  POST /legal/obligations/{workspace_id}       — Summarize obligations for a party
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.deps import get_current_user, get_db, get_workspace_for_user
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.models.knowledge_base import KnowledgeBase
from app.models.document import Document, DocumentStatus
from app.models.legal_source import LegalSourceDocument
from app.schemas.legal import (
    LegalQueryRequest,
    LegalQueryResponse,
    SmartLegalQueryResponse,
    LegalProcessRequest,
    LegalProcessResponse,
    ContractFieldsResponse,
    IntentRouteRequest,
    IntentRouteResponse,
    LegalAskRequest,
    LegalAskResponse,
    AskEvidenceOverviewResponse,
    AskNextActionResponse,
    LiveSearchRequest,
    LiveSearchResponse,
    LiveSearchResultResponse,
    ValidityCheckRequest,
    ValidityCheckResponse,
    RiskAnalysisRequest,
    RiskAnalysisResponse,
    RiskItemResponse,
    RiskCountsResponse,
    ReviewActionResponse,
    ConsultationRiskRequest,
    ConsultationRiskResponse,
    ConsultationFindingResponse,
    LegalBasisCitationResponse,
    ClauseCompareRequest,
    ClauseCompareResponse,
    MissingClauseRequest,
    MissingClausesResponse,
    MissingClauseResponse,
    ObligationSummaryRequest,
    ObligationSummaryResponse,
    ObligationItemResponse,
    RightItemResponse,
    PenaltyItemResponse,
    ClauseResponse,
)
from app.services.legal.legal_rag_service import LegalRAGService
from app.models.user import User
from app.services.legal.legal_static_index_service import LegalStaticIndexService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/legal", tags=["legal"])
internal_router = APIRouter(prefix="/internal", tags=["legal-internal"])

UPLOAD_DIR = "uploads"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _verify_workspace(workspace_id: int, db: AsyncSession, current_user: User) -> KnowledgeBase:
    """Verify knowledge base exists."""
    return await get_workspace_for_user(workspace_id, db, current_user)


def _get_legal_service(db: AsyncSession, workspace_id: int) -> LegalRAGService:
    """Instantiate the Legal RAG service."""
    return LegalRAGService(db=db, workspace_id=workspace_id)


def _ensure_legacy_internal_routes_enabled() -> None:
    if not settings.LEGAL_LEGACY_INTERNAL_ROUTES_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This legacy internal route is disabled. Use /legal/internal/* instead.",
        )


def _normalize_risk_level(level: str) -> str:
    lowered = (level or "").strip().lower()
    if lowered in {"critical", "high", "vi phạm", "rủi ro cao"}:
        return "high"
    if lowered in {"medium", "trung bình"}:
        return "medium"
    return "low"


def _build_risk_counts(levels: list[str]) -> RiskCountsResponse:
    counts = {"high": 0, "medium": 0, "low": 0}
    for level in levels:
        counts[_normalize_risk_level(level)] += 1
    return RiskCountsResponse(
        high=counts["high"],
        medium=counts["medium"],
        low=counts["low"],
        total=len(levels),
    )


def _build_risk_actions(*, has_missing_clauses: bool, highest_level: str) -> list[ReviewActionResponse]:
    actions: list[ReviewActionResponse] = []
    if highest_level == "high":
        actions.append(
            ReviewActionResponse(
                label="Review high-risk clauses first",
                description="Prioritize clauses marked high risk before sharing or signing the contract.",
                priority="high",
            )
        )
    if has_missing_clauses:
        actions.append(
            ReviewActionResponse(
                label="Add missing standard clauses",
                description="Review the missing-clause list and decide which protections should be inserted.",
                priority="medium",
            )
        )
    actions.append(
        ReviewActionResponse(
            label="Export legal memo",
            description="Turn the analysis into a shareable legal summary for stakeholders.",
            priority="low",
        )
    )
    return actions


def _build_evidence_overview_from_clauses(clauses: list[dict]) -> AskEvidenceOverviewResponse:
    total_sources = len(clauses)
    statute_sources = sum(1 for item in clauses if (
        item.get("index_scope") or "").lower() == "static")
    kg_sources = sum(1 for item in clauses if (
        item.get("retrieval_source") or "").lower() == "kg")
    case_sources = max(total_sources - statute_sources, 0)
    return AskEvidenceOverviewResponse(
        total_sources=total_sources,
        statute_sources=statute_sources,
        case_sources=case_sources,
        kg_sources=kg_sources,
    )


def _build_ask_next_actions(intent: str, *, has_documents: bool) -> list[AskNextActionResponse]:
    if intent == "CONTRACT_RISK" and not has_documents:
        return [
            AskNextActionResponse(
                label="Select a contract document",
                description="Choose an uploaded contract so the review flow can generate grounded findings.",
            )
        ]
    if intent == "LIVE_SEARCH":
        return [
            AskNextActionResponse(
                label="Open trusted sources",
                description="Review the latest trusted-domain sources linked in the result list.",
            )
        ]
    return [
        AskNextActionResponse(
            label="Open evidence",
            description="Review the cited clauses and verify the answer against source text.",
        )
    ]


def _to_clause_responses(items: list[dict]) -> list[ClauseResponse]:
    return [
        ClauseResponse(
            clause_id=c["clause_id"],
            reference=c["reference"],
            text=c["text"],
            article=c["article"],
            clause=c["clause"],
            clause_type=c["clause_type"],
            score=c["score"],
            retrieval_source=c["retrieval_source"],
            title=c.get("title", ""),
            document_type=c.get("document_type", ""),
            issuing_authority=c.get("issuing_authority", ""),
            effective_date=c.get("effective_date", ""),
            status=c.get("status", ""),
            index_scope=c.get("index_scope", "case"),
            canonical_citation=c.get("canonical_citation", ""),
        )
        for c in items
    ]


def _normalize_clause_reference(item: dict) -> str:
    return (
        item.get("clause_reference")
        or item.get("clause_ref")
        or item.get("reference")
        or ""
    )


def _to_obligation_items(items: list[dict]) -> list[ObligationItemResponse]:
    return [
        ObligationItemResponse(
            clause_id=str(item.get("clause_id", "")),
            clause_reference=_normalize_clause_reference(item),
            obligation_text=str(
                item.get("obligation_text", item.get("text", ""))),
            deadline=str(item.get("deadline", "")),
        )
        for item in items
    ]


def _to_right_items(items: list[dict]) -> list[RightItemResponse]:
    return [
        RightItemResponse(
            clause_id=str(item.get("clause_id", "")),
            clause_reference=_normalize_clause_reference(item),
            right_text=str(item.get("right_text", item.get("text", ""))),
        )
        for item in items
    ]


def _to_penalty_items(items: list[dict]) -> list[PenaltyItemResponse]:
    return [
        PenaltyItemResponse(
            clause_id=str(item.get("clause_id", "")),
            clause_reference=_normalize_clause_reference(item),
            penalty_text=str(item.get("penalty_text", item.get("text", ""))),
        )
        for item in items
    ]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/process/{workspace_id}", response_model=LegalProcessResponse)
async def process_legal_document(
    workspace_id: int,
    request: LegalProcessRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Process a document through the Legal AI pipeline (clause-level parsing + indexing).

    This is separate from the standard NexusRAG pipeline — it uses:
      - LegalDocumentParser  (clause-level extraction, not generic chunking)
      - ClauseChunker        (one chunk per clause)
      - LegalKGService       (legal entity types)
    """
    await _verify_workspace(workspace_id, db, current_user)

    # Fetch the document
    result = await db.execute(
        select(Document).where(Document.id == request.document_id)
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise NotFoundError("Document", request.document_id)

    if document.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Document does not belong to this workspace",
        )

    if document.status in (
        DocumentStatus.PROCESSING, DocumentStatus.PARSING, DocumentStatus.INDEXING
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document is already being processed",
        )

    file_path = Path(UPLOAD_DIR) / document.filename
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document file not found on disk",
        )

    legal_service = _get_legal_service(db, workspace_id)

    try:
        clause_count = await legal_service.process_document(
            document_id=request.document_id,
            file_path=str(file_path),
        )
        return LegalProcessResponse(
            document_id=request.document_id,
            clause_count=clause_count,
            message=f"Legal processing complete: {clause_count} clauses extracted and indexed",
            status="indexed",
        )
    except Exception as e:
        logger.error(
            f"Legal processing failed for document {request.document_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Legal processing failed: {str(e)}",
        )


@router.post("/query/{workspace_id}", response_model=LegalQueryResponse)
async def legal_query(
    workspace_id: int,
    request: LegalQueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Answer a legal question with strict grounding.

    - Retrieves relevant clauses using BM25 + vector search + KG
    - Applies clause-level metadata filtering
    - Runs LLM reasoning with strict grounding enforcement
    - Returns "Insufficient information" if answer cannot be grounded in clauses
    """
    await _verify_workspace(workspace_id, db, current_user)
    legal_service = _get_legal_service(db, workspace_id)

    try:
        result = await legal_service.legal_query(
            question=request.question,
            top_k=request.top_k,
            document_ids=request.document_ids,
            clause_types=request.clause_types,
            articles=request.articles,
        )

        clauses = _to_clause_responses(result["clauses"])

        return LegalQueryResponse(
            answer=result["answer"],
            is_grounded=result["is_grounded"],
            clauses=clauses,
            kg_context=result["kg_context"],
            workspace_id=workspace_id,
        )
    except Exception as e:
        logger.error(f"Legal query failed for workspace {workspace_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Legal query failed: {str(e)}",
        )


@router.post("/route-intent/{workspace_id}", response_model=IntentRouteResponse)
async def route_legal_intent(
    workspace_id: int,
    request: IntentRouteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Route a legal consultation request to the right backend path."""
    await _verify_workspace(workspace_id, db, current_user)
    legal_service = _get_legal_service(db, workspace_id)
    result = await legal_service.route_legal_intent(
        question=request.question,
        chat_history=request.chat_history,
    )
    return IntentRouteResponse(**result)


@router.post("/ask/{workspace_id}", response_model=LegalAskResponse)
async def ask_legal_copilot(
    workspace_id: int,
    request: LegalAskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Intent-first ask flow for the newer LexGuardian UI.

    This route standardizes the legal ask experience without replacing
    existing /legal/query or /rag/chat compatibility flows.
    """
    await _verify_workspace(workspace_id, db, current_user)
    legal_service = _get_legal_service(db, workspace_id)

    routing = await legal_service.route_legal_intent(
        question=request.question,
        chat_history=request.chat_history,
    )
    intent = routing["intent"]

    if intent == "LIVE_SEARCH":
        live = await legal_service.live_search(query=request.question, max_results=min(request.top_k, 10))
        top_results = live["results"][:3]
        answer = (
            "Found trusted live legal sources for this question. "
            "Review the latest source list below to verify the current legal position."
        )
        return LegalAskResponse(
            mode="live_search",
            intent=intent,
            answer=answer,
            is_grounded=len(top_results) > 0,
            reasoning=routing["reasoning"],
            suggested_tools=routing.get("suggested_tools", []),
            evidence_overview=AskEvidenceOverviewResponse(
                total_sources=len(top_results)),
            live_results=[LiveSearchResultResponse(
                **item) for item in top_results],
            next_actions=_build_ask_next_actions(
                intent, has_documents=bool(request.document_ids)),
        )

    if intent == "CONTRACT_RISK":
        if request.document_ids:
            report = await legal_service.analyze_contract_consultation(
                document_id=request.document_ids[0],
                document_name="",
            )
            return LegalAskResponse(
                mode="review_contract",
                intent=intent,
                answer=report.get(
                    "summary", "Contract review summary generated."),
                is_grounded=bool(report.get("findings")),
                reasoning=routing["reasoning"],
                suggested_tools=routing.get("suggested_tools", []),
                evidence_overview=AskEvidenceOverviewResponse(
                    total_sources=len(report.get("findings", []))),
                next_actions=_build_ask_next_actions(
                    intent, has_documents=True),
            )

        return LegalAskResponse(
            mode="review_contract",
            intent=intent,
            answer="This request is better handled as a contract review. Select or upload a contract document to continue.",
            is_grounded=False,
            reasoning=routing["reasoning"],
            suggested_tools=routing.get("suggested_tools", []),
            next_actions=_build_ask_next_actions(intent, has_documents=False),
        )

    result = await legal_service.smart_legal_query(
        question=request.question,
        top_k=request.top_k,
        document_ids=request.document_ids or None,
    )
    clauses = _to_clause_responses(result["clauses"])
    return LegalAskResponse(
        mode="legal_query",
        intent=intent,
        answer=result["answer"],
        is_grounded=result["is_grounded"],
        reasoning=routing["reasoning"],
        suggested_tools=routing.get("suggested_tools", []),
        evidence_overview=_build_evidence_overview_from_clauses(
            result["clauses"]),
        clauses=clauses,
        next_actions=_build_ask_next_actions(
            intent, has_documents=bool(request.document_ids)),
    )


@router.post("/live-search/{workspace_id}", response_model=LiveSearchResponse)
async def live_legal_search(
    workspace_id: int,
    request: LiveSearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search trusted legal/government websites via Tavily."""
    await _verify_workspace(workspace_id, db, current_user)
    legal_service = _get_legal_service(db, workspace_id)
    result = await legal_service.live_search(
        query=request.query,
        max_results=request.max_results,
    )
    return LiveSearchResponse(
        query=result["query"],
        results=[LiveSearchResultResponse(**item)
                 for item in result["results"]],
    )


@router.post("/check-validity/{workspace_id}", response_model=ValidityCheckResponse)
async def check_legal_validity(
    workspace_id: int,
    request: ValidityCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check whether a legal document is still effective."""
    await _verify_workspace(workspace_id, db, current_user)
    legal_service = _get_legal_service(db, workspace_id)
    result = await legal_service.check_legal_validity(request.doc_title)
    return ValidityCheckResponse(**result)


@router.post("/analyze-risk/{workspace_id}", response_model=RiskAnalysisResponse)
async def analyze_contract_risk(
    workspace_id: int,
    request: RiskAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Run full contract risk analysis on a document.

    Analyzes:
    - Ambiguous or one-sided obligations
    - Missing penalty clauses
    - Unlimited liability exposure
    - Missing standard clauses (termination, force majeure, etc.)
    - Governing law gaps
    """
    await _verify_workspace(workspace_id, db, current_user)
    legal_service = _get_legal_service(db, workspace_id)

    try:
        report = await legal_service.analyze_contract_risk(
            document_id=request.document_id,
            document_name=request.document_name or "",
        )
        normalized_levels = [_normalize_risk_level(
            r.risk_level) for r in report.risks]
        risk_counts = _build_risk_counts(normalized_levels)
        top_issues = [
            f"{r.clause_reference}: {r.risk_type}" for r in report.risks[:3]]
        recommended_actions = _build_risk_actions(
            has_missing_clauses=bool(report.missing_clauses),
            highest_level="high" if risk_counts.high > 0 else "medium" if risk_counts.medium > 0 else "low",
        )

        return RiskAnalysisResponse(
            document_id=report.document_id,
            document_name=report.document_name,
            overall_risk_level=report.overall_risk_level,
            risks=[
                RiskItemResponse(
                    clause_id=r.clause_id,
                    clause_reference=r.clause_reference,
                    risk_level=r.risk_level,
                    risk_type=r.risk_type,
                    description=r.description,
                    recommendation=r.recommendation,
                )
                for r in report.risks
            ],
            parties_identified=report.parties_identified,
            governing_law=report.governing_law,
            summary=report.summary,
            missing_clauses=report.missing_clauses,
            risk_counts=risk_counts,
            top_issues=top_issues,
            recommended_actions=recommended_actions,
        )
    except Exception as e:
        logger.error(
            f"Risk analysis failed for doc {request.document_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Risk analysis failed: {str(e)}",
        )


@router.post("/review-summary/{workspace_id}", response_model=RiskAnalysisResponse)
async def review_contract_summary(
    workspace_id: int,
    request: RiskAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Standardized alias for the contract review summary flow.

    Keeps FE aligned with the newer product language while reusing the
    stable /legal/analyze-risk implementation.
    """
    return await analyze_contract_risk(
        workspace_id=workspace_id,
        request=request,
        db=db,
        current_user=current_user,
    )


@router.post("/consult-risk/{workspace_id}", response_model=ConsultationRiskResponse)
async def analyze_contract_consultation(
    workspace_id: int,
    request: ConsultationRiskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Run the newer clause-level consultation risk analysis.

    This route combines:
    - clause extraction
    - static legal retrieval
    - trusted live legal web search
    - LLM comparison when available
    - deterministic legal fallback checks
    """
    await _verify_workspace(workspace_id, db, current_user)
    legal_service = _get_legal_service(db, workspace_id)

    try:
        report = await legal_service.analyze_contract_consultation(
            document_id=request.document_id,
            document_name=request.document_name or "",
        )
        normalized_levels = [_normalize_risk_level(
            item.get("status", "")) for item in report["findings"]]
        finding_counts = _build_risk_counts(normalized_levels)
        top_issues = [
            f'{item.get("clause_reference", "Clause")}: {item.get("status", "Review")}'
            for item in report["findings"][:3]
        ]
        recommended_actions = _build_risk_actions(
            has_missing_clauses=False,
            highest_level="high" if finding_counts.high > 0 else "medium" if finding_counts.medium > 0 else "low",
        )
        return ConsultationRiskResponse(
            document_name=report["document_name"],
            document_type=report["document_type"],
            findings=[
                ConsultationFindingResponse(
                    clause_type=item["clause_type"],
                    clause_reference=item["clause_reference"],
                    clause_text=item["clause_text"],
                    status=item["status"],
                    legal_basis=[
                        LegalBasisCitationResponse(**basis)
                        for basis in item.get("legal_basis", [])
                    ],
                    revision_advice=item.get("revision_advice", ""),
                    reasoning=item.get("reasoning", ""),
                    comparison_question=item.get("comparison_question", ""),
                )
                for item in report["findings"]
            ],
            summary=report["summary"],
            finding_counts=finding_counts,
            top_issues=top_issues,
            recommended_actions=recommended_actions,
        )
    except Exception as e:
        logger.error(
            f"Consultation risk analysis failed for doc {request.document_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Consultation risk analysis failed: {str(e)}",
        )


@router.get("/review-findings/{workspace_id}/{document_id}", response_model=ConsultationRiskResponse)
async def review_contract_findings(
    workspace_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Standardized alias for detailed clause-level review findings.
    """
    return await analyze_contract_consultation(
        workspace_id=workspace_id,
        request=ConsultationRiskRequest(
            document_id=document_id, document_name=""),
        db=db,
        current_user=current_user,
    )


@router.post("/compare-clauses/{workspace_id}", response_model=ClauseCompareResponse)
async def compare_clauses(
    workspace_id: int,
    request: ClauseCompareRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Compare two contract clauses by their clause IDs.

    Returns similarities, differences, conflicts, and a recommendation.
    """
    await _verify_workspace(workspace_id, db, current_user)
    legal_service = _get_legal_service(db, workspace_id)

    try:
        comparison = await legal_service.compare_clauses(
            clause_id_a=request.clause_id_a,
            clause_id_b=request.clause_id_b,
        )

        return ClauseCompareResponse(
            clause_a_id=comparison.clause_a_id,
            clause_b_id=comparison.clause_b_id,
            clause_a_text=comparison.clause_a_text,
            clause_b_text=comparison.clause_b_text,
            similarities=comparison.similarities,
            differences=comparison.differences,
            conflicts=comparison.conflicts,
            recommendation=comparison.recommendation,
            analysis=comparison.analysis,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Clause comparison failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Clause comparison failed: {str(e)}",
        )


@router.post("/missing-clauses/{workspace_id}", response_model=MissingClausesResponse)
async def detect_missing_clauses(
    workspace_id: int,
    request: MissingClauseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Detect standard legal clauses missing from a contract.

    Checks for: termination, force majeure, governing law, dispute resolution,
    confidentiality, limitation of liability, indemnification, IP, payment terms,
    representations & warranties.
    """
    await _verify_workspace(workspace_id, db, current_user)
    legal_service = _get_legal_service(db, workspace_id)

    try:
        missing = await legal_service.detect_missing_clauses(request.document_id)

        return MissingClausesResponse(
            document_id=request.document_id,
            missing_clauses=[
                MissingClauseResponse(
                    clause_type=m.clause_type,
                    description=m.description,
                    risk_if_missing=m.risk_if_missing,
                    suggested_text=m.suggested_text,
                )
                for m in missing
            ],
            total=len(missing),
        )
    except Exception as e:
        logger.error(
            f"Missing clause detection failed for doc {request.document_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Missing clause detection failed: {str(e)}",
        )


@router.post("/obligations/{workspace_id}", response_model=ObligationSummaryResponse)
async def summarize_obligations(
    workspace_id: int,
    request: ObligationSummaryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Summarize all obligations, rights, and penalties for a specific party.

    Returns structured lists of:
    - What the party MUST do (obligations)
    - What the party MAY do (rights)
    - What happens if the party breaches (penalties)
    """
    await _verify_workspace(workspace_id, db, current_user)
    legal_service = _get_legal_service(db, workspace_id)

    try:
        summary = await legal_service.summarize_obligations(
            party=request.party,
            document_id=request.document_id,
            top_k=request.top_k,
        )

        return ObligationSummaryResponse(
            party=summary.party,
            document_id=summary.document_id,
            obligations=_to_obligation_items(summary.obligations),
            rights=_to_right_items(summary.rights),
            penalties=_to_penalty_items(summary.penalties),
            summary=summary.summary,
        )
    except Exception as e:
        logger.error(
            f"Obligation summary failed for party '{request.party}' "
            f"in doc {request.document_id}: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Obligation summary failed: {str(e)}",
        )


@router.post("/smart-query/{workspace_id}", response_model=SmartLegalQueryResponse)
async def smart_legal_query(
    workspace_id: int,
    request: LegalQueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Domain-aware legal QA.

    Automatically:
      - Detects legal signals from the query (keyword + regex)
      - Infers clause_type filters (payment → ["payment", "obligation"])
      - Infers article filters from "Điều X" mentions in query
      - Runs grounded legal QA with auto-populated filters

    Returns the answer + domain detection metadata (confidence, signals).
    """
    await _verify_workspace(workspace_id, db, current_user)
    legal_service = _get_legal_service(db, workspace_id)

    try:
        result = await legal_service.smart_legal_query(
            question=request.question,
            top_k=request.top_k,
            document_ids=request.document_ids,
        )
        return SmartLegalQueryResponse(
            answer=result["answer"],
            is_grounded=result["is_grounded"],
            clauses=_to_clause_responses(result["clauses"]),
            kg_context=result.get("kg_context", ""),
            workspace_id=workspace_id,
            domain=result.get("domain", ""),
            domain_confidence=result.get("domain_confidence", 0.0),
            clause_type_filter=result.get("clause_type_filter"),
            article_filter=result.get("article_filter"),
            domain_signals=result.get("domain_signals", []),
            field_tags_filter=result.get("field_tags_filter"),
            static_doc_types_filter=result.get("static_doc_types_filter"),
            rewritten_query=result.get("rewritten_query", request.question),
        )
    except Exception as e:
        logger.error(f"Smart legal query failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Smart query failed: {str(e)}",
        )


@router.post("/extract-fields/{workspace_id}", response_model=ContractFieldsResponse)
async def extract_contract_fields(
    workspace_id: int,
    document_id: int,
    use_llm_fallback: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Extract structured fields from a contract document.

    Returns:
      - contract_value, contract_currency
      - vat_rate, vat_amount
      - party_a, party_b
      - effective_date, signing_date
      - payment_deadline_days
      - penalty_rate, late_payment_rate
      - governing_law
      - which fields came from regex vs LLM
    """
    _ensure_legacy_internal_routes_enabled()
    await _verify_workspace(workspace_id, db, current_user)
    legal_service = _get_legal_service(db, workspace_id)

    try:
        fields = await legal_service.extract_fields(
            document_id=document_id,
            use_llm_fallback=use_llm_fallback,
        )
        return ContractFieldsResponse(**fields.to_dict())
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Field extraction failed for doc {document_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Field extraction failed: {str(e)}",
        )


@router.post("/build-kg-relationships/{workspace_id}")
async def build_kg_relationships(
    workspace_id: int,
    document_id: int,
    use_llm: bool = False,
    reingest: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fix the KG '0 relationships' problem.

    Extracts (subject, predicate, object) triplets from contract clauses
    using rule-based patterns + optional LLM, then re-ingests annotated
    text into LightRAG so it finds the relationships.

    Args:
        document_id: Document to process
        use_llm: Use LLM for complex clauses (more accurate, slower)
        reingest: Re-ingest enriched text into KG (default True)

    Returns: List of extracted relationships
    """
    _ensure_legacy_internal_routes_enabled()
    await _verify_workspace(workspace_id, db, current_user)
    legal_service = _get_legal_service(db, workspace_id)

    try:
        relationships = await legal_service.build_kg_relationships(
            document_id=document_id,
            use_llm=use_llm,
            reingest_enriched_text=reingest,
        )
        return {
            "document_id": document_id,
            "relationship_count": len(relationships),
            "relationships": relationships,
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(
            f"KG relationship building failed for doc {document_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"KG relationship building failed: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Phase 2: Static Legal Index Endpoints
# ---------------------------------------------------------------------------

@router.get("/static/stats")
async def get_static_index_stats():
    """
    Return statistics about the Static Legal Index collection.
    Reports ChromaDB chunk count and whether the collection exists.
    """
    _ensure_legacy_internal_routes_enabled()
    from app.services.legal.legal_static_index_service import LegalStaticIndexService
    from app.core.config import settings as cfg
    svc = LegalStaticIndexService()
    return {
        "enabled": cfg.LEGAL_STATIC_INDEX_ENABLED,
        "collection_name": cfg.LEGAL_STATIC_COLLECTION_NAME,
        "collection_exists": svc.collection_exists(),
        "chunk_count": svc.count(),
    }


@router.post("/static/ingest-record")
async def ingest_static_record(
    record: dict,
    augment: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """
    Ingest a single legal document record dict into the Static Legal Index.

    Required fields:
      - content / text / markdown: document markdown text
      - title: document title (recommended)
      - document_type: "law" | "decree" | "circular" etc.

    All metadata fields are optional with safe defaults.
    Set augment=true to enable SAC summary generation.
    """
    _ensure_legacy_internal_routes_enabled()
    from app.core.config import settings as cfg
    from app.services.legal.legal_dataset_ingestor import LegalDatasetIngestor
    from app.services.legal.legal_chunk_augmentor import LegalChunkAugmentor

    if not cfg.LEGAL_STATIC_INDEX_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="LEGAL_STATIC_INDEX_ENABLED is false. Set it to true in .env.",
        )

    augmentor = None
    if augment and cfg.LEGAL_CHUNK_AUGMENT_ENABLED:
        from app.services.llm import get_llm_provider
        augmentor = LegalChunkAugmentor(llm_provider=get_llm_provider())

    ingestor = LegalDatasetIngestor(db=db, augmentor=augmentor)
    try:
        result = await ingestor.ingest_single_record(record, augment=augment)
        return result
    except Exception as e:
        logger.error(f"Static record ingest failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Static record ingest failed: {str(e)}",
        )


@router.post("/static/ingest-dataset")
async def trigger_dataset_ingest(
    dataset_name: str = "th1nhng0/vietnamese-legal-documents",
    split: str = "data",
    max_docs: int = 0,
    skip_existing: bool = True,
    augment: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger batch ingestion from a HuggingFace dataset.

    Warning: Long-running — for production use, invoke from a background task.
    Args:
        dataset_name: HuggingFace dataset path
        split: Dataset split (default: train)
        max_docs: Max documents (0 = use config or unlimited)
        skip_existing: Hash-based dedup (default: True)
        augment: Enable SAC summaries via LLM
    """
    _ensure_legacy_internal_routes_enabled()
    from app.core.config import settings as cfg
    from app.services.legal.legal_dataset_ingestor import LegalDatasetIngestor
    from app.services.legal.legal_chunk_augmentor import LegalChunkAugmentor

    if not cfg.LEGAL_STATIC_INDEX_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="LEGAL_STATIC_INDEX_ENABLED is false. Set it to true in .env first.",
        )

    augmentor = None
    if augment and cfg.LEGAL_CHUNK_AUGMENT_ENABLED:
        from app.services.llm import get_llm_provider
        augmentor = LegalChunkAugmentor(llm_provider=get_llm_provider())

    ingestor = LegalDatasetIngestor(db=db, augmentor=augmentor)
    try:
        summary = await ingestor.ingest_from_huggingface(
            dataset_name=dataset_name,
            split=split,
            max_docs=max_docs,
            skip_existing=skip_existing,
        )
        return summary
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Dataset ingest failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Dataset ingest failed: {str(e)}",
        )


@router.post("/static/query")
async def query_static_statutes(
    question: str,
    top_k: int = 10,
    document_type: str | None = None,
    status_filter: str | None = None,
    field_tag: str | None = None,
):
    """
    Query the Static Legal Index directly (no workspace required).

    Returns top-K matching clauses from the statutory corpus.
    Args:
        question: Natural language legal question
        top_k: Number of results (1-30)
        document_type: Filter by type (law / decree / circular etc.)
        status_filter: Filter by effectiveness (active / expired etc.)
        field_tag: Filter by one legal domain tag
    """
    _ensure_legacy_internal_routes_enabled()
    from app.core.config import settings as cfg
    from app.services.legal.legal_static_index_service import LegalStaticIndexService
    from app.services.embedder import get_embedding_service

    if not cfg.LEGAL_STATIC_INDEX_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="LEGAL_STATIC_INDEX_ENABLED is false.",
        )

    top_k = max(1, min(top_k, 30))
    conditions = []
    if document_type:
        conditions.append({"document_type": {"$eq": document_type}})
    if status_filter:
        conditions.append({"status": {"$eq": status_filter}})

    where = None
    if len(conditions) == 1:
        where = conditions[0]
    elif len(conditions) > 1:
        where = {"$and": conditions}

    embedder = get_embedding_service()
    query_embedding = embedder.embed_query(question)
    svc = LegalStaticIndexService(embedder=embedder)

    try:
        results = svc.query_statutes(
            query_embedding=query_embedding,
            n_results=top_k,
            where=where,
        )
        if field_tag:
            results = [r for r in results if field_tag in r.clause.field_tags]

        return {
            "question": question,
            "total": len(results),
            "clauses": [
                {
                    "clause_id": r.clause.clause_id,
                    "reference": r.clause.format_reference(),
                    "text": r.clause.text[:500],
                    "title": r.clause.title,
                    "document_type": r.clause.document_type,
                    "issuing_authority": r.clause.issuing_authority,
                    "effective_date": r.clause.effective_date,
                    "status": r.clause.status,
                    "field_tags": r.clause.field_tags,
                    "score": round(r.score, 4),
                    "index_scope": r.clause.index_scope,
                }
                for r in results
            ],
        }
    except Exception as e:
        logger.error(f"Static statute query failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Static query failed: {str(e)}",
        )


@router.get("/static/source/{workspace_id}/{source_id}")
async def get_static_source_document(
    workspace_id: int,
    source_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return an assembled markdown view for a static legal source so the frontend
    can render statutory documents similarly to workspace documents.
    """
    await _verify_workspace(workspace_id, db, current_user)

    static_index = LegalStaticIndexService()
    result = await db.execute(
        select(LegalSourceDocument).where(
            LegalSourceDocument.id == source_id,
            LegalSourceDocument.index_scope == "static",
        )
    )
    source = result.scalar_one_or_none()

    def _collection_get_by_document_id(value):
        try:
            return static_index._vector_store.get_all(
                where={"document_id": {"$eq": value}},
            )
        except Exception:
            return {"documents": [], "metadatas": []}

    raw = _collection_get_by_document_id(source_id)
    documents = raw.get("documents") or []
    metadatas = raw.get("metadatas") or []

    if not documents:
        raw = _collection_get_by_document_id(str(source_id))
        documents = raw.get("documents") or []
        metadatas = raw.get("metadatas") or []

    if not documents and source is not None and source.canonical_citation:
        try:
            raw = static_index._vector_store.get_all(
                where={"canonical_citation": {
                    "$eq": source.canonical_citation}},
            )
            documents = raw.get("documents") or []
            metadatas = raw.get("metadatas") or []
        except Exception:
            documents = []
            metadatas = []

    if source is None and not documents:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Legal source not found",
        )

    assembled_rows: list[tuple[int, str, str, str]] = []
    for idx, text in enumerate(documents):
        meta = metadatas[idx] if idx < len(metadatas) else {}
        chunk_index = int(meta.get("chunk_index", idx) or idx)
        article = str(meta.get("article", "") or "")
        clause = str(meta.get("clause", "") or "")
        point = str(meta.get("point", "") or "")
        header = " > ".join(part for part in [article, clause, point] if part)
        assembled_rows.append((chunk_index, header, str(
            text or ""), str(meta.get("page", "") or "")))

    assembled_rows.sort(key=lambda item: item[0])

    md_parts: list[str] = []
    first_meta = metadatas[0] if metadatas else {}
    title = (
        (source.title if source is not None else "")
        or (source.canonical_citation if source is not None else "")
        or str(first_meta.get("title", "") or "")
        or str(first_meta.get("canonical_citation", "") or "")
        or f"Legal Source {source_id}"
    )
    md_parts.append(f"# {title}")
    meta_lines: list[str] = []
    document_type = (
        (source.document_type if source is not None else "")
        or str(first_meta.get("document_type", "") or "")
    )
    issuing_authority = (
        (source.issuing_authority if source is not None else "")
        or str(first_meta.get("issuing_authority", "") or "")
    )
    status_value = (
        (source.status if source is not None else "")
        or str(first_meta.get("status", "") or "")
    )
    effective_date = (
        (source.effective_date if source is not None else "")
        or str(first_meta.get("effective_date", "") or "")
    )
    field_tags = (
        (source.field_tags if source is not None else [])
        or [t for t in str(first_meta.get("field_tags", "") or "").split("|") if t]
    )
    source_url = (source.source_url if source is not None else "") or ""

    if document_type:
        meta_lines.append(f"- Document type: {document_type}")
    if issuing_authority:
        meta_lines.append(f"- Issuing authority: {issuing_authority}")
    if status_value:
        meta_lines.append(f"- Status: {status_value}")
    if effective_date:
        meta_lines.append(f"- Effective date: {effective_date}")
    if field_tags:
        meta_lines.append(f"- Field tags: {', '.join(field_tags)}")
    if source_url:
        meta_lines.append(f"- Source URL: {source_url}")
    if meta_lines:
        md_parts.append("\n".join(meta_lines))

    last_header = ""
    for _, header, text, page in assembled_rows:
        if header and header != last_header:
            level = "##" if ">" not in header else "###"
            md_parts.append(f"{level} {header}")
            last_header = header
        elif page:
            md_parts.append(f"<!-- page {page} -->")
        md_parts.append(text.strip())

    return {
        "id": source.id if source is not None else source_id,
        "title": source.title if source is not None else str(first_meta.get("title", "") or title),
        "canonical_citation": (
            source.canonical_citation if source is not None
            else str(first_meta.get("canonical_citation", "") or title)
        ),
        "document_type": document_type,
        "issuing_authority": issuing_authority,
        "effective_date": effective_date,
        "status": status_value,
        "field_tags": field_tags,
        "source_url": source_url,
        "content_markdown": "\n\n".join(part for part in md_parts if part),
    }


# ---------------------------------------------------------------------------
# Internal namespace aliases
# ---------------------------------------------------------------------------

if settings.LEGAL_INTERNAL_API_ENABLED:

    @internal_router.post("/extract-fields/{workspace_id}", response_model=ContractFieldsResponse)
    async def internal_extract_contract_fields(
        workspace_id: int,
        document_id: int,
        use_llm_fallback: bool = True,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        return await extract_contract_fields(
            workspace_id=workspace_id,
            document_id=document_id,
            use_llm_fallback=use_llm_fallback,
            db=db,
            current_user=current_user,
        )

    @internal_router.post("/build-kg-relationships/{workspace_id}")
    async def internal_build_kg_relationships(
        workspace_id: int,
        document_id: int,
        use_llm: bool = False,
        reingest: bool = True,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        return await build_kg_relationships(
            workspace_id=workspace_id,
            document_id=document_id,
            use_llm=use_llm,
            reingest=reingest,
            db=db,
            current_user=current_user,
        )

    @internal_router.get("/static/stats")
    async def internal_get_static_index_stats():
        return await get_static_index_stats()

    @internal_router.post("/static/ingest-record")
    async def internal_ingest_static_record(
        record: dict,
        augment: bool = False,
        db: AsyncSession = Depends(get_db),
    ):
        return await ingest_static_record(record=record, augment=augment, db=db)

    @internal_router.post("/static/ingest-dataset")
    async def internal_trigger_dataset_ingest(
        dataset_name: str = "th1nhng0/vietnamese-legal-documents",
        split: str = "data",
        max_docs: int = 0,
        skip_existing: bool = True,
        augment: bool = False,
        db: AsyncSession = Depends(get_db),
    ):
        return await trigger_dataset_ingest(
            dataset_name=dataset_name,
            split=split,
            max_docs=max_docs,
            skip_existing=skip_existing,
            augment=augment,
            db=db,
        )

    @internal_router.post("/static/query")
    async def internal_query_static_statutes(
        question: str,
        top_k: int = 10,
        document_type: str | None = None,
        status_filter: str | None = None,
        field_tag: str | None = None,
    ):
        return await query_static_statutes(
            question=question,
            top_k=top_k,
            document_type=document_type,
            status_filter=status_filter,
            field_tag=field_tag,
        )

    router.include_router(internal_router)
