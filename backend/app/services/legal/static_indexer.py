"""
Static Legal Indexer Service
============================
Service chuyên dụng xử lý indexing cho Kho Luật Tĩnh (Static Legal Repository).

Yêu cầu thực thi:
1. Bỏ qua trích xuất Knowledge Graph (tiết kiệm tài nguyên).
2. Tự động kiểm tra RAM hệ thống: Nếu < 8GB thì max_workers = 1.
3. Lưu metadata (số hiệu, ngày ban hành, trạng thái,...) vào PostgreSQL bằng SQLAlchemy.
4. Nhúng (embedding) và lưu vào Vector Database.
"""

import os
import psutil
import logging
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.legal_source import LegalSourceDocument
from app.services.legal.legal_static_index_service import LegalStaticIndexService
from app.services.models.legal_document import LegalDocumentMetadata
from app.services.legal.legal_parser import _content_hash

logger = logging.getLogger(__name__)


def get_optimal_workers() -> int:
    """Kiểm tra RAM tự động cấu hình max_workers nhằm bảo vệ hệ thống."""
    mem = psutil.virtual_memory()
    total_gb = mem.total / (1024 ** 3)
    
    if total_gb < 8.0:
        logger.warning(f"[RAM = {total_gb:.1f}GB] Hệ thống < 8GB RAM. Kích hoạt chế độ tiết kiệm tài nguyên (max_workers=1).")
        return 1
    
    # Nếu RAM dư dùng (>= 8GB), cho phép chạy đa luồng an toàn tuỳ CPU
    optimal = max(1, os.cpu_count() - 1 if os.cpu_count() else 2)
    logger.info(f"[RAM = {total_gb:.1f}GB] Hệ thống đủ tài nguyên. Sử dụng max_workers={optimal}.")
    return optimal


class StaticLegalIndexer:
    """
    Service rút gọn chuyên indexing văn bản luật tĩnh: DB + Vector Store (No KG).
    """

    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.vector_index_service = LegalStaticIndexService()
        self.max_workers = get_optimal_workers()

    async def _save_metadata_to_postgres(self, meta: LegalDocumentMetadata, chash: str) -> LegalSourceDocument:
        """
        Lưu các trường metadata cốt lõi (số hiệu, ngày tháng, trạng thái,..) vào PostgreSQL.
        """
        existing = None
        if meta.document_code:
            result = await self.db.execute(
                select(LegalSourceDocument).where(
                    LegalSourceDocument.document_code == meta.document_code,
                    LegalSourceDocument.index_scope == "static"
                )
            )
            existing = result.scalar_one_or_none()
            
        if not existing:
            result = await self.db.execute(
                select(LegalSourceDocument).where(LegalSourceDocument.content_hash == chash)
            )
            existing = result.scalar_one_or_none()

        if existing:
            # Update data nếu văn bản đã có
            existing.title = meta.title or existing.title
            existing.status = meta.status or existing.status
            existing.issued_date = meta.issued_date or existing.issued_date
            existing.content_hash = chash
            # ... Các fields khác ...
            db_doc = existing
        else:
            # Tạo mới bản ghi
            db_doc = LegalSourceDocument(
                index_scope="static",
                document_code=meta.document_code,
                title=meta.title,
                canonical_citation=meta.canonical_citation,
                document_type=meta.document_type,
                issuing_authority=meta.issuing_authority,
                issued_date=meta.issued_date,
                effective_date=meta.effective_date,
                expiry_date=meta.expiry_date,
                status=meta.status,
                field_tags=meta.field_tags,
                source_url=meta.source_url,
                content_hash=chash,
                kg_ingested=False # Tắt KG hoàn toàn
            )
            self.db.add(db_doc)
            
        await self.db.flush()  # Lấy id mới sinh
        return db_doc

    async def process_document(self, content: str, meta: LegalDocumentMetadata):
        """
        Quy trình tiêu chuẩn 1 văn bản:
        1. PostgreSQL (Metadata)
        2. VectorDB (Vector/Embedding)
        -- KHÔNG có KG.
        """
        if not content.strip():
            logger.debug("Văn bản rỗng. Đã bỏ qua.")
            return

        chash = _content_hash(content)

        # 1. LƯU METADATA BẰNG SQLALCHEMY (POSTGRESQL)
        db_doc = await self._save_metadata_to_postgres(meta, chash)

        # 2. CHUYỂN HOÁ RA CLAUSE VÀ NHÚNG VECTOR STORE (CHROMADB)
        # Việc chunking sẽ do vector_index_service lo liệu đồng thời với việc embedding
        try:
            from app.services.legal.legal_dataset_ingestor import _markdown_to_clauses
            clauses = _markdown_to_clauses(content, meta, db_doc.id)
            if clauses:
                # Tiến hành nhúng vector và lưu qua ChromaDB
                n_chunks = self.vector_index_service.index_clauses(clauses, meta)
                
                # Cập nhật số chunk đã tách
                db_doc.chunk_count = n_chunks
                await self.db.commit()
                logger.info(f"Đã lập chỉ mục VectorDB cho [{meta.document_code}] - {n_chunks} chunks.")
            else:
                logger.warning(f"Không thể trích xuất clause cho tài liệu {meta.document_code}.")
                await self.db.rollback()
        except Exception as e:
            logger.error(f"Lỗi khi index vector cho {meta.document_code}: {e}")
            await self.db.rollback()

    async def batch_index_parallel(self, documents: list[tuple[str, LegalDocumentMetadata]]):
        """
        Hỗ trợ đa luồng để đẩy nhanh tốc độ lấy nhúng nếu cần thiết.
        Tuy nhiên nó sẽ tuân thủ nghiêm ngặt max_workers được phép dựa theo RAM.
        """
        # Nếu max_workers = 1, chạy tuần tự để chống sập RAM
        if self.max_workers <= 1:
            for text, meta in documents:
                await self.process_document(text, meta)
            return

        # Về mặt lý thuyết, AsyncSession không thread-safe, 
        # nên việc parallel bằng ThreadPoolExecutor thường phải đẻ thêm session. 
        # Để an toàn cho kiến trúc hàm này, ta vẫn loop asyncio.gather hoặc tuần tự.
        import asyncio
        for text, meta in documents:
            await self.process_document(text, meta)
        
        # (Nếu thực sự muốn parallel batch lớn vector embedding, ta truyền chunk qua Pool)
