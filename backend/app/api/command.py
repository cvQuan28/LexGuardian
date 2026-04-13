"""
LexGuardian Command API
========================
Unified entry point: nhận user input bất kỳ, detect intent, route đến đúng service.

Đây là endpoint chính mà Command Center frontend gọi.

Intent types:
  - ASK_DOCUMENT    → Legal QA từ documents trong workspace
  - ASK_LAW         → Live search trên legal databases
  - ANALYZE_RISK    → Contract risk analysis
  - CHECK_VALIDITY  → Kiểm tra văn bản pháp luật còn hiệu lực không
  - GENERAL         → General conversation
"""
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from app.core.deps import get_current_user, get_db, get_workspace_for_user
from app.models.user import User
from app.services.legal.legal_router import LegalDomainRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/command", tags=["command"])


class CommandRequest(BaseModel):
    input: str
    document_id: Optional[int] = None
    conversation_id: Optional[int] = None
    conversation_history: list[dict] = []


class CommandResponse(BaseModel):
    intent: str           # ASK_DOCUMENT | ASK_LAW | ANALYZE_RISK | CHECK_VALIDITY | GENERAL
    confidence: float
    suggested_action: str
    signals: list[str]
    domain: str


@router.post("/detect-intent/{workspace_id}", response_model=CommandResponse)
async def detect_intent(
    workspace_id: int,
    body: CommandRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Phân tích input của user và trả về intent + suggested action.
    Frontend dùng endpoint này để quyết định hiển thị UI nào.
    """
    await get_workspace_for_user(workspace_id, db, current_user)
    domain_router = LegalDomainRouter()
    result = domain_router.detect(body.input)

    # Map domain detection → LexGuardian intent
    if body.document_id:
        intent = "ASK_DOCUMENT"
        suggested_action = "query_document"
    elif result.domain == "legal":
        validity_keywords = ["còn hiệu lực", "hết hiệu lực", "expired", "still valid", "in force"]
        if any(kw in body.input.lower() for kw in validity_keywords):
            intent = "CHECK_VALIDITY"
            suggested_action = "check_validity"
        else:
            intent = "ASK_LAW"
            suggested_action = "live_search"
    else:
        intent = "GENERAL"
        suggested_action = "general_chat"

    return CommandResponse(
        intent=intent,
        confidence=result.confidence,
        suggested_action=suggested_action,
        signals=result.signals,
        domain=result.domain,
    )
