from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, get_workspace_for_user
from app.core.exceptions import NotFoundError
from app.models.user import Conversation, User
from app.schemas.conversation import (
    ConversationCreate,
    ConversationResponse,
    ConversationUpdate,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    workspace_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_workspace_for_user(workspace_id, db, current_user)
    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.user_id == current_user.id,
            Conversation.workspace_id == workspace_id,
        )
        .order_by(Conversation.updated_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=ConversationResponse)
async def create_conversation(
    body: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_workspace_for_user(body.workspace_id, db, current_user)
    conversation = Conversation(
        user_id=current_user.id,
        workspace_id=body.workspace_id,
        title=(body.title or "New chat").strip()[:255],
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.patch("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: int,
    body: ConversationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise NotFoundError("Conversation", conversation_id)
    conversation.title = body.title.strip()
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise NotFoundError("Conversation", conversation_id)
    await db.delete(conversation)
    await db.commit()
    return {"status": "deleted", "conversation_id": conversation_id}
