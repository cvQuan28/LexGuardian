"""
LexGuardian API router — aggregates workspace, document, command, and Legal AI endpoints.
"""
from fastapi import APIRouter

from app.api.workspaces import router as workspaces_router
from app.api.documents import router as documents_router
from app.api.config import router as config_router
from app.api.legal import router as legal_router
from app.api.evaluations import router as evaluations_router
from app.api.auth import router as auth_router
from app.api.conversations import router as conversations_router
from app.api.command import router as command_router
from app.api.chat import router as chat_router
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(workspaces_router)
api_router.include_router(documents_router)
api_router.include_router(config_router)
api_router.include_router(auth_router)
api_router.include_router(conversations_router)
api_router.include_router(legal_router)
api_router.include_router(evaluations_router)
api_router.include_router(command_router)
api_router.include_router(chat_router)

if settings.ENABLE_GENERIC_RAG_API:
    from app.api.rag import router as rag_router

    api_router.include_router(rag_router)
