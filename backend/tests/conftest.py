"""
Shared pytest fixtures for LexGuardian backend tests.

All fixtures mock heavy I/O (DB, LLM, embedder) so tests run
without a live database, GPU, or API keys.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Event loop (single loop for all async tests)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Fake DB session
# ---------------------------------------------------------------------------

class FakeDB:
    """Minimal AsyncSession stub for unit tests."""

    def __init__(self):
        self._store: dict = {}
        self.committed = False
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        pass

    async def execute(self, stmt):
        return FakeResult(None)

    async def delete(self, obj):
        pass

    async def rollback(self):
        pass


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return []


@pytest.fixture
def fake_db():
    return FakeDB()


# ---------------------------------------------------------------------------
# Fake User / Workspace
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_user():
    return SimpleNamespace(id=1, email="test@example.com", display_name="Test User")


@pytest.fixture
def fake_workspace():
    return SimpleNamespace(id=1, user_id=1, name="Test Workspace", system_prompt=None)


# ---------------------------------------------------------------------------
# Fake LegalRetriever components
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_embedder():
    embedder = MagicMock()
    embedder.embed_query.return_value = [0.1] * 1024
    embedder.embed_texts.return_value = [[0.1] * 1024]
    return embedder


@pytest.fixture
def mock_vector_store():
    vs = MagicMock()
    vs.query.return_value = {"documents": [], "metadatas": [], "distances": []}
    vs.get_all.return_value = {"documents": [], "metadatas": []}
    return vs


@pytest.fixture
def mock_reranker():
    reranker = MagicMock()
    reranker.rerank.return_value = []
    return reranker


@pytest.fixture
def mock_kg_service():
    kg = AsyncMock()
    kg.get_legal_context = AsyncMock(return_value="")
    return kg
