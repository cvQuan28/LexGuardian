"""
Legal Retriever
================

Hybrid retrieval pipeline for legal documents:
  1. BM25 keyword search (optional, requires rank_bm25)
  2. Vector search (ChromaDB, existing embedding service)
  3. KG context (LegalKGService)
  4. Reciprocal Rank Fusion (RRF) to merge BM25 + vector results
  5. Cross-encoder reranking (existing RerankerService)

Metadata filtering:
  - By clause_id
  - By article
  - By clause_type (obligation, penalty, right, etc.)
  - By document_id
"""
from __future__ import annotations

import asyncio
import logging
import math
from typing import Optional

from app.core.config import settings
from app.services.embedder import EmbeddingService
from app.services.vector_store import VectorStore
from app.services.reranker import RerankerService, get_reranker_service
from app.services.models.legal_document import (
    LegalClause,
    LegalCitedClause,
    LegalRetrievalResult,
    RetrievalMode,
)
from app.services.legal.legal_kg_service import LegalKGService

logger = logging.getLogger(__name__)

# RRF constant — standard value is 60 (Robertson & Zaragoza, 2009)
RRF_K = 60

# Metadata bonus/penalty weights (Spec 07)
_STATUS_BONUS = {"active": 0.15, "expired": -0.30, "superseded": -0.20, "pending": -0.05}
_DOCTYPE_BONUS = {"law": 0.05, "code": 0.05, "decree": 0.02, "circular": 0.0}


def _rrf_score(rank: int) -> float:
    """Reciprocal Rank Fusion score for a given 1-indexed rank."""
    return 1.0 / (RRF_K + rank)


class LegalRetriever:
    """
    Clause-level hybrid retriever for legal documents.

    Supports three routing modes (Phase 4 — Spec 02 / 07):
      RetrievalMode.CASE_ONLY   — workspace case index only (default / backward-compat)
      RetrievalMode.STATIC_ONLY — statutory corpus only   (regulatory_lookup)
      RetrievalMode.MIXED       — both pools merged        (contract_risk_analysis)

    Fusion pipeline (per active mode):
      BM25(top-N) + Vector(top-N)  →  RRF merge  →  metadata bonus/penalty  →  rerank(top-K)
      + KG context (separate, added to context string)
    """

    def __init__(
        self,
        workspace_id: int,
        kg_service: Optional[LegalKGService],
        vector_store: VectorStore,
        embedder: EmbeddingService,
        reranker: Optional[RerankerService] = None,
        static_index=None,          # Optional[LegalStaticIndexService] — lazy import
    ):
        self.workspace_id = workspace_id
        self.kg_service = kg_service
        self.vector_store = vector_store
        self.embedder = embedder
        self.reranker = reranker or get_reranker_service()
        self._static_index = static_index  # set lazily or injected

        # BM25 in-memory index (rebuilt on demand, lazy)
        self._bm25_corpus: list[str] = []
        self._bm25_metadata: list[dict] = []
        self._bm25_model = None

    @property
    def static_index(self):
        """Lazy-load LegalStaticIndexService to avoid circular imports."""
        if self._static_index is None and settings.LEGAL_STATIC_INDEX_ENABLED:
            from app.services.legal.legal_static_index_service import LegalStaticIndexService
            self._static_index = LegalStaticIndexService(embedder=self.embedder)
        return self._static_index

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def query(
        self,
        question: str,
        top_k: int = 8,
        document_ids: Optional[list[int]] = None,
        clause_types: Optional[list[str]] = None,
        articles: Optional[list[str]] = None,
        prefetch_n: int = 20,
        # Phase 4 — routing & static filters
        routing_mode: RetrievalMode = RetrievalMode.CASE_ONLY,
        static_statuses: Optional[list[str]] = None,
        static_doc_types: Optional[list[str]] = None,
        static_field_tags: Optional[list[str]] = None,
    ) -> LegalRetrievalResult:
        """
        Execute hybrid legal retrieval.

        Args:
            question:         Natural language query.
            top_k:            Final number of clauses to return (after reranking).
            document_ids:     Optional filter to specific case documents.
            clause_types:     Optional filter by clause type (e.g. ["obligation"]).
            articles:         Optional filter by article (e.g. ["Article 5"]).
            prefetch_n:       How many results to fetch before reranking.
            routing_mode:     CASE_ONLY | STATIC_ONLY | MIXED (Phase 4).
            static_statuses:  Optional ["active"] filter for static queries.
            static_doc_types: Optional ["law", "decree"] filter for static queries.
            static_field_tags: Optional field domain filter for static queries.

        Returns:
            LegalRetrievalResult with ranked clauses, static_clauses, and KG context.
        """
        # --- KG is always queried (parallel) regardless of mode ---
        kg_task = asyncio.create_task(self._kg_query(question))

        # --- Case index retrieval (CASE_ONLY or MIXED) ---
        case_vector_results: list[LegalCitedClause] = []
        case_bm25_results: list[LegalCitedClause] = []
        if routing_mode in (RetrievalMode.CASE_ONLY, RetrievalMode.MIXED):
            vector_task = asyncio.create_task(
                asyncio.to_thread(
                    self._vector_query, question, prefetch_n, document_ids, clause_types, articles,
                )
            )
            bm25_task = asyncio.create_task(
                asyncio.to_thread(
                    self._bm25_query, question, prefetch_n, document_ids, clause_types,
                )
            )
            case_vector_results = await vector_task
            case_bm25_results = await bm25_task

        # --- Static index retrieval (STATIC_ONLY or MIXED) ---
        static_results: list[LegalCitedClause] = []
        if routing_mode in (RetrievalMode.STATIC_ONLY, RetrievalMode.MIXED):
            static_results = await asyncio.to_thread(
                self._static_vector_query,
                question,
                prefetch_n,
                static_statuses,
                static_doc_types,
                static_field_tags,
            )

        kg_context = ""
        try:
            kg_context = await kg_task
        except Exception as e:
            logger.warning(f"Legal KG query failed, continuing: {e}")

        # --- RRF fusion of case results ---
        fused_case = self._rrf_fuse(case_vector_results, case_bm25_results)

        # --- Apply metadata bonuses/penalties (Spec 07) ---
        fused_case = self._apply_metadata_bonuses(fused_case)
        static_results = self._apply_metadata_bonuses(static_results)

        # --- For MIXED mode: merge and re-sort both pools ---
        if routing_mode == RetrievalMode.MIXED:
            combined = fused_case + static_results
            combined.sort(key=lambda c: c.score, reverse=True)
            final_candidates = combined
        elif routing_mode == RetrievalMode.STATIC_ONLY:
            final_candidates = static_results
        else:
            final_candidates = fused_case

        # --- Cross-encoder reranking ---
        final_clauses = await asyncio.to_thread(
            self._rerank, question, final_candidates, top_k
        )

        # Segregate static vs case in result for callers that need both
        result_static = [c for c in final_clauses if c.clause.index_scope == "static"]
        result_case   = [c for c in final_clauses if c.clause.index_scope != "static"]

        logger.info(
            f"LegalRetriever [{routing_mode.value}]: "
            f"{len(result_case)} case + {len(result_static)} static clauses returned "
            f"(kg={'yes' if kg_context else 'no'})"
        )

        return LegalRetrievalResult(
            query=question,
            clauses=final_clauses,
            static_clauses=result_static,
            kg_context=kg_context,
            mode=routing_mode.value,
        )

    # ------------------------------------------------------------------
    # KG retrieval
    # ------------------------------------------------------------------

    async def _kg_query(self, question: str) -> str:
        """Get legal KG context."""
        if not self.kg_service:
            return ""
        try:
            return await asyncio.wait_for(
                self.kg_service.get_legal_context(question),
                timeout=settings.NEXUSRAG_KG_QUERY_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("Legal KG query timed out")
            return ""
        except Exception as e:
            logger.warning(f"Legal KG query error: {e}")
            return ""

    # ------------------------------------------------------------------
    # Static index retrieval (Phase 4)
    # ------------------------------------------------------------------

    def _static_vector_query(
        self,
        question: str,
        top_n: int,
        statuses: Optional[list[str]],
        doc_types: Optional[list[str]],
        field_tags: Optional[list[str]],
    ) -> list[LegalCitedClause]:
        """Query the global static legal corpus via LegalStaticIndexService."""
        svc = self.static_index
        if svc is None:
            logger.debug("Static index not available (LEGAL_STATIC_INDEX_ENABLED=false or not injected).")
            return []

        query_embedding = self.embedder.embed_query(question)

        def _run_query(
            use_statuses: Optional[list[str]],
            use_doc_types: Optional[list[str]],
        ) -> list[LegalCitedClause]:
            conditions = [{"index_scope": {"$eq": "static"}}]
            if use_statuses:
                expanded_statuses = list(use_statuses)
                if "active" in [s.lower() for s in use_statuses]:
                    expanded_statuses = list(dict.fromkeys([*expanded_statuses, ""]))
                conditions.append({"status": {"$in": expanded_statuses}})
            if use_doc_types:
                conditions.append({"document_type": {"$in": use_doc_types}})
            where = {"$and": conditions} if len(conditions) > 1 else conditions[0]
            return svc.query_statutes(
                query_embedding=query_embedding,
                n_results=top_n,
                where=where,
            )

        # Field tags in the current corpus are not normalized consistently.
        # Do not use them as a hard filter yet; use them only as planning hints.
        results = _run_query(statuses, doc_types)
        if results:
            return results

        if statuses:
            logger.info("Static retrieval returned 0 results; retrying without status filter")
            results = _run_query(None, doc_types)
            if results:
                return results

        if doc_types:
            logger.info("Static retrieval still empty; retrying without document_type filter")
            results = _run_query(None, None)
            if results:
                return results

        return results

    # ------------------------------------------------------------------
    # Vector retrieval
    # ------------------------------------------------------------------

    def _vector_query(
        self,
        question: str,
        top_n: int,
        document_ids: Optional[list[int]],
        clause_types: Optional[list[str]],
        articles: Optional[list[str]],
    ) -> list[LegalCitedClause]:
        """ChromaDB vector search with metadata filtering."""
        query_embedding = self.embedder.embed_query(question)

        # Build ChromaDB where filter
        where = self._build_where_filter(document_ids, clause_types, articles)

        results = self.vector_store.query(
            query_embedding=query_embedding,
            n_results=top_n,
            where=where,
        )

        clauses = []
        for i, doc_text in enumerate(results.get("documents", [])):
            meta = results["metadatas"][i] if results.get("metadatas") else {}
            clause = self._meta_to_clause(doc_text, meta)
            dist = results["distances"][i] if results.get("distances") else [0.0]
            score = 1.0 - (dist[0] if isinstance(dist, list) else dist)
            clauses.append(LegalCitedClause(
                clause=clause,
                score=score,
                retrieval_source="vector",
            ))

        return clauses

    # ------------------------------------------------------------------
    # BM25 retrieval
    # ------------------------------------------------------------------

    def _bm25_query(
        self,
        question: str,
        top_n: int,
        document_ids: Optional[list[int]],
        clause_types: Optional[list[str]],
    ) -> list[LegalCitedClause]:
        """
        BM25 keyword search using rank_bm25.
        Falls back to empty list if rank_bm25 is not installed.
        """
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.debug("rank_bm25 not installed — BM25 disabled")
            return []

        try:
            corpus_docs, corpus_meta = self._get_bm25_corpus(document_ids, clause_types)
        except Exception as e:
            logger.warning(f"BM25 corpus build failed: {e}")
            return []

        if not corpus_docs:
            return []

        # Tokenize (simple whitespace tokenization)
        tokenized_corpus = [doc.lower().split() for doc in corpus_docs]
        bm25 = BM25Okapi(tokenized_corpus)

        query_tokens = question.lower().split()
        scores = bm25.get_scores(query_tokens)

        # Get top_n indices
        top_indices = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True,
        )[:top_n]

        results = []
        for idx in top_indices:
            if scores[idx] <= 0:
                continue
            meta = corpus_meta[idx]
            clause = self._meta_to_clause(corpus_docs[idx], meta)
            results.append(LegalCitedClause(
                clause=clause,
                score=float(scores[idx]),
                retrieval_source="bm25",
            ))

        return results

    def _get_bm25_corpus(
        self,
        document_ids: Optional[list[int]],
        clause_types: Optional[list[str]],
    ) -> tuple[list[str], list[dict]]:
        """
        Fetch all documents from PGVector to build the BM25 corpus.
        This is O(N) on the collection but is done in-memory.
        """
        try:
            # Get all docs from vector store via get_all()
            where = {}
            if document_ids:
                where["document_id"] = {"$in": document_ids}
            if clause_types:
                where["clause_type"] = {"$in": clause_types}

            all_results = self.vector_store.get_all(
                where=where if where else None,
            )

            docs = all_results.get("documents", []) or []
            metas = all_results.get("metadatas", []) or []
            return docs, metas
        except Exception as e:
            logger.warning(f"PGVector get for BM25 failed: {e}")
            return [], []

    # ------------------------------------------------------------------
    # RRF fusion
    # ------------------------------------------------------------------

    @staticmethod
    def _rrf_fuse(
        vector_results: list[LegalCitedClause],
        bm25_results: list[LegalCitedClause],
    ) -> list[LegalCitedClause]:
        """
        Reciprocal Rank Fusion: merge two ranked lists into one.

        Each result is identified by clause_id.  Results appearing
        in both lists get an additive RRF boost.
        """
        # clause_id → cumulative RRF score
        rrf_scores: dict[str, float] = {}
        # clause_id → LegalCitedClause (first seen wins)
        clause_map: dict[str, LegalCitedClause] = {}

        for rank, cited in enumerate(vector_results, start=1):
            cid = cited.clause.clause_id
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + _rrf_score(rank)
            if cid not in clause_map:
                clause_map[cid] = cited

        for rank, cited in enumerate(bm25_results, start=1):
            cid = cited.clause.clause_id
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + _rrf_score(rank)
            if cid not in clause_map:
                clause_map[cid] = LegalCitedClause(
                    clause=cited.clause,
                    score=cited.score,
                    retrieval_source="bm25+vector",
                )

        # Sort by RRF score descending
        sorted_ids = sorted(rrf_scores, key=lambda k: rrf_scores[k], reverse=True)
        return [
            LegalCitedClause(
                clause=clause_map[cid].clause,
                score=rrf_scores[cid],
                retrieval_source=clause_map[cid].retrieval_source,
            )
            for cid in sorted_ids
        ]

    # ------------------------------------------------------------------
    # Metadata bonus/penalty scoring (Phase 4 — Spec 07)
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_metadata_bonuses(candidates: list[LegalCitedClause]) -> list[LegalCitedClause]:
        """Apply status + document-type bonuses/penalties then re-sort.

        Bonuses per Spec 07:
          active_status_bonus:    +0.15
          expired_penalty:        –0.30
          superseded_penalty:     –0.20
          law/code priority:      +0.05
          decree priority:        +0.02
        """
        for c in candidates:
            status = (c.clause.status or "").lower()
            c.score += _STATUS_BONUS.get(status, 0.0)
            dtype = (c.clause.document_type or "").lower()
            c.score += _DOCTYPE_BONUS.get(dtype, 0.0)
            c.score = max(0.0, c.score)
        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates

    # ------------------------------------------------------------------
    # Reranking
    # ------------------------------------------------------------------

    def _rerank(
        self,
        question: str,
        candidates: list[LegalCitedClause],
        top_k: int,
    ) -> list[LegalCitedClause]:
        """Cross-encoder reranking of fused candidates."""
        if not candidates:
            return []

        doc_texts = [c.clause.text for c in candidates]
        reranked = self.reranker.rerank(
            query=question,
            documents=doc_texts,
            top_k=top_k,
            min_score=settings.NEXUSRAG_MIN_RELEVANCE_SCORE,
        )

        if not reranked:
            logger.warning(
                f"Legal reranker filtered all {len(candidates)} candidates "
                f"(min_score={settings.NEXUSRAG_MIN_RELEVANCE_SCORE}) — returning empty"
            )
            return []

        result = []
        for r in reranked:
            cited = candidates[r.index]
            result.append(LegalCitedClause(
                clause=cited.clause,
                score=r.score,
                retrieval_source=cited.retrieval_source,
            ))

        logger.info(
            f"Legal reranker: {len(candidates)} → {len(result)} clauses "
            f"(scores: {result[0].score:.3f} → {result[-1].score:.3f})"
        )
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_where_filter(
        document_ids: Optional[list[int]],
        clause_types: Optional[list[str]],
        articles: Optional[list[str]],
    ) -> Optional[dict]:
        """Build ChromaDB $and where filter from optional filters."""
        conditions = []
        if document_ids:
            conditions.append({"document_id": {"$in": document_ids}})
        if clause_types:
            conditions.append({"clause_type": {"$in": clause_types}})
        if articles:
            conditions.append({"article": {"$in": articles}})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    @staticmethod
    def _meta_to_clause(text: str, meta: dict) -> LegalClause:
        """Reconstruct a LegalClause from ChromaDB metadata."""
        parties_raw = meta.get("parties_mentioned", "")
        parties = [p for p in parties_raw.split("|") if p] if parties_raw else []
        field_tags_raw = meta.get("field_tags", "")
        field_tags = [t for t in field_tags_raw.split("|") if t] if field_tags_raw else []

        return LegalClause(
            clause_id=meta.get("clause_id", ""),
            document_id=meta.get("document_id", 0),
            source_file=meta.get("source", ""),
            text=text,
            article=meta.get("article", ""),
            clause=meta.get("clause", ""),
            point=meta.get("point", ""),
            page=meta.get("page_no", 0),
            clause_type=meta.get("clause_type", "general"),
            parties_mentioned=parties,
            chunk_index=meta.get("chunk_index", 0),
            title=meta.get("title", ""),
            document_type=meta.get("document_type", ""),
            issuing_authority=meta.get("issuing_authority", ""),
            issued_date=meta.get("issued_date", ""),
            effective_date=meta.get("effective_date", ""),
            expiry_date=meta.get("expiry_date", ""),
            status=meta.get("status", ""),
            field_tags=field_tags,
            summary_text=meta.get("summary_text", ""),
            index_scope=meta.get("index_scope", "case"),
            canonical_citation=meta.get("canonical_citation", ""),
            # Phase 1 additions
            section_path=meta.get("section_path", ""),
            chunk_kind=meta.get("chunk_kind", "clause"),
        )
