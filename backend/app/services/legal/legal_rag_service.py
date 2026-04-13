"""
Legal RAG Service (Orchestrator)
==================================

Top-level orchestrator for the Legal AI pipeline.

Phases:
  PARSING  → LegalDocumentParser  → LegalClause[]
  CHUNKING → ClauseChunker        → ClauseChunk[] (clause-level, no splitting)
  INDEXING → ChromaDB embed       + LegalKGService ingest
  INDEXED  → ready for retrieval

Query pipeline:
  LegalRetriever (BM25 + vector + KG) → LegalReasoningLayer → grounded answer

Exposes the same core interface as NexusRAGService for drop-in use:
  process_document(), query(), query_deep(), delete_document(), get_chunk_count()
Plus new legal-specific methods:
  analyze_contract_risk(), compare_clauses(), detect_missing_clauses(),
  summarize_obligations(), legal_query()
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional
from types import SimpleNamespace
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.core.config import settings
from app.models.document import Document, DocumentStatus
from app.services.embedder import EmbeddingService, get_embedding_service
from app.services.vector_store import VectorStore, get_vector_store
from app.services.reranker import get_reranker_service
from app.services.legal.legal_parser import LegalDocumentParser
from app.services.legal.clause_chunker import ClauseChunker
from app.services.legal.legal_kg_service import LegalKGService
from app.services.legal.legal_retriever import LegalRetriever
from app.services.legal.legal_reasoning import LegalReasoningLayer
from app.services.legal.legal_router import detect_domain
from app.services.legal.contract_extractor import (
    ContractFieldExtractor,
    extract_with_llm_fallback,
    ContractFields,
)
from app.services.legal.kg_relationship_builder import (
    HybridRelationshipExtractor,
    build_relationship_enriched_text,
    KGRelationship,
)
from app.services.models.legal_document import (
    LegalCitedClause,
    LegalRetrievalResult,
    RetrievalMode,           # Phase 4
    ContractRiskReport,
    ClauseComparison,
    MissingClause,
    ObligationSummary,
)

logger = logging.getLogger(__name__)


@dataclass
class LegalCitation:
    """Compatibility citation model for legacy /rag/* response builders."""
    source_file: str
    document_id: int
    page_no: int = 0
    heading_path: list[str] = None
    formatted_text: str = ""

    def __post_init__(self):
        if self.heading_path is None:
            self.heading_path = []

    def format(self) -> str:
        return self.formatted_text or self.source_file


class LegalRAGService:
    """
    Legal AI pipeline orchestrator.

    This service can be used alongside the existing NexusRAGService.
    It stores legal clauses in a separate ChromaDB collection
    (prefixed with "legal_") to avoid mixing with generic chunks.
    """

    def __init__(self, db: AsyncSession, workspace_id: int):
        self.db = db
        self.workspace_id = workspace_id

        # Core services (reuse existing infrastructure)
        self.parser = LegalDocumentParser(workspace_id=workspace_id)
        self.chunker = ClauseChunker()
        self.embedder: EmbeddingService = get_embedding_service()

        # Use a separate vector store collection for legal documents
        self.vector_store: VectorStore = get_vector_store(
            workspace_id,
            collection_suffix="_legal",
        )

        # Legal KG service
        self.kg_service: Optional[LegalKGService] = None
        if settings.NEXUSRAG_ENABLE_KG:
            self.kg_service = LegalKGService(workspace_id=workspace_id)

        # Retriever and reasoning
        # Phase 4: static_index is injected lazily inside LegalRetriever via property
        self.retriever = LegalRetriever(
            workspace_id=workspace_id,
            kg_service=self.kg_service,
            vector_store=self.vector_store,
            embedder=self.embedder,
            reranker=get_reranker_service(),
            # static_index is resolved on-demand when LEGAL_STATIC_INDEX_ENABLED=true
        )
        self.reasoning = LegalReasoningLayer()
        self._field_extractor = ContractFieldExtractor()
        # Phase 5: agentic workflow (lazy init to avoid import cost)
        self._agent_workflow = None
        self._intent_router = None
        self._web_searcher = None
        self._risk_analysis_agent = None

    # ------------------------------------------------------------------
    # Document Processing
    # ------------------------------------------------------------------

    async def process_document(self, document_id: int, file_path: str) -> int:
        """
        Process a legal document through the full Legal AI pipeline.

        Returns:
            Number of clause chunks created
        """
        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()
        if document is None:
            raise ValueError(f"Document {document_id} not found")

        start_time = time.time()

        try:
            # Phase 1: PARSING
            document.status = DocumentStatus.PARSING
            await self.db.commit()

            parse_result = self.parser.parse(
                file_path=file_path,
                document_id=document_id,
                original_filename=document.original_filename,
            )

            # Save markdown to DB
            document.markdown_content = parse_result.markdown
            document.page_count = parse_result.page_count
            document.parser_version = "legal_docling"
            await self.db.commit()

            # Phase 2: INDEXING
            document.status = DocumentStatus.INDEXING
            await self.db.commit()

            # Clause-level chunking
            chunks = self.chunker.chunk(parse_result)

            chunk_count = 0
            if chunks:
                chunk_texts = [c.content for c in chunks]
                embeddings = self.embedder.embed_texts(chunk_texts)
                ids = [c.chunk_id for c in chunks]
                metadatas = [c.metadata for c in chunks]

                self.vector_store.add_documents(
                    ids=ids,
                    embeddings=embeddings,
                    documents=chunk_texts,
                    metadatas=metadatas,
                )
                chunk_count = len(chunks)

            # KG ingest with legal markdown
            if self.kg_service and parse_result.markdown:
                try:
                    await self.kg_service.ingest(parse_result.markdown)
                except Exception as e:
                    logger.error(
                        f"Legal KG ingest failed for document {document_id}: {e}"
                    )

            # Phase 3: INDEXED
            elapsed_ms = int((time.time() - start_time) * 1000)
            document.status = DocumentStatus.INDEXED
            document.chunk_count = chunk_count
            document.processing_time_ms = elapsed_ms
            await self.db.commit()

            logger.info(
                f"LegalRAG processed document {document_id}: "
                f"{chunk_count} clause chunks, {parse_result.page_count} pages "
                f"in {elapsed_ms}ms"
            )
            return chunk_count

        except Exception as e:
            logger.error(f"LegalRAG failed for document {document_id}: {e}")
            document.status = DocumentStatus.FAILED
            document.error_message = str(e)[:500]
            await self.db.commit()
            raise

    # ------------------------------------------------------------------
    # Legal QA — with strict grounding
    # ------------------------------------------------------------------

    async def legal_query(
        self,
        question: str,
        top_k: int = 8,
        document_ids: Optional[list[int]] = None,
        clause_types: Optional[list[str]] = None,
        articles: Optional[list[str]] = None,
        # Phase 4 — routing
        routing_mode: Optional[RetrievalMode] = None,
        static_statuses: Optional[list[str]] = None,
        static_doc_types: Optional[list[str]] = None,
        static_field_tags: Optional[list[str]] = None,
    ) -> dict:
        """
        Answer a legal question with strict grounding.

        routing_mode defaults to auto-detection based on question content:
          - regulatory_lookup  → STATIC_ONLY
          - contract question  → CASE_ONLY
          - all others         → MIXED (if static index enabled) else CASE_ONLY

        Returns:
            {
              "answer": str,
              "is_grounded": bool,
              "clauses": [citation dicts],
              "static_clauses": [citation dicts],  # Phase 4
              "kg_context": str,
              "routing_mode": str,                 # Phase 4
            }
        """
        effective_mode = routing_mode or self._detect_routing_mode(question, document_ids)

        # For STATIC_ONLY, prefer active documents by default
        if effective_mode == RetrievalMode.STATIC_ONLY and static_statuses is None:
            static_statuses = ["active"]

        retrieval = await self.retriever.query(
            question=question,
            top_k=top_k,
            document_ids=document_ids,
            clause_types=clause_types,
            articles=articles,
            routing_mode=effective_mode,
            static_statuses=static_statuses,
            static_doc_types=static_doc_types,
            static_field_tags=static_field_tags,
        )

        # Warn caller if only inactive statutes are available (Spec 07 fallback policy)
        inactive_only = (
            bool(retrieval.static_clauses)
            and all(
                (c.clause.status or "").lower() in {"expired", "superseded"}
                for c in retrieval.static_clauses
            )
        )

        answer, is_grounded = await self.reasoning.legal_qa(question, retrieval)

        return {
            "answer": answer,
            "is_grounded": is_grounded,
            "clauses": [
                {
                    "clause_id": c.clause.clause_id,
                    "document_id": c.clause.document_id,
                    "reference": c.clause.format_reference(),
                    "text": c.clause.text,
                    "article": c.clause.article,
                    "clause": c.clause.clause,
                    "point": c.clause.point,
                    "page": c.clause.page,
                    "clause_type": c.clause.clause_type,
                    "score": c.score,
                    "retrieval_source": c.retrieval_source,
                    "title": c.clause.title,
                    "document_type": c.clause.document_type,
                    "issuing_authority": c.clause.issuing_authority,
                    "effective_date": c.clause.effective_date,
                    "status": c.clause.status,
                    "index_scope": c.clause.index_scope,
                    "canonical_citation": c.clause.canonical_citation,
                }
                for c in retrieval.clauses
            ],
            "static_clauses": [
                {
                    "clause_id": c.clause.clause_id,
                    "reference": c.clause.format_reference(),
                    "status": c.clause.status,
                    "document_type": c.clause.document_type,
                    "score": c.score,
                    "canonical_citation": c.clause.canonical_citation,
                    "text": c.clause.text[:400],
                }
                for c in retrieval.static_clauses
            ],
            "kg_context": retrieval.kg_context,
            "routing_mode": effective_mode.value,
            "inactive_statute_fallback": inactive_only,
        }

    async def query_deep(
        self,
        question: str,
        top_k: int = 5,
        document_ids: Optional[list[int]] = None,
        mode: str = "hybrid",
        include_images: bool = True,
        assistant_mode: str = "document_qa",
    ):
        """
        Compatibility layer for legacy /rag/* and chat endpoints.

        Returns a lightweight object with the same attributes used by the
        old NexusRAG response builders: query, chunks, citations,
        knowledge_graph_summary, context, and image_refs.
        """
        if assistant_mode == "legal_consultation":
            legal_result = await self._run_consultation_query_deep(
                question=question,
                top_k=max(top_k, 8),
            )
        else:
            legal_result = await self.smart_legal_query(
                question=question,
                top_k=top_k,
                document_ids=document_ids,
            )
            # Auto-fallback: if document_qa returns nothing and caller didn't
            # pin to specific documents, escalate to consultation + live search.
            # This covers: (a) docs not yet indexed, (b) general legal questions
            # that have no matching workspace content.
            if not legal_result.get("clauses") and not document_ids:
                logger.info(
                    "[query_deep] document_qa returned 0 clauses with no doc scope — "
                    "escalating to legal_consultation with live-search fallback"
                )
                legal_result = await self._run_consultation_query_deep(
                    question=question,
                    top_k=max(top_k, 8),
                )

        chunks = []
        citations = []
        context_parts: list[str] = []
        doc_name_map = await self._get_document_name_map(
            [
                int(item.get("document_id", 0) or 0)
                for item in legal_result["clauses"]
                if int(item.get("document_id", 0) or 0) > 0
            ]
        )

        for idx, item in enumerate(legal_result["clauses"]):
            heading_path = [
                part for part in [item.get("article"), item.get("clause"), item.get("point")] if part
            ]
            source_file = self._build_source_label(item, doc_name_map)
            formatted_ref = self._build_formatted_reference(item, source_file)
            chunk = SimpleNamespace(
                content=item.get("text", ""),
                document_id=int(item.get("document_id", 0) or 0),
                chunk_index=idx,
                page_no=int(item.get("page", 0) or 0),
                heading_path=heading_path,
                source_file=source_file,
                image_refs=[],
                score=float(item.get("score", 0.0) or 0.0),
                index_scope=item.get("index_scope", "case"),
            )
            citation = LegalCitation(
                source_file=source_file,
                document_id=int(item.get("document_id", 0) or 0),
                page_no=int(item.get("page", 0) or 0),
                heading_path=heading_path,
                formatted_text=formatted_ref,
            )
            chunks.append(chunk)
            citations.append(citation)
            context_parts.append(f"[{idx + 1}] {citation.format()}\n{chunk.content}")

        return SimpleNamespace(
            query=question,
            chunks=chunks,
            citations=citations,
            knowledge_graph_summary=legal_result.get("kg_context", ""),
            context="\n\n---\n\n".join(context_parts),
            image_refs=[],
        )

    async def _run_consultation_query_deep(
        self,
        *,
        question: str,
        top_k: int,
    ) -> dict:
        """Consultation-mode retrieval with intent routing and live-search fallback."""
        planning = detect_domain(question)
        planned_query = planning.rewritten_query or question
        static_doc_types = planning.static_doc_types_hint or None
        static_field_tags = planning.field_tags_hint or None
        router_result = await self.route_legal_intent(question=question, chat_history=[])
        intent = str(router_result.get("intent", "INTERNAL_RECALL"))

        if intent == "LIVE_SEARCH":
            live_result = await self._build_live_search_legal_result(question, top_k=top_k)
            live_result["rewritten_query"] = planned_query
            live_result["field_tags_filter"] = static_field_tags
            live_result["static_doc_types_filter"] = static_doc_types
            live_result["intent"] = intent
            return live_result

        if settings.LEGAL_STATIC_INDEX_ENABLED:
            active_only = self._should_prefer_active_statutes_only(question)
            static_statuses = ["active"] if active_only else None
            legal_result = await self.legal_query(
                question=planned_query,
                top_k=top_k,
                document_ids=None,
                routing_mode=RetrievalMode.STATIC_ONLY,
                static_statuses=static_statuses,
                static_doc_types=static_doc_types,
                static_field_tags=static_field_tags,
            )
            if not legal_result.get("clauses"):
                logger.info(
                    "[legal_consultation] STATIC_ONLY returned no clauses; retrying MIXED fallback"
                )
                legal_result = await self.legal_query(
                    question=planned_query,
                    top_k=top_k,
                    document_ids=None,
                    routing_mode=RetrievalMode.MIXED,
                    static_statuses=static_statuses,
                    static_doc_types=static_doc_types,
                    static_field_tags=static_field_tags,
                )
        else:
            legal_result = await self.smart_legal_query(
                question=question,
                top_k=top_k,
                document_ids=None,
            )

        if not legal_result.get("clauses"):
            logger.info(
                "[legal_consultation] No internal legal clauses found; falling back to trusted live search"
            )
            live_result = await self._build_live_search_legal_result(question, top_k=top_k)
            live_result["rewritten_query"] = planned_query
            live_result["field_tags_filter"] = static_field_tags
            live_result["static_doc_types_filter"] = static_doc_types
            live_result["intent"] = "LIVE_SEARCH_FALLBACK"
            return live_result

        legal_result["rewritten_query"] = planned_query
        legal_result["field_tags_filter"] = static_field_tags
        legal_result["static_doc_types_filter"] = static_doc_types
        legal_result["intent"] = intent
        return legal_result

    async def _build_live_search_legal_result(self, question: str, top_k: int) -> dict:
        """Convert live Tavily search results into the legacy legal_result shape used by chat."""
        searcher = self._get_web_searcher()
        clauses: list[dict] = []
        static_clauses: list[dict] = []
        comparison_title = self._extract_legal_doc_title(question)
        include_validity = self._should_run_validity_check(question, comparison_title)

        if include_validity and comparison_title:
            try:
                validity = await searcher.check_validity(comparison_title)
                status_label = {
                    "active": "Còn hiệu lực",
                    "expired": "Hết hiệu lực",
                    "unknown": "Chưa rõ hiệu lực",
                }.get(validity.status, validity.status)
                validity_text = (
                    f"Trạng thái hiệu lực: {status_label}.\n"
                    f"Nhận định: {validity.reasoning}\n"
                    f"Nguồn: {validity.source_url}\n"
                    f"Trích đoạn: {validity.source_snippet}"
                ).strip()
                clauses.append(
                    {
                        "clause_id": f"web-validity:{comparison_title}",
                        "document_id": 0,
                        "reference": validity.source_title or comparison_title,
                        "text": validity_text,
                        "article": "",
                        "clause": "",
                        "point": "",
                        "page": 0,
                        "clause_type": "web_validity",
                        "score": 1.0,
                        "retrieval_source": "live_search",
                        "title": validity.source_title or comparison_title,
                        "document_type": "web_result",
                        "issuing_authority": validity.source_domain,
                        "effective_date": "",
                        "status": validity.status,
                        "index_scope": "web",
                        "canonical_citation": validity.source_url or comparison_title,
                    }
                )
            except Exception as exc:
                logger.warning("Legal consultation validity check failed: %s", exc)

        results = await searcher.search(
            query=question,
            max_results=max(3, min(top_k, 8)),
            include_raw_content=True,
        )

        for idx, item in enumerate(results[: max(3, min(top_k, 8))], start=1):
            snippet = item.content or item.raw_content
            text = (
                f"Tiêu đề: {item.title}\n"
                f"Domain: {item.domain}\n"
                f"URL: {item.url}\n"
                f"Snippet: {snippet}"
            ).strip()
            clause = {
                "clause_id": f"web:{idx}:{item.url}",
                "document_id": 0,
                "reference": item.title or item.url,
                "text": text,
                "article": "",
                "clause": "",
                "point": "",
                "page": 0,
                "clause_type": "web_search_result",
                "score": float(item.score or 0.0),
                "retrieval_source": "live_search",
                "title": item.title,
                "document_type": "web_result",
                "issuing_authority": item.domain,
                "effective_date": item.published_date,
                "status": "",
                "index_scope": "web",
                "canonical_citation": item.url,
            }
            clauses.append(clause)
            static_clauses.append(
                {
                    "clause_id": clause["clause_id"],
                    "reference": clause["reference"],
                    "status": clause["status"],
                    "document_type": clause["document_type"],
                    "score": clause["score"],
                    "canonical_citation": clause["canonical_citation"],
                    "text": snippet[:400],
                }
            )

        return {
            "answer": "",
            "is_grounded": bool(clauses),
            "clauses": clauses,
            "static_clauses": static_clauses,
            "kg_context": "Trusted live legal web search results",
            "routing_mode": "LIVE_SEARCH",
            "inactive_statute_fallback": False,
        }

    @staticmethod
    def _should_prefer_active_statutes_only(question: str) -> bool:
        """Do not force active-only filtering for historical/effectiveness lookups."""
        question_lower = question.lower()
        historical_patterns = (
            "hiệu lực",
            "còn hiệu lực",
            "hết hiệu lực",
            "bị thay thế",
            "được thay thế",
            "ban hành năm",
            "năm ",
            "2013",
            "2014",
            "2015",
            "2016",
            "2017",
            "2018",
            "2019",
            "2020",
            "2021",
            "2022",
            "2023",
            "2024",
        )
        return not any(token in question_lower for token in historical_patterns)

    @staticmethod
    def _extract_legal_doc_title(question: str) -> str:
        """Best-effort extraction of a statute/document title from the user's question."""
        normalized = " ".join(question.split()).strip(" ?.!,:;")
        match = re.search(
            r"((?:luật|bộ luật|nghị định|thông tư|nghị quyết|quyết định)[^\\n,;:.!?]{0,120})",
            normalized,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip(" ?.!,:;")
        return normalized

    def _should_run_validity_check(self, question: str, extracted_title: str) -> bool:
        question_lower = question.lower()
        if any(
            token in question_lower
            for token in ("hiệu lực", "còn hiệu lực", "hết hiệu lực", "bị thay thế", "được thay thế")
        ):
            return True
        return bool(extracted_title and re.search(r"\b(19|20)\d{2}\b", extracted_title))

    async def _get_document_name_map(self, document_ids: list[int]) -> dict[int, str]:
        """Resolve workspace document IDs to original filenames for better labels."""
        if not document_ids:
            return {}

        result = await self.db.execute(
            select(Document).where(Document.id.in_(sorted(set(document_ids))))
        )
        return {
            int(doc.id): (doc.original_filename or doc.filename or f"Document {doc.id}")
            for doc in result.scalars().all()
        }

    def _build_source_label(self, item: dict, doc_name_map: dict[int, str]) -> str:
        """Choose the source label that best fits the legal document type."""
        document_id = int(item.get("document_id", 0) or 0)
        doc_name = doc_name_map.get(document_id, "")
        index_scope = (item.get("index_scope") or "case").lower()

        if index_scope == "static":
            return (
                item.get("canonical_citation")
                or item.get("title")
                or doc_name
                or item.get("reference")
                or f"Document {document_id}"
            )

        return (
            doc_name
            or item.get("title")
            or item.get("canonical_citation")
            or item.get("reference")
            or f"Document {document_id}"
        )

    def _build_formatted_reference(self, item: dict, source_label: str) -> str:
        """Create a compact, readable legal citation for the classic UI."""
        parts = [source_label]
        for key in ("article", "clause", "point"):
            value = item.get(key)
            if value:
                parts.append(str(value))
        page = int(item.get("page", 0) or 0)
        if page > 0:
            parts.append(f"p.{page}")
        return " > ".join(parts)

    # ------------------------------------------------------------------
    # Contract Risk Analysis
    # ------------------------------------------------------------------

    async def analyze_contract_risk(
        self,
        document_id: int,
        document_name: str = "",
        allow_inactive_statutes: bool = False,
    ) -> ContractRiskReport:
        """
        Analyze a contract using the Phase 5 multi-step agent workflow.

        Pipeline (Spec 05):
          ExtractAgent → StatutorySearchAgent → ComparisonAgent → RiskAuditorAgent

        Falls back to the Phase 4 one-shot path if markdown is not available.
        """
        # Fetch document markdown from DB
        markdown_text = ""
        try:
            result = await self.db.execute(
                select(Document).where(Document.id == document_id)
            )
            doc = result.scalar_one_or_none()
            if doc:
                markdown_text = doc.markdown_content or ""
                document_name = document_name or doc.original_filename or ""
        except Exception as e:
            logger.warning(f"Could not fetch markdown for doc {document_id}: {e}")

        # Phase 5: use agentic workflow when markdown is available
        if markdown_text and settings.LEGAL_STATIC_INDEX_ENABLED:
            workflow = self._get_agent_workflow()
            return await workflow.analyze_contract_risk(
                workspace_id=self.workspace_id,
                document_id=document_id,
                markdown_text=markdown_text,
                document_name=document_name,
                allow_inactive_statutes=allow_inactive_statutes,
            )

        # Phase 4 fallback: one-shot retrieval-based path
        logger.info(
            f"[analyze_contract_risk] doc={document_id}: falling back to one-shot path "
            f"(markdown_available={bool(markdown_text)}, static_enabled={settings.LEGAL_STATIC_INDEX_ENABLED})"
        )
        all_clauses = await self.retriever.query(
            question="all obligations rights penalties termination governing law",
            top_k=50,
            document_ids=[document_id],
            prefetch_n=100,
            routing_mode=RetrievalMode.MIXED,
            static_statuses=["active"],
        )
        context = all_clauses.format_context()
        detected_types = list({c.clause.clause_type for c in all_clauses.clauses})
        parties = list({p for c in all_clauses.clauses for p in c.clause.parties_mentioned})
        governing_law = ""
        for c in all_clauses.clauses:
            if c.clause.clause_type == "governing_law":
                governing_law = c.clause.text[:100]
                break
        return await self.reasoning.analyze_contract_risk(
            context=context,
            document_id=document_id,
            document_name=document_name,
            parties=parties,
            governing_law=governing_law,
            detected_clause_types=detected_types,
        )

    async def analyze_contract_consultation(
        self,
        document_id: int,
        document_name: str = "",
    ) -> dict:
        """Run the newer clause-level consultation risk analysis report."""
        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            raise ValueError(f"Document {document_id} not found")

        document_name = document_name or doc.original_filename or doc.filename or f"Document {document_id}"
        file_path = self._resolve_document_file_path(doc.filename)
        agent = self._get_risk_analysis_agent()

        if file_path and file_path.exists():
            report = await agent.analyze_file(
                str(file_path),
                document_id=document_id,
                document_name=document_name,
            )
        elif doc.markdown_content:
            report = await agent.analyze_markdown(
                markdown_text=doc.markdown_content,
                document_name=document_name,
                document_type="contract",
            )
        else:
            raise ValueError(f"Document {document_id} has no accessible file or parsed markdown")

        return report.to_dict()

    # ------------------------------------------------------------------
    # Clause Comparison
    # ------------------------------------------------------------------

    async def compare_clauses(
        self,
        clause_id_a: str,
        clause_id_b: str,
    ) -> ClauseComparison:
        """
        Compare two clauses by their IDs.
        Retrieves each clause from the vector store by clause_id metadata.
        """
        def _fetch_clause(clause_id: str) -> Optional[LegalCitedClause]:
            try:
                result = self.vector_store.get_all(
                    where={"clause_id": {"$eq": clause_id}},
                )
                docs = result.get("documents", [])
                metas = result.get("metadatas", [])
                if docs and metas:
                    from app.services.legal.legal_retriever import LegalRetriever
                    clause = LegalRetriever._meta_to_clause(docs[0], metas[0])
                    return LegalCitedClause(clause=clause, score=1.0)
                return None
            except Exception as e:
                logger.warning(f"Could not fetch clause {clause_id}: {e}")
                return None

        import asyncio
        clause_a, clause_b = await asyncio.gather(
            asyncio.to_thread(_fetch_clause, clause_id_a),
            asyncio.to_thread(_fetch_clause, clause_id_b),
        )

        if not clause_a or not clause_b:
            missing = []
            if not clause_a:
                missing.append(clause_id_a)
            if not clause_b:
                missing.append(clause_id_b)
            raise ValueError(f"Clause(s) not found: {missing}")

        return await self.reasoning.compare_clauses(clause_a, clause_b)

    # ------------------------------------------------------------------
    # Missing Clause Detection
    # ------------------------------------------------------------------

    async def detect_missing_clauses(self, document_id: int) -> list[MissingClause]:
        """
        Detect standard clauses that are missing from a document.
        Uses all clause types present in the document.
        """
        try:
            result = self.vector_store.get_all(
                where={"document_id": {"$eq": document_id}},
            )
            metas = result.get("metadatas", []) or []
            detected_types = list({m.get("clause_type", "") for m in metas if m})
        except Exception as e:
            logger.warning(f"Could not fetch clause types for doc {document_id}: {e}")
            detected_types = []

        return await self.reasoning.detect_missing_clauses(detected_types)

    # ------------------------------------------------------------------
    # Obligation Summary
    # ------------------------------------------------------------------

    async def summarize_obligations(
        self,
        party: str,
        document_id: int,
        top_k: int = 30,
    ) -> ObligationSummary:
        """
        Summarize obligations, rights, and penalties for a specific party.
        """
        retrieval = await self.retriever.query(
            question=f"{party} obligation right penalty shall must may",
            top_k=top_k,
            document_ids=[document_id],
            prefetch_n=50,
        )

        return await self.reasoning.summarize_obligations(party, retrieval)

    async def route_legal_intent(
        self,
        question: str,
        chat_history: Optional[list[dict]] = None,
    ) -> dict:
        router = self._get_intent_router()
        return await router.route(question=question, chat_history=chat_history or [])

    async def live_search(
        self,
        query: str,
        max_results: int = 5,
    ) -> dict:
        searcher = self._get_web_searcher()
        results = await searcher.search(query=query, max_results=max_results)
        return {
            "query": query,
            "results": [item.to_dict() for item in results],
        }

    async def check_legal_validity(self, doc_title: str) -> dict:
        searcher = self._get_web_searcher()
        result = await searcher.check_validity(doc_title)
        return result.to_dict()

    # ------------------------------------------------------------------
    # Management
    # ------------------------------------------------------------------

    async def delete_document(self, document_id: int) -> None:
        """Delete a document's clauses from the legal vector store."""
        self.vector_store.delete_by_document_id(document_id)
        logger.info(f"Deleted legal document {document_id} from vector store")

    # ------------------------------------------------------------------
    # Phase 5 helpers
    # ------------------------------------------------------------------

    def _get_agent_workflow(self):
        """Lazy-init LegalAgentWorkflow to avoid import cost at startup."""
        if self._agent_workflow is None:
            from app.services.legal.legal_agent_workflow import LegalAgentWorkflow
            self._agent_workflow = LegalAgentWorkflow(retriever=self.retriever)
        return self._agent_workflow

    def _get_intent_router(self):
        """Lazy-init IntentRouterAgent with service-aware loaders."""
        if self._intent_router is None:
            from app.services.legal.router import IntentRouterAgent
            self._intent_router = IntentRouterAgent(
                internal_recall_loader=lambda: self,
                live_search_loader=self._get_web_searcher,
                contract_risk_loader=self._get_risk_analysis_agent,
            )
        return self._intent_router

    def _get_web_searcher(self):
        if self._web_searcher is None:
            from app.services.legal.web_search import LegalWebSearcher
            self._web_searcher = LegalWebSearcher()
        return self._web_searcher

    def _get_risk_analysis_agent(self):
        if self._risk_analysis_agent is None:
            from app.services.legal.risk_analysis_agent import RiskAnalysisAgent
            self._risk_analysis_agent = RiskAnalysisAgent(
                workspace_id=self.workspace_id,
            )
        return self._risk_analysis_agent

    @staticmethod
    def _resolve_document_file_path(filename: str | None):
        if not filename:
            return None
        return settings.BASE_DIR / "uploads" / filename

    # ------------------------------------------------------------------
    # Phase 4 helpers
    # ------------------------------------------------------------------

    def _detect_routing_mode(self, question: str, document_ids: Optional[list[int]]) -> RetrievalMode:
        """Auto-select routing mode based on question context.

        Per Spec 02 routing rules:
          regulatory_lookup  → STATIC_ONLY
          contract question  → CASE_ONLY  (document_ids supplied)
          general legal QA   → MIXED when static index is enabled, else CASE_ONLY
        """
        q_lower = question.lower()

        # Signals that suggest a pure regulatory lookup
        regulatory_keywords = (
            "luật", "nghị định", "thông tư", "nghị quyết",
            "quy định", "statute", "regulation", "decree", "circular",
        )
        if any(kw in q_lower for kw in regulatory_keywords) and not document_ids:
            return RetrievalMode.STATIC_ONLY

        # If caller scoped to specific documents → case-only
        if document_ids:
            return RetrievalMode.CASE_ONLY

        # Default: MIXED when static index is available
        if settings.LEGAL_STATIC_INDEX_ENABLED:
            return RetrievalMode.MIXED

        return RetrievalMode.CASE_ONLY

    def get_chunk_count(self) -> int:
        """Return total number of legal clause chunks in this workspace."""
        return self.vector_store.count()

    # ------------------------------------------------------------------
    # Smart Legal Query (domain-router aware)
    # ------------------------------------------------------------------

    async def smart_legal_query(
        self,
        question: str,
        top_k: int = 8,
        document_ids: Optional[list[int]] = None,
    ) -> dict:
        """
        Domain-aware legal query:
          1. Run domain router to detect legal signals
          2. Auto-infer clause_type filters from query
          3. Extract entity hints (Điều X, Bên A) for article filter
          4. Run legal_query with auto-populated filters

        Returns same dict as legal_query() + domain detection metadata.
        """
        detection = detect_domain(question)
        rewritten_query = detection.rewritten_query or question

        # Infer clause_type filters from domain router
        clause_types = detection.clause_types_hint or None

        # Infer article filters from entity hints like "Điều 5"
        import re
        articles = [
            h.title() for h in detection.entity_hints
            if re.match(r'(điều|article|section)', h, re.IGNORECASE)
        ] or None

        result = await self.legal_query(
            question=rewritten_query,
            top_k=top_k,
            document_ids=document_ids,
            clause_types=clause_types,
            articles=articles,
            static_doc_types=detection.static_doc_types_hint or None,
            static_field_tags=detection.field_tags_hint or None,
        )

        # Live search fallback: if internal retrieval finds nothing AND the
        # caller didn't restrict to specific document_ids, try Tavily.
        # This handles both "no indexed docs yet" and "question outside corpus".
        if not result.get("clauses") and not document_ids:
            logger.info(
                "[smart_legal_query] 0 clauses from vector search — "
                "falling back to live web search for: %s", question[:80]
            )
            try:
                live = await self._build_live_search_legal_result(question, top_k=top_k)
                live["domain"] = detection.domain
                live["domain_confidence"] = detection.confidence
                live["clause_type_filter"] = clause_types
                live["article_filter"] = articles
                live["domain_signals"] = detection.signals[:5]
                live["field_tags_filter"] = detection.field_tags_hint
                live["static_doc_types_filter"] = detection.static_doc_types_hint
                live["rewritten_query"] = rewritten_query
                return live
            except Exception as exc:
                logger.warning("[smart_legal_query] live search fallback failed: %s", exc)

        result["domain"] = detection.domain
        result["domain_confidence"] = detection.confidence
        result["clause_type_filter"] = clause_types
        result["article_filter"] = articles
        result["domain_signals"] = detection.signals[:5]
        result["field_tags_filter"] = detection.field_tags_hint
        result["static_doc_types_filter"] = detection.static_doc_types_hint
        result["rewritten_query"] = rewritten_query

        return result

    # ------------------------------------------------------------------
    # Structured Field Extraction
    # ------------------------------------------------------------------

    async def extract_fields(
        self,
        document_id: int,
        use_llm_fallback: bool = True,
    ) -> ContractFields:
        """
        Extract structured fields from a document's stored markdown.

        First tries regex (instant). If any key fields are missing
        and use_llm_fallback=True, calls LLM once to fill the gaps.

        Returns:
            ContractFields with contract_value, parties, VAT, penalty, etc.
        """
        from sqlalchemy import select
        from app.models.document import Document

        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise ValueError(f"Document {document_id} not found")

        text = doc.markdown_content or ""
        if not text:
            raise ValueError(f"Document {document_id} has no parsed text. Process it first.")

        # Step 1: Regex extraction (instant)
        fields = self._field_extractor.extract(text)

        # Step 2: LLM fallback for missing fields
        if use_llm_fallback:
            from app.services.llm import get_llm_provider
            llm = get_llm_provider()
            fields = await extract_with_llm_fallback(text, fields, llm)

        logger.info(
            f"Extracted fields for doc {document_id}: "
            f"regex={fields.regex_extracted} llm={fields.llm_extracted}"
        )
        return fields

    # ------------------------------------------------------------------
    # KG Relationship Builder
    # ------------------------------------------------------------------

    async def build_kg_relationships(
        self,
        document_id: int,
        use_llm: bool = False,
        reingest_enriched_text: bool = True,
    ) -> list[dict]:
        """
        Extract and inject relationships into the Knowledge Graph.

        This is the fix for the "0 relationships" KG problem.

        Steps:
          1. Fetch all clauses for the document from ChromaDB
          2. Run HybridRelationshipExtractor (rule + optionally LLM)
          3. Build enriched markdown with [LEGAL_RELATIONSHIP] tags
          4. Re-ingest enriched text into LightRAG
             → this causes LightRAG to find the relationships on re-run

        Args:
            document_id: Document to process
            use_llm: Use LLM for ambiguous clauses (slower, more accurate)
            reingest_enriched_text: Re-ingest annotated text into KG

        Returns:
            List of extracted relationship dicts
        """
        if not self.kg_service:
            raise ValueError("KG is not enabled (NEXUSRAG_ENABLE_KG=False)")

        # Step 1: Fetch all clauses from PGVector
        try:
            raw = self.vector_store.get_all(
                where={"document_id": {"$eq": document_id}},
            )
            docs = raw.get("documents", []) or []
            metas = raw.get("metadatas", []) or []
        except Exception as e:
            raise ValueError(f"Could not fetch clauses for doc {document_id}: {e}")

        if not docs:
            raise ValueError(f"No clauses found for document {document_id}. Process it first.")

        clauses = [
            {
                "clause_id": m.get("clause_id", ""),
                "text": d,
                "article": m.get("article", ""),
                "clause": m.get("clause", ""),
                "clause_type": m.get("clause_type", ""),
            }
            for d, m in zip(docs, metas)
        ]

        # Step 2: Extract relationships
        from app.services.llm import get_llm_provider
        llm_provider = get_llm_provider() if use_llm else None
        extractor = HybridRelationshipExtractor(llm_provider=llm_provider)
        relationships = await extractor.extract(
            clauses=clauses,
            use_llm_for_empty=use_llm,
        )

        # Step 3: Build enriched markdown
        if reingest_enriched_text and relationships:
            from sqlalchemy import select
            from app.models.document import Document
            result = await self.db.execute(
                select(Document).where(Document.id == document_id)
            )
            doc = result.scalar_one_or_none()
            markdown = doc.markdown_content if doc else ""

            enriched = build_relationship_enriched_text(markdown, relationships)

            # Step 4: Re-ingest into LightRAG
            try:
                await self.kg_service.ingest(enriched)
                logger.info(
                    f"Re-ingested relationship-enriched text for doc {document_id} "
                    f"({len(relationships)} relationships)"
                )
            except Exception as e:
                logger.error(f"KG re-ingest failed: {e}")

        return [r.to_dict() for r in relationships]
