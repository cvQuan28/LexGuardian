"""
Static Legal Retriever
======================
Connects and queries the static legal Vector DB (PGVector).
Dataset: 344k Vietnamese legal documents (th1nhng0/vietnamese-legal-documents).

Read-only module — no data ingestion/writing here.
"""

import logging
from typing import List, Dict, Any

from app.services.vector_store import VectorStore
from app.services.embedder import get_embedding_service

logger = logging.getLogger(__name__)

# Constants
COLLECTION_NAME = "legal_static_global"


class StaticLegalRetriever:
    """Search the static legal corpus via PGVector."""

    def __init__(self, db_path: str = None):
        # db_path is kept for backward compatibility but ignored — vectors are in PostgreSQL now
        self._vector_store = VectorStore(workspace_id=0, collection_suffix="")
        self._vector_store.collection_name = COLLECTION_NAME
        self._embedder = get_embedding_service()

        count = self._vector_store.count()
        logger.info(
            f"✓ StaticLegalRetriever ready — PGVector collection '{COLLECTION_NAME}', "
            f"total chunks: {count}"
        )

    def retrieve(self, query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Embed the query and search for the top-K most similar legal clauses.
        """
        if not query_text or not query_text.strip():
            return []

        # 1. Encode the user query
        query_embedding = self._embedder.embed_query(query_text)

        # 2. Vector similarity search
        results = self._vector_store.query(
            query_embedding=query_embedding,
            n_results=top_k,
        )

        retrieved_list = []

        ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])
        distances = results.get("distances", [])

        if not ids:
            return retrieved_list

        # 3. Map results
        for i in range(len(ids)):
            doc_id = ids[i]
            content = documents[i] if i < len(documents) else ""
            meta = metadatas[i] if i < len(metadatas) else {}
            distance = distances[i] if i < len(distances) else 0.0

            # Cosine distance → similarity score
            sim_score = 1.0 - distance

            retrieved_list.append({
                "id": doc_id,
                "similarity_score": round(sim_score, 4),
                "metadata": meta,
                "content": content,
            })

        return retrieved_list
