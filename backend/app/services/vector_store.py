"""
Vector Store Service — PGVector
=================================
Stores and retrieves document embeddings using pgvector extension on PostgreSQL.
Replaces ChromaDB to eliminate in-memory index loading.

Vectors are stored on disk and PostgreSQL's buffer cache loads only the
pages required for each query, allowing large corpora without excessive RAM.
"""
from __future__ import annotations

import json
import logging
from typing import Sequence, Optional

import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

_sync_conn: Optional[psycopg2.extensions.connection] = None


def _parse_database_url(url: str) -> dict:
    """Convert an asyncpg:// DATABASE_URL to psycopg2 connection kwargs."""
    # postgresql+asyncpg://user:pass@host:port/db → psycopg2 params
    clean = url.replace("postgresql+asyncpg://", "")
    userpass, hostdb = clean.split("@", 1)
    user, password = userpass.split(":", 1)
    hostport, dbname = hostdb.split("/", 1)
    if ":" in hostport:
        host, port = hostport.split(":", 1)
    else:
        host, port = hostport, "5432"
    return dict(
        host=host,
        port=int(port),
        user=user,
        password=password,
        dbname=dbname,
    )


def get_sync_connection() -> psycopg2.extensions.connection:
    """Get or create a reusable synchronous psycopg2 connection with pgvector."""
    global _sync_conn
    if _sync_conn is None or _sync_conn.closed:
        params = _parse_database_url(settings.DATABASE_URL)
        _sync_conn = psycopg2.connect(**params)
        _sync_conn.autocommit = True
        register_vector(_sync_conn)
        logger.info(
            f"PGVector: Connected to PostgreSQL at {params['host']}:{params['port']}/{params['dbname']}"
        )
    return _sync_conn


def _reset_connection():
    """Reset the global connection (e.g. after an error)."""
    global _sync_conn
    if _sync_conn is not None:
        try:
            _sync_conn.close()
        except Exception:
            pass
        _sync_conn = None


def ensure_vector_tables():
    """Create the vector_chunks table and indexes if they don't exist.

    Called once at application startup from main.py lifespan.
    """
    conn = get_sync_connection()
    cur = conn.cursor()
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vector_chunks (
                id TEXT NOT NULL,
                collection_name TEXT NOT NULL,
                document TEXT,
                metadata JSONB DEFAULT '{}',
                embedding vector,
                PRIMARY KEY (id, collection_name)
            )
        """)
        # Indexes for common query patterns
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_vc_collection
            ON vector_chunks (collection_name)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_vc_metadata_document_id
            ON vector_chunks ((metadata->>'document_id'))
        """)
        logger.info("PGVector: vector_chunks table ensured")
    except Exception as e:
        logger.error(f"PGVector: Failed to create tables: {e}")
        _reset_connection()
        raise
    finally:
        cur.close()


def _ensure_ivfflat_index(collection_name: str, dimension: int):
    """Create an IVFFlat index for the collection if it doesn't exist yet.

    IVFFlat is chosen over HNSW because:
      - Lower memory usage (indexes stay on disk)
      - Good accuracy for < 1M vectors with lists~100
    """
    index_name = f"idx_vc_ivfflat_{collection_name.replace('-', '_')}"
    conn = get_sync_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT 1 FROM pg_indexes WHERE indexname = %s", (index_name,)
        )
        if cur.fetchone() is None:
            # Choose number of lists based on expected corpus size
            # sqrt(n) is a good heuristic; default to 100 for safety
            n_lists = 100
            cur.execute(f"""
                CREATE INDEX {index_name}
                ON vector_chunks
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = {n_lists})
                WHERE collection_name = '{collection_name}'
            """)
            logger.info(
                f"PGVector: Created IVFFlat index '{index_name}' "
                f"(dim={dimension}, lists={n_lists})"
            )
    except Exception as e:
        # Index creation can fail if no rows yet (dimension unknown)
        # This is fine — it will be created on next add
        logger.debug(f"PGVector: IVFFlat index not created yet: {e}")
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# VectorStore class — same public API as the old ChromaDB wrapper
# ---------------------------------------------------------------------------

class VectorStore:
    """
    Vector store service for managing document embeddings in PostgreSQL.
    Each workspace has its own collection (identified by collection_name).
    """

    COLLECTION_PREFIX = "kb_"

    def __init__(self, workspace_id: int, collection_suffix: str = ""):
        self.workspace_id = workspace_id
        self.collection_name = f"{self.COLLECTION_PREFIX}{workspace_id}{collection_suffix}"
        self._dimension: Optional[int] = None

    def add_documents(
        self,
        ids: Sequence[str],
        embeddings: Sequence[list[float]],
        documents: Sequence[str],
        metadatas: Sequence[dict] | None = None,
    ) -> None:
        """Add documents with their embeddings to the collection."""
        if not ids:
            return

        conn = get_sync_connection()
        cur = conn.cursor()
        try:
            values = []
            for i, (doc_id, emb, doc) in enumerate(zip(ids, embeddings, documents)):
                meta = metadatas[i] if metadatas else {}
                # Serialize metadata to JSON string
                meta_json = json.dumps(meta, ensure_ascii=False, default=str)
                values.append((doc_id, self.collection_name, doc, meta_json, emb))

            # Upsert: ON CONFLICT update the document
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO vector_chunks (id, collection_name, document, metadata, embedding)
                VALUES %s
                ON CONFLICT (id, collection_name) DO UPDATE SET
                    document = EXCLUDED.document,
                    metadata = EXCLUDED.metadata,
                    embedding = EXCLUDED.embedding
                """,
                values,
                template="(%s, %s, %s, %s::jsonb, %s::vector)",
                page_size=500,
            )

            if self._dimension is None and embeddings:
                self._dimension = len(embeddings[0])
                _ensure_ivfflat_index(self.collection_name, self._dimension)

            logger.info(
                f"PGVector: Added {len(ids)} documents to collection '{self.collection_name}'"
            )
        except Exception as e:
            logger.error(f"PGVector: add_documents failed: {e}")
            _reset_connection()
            raise
        finally:
            cur.close()

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 5,
        where: dict | None = None,
        include: list[str] | None = None,
    ) -> dict:
        """Query the collection for similar documents using cosine distance.

        Returns dict with keys: ids, documents, metadatas, distances
        (same shape as the old ChromaDB response).
        """
        conn = get_sync_connection()
        cur = conn.cursor()
        try:
            # Build WHERE clause from metadata filters
            conditions = ["collection_name = %s"]
            params: list = [self.collection_name]

            if where:
                sql_cond, sql_params = self._build_where_sql(where)
                if sql_cond:
                    conditions.append(sql_cond)
                    params.extend(sql_params)

            where_clause = " AND ".join(conditions)

            # Cosine distance: lower = more similar
            # pgvector <=> operator = cosine distance
            # ORDER BY distance (alias) works in PostgreSQL
            cur.execute(
                f"""
                SELECT id, document, metadata,
                       embedding <=> %s::vector AS distance
                FROM vector_chunks
                WHERE {where_clause}
                ORDER BY distance
                LIMIT %s
                """,
                [query_embedding] + params + [n_results],
            )

            rows = cur.fetchall()

            result_ids = []
            result_docs = []
            result_metas = []
            result_distances = []

            for row in rows:
                result_ids.append(row[0])
                result_docs.append(row[1] or "")
                meta = row[2] if isinstance(row[2], dict) else {}
                result_metas.append(meta)
                result_distances.append(float(row[3]))

            return {
                "ids": result_ids,
                "documents": result_docs,
                "metadatas": result_metas,
                "distances": result_distances,
            }
        except Exception as e:
            logger.error(f"PGVector: query failed: {e}")
            _reset_connection()
            return {"ids": [], "documents": [], "metadatas": [], "distances": []}
        finally:
            cur.close()

    def delete_by_document_id(self, document_id: int) -> None:
        """Delete all chunks belonging to a specific document."""
        conn = get_sync_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                DELETE FROM vector_chunks
                WHERE collection_name = %s
                  AND metadata->>'document_id' = %s
                """,
                [self.collection_name, str(document_id)],
            )
            logger.info(
                f"PGVector: Deleted chunks for document {document_id} "
                f"from collection '{self.collection_name}'"
            )
        except Exception as e:
            logger.error(f"PGVector: delete_by_document_id failed: {e}")
            _reset_connection()
        finally:
            cur.close()

    def delete_collection(self) -> None:
        """Delete all data for this collection."""
        conn = get_sync_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "DELETE FROM vector_chunks WHERE collection_name = %s",
                [self.collection_name],
            )
            logger.info(f"PGVector: Deleted collection '{self.collection_name}'")
        except Exception as e:
            logger.warning(f"PGVector: Failed to delete collection '{self.collection_name}': {e}")
            _reset_connection()
        finally:
            cur.close()

    def count(self) -> int:
        """Return the number of documents in the collection."""
        conn = get_sync_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT COUNT(*) FROM vector_chunks WHERE collection_name = %s",
                [self.collection_name],
            )
            return cur.fetchone()[0]
        except Exception as e:
            logger.error(f"PGVector: count failed: {e}")
            _reset_connection()
            return 0
        finally:
            cur.close()

    def get_by_ids(self, ids: Sequence[str]) -> dict:
        """Get documents by their IDs."""
        if not ids:
            return {"ids": [], "documents": [], "metadatas": []}

        conn = get_sync_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT id, document, metadata
                FROM vector_chunks
                WHERE collection_name = %s AND id = ANY(%s)
                """,
                [self.collection_name, list(ids)],
            )
            rows = cur.fetchall()
            return {
                "ids": [r[0] for r in rows],
                "documents": [r[1] or "" for r in rows],
                "metadatas": [r[2] if isinstance(r[2], dict) else {} for r in rows],
            }
        except Exception as e:
            logger.error(f"PGVector: get_by_ids failed: {e}")
            _reset_connection()
            return {"ids": [], "documents": [], "metadatas": []}
        finally:
            cur.close()

    def get_all(
        self,
        where: dict | None = None,
        include: list[str] | None = None,
    ) -> dict:
        """Get all documents from the collection (with optional filter).

        This replaces the old ChromaDB collection.get() calls.
        """
        conn = get_sync_connection()
        cur = conn.cursor()
        try:
            conditions = ["collection_name = %s"]
            params: list = [self.collection_name]

            if where:
                sql_cond, sql_params = self._build_where_sql(where)
                if sql_cond:
                    conditions.append(sql_cond)
                    params.extend(sql_params)

            where_clause = " AND ".join(conditions)
            cur.execute(
                f"SELECT id, document, metadata FROM vector_chunks WHERE {where_clause}",
                params,
            )
            rows = cur.fetchall()
            return {
                "ids": [r[0] for r in rows],
                "documents": [r[1] or "" for r in rows],
                "metadatas": [r[2] if isinstance(r[2], dict) else {} for r in rows],
            }
        except Exception as e:
            logger.error(f"PGVector: get_all failed: {e}")
            _reset_connection()
            return {"ids": [], "documents": [], "metadatas": []}
        finally:
            cur.close()

    def delete_where(self, where: dict) -> None:
        """Delete documents matching a metadata filter."""
        conn = get_sync_connection()
        cur = conn.cursor()
        try:
            conditions = ["collection_name = %s"]
            params: list = [self.collection_name]

            sql_cond, sql_params = self._build_where_sql(where)
            if sql_cond:
                conditions.append(sql_cond)
                params.extend(sql_params)

            where_clause = " AND ".join(conditions)
            cur.execute(f"DELETE FROM vector_chunks WHERE {where_clause}", params)
        except Exception as e:
            logger.error(f"PGVector: delete_where failed: {e}")
            _reset_connection()
        finally:
            cur.close()

    # ------------------------------------------------------------------
    # Metadata filter → SQL translation
    # ------------------------------------------------------------------

    @staticmethod
    def _build_where_sql(where: dict) -> tuple[str, list]:
        """Convert ChromaDB-style where filters to SQL conditions.

        Supports:
          {"key": value}                    → metadata->>'key' = value
          {"key": {"$eq": value}}           → metadata->>'key' = value
          {"key": {"$in": [values]}}        → metadata->>'key' = ANY(...)
          {"$and": [...conditions]}         → (cond1) AND (cond2) ...
        """
        if not where:
            return "", []

        if "$and" in where:
            parts = []
            params = []
            for sub in where["$and"]:
                sub_sql, sub_params = VectorStore._build_where_sql(sub)
                if sub_sql:
                    parts.append(f"({sub_sql})")
                    params.extend(sub_params)
            return " AND ".join(parts), params

        conditions = []
        params = []
        for key, value in where.items():
            if key.startswith("$"):
                continue
            if isinstance(value, dict):
                if "$eq" in value:
                    conditions.append(f"metadata->>'{key}' = %s")
                    params.append(str(value["$eq"]))
                elif "$in" in value:
                    str_values = [str(v) for v in value["$in"]]
                    conditions.append(f"metadata->>'{key}' = ANY(%s)")
                    params.append(str_values)
                elif "$ne" in value:
                    conditions.append(f"metadata->>'{key}' != %s")
                    params.append(str(value["$ne"]))
            else:
                conditions.append(f"metadata->>'{key}' = %s")
                params.append(str(value))

        return " AND ".join(conditions), params


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_vector_store(workspace_id: int, collection_suffix: str = "") -> VectorStore:
    """Factory function to create a VectorStore for a workspace.

    Args:
        workspace_id: The workspace ID
        collection_suffix: Optional suffix (e.g. '_legal')
    """
    return VectorStore(workspace_id, collection_suffix=collection_suffix)
