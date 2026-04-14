"""
LexGuardian Chat API
=====================
SSE streaming chat endpoint for document Q&A, plus chat history endpoints.
Separated from the generic RAG API to remain always-available.
"""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.deps import get_current_user, get_db, get_workspace_for_user
from app.core.exceptions import NotFoundError
from app.models.user import Conversation, User
from app.schemas.rag import ChatHistoryResponse, ChatRequest, PersistedChatMessage

router = APIRouter(prefix="/chat", tags=["chat"])
_limiter = Limiter(key_func=get_remote_address)


@router.post("/{workspace_id}/stream")
@_limiter.limit("30/minute")
async def chat_stream(
    request: Request,
    workspace_id: int,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SSE streaming chat — 30 req/min per IP."""
    from app.api.chat_agent import chat_stream_endpoint
    return await chat_stream_endpoint(workspace_id, body, db, current_user)


async def _get_conversation(
    db: AsyncSession,
    current_user: User,
    workspace_id: int,
    conversation_id: int | None,
) -> Conversation | None:
    if conversation_id is None:
        return None
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
            Conversation.workspace_id == workspace_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise NotFoundError("Conversation", conversation_id)
    return conversation


@router.get("/{workspace_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    workspace_id: int,
    conversation_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Load persisted chat history for a workspace/conversation."""
    await get_workspace_for_user(workspace_id, db, current_user)
    conversation = await _get_conversation(db, current_user, workspace_id, conversation_id)

    from app.models.chat_message import ChatMessage as ChatMessageModel
    stmt = (
        select(ChatMessageModel)
        .where(
            ChatMessageModel.workspace_id == workspace_id,
            ChatMessageModel.user_id == current_user.id,
        )
        .order_by(ChatMessageModel.created_at.asc())
    )
    if conversation:
        stmt = stmt.where(ChatMessageModel.conversation_id == conversation.id)
    result = await db.execute(stmt)
    messages = result.scalars().all()

    return ChatHistoryResponse(
        workspace_id=workspace_id,
        messages=[
            PersistedChatMessage(
                id=m.id,
                message_id=m.message_id,
                role=m.role,
                content=m.content,
                sources=m.sources,
                related_entities=m.related_entities,
                image_refs=m.image_refs,
                thinking=m.thinking,
                agent_steps=m.agent_steps,
                conversation_id=m.conversation_id,
                created_at=m.created_at.isoformat() if m.created_at else "",
            )
            for m in messages
        ],
        conversation_id=conversation.id if conversation else None,
        total=len(messages),
    )


@router.delete("/{workspace_id}/history")
async def delete_chat_history(
    workspace_id: int,
    conversation_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Clear chat history for a workspace/conversation."""
    await get_workspace_for_user(workspace_id, db, current_user)
    conversation = await _get_conversation(db, current_user, workspace_id, conversation_id)

    from app.models.chat_message import ChatMessage as ChatMessageModel
    stmt = delete(ChatMessageModel).where(
        ChatMessageModel.workspace_id == workspace_id,
        ChatMessageModel.user_id == current_user.id,
    )
    if conversation:
        stmt = stmt.where(ChatMessageModel.conversation_id == conversation.id)
    await db.execute(stmt)
    await db.commit()
    return {
        "status": "cleared",
        "workspace_id": workspace_id,
        "conversation_id": conversation.id if conversation else None,
    }
