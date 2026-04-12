#!/usr/bin/env python3
"""
Import Static Legal Data: ChromaDB → PGVector
===============================================

Lấy dữ liệu static legal từ file ChromaDB tại:
    backend/data/static_legal_data/chroma.sqlite3

Và import nó vào bảng `vector_chunks` của PGVector 
với tên collection là `legal_static_global`.

Cách dùng:
    # Đi tới thư mục backend:
    cd backend/
    
    # Chạy script để cập nhật data:
    conda run -n gen_ai python scripts/import_static_legal.py

    # Dùng cờ --force nếu muốn xóa tực tiếp sạch data cũ trên PG và copy lại:
    conda run -n gen_ai python scripts/import_static_legal.py --force

Luồng làm việc cho các lần sau của bạn:
    1. Update/Ghi đè file chroma.sqlite3 vào thư mục `backend/data/static_legal_data/`
    2. Chạy script này
    3. Xong — không cần khởi động lại server
"""
import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Thêm đường dẫn thư mục backend vào sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("import_static_legal")

def main():
    parser = argparse.ArgumentParser(description="Import ChromaDB static legal data into PGVector")
    parser.add_argument(
        "--chroma-path",
        default=str(BACKEND_DIR / "data" / "static_legal_data"),
        help="Đường dẫn đến thư mục chứa ChromaDB (mặc định: backend/data/static_legal_data)",
    )
    parser.add_argument(
        "--collection",
        default="legal_static_global",
        help="Tên collection muốn đọc (mặc định: legal_static_global)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Số lượng chunk sẽ xử lý mỗi batch (mặc định: 500)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bắt buộc chép lại toàn bộ bằng cách xóa dữ liệu PGVector hiện có",
    )
    args = parser.parse_args()

    # ── Bước 1: Kết nối ChromaDB ──────────────────────────────────
    chroma_path = args.chroma_path
    if not os.path.exists(chroma_path):
        logger.error(f"Không tìm thấy thư mục ChromaDB tại: {chroma_path}")
        sys.exit(1)

    logger.info(f"📂 Đang mở ChromaDB tại: {chroma_path}")

    try:
        import chromadb
        client = chromadb.PersistentClient(path=chroma_path)
        collection = client.get_collection(name=args.collection)
        total_chunks = collection.count()
        logger.info(f"✅ Đã tìm thấy collection '{args.collection}' với {total_chunks:,} chunks")
    except Exception as e:
        logger.error(f"Không thể kết nối đến ChromaDB: {e}")
        sys.exit(1)

    if total_chunks == 0:
        logger.warning("Collection trống. Sẽ không có gì được import.")
        sys.exit(0)

    # ── Bước 2: Thiết lập PGVector ─────────────────────────────────────
    from app.services.vector_store import ensure_vector_tables, VectorStore

    ensure_vector_tables()

    # Tạo object VectorStore trỏ vào collection tĩnh static_legal_global
    vs = VectorStore(workspace_id=0, collection_suffix="")
    vs.collection_name = args.collection

    existing_count = vs.count()
    logger.info(f"📊 Dữ liệu PGVector '{args.collection}' hiện có: {existing_count:,}")

    if existing_count > 0:
        if args.force:
            logger.info("🗑️  --force flag được bật: Đang xóa PGVector data cũ...")
            vs.delete_collection()
            logger.info("   Đã xóa thành công.")
        else:
            logger.info(
                f"⚠️  PGVector hiện đã có sẵn {existing_count:,} chunks. "
                f"Thêm cờ --force nếu muốn re-import."
            )

    # ── Bước 3: Đọc qua ChromaDB và ghi sang PGVector ────
    batch_size = args.batch_size
    offset = 0
    imported = 0
    skipped = 0
    start_time = time.time()

    while offset < total_chunks:
        # Đọc theo batch từ DB cũ
        result = collection.get(
            limit=batch_size,
            offset=offset,
            include=["documents", "metadatas", "embeddings"],
        )

        ids = result.get("ids", [])
        documents = result.get("documents", [])
        metadatas = result.get("metadatas", [])
        embeddings = result.get("embeddings", [])

        if not ids:
            break

        # Loại bỏ các embedding None (nếu có để tránh lỗi)
        valid_indices = [i for i, emb in enumerate(embeddings) if emb is not None]

        if len(valid_indices) < len(ids):
            skipped += len(ids) - len(valid_indices)
            logger.warning(
                f"  Batch tại vị trí {offset}: Có {len(ids) - len(valid_indices)} chunks "
                f"bị thiếu embedding — sẽ tự động bỏ qua."
            )

        if valid_indices:
            batch_ids = [ids[i] for i in valid_indices]
            batch_docs = [documents[i] or "" for i in valid_indices]
            batch_metas = [metadatas[i] or {} for i in valid_indices]
            batch_embs = [embeddings[i] for i in valid_indices]

            try:
                vs.add_documents(
                    ids=batch_ids,
                    embeddings=batch_embs,
                    documents=batch_docs,
                    metadatas=batch_metas,
                )
                imported += len(batch_ids)
            except Exception as e:
                logger.error(f"  Lỗi khi insert batch tại vị trí {offset}: {e}")
                # Thử lại từng dòng một với batch bị lỗi này
                for j, idx in enumerate(valid_indices):
                    try:
                        vs.add_documents(
                            ids=[ids[idx]],
                            embeddings=[embeddings[idx]],
                            documents=[documents[idx] or ""],
                            metadatas=[metadatas[idx] or {}],
                        )
                        imported += 1
                    except Exception as e2:
                        logger.warning(f"    Bỏ qua chunk {ids[idx]}: {e2}")
                        skipped += 1

        offset += len(ids)
        elapsed = time.time() - start_time
        rate = imported / elapsed if elapsed > 0 else 0
        pct = min(100, offset / total_chunks * 100)
        logger.info(
            f"  Đang chuyển: {offset:,}/{total_chunks:,} ({pct:.0f}%) "
            f"| Đã nhập: {imported:,} | Tốc độ: {rate:.0f} chunks/s"
        )

    # ── Bước 4: Hoàn thành ──────────────────────────────────────────────
    elapsed = time.time() - start_time
    final_count = vs.count()

    logger.info("=" * 60)
    logger.info(f"✅ Hoàn tất việc Migrate ChromaDB -> PGVector!")
    logger.info(f"   Dữ liệu ChromaDB: {total_chunks:,} chunks")
    logger.info(f"   Tổng import:      {imported:,} chunks")
    logger.info(f"   Bỏ qua:           {skipped:,} chunks")
    logger.info(f"   Hiện có trên PG:  {final_count:,} chunks")
    logger.info(f"   Thời gian chạy:   {elapsed:.1f}s")
    logger.info("=" * 60)

if __name__ == "__main__":
    main()
