"""
LexGuardian Chat API
=====================
SSE streaming chat endpoint for document Q&A.
Separated from the generic RAG API to remain always-available.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.rag import ChatRequest

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/{workspace_id}/stream")
async def chat_stream(
    workspace_id: int,
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SSE streaming chat with semi-agentic document retrieval."""
    from app.api.chat_agent import chat_stream_endpoint
    return await chat_stream_endpoint(workspace_id, request, db, current_user)
