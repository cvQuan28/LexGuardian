"""
Unit tests for LegalRetriever.

Tests routing mode isolation, RRF fusion, metadata bonuses,
and reranker empty-return behavior — all without a real DB or LLM.
"""
from __future__ import annotations

import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.legal.legal_retriever import LegalRetriever, _rrf_score, RRF_K
from app.services.models.legal_document import (
    LegalClause,
    LegalCitedClause,
    LegalRetrievalResult,
    RetrievalMode,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_clause(
    clause_id: str,
    text: str = "Some clause text.",
    document_id: int = 1,
    index_scope: str = "case",
    status: str = "active",
    document_type: str = "contract",
) -> LegalClause:
    return LegalClause(
        clause_id=clause_id,
        document_id=document_id,
        source_file="test.pdf",
        text=text,
        article="Article 1",
        clause="Clause 1",
        point="",
        page=1,
        clause_type="obligation",
        title="Test Doc",
        document_type=document_type,
        issuing_authority="",
        effective_date="",
        status=status,
        index_scope=index_scope,
        canonical_citation="",
    )


def _make_cited(clause_id: str, score: float = 0.8, **kwargs) -> LegalCitedClause:
    return LegalCitedClause(
        clause=_make_clause(clause_id, **kwargs),
        score=score,
        retrieval_source="vector",
    )


def _make_retriever(mock_embedder, mock_vector_store, mock_reranker, kg_service=None):
    return LegalRetriever(
        workspace_id=1,
        kg_service=kg_service,
        vector_store=mock_vector_store,
        embedder=mock_embedder,
        reranker=mock_reranker,
    )


# ---------------------------------------------------------------------------
# RRF scoring
# ---------------------------------------------------------------------------

class TestRRFScore:
    def test_higher_rank_gives_lower_score(self):
        assert _rrf_score(1) > _rrf_score(2) > _rrf_score(10)

    def test_formula(self):
        assert _rrf_score(1) == pytest.approx(1.0 / (RRF_K + 1))
        assert _rrf_score(60) == pytest.approx(1.0 / (RRF_K + 60))

    def test_large_rank_approaches_zero(self):
        assert _rrf_score(10_000) < 0.0002


# ---------------------------------------------------------------------------
# Metadata bonuses
# ---------------------------------------------------------------------------

class TestMetadataBonuses:
    def test_active_status_gets_bonus(self):
        c = _make_cited("c1", score=0.5, status="active")
        result = LegalRetriever._apply_metadata_bonuses([c])
        assert result[0].score > 0.5

    def test_expired_gets_penalty(self):
        c = _make_cited("c1", score=0.5, status="expired")
        result = LegalRetriever._apply_metadata_bonuses([c])
        assert result[0].score < 0.5

    def test_superseded_gets_penalty(self):
        c = _make_cited("c1", score=0.5, status="superseded")
        result = LegalRetriever._apply_metadata_bonuses([c])
        assert result[0].score < 0.5

    def test_law_doctype_gets_bonus(self):
        c = _make_cited("c1", score=0.5, document_type="law")
        result = LegalRetriever._apply_metadata_bonuses([c])
        assert result[0].score > 0.5

    def test_score_never_negative(self):
        # expired penalty should floor at 0
        c = _make_cited("c1", score=0.0, status="expired")
        result = LegalRetriever._apply_metadata_bonuses([c])
        assert result[0].score >= 0.0

    def test_sorted_descending(self):
        clauses = [
            _make_cited("a", score=0.3, status="active"),   # 0.3 + 0.15 = 0.45
            _make_cited("b", score=0.6, status="expired"),  # 0.6 - 0.30 = 0.30
            _make_cited("c", score=0.5, status="active"),   # 0.5 + 0.15 = 0.65
        ]
        result = LegalRetriever._apply_metadata_bonuses(clauses)
        scores = [r.score for r in result]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# RRF fusion
# ---------------------------------------------------------------------------

class TestRRFFusion:
    def test_deduplication(self):
        """Same clause_id in vector + BM25 → single fused entry."""
        cited = _make_cited("same_id")
        result = LegalRetriever._rrf_fuse([cited], [cited])
        assert len(result) == 1

    def test_combined_score_higher_than_single(self):
        """A result appearing in both lists should outscore one appearing in only one."""
        in_both = _make_cited("both")
        vector_only = _make_cited("vector_only")
        bm25_only = _make_cited("bm25_only")

        fused = LegalRetriever._rrf_fuse([in_both, vector_only], [in_both, bm25_only])
        score_map = {c.clause.clause_id: c.score for c in fused}

        assert score_map["both"] > score_map["vector_only"]
        assert score_map["both"] > score_map["bm25_only"]

    def test_empty_inputs(self):
        assert LegalRetriever._rrf_fuse([], []) == []

    def test_order_descending(self):
        c1 = _make_cited("c1")
        c2 = _make_cited("c2")
        c3 = _make_cited("c3")
        result = LegalRetriever._rrf_fuse([c1, c2, c3], [c1])
        scores = [r.score for r in result]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Reranker empty-return (the "wrong sources" regression fix)
# ---------------------------------------------------------------------------

class TestRerankerEmptyReturn:
    def test_reranker_filtered_all_returns_empty(self, mock_embedder, mock_vector_store):
        """When reranker filters ALL candidates below min_score → return []."""
        reranker = MagicMock()
        reranker.rerank.return_value = []  # all filtered

        retriever = _make_retriever(mock_embedder, mock_vector_store, reranker)
        candidates = [_make_cited("c1"), _make_cited("c2")]
        result = retriever._rerank("any question", candidates, top_k=5)

        assert result == [], "Must return empty when reranker filters all"

    def test_reranker_partial_return(self, mock_embedder, mock_vector_store):
        """Reranker returning a subset → that subset is returned."""
        from app.services.reranker import RerankResult

        reranker = MagicMock()
        # reranker returns index=0 (first candidate "kept"), filtered out index=1
        reranker.rerank.return_value = [RerankResult(index=0, score=0.9, text="Some clause text.")]

        retriever = _make_retriever(mock_embedder, mock_vector_store, reranker)
        candidates = [_make_cited("kept"), _make_cited("filtered")]
        result = retriever._rerank("question", candidates, top_k=5)

        assert len(result) == 1
        assert result[0].clause.clause_id == "kept"

    def test_empty_candidates_skips_reranker(self, mock_embedder, mock_vector_store):
        reranker = MagicMock()
        retriever = _make_retriever(mock_embedder, mock_vector_store, reranker)
        result = retriever._rerank("question", [], top_k=5)
        reranker.rerank.assert_not_called()
        assert result == []


# ---------------------------------------------------------------------------
# KG query — timeout and graceful failure
# ---------------------------------------------------------------------------

class TestKGQuery:
    @pytest.mark.asyncio
    async def test_kg_timeout_returns_empty_string(self, mock_embedder, mock_vector_store, mock_reranker):
        """KG query timeout → returns '' and continues (non-fatal)."""
        async def slow_context(_):
            await asyncio.sleep(100)  # will time out
            return "should not return"

        kg = AsyncMock()
        kg.get_legal_context = slow_context

        retriever = _make_retriever(mock_embedder, mock_vector_store, mock_reranker, kg)

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.NEXUSRAG_KG_QUERY_TIMEOUT = 0.01
            result = await retriever._kg_query("test question")

        assert result == ""

    @pytest.mark.asyncio
    async def test_no_kg_service_returns_empty(self, mock_embedder, mock_vector_store, mock_reranker):
        retriever = _make_retriever(mock_embedder, mock_vector_store, mock_reranker, kg_service=None)
        result = await retriever._kg_query("test question")
        assert result == ""


# ---------------------------------------------------------------------------
# Mode isolation — CASE_ONLY never touches static index
# ---------------------------------------------------------------------------

class TestModeIsolation:
    @pytest.mark.asyncio
    async def test_case_only_does_not_call_static_index(
        self, mock_embedder, mock_vector_store, mock_reranker, mock_kg_service
    ):
        retriever = _make_retriever(mock_embedder, mock_vector_store, mock_reranker, mock_kg_service)
        static_mock = MagicMock()
        retriever._static_index = static_mock

        with patch.object(retriever, "_vector_query", return_value=[]), \
             patch.object(retriever, "_bm25_query", return_value=[]):
            result = await retriever.query(
                "test question",
                routing_mode=RetrievalMode.CASE_ONLY,
            )

        static_mock.query.assert_not_called()
        assert result.mode == "case_only"

    @pytest.mark.asyncio
    async def test_static_only_does_not_call_case_vector(
        self, mock_embedder, mock_vector_store, mock_reranker, mock_kg_service
    ):
        retriever = _make_retriever(mock_embedder, mock_vector_store, mock_reranker, mock_kg_service)
        static_mock = MagicMock()
        static_mock.query.return_value = []
        retriever._static_index = static_mock

        with patch.object(retriever, "_vector_query", return_value=[]) as mock_vec, \
             patch.object(retriever, "_bm25_query", return_value=[]) as mock_bm25, \
             patch.object(retriever, "_static_vector_query", return_value=[]):
            result = await retriever.query(
                "test question",
                routing_mode=RetrievalMode.STATIC_ONLY,
            )

        mock_vec.assert_not_called()
        mock_bm25.assert_not_called()
        assert result.mode == "static_only"
