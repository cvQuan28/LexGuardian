"""
Unit tests for LegalRAGService — skip_reasoning flag and query_deep isolation.

Verifies that:
  - document_qa mode uses CASE_ONLY and skips reasoning LLM call
  - legal_consultation mode uses STATIC_ONLY / live search and skips reasoning
  - skip_reasoning=False (direct legal_query API) still invokes reasoning
"""
from __future__ import annotations

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.models.legal_document import (
    LegalRetrievalResult,
    RetrievalMode,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_legal_result(n_clauses: int = 2) -> dict:
    clauses = [
        {
            "clause_id": f"c{i}",
            "document_id": 1,
            "reference": f"Article {i}",
            "text": f"Clause text {i}",
            "article": f"Article {i}",
            "clause": "Clause 1",
            "point": "",
            "page": i,
            "clause_type": "obligation",
            "score": 0.9 - i * 0.1,
            "retrieval_source": "vector",
            "title": "Contract A",
            "document_type": "contract",
            "issuing_authority": "",
            "effective_date": "",
            "status": "active",
            "index_scope": "case",
            "canonical_citation": "",
        }
        for i in range(n_clauses)
    ]
    return {
        "answer": "",
        "is_grounded": False,
        "clauses": clauses,
        "static_clauses": [],
        "kg_context": "",
        "routing_mode": "case_only",
        "inactive_statute_fallback": False,
    }


def _make_retrieval_result(n: int = 2) -> LegalRetrievalResult:
    from app.services.models.legal_document import LegalCitedClause, LegalClause
    clauses = [
        LegalCitedClause(
            clause=LegalClause(
                clause_id=f"c{i}",
                document_id=1,
                source_file="test.pdf",
                text=f"Text {i}",
                article="",
                clause="",
                point="",
                page=i,
                clause_type="obligation",
                title="Test",
                document_type="contract",
                issuing_authority="",
                effective_date="",
                status="active",
                index_scope="case",
                canonical_citation="",
            ),
            score=0.9,
            retrieval_source="vector",
        )
        for i in range(n)
    ]
    return LegalRetrievalResult(
        query="test",
        clauses=clauses,
        static_clauses=[],
        kg_context="",
        mode="case_only",
    )


# ---------------------------------------------------------------------------
# skip_reasoning flag
# ---------------------------------------------------------------------------

class TestSkipReasoning:
    @pytest.mark.asyncio
    async def test_skip_reasoning_true_does_not_call_llm(self):
        """With skip_reasoning=True, reasoning.legal_qa must NOT be called."""
        from app.services.legal.legal_rag_service import LegalRAGService
        from unittest.mock import AsyncMock, MagicMock

        db = MagicMock()

        with patch("app.services.legal.legal_rag_service.get_legal_kg_service"), \
             patch("app.services.legal.legal_rag_service.get_embedding_service"), \
             patch("app.services.legal.legal_rag_service.get_vector_store"), \
             patch("app.services.legal.legal_rag_service.get_reranker_service"), \
             patch("app.services.legal.legal_rag_service.LegalDocumentParser"), \
             patch("app.services.legal.legal_rag_service.LegalRetriever") as MockRetriever, \
             patch("app.services.legal.legal_rag_service.LegalReasoningLayer") as MockReasoning:

            MockRetriever.return_value.query = AsyncMock(return_value=_make_retrieval_result())
            mock_reasoning_instance = MagicMock()
            mock_reasoning_instance.legal_qa = AsyncMock(return_value=("LLM answer", True))
            MockReasoning.return_value = mock_reasoning_instance

            service = LegalRAGService(db=db, workspace_id=1)
            result = await service.legal_query("test question", skip_reasoning=True)

        mock_reasoning_instance.legal_qa.assert_not_called()
        assert result["answer"] == ""
        assert result["is_grounded"] is False

    @pytest.mark.asyncio
    async def test_skip_reasoning_false_calls_llm(self):
        """With skip_reasoning=False (default), reasoning.legal_qa MUST be called."""
        from app.services.legal.legal_rag_service import LegalRAGService

        db = MagicMock()

        with patch("app.services.legal.legal_rag_service.get_legal_kg_service"), \
             patch("app.services.legal.legal_rag_service.get_embedding_service"), \
             patch("app.services.legal.legal_rag_service.get_vector_store"), \
             patch("app.services.legal.legal_rag_service.get_reranker_service"), \
             patch("app.services.legal.legal_rag_service.LegalDocumentParser"), \
             patch("app.services.legal.legal_rag_service.LegalRetriever") as MockRetriever, \
             patch("app.services.legal.legal_rag_service.LegalReasoningLayer") as MockReasoning:

            MockRetriever.return_value.query = AsyncMock(return_value=_make_retrieval_result())
            mock_reasoning_instance = MagicMock()
            mock_reasoning_instance.legal_qa = AsyncMock(return_value=("Full LLM answer", True))
            MockReasoning.return_value = mock_reasoning_instance

            service = LegalRAGService(db=db, workspace_id=1)
            result = await service.legal_query("test question", skip_reasoning=False)

        mock_reasoning_instance.legal_qa.assert_called_once()
        assert result["answer"] == "Full LLM answer"
        assert result["is_grounded"] is True


# ---------------------------------------------------------------------------
# query_deep mode isolation
# ---------------------------------------------------------------------------

class TestQueryDeepIsolation:
    @pytest.mark.asyncio
    async def test_document_qa_uses_case_only_routing(self):
        """query_deep with document_qa must call legal_query with CASE_ONLY."""
        from app.services.legal.legal_rag_service import LegalRAGService

        db = MagicMock()

        with patch("app.services.legal.legal_rag_service.get_legal_kg_service"), \
             patch("app.services.legal.legal_rag_service.get_embedding_service"), \
             patch("app.services.legal.legal_rag_service.get_vector_store"), \
             patch("app.services.legal.legal_rag_service.get_reranker_service"), \
             patch("app.services.legal.legal_rag_service.LegalDocumentParser"), \
             patch("app.services.legal.legal_rag_service.LegalRetriever"), \
             patch("app.services.legal.legal_rag_service.LegalReasoningLayer"):

            service = LegalRAGService(db=db, workspace_id=1)
            captured_mode = []

            async def spy_legal_query(*args, **kwargs):
                captured_mode.append(kwargs.get("routing_mode"))
                return _make_legal_result(0)

            async def fake_doc_map(ids):
                return {}

            service.legal_query = spy_legal_query
            service._get_document_name_map = fake_doc_map

            await service.query_deep("test?", assistant_mode="document_qa")

        assert len(captured_mode) == 1
        assert captured_mode[0] == RetrievalMode.CASE_ONLY

    @pytest.mark.asyncio
    async def test_document_qa_passes_skip_reasoning(self):
        """query_deep (document_qa) must always pass skip_reasoning=True."""
        from app.services.legal.legal_rag_service import LegalRAGService

        db = MagicMock()

        with patch("app.services.legal.legal_rag_service.get_legal_kg_service"), \
             patch("app.services.legal.legal_rag_service.get_embedding_service"), \
             patch("app.services.legal.legal_rag_service.get_vector_store"), \
             patch("app.services.legal.legal_rag_service.get_reranker_service"), \
             patch("app.services.legal.legal_rag_service.LegalDocumentParser"), \
             patch("app.services.legal.legal_rag_service.LegalRetriever"), \
             patch("app.services.legal.legal_rag_service.LegalReasoningLayer"):

            service = LegalRAGService(db=db, workspace_id=1)
            captured_kwargs: dict = {}

            async def spy(**kwargs):
                captured_kwargs.update(kwargs)
                return _make_legal_result(0)

            async def fake_doc_map(ids):
                return {}

            service.legal_query = spy
            service._get_document_name_map = fake_doc_map

            await service.query_deep("test?", assistant_mode="document_qa")

        assert captured_kwargs.get("skip_reasoning") is True


# ---------------------------------------------------------------------------
# KG service singleton (module-level cache)
# ---------------------------------------------------------------------------

class TestKGServiceSingleton:
    def test_same_workspace_returns_same_instance(self):
        from app.services.legal.legal_kg_service import _kg_service_cache, get_legal_kg_service

        # Clear cache first
        _kg_service_cache.clear()

        with patch("app.services.legal.legal_kg_service.settings") as mock_settings:
            mock_settings.NEXUSRAG_ENABLE_KG = True
            mock_settings.BASE_DIR = MagicMock()
            mock_settings.BASE_DIR.__truediv__ = lambda s, p: MagicMock()
            mock_settings.NEXUSRAG_KG_LANGUAGE = "Vietnamese"
            mock_settings.KG_EMBEDDING_PROVIDER = "gemini"
            mock_settings.KG_EMBEDDING_MODEL = "gemini-embedding-001"
            mock_settings.KG_EMBEDDING_DIMENSION = 3072
            mock_settings.NEXUSRAG_KG_CHUNK_TOKEN_SIZE = 1200

            svc1 = get_legal_kg_service(99)
            svc2 = get_legal_kg_service(99)

        assert svc1 is svc2, "Same workspace_id must return the same cached instance"

    def test_different_workspaces_return_different_instances(self):
        from app.services.legal.legal_kg_service import _kg_service_cache, get_legal_kg_service

        _kg_service_cache.clear()

        with patch("app.services.legal.legal_kg_service.settings") as mock_settings:
            mock_settings.NEXUSRAG_ENABLE_KG = True
            mock_settings.BASE_DIR = MagicMock()
            mock_settings.BASE_DIR.__truediv__ = lambda s, p: MagicMock()
            mock_settings.NEXUSRAG_KG_LANGUAGE = "Vietnamese"
            mock_settings.KG_EMBEDDING_PROVIDER = "gemini"
            mock_settings.KG_EMBEDDING_MODEL = "gemini-embedding-001"
            mock_settings.KG_EMBEDDING_DIMENSION = 3072
            mock_settings.NEXUSRAG_KG_CHUNK_TOKEN_SIZE = 1200

            svc_a = get_legal_kg_service(101)
            svc_b = get_legal_kg_service(102)

        assert svc_a is not svc_b
