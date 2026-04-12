"""
Legal Static Index Service
============================

Manages the Static Legal Corpus vector collection via PGVector.

Responsibilities:
  - Index LegalClause objects into the global static collection
  - Provide clause-level retrieval from the static collection only
  - Support batch indexing for large dataset ingestion
  - Expose collection statistics

The static collection is intentionally separate from the workspace case
collection (kb_{workspace_id}_legal) so that statutory law is never mixed
with private case documents in the same retrieval candidate pool.

Collection name: configured by settings.LEGAL_STATIC_COLLECTION_NAME
Default:         "legal_static_global"
"""
from __future__ import annotations

import logging
from typing import Optional

from app.core.config import settings
from app.services.embedder import EmbeddingService, get_embedding_service
from app.services.vector_store import VectorStore
from app.services.models.legal_document import (
    LegalClause,
    LegalCitedClause,
    LegalDocumentMetadata,
)
from app.services.legal.clause_chunker import ClauseChunker, ClauseChunk

logger = logging.getLogger(__name__)


class LegalStaticIndexService:
    """
    Manages the Static Legal Index (PGVector collection for statutory law).

    Usage:
        service = LegalStaticIndexService()
        await service.index_clauses(clauses, doc_metadata)
        results = service.query_statutes(query_embedding, n=10)
    """

    def __init__(self, embedder: Optional[EmbeddingService] = None):
        self.collection_name = settings.LEGAL_STATIC_COLLECTION_NAME
        self.embedder = embedder or get_embedding_service()
        self._chunker = ClauseChunker()
        # Use a VectorStore with workspace_id=0 and the static collection name
        self._vector_store = VectorStore(workspace_id=0, collection_suffix="")
        self._vector_store.collection_name = self.collection_name
        logger.info(
            f"StaticIndex: initialized PGVector collection '{self.collection_name}'"
        )

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index_clauses(
        self,
        clauses: list[LegalClause],
        doc_metadata: Optional[LegalDocumentMetadata] = None,
    ) -> int:
        """
        Embed and index a list of LegalClause objects into the static collection.

        Each clause is first passed through ClauseChunker (which may split
        very long clauses at paragraph boundaries). The resulting ClauseChunks
        are embedded as a batch and upserted into PGVector.

        Args:
            clauses: Parsed LegalClause objects (index_scope must be "static")
            doc_metadata: Optional document-level metadata to stamp onto clauses
                         before indexing (used for dataset-level fields).

        Returns:
            Number of chunks indexed.
        """
        if not clauses:
            return 0

        # Stamp document-level metadata onto each clause if provided
        if doc_metadata:
            for c in clauses:
                if not c.title and doc_metadata.title:
                    c.title = doc_metadata.title
                if not c.document_type and doc_metadata.document_type:
                    c.document_type = doc_metadata.document_type
                if not c.issuing_authority and doc_metadata.issuing_authority:
                    c.issuing_authority = doc_metadata.issuing_authority
                if not c.effective_date and doc_metadata.effective_date:
                    c.effective_date = doc_metadata.effective_date
                if not c.status and doc_metadata.status:
                    c.status = doc_metadata.status
                if not c.field_tags and doc_metadata.field_tags:
                    c.field_tags = doc_metadata.field_tags
                if not c.canonical_citation and doc_metadata.canonical_citation:
                    c.canonical_citation = doc_metadata.canonical_citation
                c.index_scope = "static"

        # Build clause chunks
        chunks: list[ClauseChunk] = []
        for clause in clauses:
            clause_chunks = self._chunker._process_clause(clause)
            chunks.extend(clause_chunks)

        if not chunks:
            return 0

        # Embed
        texts = [c.content for c in chunks]
        embeddings = self.embedder.embed_texts(texts)

        # Upsert into PGVector
        self._vector_store.add_documents(
            ids=[c.chunk_id for c in chunks],
            embeddings=embeddings,
            documents=texts,
            metadatas=[c.metadata for c in chunks],
        )

        logger.info(
            f"StaticIndex: indexed {len(chunks)} chunks from {len(clauses)} clauses "
            f"into '{self.collection_name}'"
        )
        return len(chunks)

    def delete_document_chunks(self, document_id: int | str) -> None:
        """Remove all chunks belonging to a static document."""
        try:
            self._vector_store.delete_where(
                {"document_id": {"$eq": document_id}}
            )
            logger.info(
                f"StaticIndex: deleted chunks for document {document_id} "
                f"from '{self.collection_name}'"
            )
        except Exception as e:
            logger.warning(f"StaticIndex: delete failed for doc {document_id}: {e}")

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def query_statutes(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        where: Optional[dict] = None,
    ) -> list[LegalCitedClause]:
        """
        Run vector similarity search against the static legal corpus.

        Args:
            query_embedding: Pre-computed query embedding vector.
            n_results: Number of results to return.
            where: Optional filter dict (ChromaDB-compatible syntax).

        Returns:
            List of LegalCitedClause ordered by descending similarity.
        """
        raw = self._vector_store.query(
            query_embedding=query_embedding,
            n_results=n_results,
            where=where,
        )

        from app.services.legal.legal_retriever import LegalRetriever
        results: list[LegalCitedClause] = []
        documents = raw.get("documents", [])
        metadatas = raw.get("metadatas", [])
        distances = raw.get("distances", [])
        for i, doc_text in enumerate(documents):
            meta = metadatas[i] if i < len(metadatas) else {}
            dist = distances[i] if i < len(distances) else 0.0
            score = 1.0 - (dist if isinstance(dist, float) else float(dist))
            clause = LegalRetriever._meta_to_clause(doc_text, meta)
            results.append(LegalCitedClause(
                clause=clause,
                score=score,
                retrieval_source="static_vector",
            ))

        return results

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return total number of chunks in the static collection."""
        try:
            return self._vector_store.count()
        except Exception:
            return -1

    def collection_exists(self) -> bool:
        """Return True if the static collection exists and has content."""
        try:
            return self._vector_store.count() >= 0
        except Exception:
            return False
