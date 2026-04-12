from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    session_expiry,
    verify_password,
)
from app.models.knowledge_base import KnowledgeBase
from app.models.user import AuthSession, User
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


async def _create_session(db: AsyncSession, user: User) -> AuthResponse:
    token = generate_session_token()
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=session_expiry(),
        )
    )
    await db.commit()
    return AuthResponse(token=token, user=UserResponse.model_validate(user))


@router.post("/register", response_model=AuthResponse)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    existing = result.scalar_one_or_none()
    if existing:
        raise ConflictError("Email is already registered")

    user = User(
        email=body.email.lower(),
        display_name=body.display_name.strip(),
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    orphan_workspaces = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.user_id.is_(None))
    )
    for workspace in orphan_workspaces.scalars().all():
        workspace.user_id = user.id
    await db.commit()

    return await _create_session(db, user)


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise UnauthorizedError("Invalid email or password")
    return await _create_session(db, user)


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    if authorization and authorization.startswith("Bearer "):
        token_hash = hash_session_token(authorization.removeprefix("Bearer ").strip())
        result = await db.execute(select(AuthSession).where(AuthSession.token_hash == token_hash))
        session = result.scalar_one_or_none()
        if session:
            await db.delete(session)
            await db.commit()
    return {"status": "ok", "user_id": current_user.id}
