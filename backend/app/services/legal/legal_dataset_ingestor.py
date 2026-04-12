"""
Legal Dataset Ingestor
========================

Phase 2 — Ingests `th1nhng0/vietnamese-legal-documents` from HuggingFace
into the Static Legal Index.

Pipeline per document:
  1. Load dataset record
  2. Normalise & validate metadata (graceful defaults for missing fields)
  3. Parse markdown content into LegalClause objects
  4. (Optional) Generate summary_text via LegalChunkAugmentor (SAC)
  5. Embed and index into the static ChromaDB collection
  6. Persist document-level metadata into PostgreSQL (LegalSourceDocument)
  7. (Optional) Ingest into KG if document_type is in LEGAL_STATIC_KG_DOC_TYPES

Running this service:
    python -m scripts.run_legal_ingest --max-docs 100
    # or call LegalDatasetIngestor directly in a background task

Config flags (set in .env):
    LEGAL_STATIC_INDEX_ENABLED   — must be true to run
    LEGAL_STATIC_BATCH_SIZE      — records per embedding batch
    LEGAL_STATIC_INGEST_MAX_DOCS — 0 = no limit
    LEGAL_STATIC_KG_DOC_TYPES    — doc types eligible for KG ingest
    LEGAL_CHUNK_AUGMENT_ENABLED  — enable SAC summary generation
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional, AsyncIterator, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.models.legal_document import (
    LegalClause,
    LegalDocumentMetadata,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Metadata normalisation helpers
# ---------------------------------------------------------------------------

_KNOWN_DOC_TYPES = {
    "luật": "law",
    "bộ luật": "code",
    "nghị định": "decree",
    "thông tư": "circular",
    "quyết định": "decision",
    "chỉ thị": "directive",
    "nghị quyết": "resolution",
    "pháp lệnh": "ordinance",
    "hiến pháp": "constitution",
    "law": "law",
    "code": "code",
    "decree": "decree",
    "circular": "circular",
    "decision": "decision",
    "directive": "directive",
}


def _normalise_document_type(raw: str) -> str:
    """Map Vietnamese/English doc type strings to a canonical lowercase key."""
    if not raw:
        return ""
    lower = raw.strip().lower()
    for key, val in _KNOWN_DOC_TYPES.items():
        if lower.startswith(key):
            return val
    return lower


def _normalise_status(raw: str) -> str:
    """Return 'active' | 'expired' | 'superseded' | 'pending' | '' ."""
    if not raw:
        return ""
    lower = raw.strip().lower()
    active_terms = {"còn hiệu lực", "active", "đang có hiệu lực", "có hiệu lực"}
    expired_terms = {"hết hiệu lực", "expired", "đã hết hiệu lực"}
    superseded_terms = {"bị thay thế", "superseded", "bị bãi bỏ"}
    pending_terms = {"chưa có hiệu lực", "pending", "chưa hiệu lực"}
    if lower in active_terms:
        return "active"
    if lower in expired_terms:
        return "expired"
    if lower in superseded_terms:
        return "superseded"
    if lower in pending_terms:
        return "pending"
    return lower


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _parse_field_tags(raw) -> list[str]:
    """Accept string or list; return a clean list of tag strings."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if t]
    if isinstance(raw, str):
        # comma or pipe-delimited
        tags = [t.strip() for t in raw.replace("|", ",").split(",") if t.strip()]
        return tags
    return []


def _parse_list_field(raw) -> list[str]:
    """Parse a field that might be a list or a string."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    return []


# ---------------------------------------------------------------------------
# Record normaliser
# ---------------------------------------------------------------------------

def normalise_record(record: dict) -> LegalDocumentMetadata:
    """
    Convert one raw HuggingFace dataset record into a LegalDocumentMetadata.

    Tolerates any missing field with safe defaults.
    """
    raw_type = record.get("document_type") or record.get("legal_type") or record.get("type") or ""
    raw_status = (
        record.get("status")
        or record.get("hieu_luc")
        or record.get("effectiveness")
        or ""
    )
    field_tags = _parse_field_tags(
        record.get("field_tags")
        or record.get("legal_sectors")
        or record.get("linh_vuc")
        or record.get("field")
        or record.get("fields")
        or ""
    )
    replaces = _parse_list_field(
        record.get("replaces_documents")
        or record.get("replaces")
        or record.get("supersedes")
        or []
    )
    guides = _parse_list_field(
        record.get("guides_documents")
        or record.get("guides")
        or []
    )

    doc_code = (
        str(record.get("document_code") or record.get("document_number") or record.get("doc_code") or record.get("code") or "")
    )
    title = str(record.get("title") or record.get("ten_van_ban") or "")
    authority = str(
        record.get("issuing_authority")
        or record.get("co_quan_ban_hanh")
        or record.get("authority")
        or ""
    )
    issued = str(record.get("issued_date") or record.get("issuance_date") or record.get("ngay_ban_hanh") or record.get("issue_date") or "")
    effective = str(record.get("effective_date") or record.get("ngay_hieu_luc") or "")
    expiry = str(record.get("expiry_date") or record.get("ngay_het_hieu_luc") or "")
    source_url = str(record.get("source_url") or record.get("url") or "")
    version_label = str(record.get("version_label") or record.get("version") or "")
    is_amending = bool(record.get("is_amending_document") or record.get("is_amending") or False)
    canonical = title or doc_code

    doc_id = record.get("document_id") or record.get("id") or 0

    return LegalDocumentMetadata(
        document_id=doc_id,
        document_code=doc_code,
        title=title,
        document_type=_normalise_document_type(raw_type),
        issuing_authority=authority,
        issued_date=issued,
        effective_date=effective,
        expiry_date=expiry,
        status=_normalise_status(raw_status),
        field_tags=field_tags,
        source_url=source_url,
        version_label=version_label,
        index_scope="static",
        is_amending_document=is_amending,
        canonical_citation=canonical,
        replaces_documents=replaces,
        guides_documents=guides,
    )


# ---------------------------------------------------------------------------
# Markdown-to-clause parser for static content
# ---------------------------------------------------------------------------

def _markdown_to_clauses(
    markdown: str,
    doc_metadata: LegalDocumentMetadata,
    db_doc_id: int,
) -> list[LegalClause]:
    """
    Parse markdown content into LegalClause objects using the existing
    LegalDocumentParser regex-based extractor, then stamp static metadata.
    """
    from app.services.legal.legal_parser import LegalDocumentParser

    # Create a temporary parser (workspace_id=0 for static corpus)
    parser = LegalDocumentParser(workspace_id=0)
    try:
        # Use internal _extract_clauses (no file I/O needed)
        clauses = parser._extract_clauses(
            markdown=markdown,
            document_id=db_doc_id,
            source_file=doc_metadata.canonical_citation or doc_metadata.document_code or "static",
        )
    except Exception as e:
        logger.warning(f"Clause extraction failed for doc {db_doc_id}: {e}")
        clauses = []

    # Stamp document-level metadata
    for c in clauses:
        c.title = doc_metadata.title
        c.document_type = doc_metadata.document_type
        c.issuing_authority = doc_metadata.issuing_authority
        c.issued_date = doc_metadata.issued_date
        c.effective_date = doc_metadata.effective_date
        c.expiry_date = doc_metadata.expiry_date
        c.status = doc_metadata.status
        c.field_tags = doc_metadata.field_tags
        c.canonical_citation = doc_metadata.canonical_citation
        c.index_scope = "static"

    return clauses


# ---------------------------------------------------------------------------
# Main ingestion service
# ---------------------------------------------------------------------------

class LegalDatasetIngestor:
    """
    Ingests the th1nhng0/vietnamese-legal-documents HuggingFace dataset
    into the Static Legal Index.

    Args:
        db: SQLAlchemy async session for metadata persistence.
        static_index: LegalStaticIndexService (defaults to a new instance).
        augmentor: LegalChunkAugmentor (optional; enables SAC summaries).
        kg_service: Optional LegalKGService for KG ingest.
    """

    def __init__(
        self,
        db,  # AsyncSession — avoid top-level import for light environments
        static_index=None,
        augmentor=None,
        kg_service=None,
    ):
        self.db = db
        if static_index is None:
            from app.services.legal.legal_static_index_service import LegalStaticIndexService
            static_index = LegalStaticIndexService()
        self.static_index = static_index
        self.augmentor = augmentor
        self.kg_service = kg_service

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def ingest_from_huggingface(
        self,
        dataset_name: str = "th1nhng0/vietnamese-legal-documents",
        split: str = "data",
        max_docs: int = 0,
        skip_existing: bool = True,
    ) -> dict:
        """
        Stream-ingest from the HuggingFace dataset.

        Args:
            dataset_name: HuggingFace dataset identifier.
            split: Dataset split (usually 'train').
            max_docs: Maximum docs to ingest (0 = settings.LEGAL_STATIC_INGEST_MAX_DOCS
                      or unlimited if that is also 0).
            skip_existing: Skip documents whose content_hash is already in the DB.

        Returns:
            Summary dict: {ingested, skipped, errors, total_chunks}
        """
        if not settings.LEGAL_STATIC_INDEX_ENABLED:
            logger.warning(
                "LEGAL_STATIC_INDEX_ENABLED=false — set it to true to run ingestion."
            )
            return {"ingested": 0, "skipped": 0, "errors": 0, "total_chunks": 0,
                    "warning": "LEGAL_STATIC_INDEX_ENABLED is false"}

        effective_max = max_docs or settings.LEGAL_STATIC_INGEST_MAX_DOCS

        try:
            from datasets import load_dataset  # type: ignore
        except ImportError:
            raise RuntimeError(
                "HuggingFace `datasets` package is not installed. "
                "Run: pip install datasets"
            )

        logger.info(
            f"Loading dataset {dataset_name!r} config 'metadata' & 'content' split={split!r} "
            f"(max_docs={effective_max or 'unlimited'})..."
        )
        try:
            ds_meta = load_dataset(dataset_name, name="metadata", split=split, streaming=True)
            ds_content = load_dataset(dataset_name, name="content", split=split, streaming=True)
            dataset = zip(ds_meta, ds_content)
        except ValueError as ve:
            # Fallback if dataset has no configs
            logger.warning(f"Failed to load with configs: {ve}. Trying default load...")
            ds_default = load_dataset(dataset_name, split=split, streaming=True)
            dataset = ((rec, {"content": rec.get("content", "")}) for rec in ds_default)

        ingested = skipped = errors = total_chunks = 0
        batch_records: list[dict] = []
        batch_metas: list[LegalDocumentMetadata] = []

        async for raw_meta, raw_content in self._stream_records_zipped(
            dataset, effective_max
        ):
            try:
                if str(raw_meta.get("id", "a")) != str(raw_content.get("id", "b")):
                    logger.warning("Dataset id mismatch, skipping record")
                    skipped += 1
                    continue
                
                raw_record = {**raw_meta, **raw_content}
                meta = normalise_record(raw_record)
                content = str(raw_record.get("content") or raw_record.get("text") or raw_record.get("markdown") or "")

                if not content.strip():
                    logger.debug(f"Skipping doc (no content): {meta.title[:60]!r}")
                    skipped += 1
                    continue

                if skip_existing:
                    chash = _content_hash(content)
                    existing = await self._find_by_hash(chash)
                    if existing:
                        logger.debug(f"Skipping existing doc hash={chash[:12]}")
                        skipped += 1
                        continue
                else:
                    chash = _content_hash(content)

                # --- Persist SQL metadata ---
                db_doc = await self._upsert_legal_source(meta, content, chash)
                db_doc_id = db_doc.id

                # --- Parse into clauses ---
                clauses = _markdown_to_clauses(content, meta, db_doc_id)
                if not clauses:
                    logger.debug(f"No clauses extracted for doc id={db_doc_id} {meta.title[:60]!r}")
                    skipped += 1
                    continue

                # --- SAC: generate summaries ---
                if self.augmentor:
                    for clause in clauses:
                        try:
                            clause.summary_text = await self.augmentor.summarize_clause(clause)
                        except Exception as e:
                            logger.debug(f"Summary failed for clause {clause.clause_id}: {e}")

                # --- Index into static ChromaDB ---
                n_chunks = self.static_index.index_clauses(clauses, meta)
                total_chunks += n_chunks

                # --- Update chunk count ---
                db_doc.chunk_count = n_chunks
                await self.db.commit()

                # --- KG ingest ---
                if self._should_kg_ingest(meta):
                    await self._kg_ingest(content, db_doc, meta)

                ingested += 1
                if ingested % 50 == 0:
                    logger.info(
                        f"Ingested {ingested} docs so far "
                        f"({total_chunks} chunks, {skipped} skipped, {errors} errors)"
                    )

            except Exception as e:
                errors += 1
                logger.error(f"Ingestion error on record: {e}", exc_info=False)
                # MUST rollback the session so subsequent DB operations don't fail with InFailedSQLTransactionError
                try:
                    await self.db.rollback()
                except Exception as rollback_err:
                    logger.error(f"Rollback failed: {rollback_err}")
                continue

        summary = {
            "ingested": ingested,
            "skipped": skipped,
            "errors": errors,
            "total_chunks": total_chunks,
        }
        logger.info(f"Ingestion complete: {summary}")
        return summary

    async def ingest_single_record(
        self,
        record: dict,
        augment: bool = True,
    ) -> dict:
        """
        Ingest a single pre-loaded record dict (for testing / one-off imports).

        Args:
            record: Dict with document content and metadata fields.
            augment: Whether to generate SAC summaries.

        Returns:
            {"db_id": int, "chunks": int, "status": str}
        """
        meta = normalise_record(record)
        content = str(record.get("content") or record.get("text") or record.get("markdown") or "")

        if not content.strip():
            return {"db_id": None, "chunks": 0, "status": "skipped_empty"}

        chash = _content_hash(content)
        db_doc = await self._upsert_legal_source(meta, content, chash)

        clauses = _markdown_to_clauses(content, meta, db_doc.id)
        if not clauses:
            return {"db_id": db_doc.id, "chunks": 0, "status": "no_clauses"}

        if augment and self.augmentor:
            for clause in clauses:
                try:
                    clause.summary_text = await self.augmentor.summarize_clause(clause)
                except Exception:
                    pass

        n_chunks = self.static_index.index_clauses(clauses, meta)
        db_doc.chunk_count = n_chunks
        await self.db.commit()

        return {"db_id": db_doc.id, "chunks": n_chunks, "status": "ok"}

    # ------------------------------------------------------------------
    # SQL persistence
    # ------------------------------------------------------------------

    async def _find_by_hash(self, content_hash: str):
        from sqlalchemy import select
        from app.models.legal_source import LegalSourceDocument
        result = await self.db.execute(
            select(LegalSourceDocument).where(
                LegalSourceDocument.content_hash == content_hash
            )
        )
        return result.scalar_one_or_none()

    async def _upsert_legal_source(
        self,
        meta: LegalDocumentMetadata,
        content: str,
        content_hash: str,
    ):
        """
        Insert a new LegalSourceDocument row or update the existing one.
        Keyed by (document_code, index_scope) — document code uniquely
        identifies a statutory document in the Vietnamese legal system.
        """
        from sqlalchemy import select
        from app.models.legal_source import LegalSourceDocument
        existing = None
        if meta.document_code:
            result = await self.db.execute(
                select(LegalSourceDocument).where(
                    LegalSourceDocument.document_code == meta.document_code,
                    LegalSourceDocument.index_scope == "static",
                )
            )
            existing = result.scalar_one_or_none()

        if existing is None:
            # Try by content hash
            existing = await self._find_by_hash(content_hash)

        if existing is not None:
            # Update in place
            existing.title = meta.title or existing.title
            existing.document_type = meta.document_type or existing.document_type
            existing.issuing_authority = meta.issuing_authority or existing.issuing_authority
            existing.issued_date = meta.issued_date or existing.issued_date
            existing.effective_date = meta.effective_date or existing.effective_date
            existing.expiry_date = meta.expiry_date or existing.expiry_date
            existing.status = meta.status or existing.status
            existing.field_tags = meta.field_tags or existing.field_tags
            existing.source_url = meta.source_url or existing.source_url
            existing.version_label = meta.version_label or existing.version_label
            existing.is_amending_document = meta.is_amending_document
            existing.canonical_citation = meta.canonical_citation or existing.canonical_citation
            existing.replaces_documents = meta.replaces_documents
            existing.guides_documents = meta.guides_documents
            existing.content_hash = content_hash
            await self.db.commit()
            return existing

        # Insert new
        doc = LegalSourceDocument(
            index_scope="static",
            workspace_id=None,
            document_code=meta.document_code,
            title=meta.title,
            canonical_citation=meta.canonical_citation,
            document_type=meta.document_type,
            issuing_authority=meta.issuing_authority,
            issued_date=meta.issued_date,
            effective_date=meta.effective_date,
            expiry_date=meta.expiry_date,
            status=meta.status,
            version_label=meta.version_label,
            is_amending_document=meta.is_amending_document,
            source_url=meta.source_url,
            content_hash=content_hash,
        )
        doc.field_tags = meta.field_tags
        doc.replaces_documents = meta.replaces_documents
        doc.guides_documents = meta.guides_documents

        self.db.add(doc)
        await self.db.flush()      # get generated id
        await self.db.commit()
        return doc

    # ------------------------------------------------------------------
    # KG ingest
    # ------------------------------------------------------------------

    def _should_kg_ingest(self, meta: LegalDocumentMetadata) -> bool:
        if not self.kg_service:
            return False
        if not meta.document_type:
            return False
        return meta.document_type in settings.LEGAL_STATIC_KG_DOC_TYPES

    async def _kg_ingest(
        self,
        content: str,
        db_doc,
        meta: LegalDocumentMetadata,
    ) -> None:
        try:
            await self.kg_service.ingest(content)
            db_doc.kg_ingested = True
            await self.db.commit()
            logger.debug(f"KG ingested: {meta.title[:60]!r}")
        except Exception as e:
            logger.error(f"KG ingest failed for {meta.title[:60]!r}: {e}")

    # ------------------------------------------------------------------
    # Async record streaming
    # ------------------------------------------------------------------

    @staticmethod
    async def _stream_records_zipped(dataset, max_docs: int):
        """
        Wrap synchronous HuggingFace zipped IterableDataset in an async generator.
        Applies max_docs cap if non-zero.
        """
        import asyncio
        count = 0
        for rec_meta, rec_content in dataset:
            yield rec_meta, rec_content
            count += 1
            if max_docs and count >= max_docs:
                break
            # Yield control to the event loop to avoid blocking
            if count % 10 == 0:
                await asyncio.sleep(0)
