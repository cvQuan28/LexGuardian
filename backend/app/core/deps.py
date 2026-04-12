from datetime import datetime

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import hash_session_token
from app.models.user import AuthSession, User
from app.models.knowledge_base import KnowledgeBase


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedError()

    token = authorization.removeprefix("Bearer ").strip()
    token_hash = hash_session_token(token)
    result = await db.execute(
        select(AuthSession).where(AuthSession.token_hash == token_hash)
    )
    session = result.scalar_one_or_none()
    if not session or session.expires_at < datetime.utcnow():
        raise UnauthorizedError("Session expired or invalid")

    session.last_used_at = datetime.utcnow()
    await db.commit()

    result = await db.execute(select(User).where(User.id == session.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise UnauthorizedError()
    return user


async def get_workspace_for_user(
    workspace_id: int,
    db: AsyncSession,
    user: User,
) -> KnowledgeBase:
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == workspace_id,
            KnowledgeBase.user_id == user.id,
        )
    )
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise ForbiddenError("You do not have access to this workspace")
    return workspace
