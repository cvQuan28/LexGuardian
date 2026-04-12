"""
Legal Source Document ORM Model
=================================

Persists document-level metadata for the Static Legal Index.

Each row corresponds to one Vietnamese statutory document ingested from
the th1nhng0/vietnamese-legal-documents dataset (or other static sources).

This table enables:
- stable metadata filtering (status, document_type, issuing_authority, field_tags)
- incremental re-ingestion (hash-based deduplication)
- audit trail for which documents are in the static corpus
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import String, Integer, Text, Boolean, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LegalSourceDocument(Base):
    __tablename__ = "legal_source_documents"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Scope: "static" | "case"
    index_scope: Mapped[str] = mapped_column(String(20), default="static", index=True)

    # Optional workspace scope (NULL = global static corpus)
    workspace_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Document identity
    document_code: Mapped[str] = mapped_column(String(255), default="", index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    canonical_citation: Mapped[str] = mapped_column(String(500), default="")

    # Document classification
    document_type: Mapped[str] = mapped_column(String(100), default="", index=True)
    issuing_authority: Mapped[str] = mapped_column(String(255), default="", index=True)

    # Temporal metadata
    issued_date: Mapped[str] = mapped_column(String(50), default="")
    effective_date: Mapped[str] = mapped_column(String(50), default="", index=True)
    expiry_date: Mapped[str] = mapped_column(String(50), default="")

    # Effectiveness status: "active" | "expired" | "superseded" | "pending" | ""
    status: Mapped[str] = mapped_column(String(50), default="", index=True)

    # Pipe-delimited legal domain tags, e.g. "lao_dong|dau_tu"
    field_tags_json: Mapped[str] = mapped_column(Text, default="[]")

    # Amendment / replacement chain
    version_label: Mapped[str] = mapped_column(String(100), default="")
    is_amending_document: Mapped[bool] = mapped_column(Boolean, default=False)
    replaces_documents_json: Mapped[str] = mapped_column(Text, default="[]")
    guides_documents_json: Mapped[str] = mapped_column(Text, default="[]")

    # Storage pointers
    source_path: Mapped[str] = mapped_column(String(1000), default="")
    source_url: Mapped[str] = mapped_column(String(1000), default="")

    # Deduplication — SHA-256 hash of the raw document content
    content_hash: Mapped[str] = mapped_column(String(64), default="", index=True)

    # Ingestion bookkeeping
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    kg_ingested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Composite index for common filtering patterns
    __table_args__ = (
        Index("ix_legal_source_status_type", "status", "document_type"),
        Index("ix_legal_source_scope_status", "index_scope", "status"),
    )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def field_tags(self) -> list[str]:
        try:
            return json.loads(self.field_tags_json)
        except Exception:
            return []

    @field_tags.setter
    def field_tags(self, value: list[str]) -> None:
        self.field_tags_json = json.dumps(value, ensure_ascii=False)

    @property
    def replaces_documents(self) -> list[str]:
        try:
            return json.loads(self.replaces_documents_json)
        except Exception:
            return []

    @replaces_documents.setter
    def replaces_documents(self, value: list[str]) -> None:
        self.replaces_documents_json = json.dumps(value, ensure_ascii=False)

    @property
    def guides_documents(self) -> list[str]:
        try:
            return json.loads(self.guides_documents_json)
        except Exception:
            return []

    @guides_documents.setter
    def guides_documents(self, value: list[str]) -> None:
        self.guides_documents_json = json.dumps(value, ensure_ascii=False)

    def to_metadata(self) -> "LegalDocumentMetadata":  # type: ignore[name-defined]
        """Convert ORM row back to the dataclass used by the pipeline."""
        from app.services.models.legal_document import LegalDocumentMetadata
        return LegalDocumentMetadata(
            document_id=self.id,
            title=self.title,
            document_type=self.document_type,
            issuing_authority=self.issuing_authority,
            issued_date=self.issued_date,
            effective_date=self.effective_date,
            expiry_date=self.expiry_date,
            status=self.status,
            field_tags=self.field_tags,
            source_url=self.source_url,
            document_code=self.document_code,
            version_label=self.version_label,
            index_scope=self.index_scope,
            is_amending_document=self.is_amending_document,
            canonical_citation=self.canonical_citation,
            replaces_documents=self.replaces_documents,
            guides_documents=self.guides_documents,
        )

    def __repr__(self) -> str:
        return f"<LegalSourceDocument id={self.id} doc_type={self.document_type!r} title={self.title[:60]!r}>"
