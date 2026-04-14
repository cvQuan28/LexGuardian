"""
Legal Knowledge Graph Service
==============================

Extends KnowledgeGraphService with legal-domain entity types and schema.

Legal entity types:
  Party, Clause, Obligation, Right, Penalty, GoverningLaw,
  Definition, Deadline, Condition

Legal relations:
  Party → has_obligation → Obligation
  Clause → imposes_on    → Party
  Clause → references    → Clause
  Clause → has_penalty   → Penalty
  Obligation → governed_by → GoverningLaw
  Party → has_right      → Right

The KG is populated via LightRAG's LLM-based entity extraction,
with the legal entity types injected via addon_params.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

import numpy as np

from app.core.config import settings
from app.services.llm import get_embedding_provider, get_llm_provider
from app.services.llm.types import LLMMessage
from app.services.legal.legal_metadata_graph import (
    LegalMetadataGraph,
    get_legal_metadata_graph,
    EDGE_REPLACES,
    EDGE_AMENDS,
    EDGE_GUIDES_IMPLEMENTATION_OF,
    EDGE_REFERENCES,
)

logger = logging.getLogger(__name__)

# Legal-domain entity types for LightRAG extraction
LEGAL_ENTITY_TYPES = [
    "Party",           # contracting parties (Seller, Buyer, Company X)
    "Clause",          # named clauses (Article 5.2, Section 3)
    "Obligation",      # what a party must do
    "Right",           # what a party may do
    "Penalty",         # consequence of breach
    "GoverningLaw",    # applicable jurisdiction/law
    "Definition",      # defined terms in the contract
    "Deadline",        # time constraints
    "Condition",       # conditions precedent or subsequent
    "Payment",         # payment terms
    "Deliverable",     # goods, services, or deliverables
]


async def _legal_kg_llm_complete(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: Optional[list] = None,
    keyword_extraction: bool = False,
    **kwargs,
) -> str:
    """LightRAG-compatible LLM function for legal KG extraction."""
    provider = get_llm_provider()
    messages: list[LLMMessage] = []

    # Inject legal extraction context into system prompt
    legal_system = (
        "You are a legal document analysis assistant specializing in "
        "contract law. Extract entities and relationships from legal texts "
        "with high precision. Focus on: parties, obligations, rights, "
        "penalties, deadlines, conditions, and governing law."
    )
    if system_prompt:
        legal_system = legal_system + "\n\n" + system_prompt

    messages.append(LLMMessage(role="system", content=legal_system))

    if history_messages:
        for msg in history_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            messages.append(LLMMessage(role=role, content=content))

    messages.append(LLMMessage(role="user", content=prompt))

    return await provider.acomplete(messages, temperature=0.0, max_tokens=4096)


async def _legal_kg_embed(texts: list[str]) -> np.ndarray:
    """LightRAG-compatible embedding function."""
    provider = get_embedding_provider()
    return await provider.embed(texts)


class LegalKGService:
    """
    Legal-domain Knowledge Graph using LightRAG.

    Key differences from the base KnowledgeGraphService:
      1. Legal entity types are injected (Party, Clause, Obligation, etc.)
      2. Custom legal system prompt for entity extraction
      3. Helper: get_legal_context(question) — same interface as
         KnowledgeGraphService.get_relevant_context() for drop-in use

    Phase 6 extensions:
      4. Layer-2 metadata graph access via _metadata_graph property
      5. find_related_statutes()         — Spec 06 API helper 1
      6. trace_implementation_chain()    — Spec 06 API helper 2
      7. get_effective_related_documents() — Spec 06 API helper 3
      8. find_replacement()              — locate active document for expired one
    """

    def __init__(self, workspace_id: int):
        self.workspace_id = workspace_id
        self.working_dir = str(
            settings.BASE_DIR / "data" / "lightrag_legal" / f"kb_{workspace_id}"
        )
        self._rag = None
        self._initialized = False
        self._init_lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        """Lazily create the asyncio.Lock (requires running event loop)."""
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        return self._init_lock

    @property
    def _metadata_graph(self) -> LegalMetadataGraph:
        """Return the global LegalMetadataGraph singleton (Phase 6 Layer 2)."""
        return get_legal_metadata_graph()

    async def _get_rag(self):
        """Lazy-initialize LightRAG with legal entity types (thread-safe)."""
        if self._rag is not None and self._initialized:
            return self._rag

        async with self._get_lock():
            # Double-check inside lock to prevent concurrent duplicate init
            if self._rag is not None and self._initialized:
                return self._rag

            from lightrag import LightRAG
            from lightrag.utils import wrap_embedding_func_with_attrs
            from lightrag.kg.shared_storage import initialize_pipeline_status

            os.makedirs(self.working_dir, exist_ok=True)

            emb_provider = get_embedding_provider()
            embedding_dim = emb_provider.get_dimension()

            # Dimension mismatch guard
            dim_marker = Path(self.working_dir) / ".embedding_dim"
            if dim_marker.exists():
                prev_dim = int(dim_marker.read_text().strip())
                if prev_dim != embedding_dim:
                    logger.warning(
                        f"Legal KG: embedding dimension changed, clearing data "
                        f"for workspace {self.workspace_id}"
                    )
                    shutil.rmtree(self.working_dir)
                    os.makedirs(self.working_dir, exist_ok=True)
            dim_marker.write_text(str(embedding_dim))

            @wrap_embedding_func_with_attrs(embedding_dim=embedding_dim, max_token_size=8192)
            async def embedding_func(texts: list[str]) -> np.ndarray:
                return await _legal_kg_embed(texts)

            self._rag = LightRAG(
                working_dir=self.working_dir,
                llm_model_func=_legal_kg_llm_complete,
                embedding_func=embedding_func,
                chunk_token_size=settings.NEXUSRAG_KG_CHUNK_TOKEN_SIZE,
                enable_llm_cache=True,
                kv_storage="JsonKVStorage",
                vector_storage="NanoVectorDBStorage",
                graph_storage="NetworkXStorage",
                doc_status_storage="JsonDocStatusStorage",
                addon_params={
                    "language": settings.NEXUSRAG_KG_LANGUAGE,
                    "entity_types": LEGAL_ENTITY_TYPES,
                },
            )

            await self._rag.initialize_storages()
            await initialize_pipeline_status()
            self._initialized = True

            logger.info(
                f"LegalKG initialized for workspace {self.workspace_id} "
                f"(embedding_dim={embedding_dim})"
            )

        return self._rag

    async def ingest(self, text: str) -> None:
        """Ingest legal document text into the knowledge graph."""
        rag = await self._get_rag()
        if not text.strip():
            logger.warning(
                f"Legal KG: empty content for workspace {self.workspace_id}"
            )
            return
        try:
            await rag.ainsert(text)
            logger.info(
                f"Legal KG: ingested {len(text)} chars for workspace {self.workspace_id}"
            )
        except Exception as e:
            logger.error(
                f"Legal KG ingest failed for workspace {self.workspace_id}: {e}"
            )
            raise

    async def get_legal_context(
        self,
        question: str,
        max_entities: int = 25,
        max_relationships: int = 40,
    ) -> str:
        """
        Build legal-domain RAG context from raw KG data.

        Same interface as KnowledgeGraphService.get_relevant_context(),
        but returns entities and relations labeled with legal types.

        Returns:
            Formatted string of legal entities + relationships, or "" if empty.
        """
        rag = await self._get_rag()
        storage = rag.chunk_entity_relation_graph

        try:
            all_nodes = await storage.get_all_nodes()
            all_edges = await storage.get_all_edges()
        except Exception as e:
            logger.error(
                f"Legal KG: failed to get graph data for workspace {self.workspace_id}: {e}"
            )
            return ""

        if not all_nodes:
            return ""

        # Keyword extraction from question
        raw_tokens = question.lower().split()
        keywords = set()
        for token in raw_tokens:
            cleaned = token.strip(".,?!:;\"'()[]{}").lower()
            if len(cleaned) >= 2:
                keywords.add(cleaned)

        if not keywords:
            return ""

        # Match entities
        matched_entity_names: set[str] = set()
        entity_info: dict[str, dict] = {}

        for node in all_nodes:
            node_id = node.get("id", "")
            node_lower = node_id.lower()
            matched = any(kw in node_lower or node_lower in kw for kw in keywords)
            if matched:
                matched_entity_names.add(node_id)
                entity_info[node_id] = {
                    "entity_type": node.get("entity_type", "Unknown"),
                    "description": node.get("description", ""),
                }

        if not matched_entity_names and len(all_nodes) <= 50:
            for node in all_nodes[:15]:
                nid = node.get("id", "")
                matched_entity_names.add(nid)
                entity_info[nid] = {
                    "entity_type": node.get("entity_type", "Unknown"),
                    "description": node.get("description", ""),
                }

        if not matched_entity_names:
            return ""

        matched_list = list(matched_entity_names)[:max_entities]

        # Find relevant relationships
        relevant_rels: list[dict] = []
        matched_lower = {n.lower() for n in matched_list}

        for edge in all_edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            if src.lower() in matched_lower or tgt.lower() in matched_lower:
                relevant_rels.append({
                    "source": src,
                    "target": tgt,
                    "description": edge.get("description", ""),
                    "keywords": edge.get("keywords", ""),
                })
            if len(relevant_rels) >= max_relationships:
                break

        # Format output as legal-structured text
        parts: list[str] = []

        # Group entities by type
        type_groups: dict[str, list[str]] = {}
        for name in matched_list:
            etype = entity_info.get(name, {}).get("entity_type", "Unknown")
            type_groups.setdefault(etype, []).append(name)

        parts.append("Legal Entities identified in contract:")
        for etype, names in type_groups.items():
            parts.append(f"  [{etype}]: {', '.join(names)}")

        if relevant_rels:
            parts.append("")
            parts.append("Legal relationships:")
            for rel in relevant_rels:
                desc = rel["description"][:150]
                if desc:
                    parts.append(f"  {rel['source']} → {rel['target']}: {desc}")
                else:
                    parts.append(f"  {rel['source']} → {rel['target']}")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Phase 6: Spec 06 API Helpers (delegating to LegalMetadataGraph)
    # ------------------------------------------------------------------

    async def find_related_statutes(
        self,
        document_id: str,
        relation_types: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Find all statutes related to a given document via typed KG edges.

        Per Spec 06 query-time rules:
          - If law retrieved → fetch implementing decrees and circulars
          - If expired → find replacement

        Args:
            document_id: Canonical citation or internal doc_id.
            relation_types: Edge types to follow.
                            Defaults to GUIDES_IMPLEMENTATION_OF, REPLACES, AMENDS, REFERENCES.

        Returns:
            List of related document dicts ordered by status (active first) + authority.
        """
        graph = self._metadata_graph
        if not graph.is_built():
            logger.debug("[LegalKGService] Metadata graph not built; find_related_statutes returns [].")
            return []

        results = graph.find_related_statutes(document_id, relation_types)

        # Spec 06 query-time rule: expired retrieved → also attach replacement
        node = graph._nodes.get(document_id)
        if node and node.status.lower() in {"expired", "superseded"}:
            replacement = graph.find_replacement(document_id)
            if replacement and not any(r["doc_id"] == replacement["doc_id"] for r in results):
                replacement["relation"] = EDGE_REPLACES
                replacement["note"] = "Active replacement for this expired document"
                results.insert(0, replacement)

        logger.info(
            f"[LegalKGService.find_related_statutes] doc={document_id}: "
            f"{len(results)} related documents."
        )
        return results

    async def trace_implementation_chain(self, document_id: str) -> list[dict]:
        """
        Trace the full Law → Decree → Circular implementation chain.

        Per Spec 06: if system retrieves a high-level law,
        the KG should help fetch implementing decrees and circulars.

        Args:
            document_id: Starting document (usually a law or decree).

        Returns:
            Ordered list from highest authority to lowest, including status.
        """
        graph = self._metadata_graph
        if not graph.is_built():
            return []

        chain = graph.trace_implementation_chain(document_id)
        logger.info(
            f"[LegalKGService.trace_implementation_chain] doc={document_id}: "
            f"{len(chain)} documents in chain."
        )
        return chain

    async def get_effective_related_documents(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[dict]:
        """
        Find active (effective) documents matching a free-text query
        using the metadata graph's token overlap search.

        Enriches StatutorySearchAgent results with KG-derived cross-references.

        Args:
            query: Free-text query (Vietnamese or English).
            max_results: Maximum results.

        Returns:
            List of active document dicts sorted by relevance + authority.
        """
        graph = self._metadata_graph
        if not graph.is_built():
            return []

        results = graph.get_effective_related_documents(query, max_results)
        logger.info(
            f"[LegalKGService.get_effective_related_documents] query='{query[:50]}': "
            f"{len(results)} documents found."
        )
        return results

    async def find_replacement(self, expired_doc_id: str) -> Optional[dict]:
        """
        Find the active replacement for an expired/superseded document.

        Used by RiskAuditorAgent (Phase 5) and LegalRetriever to upgrade
        expired statute references to their active successors.

        Returns:
            Dict of the active replacement or None if not known.
        """
        graph = self._metadata_graph
        if not graph.is_built():
            return None
        return graph.find_replacement(expired_doc_id)

    def get_metadata_graph_stats(self) -> dict:
        """Return statistics about the Phase 6 metadata graph."""
        return self._metadata_graph.stats()

    # ------------------------------------------------------------------
    # Frontend graph compatibility
    # ------------------------------------------------------------------

    async def get_entities(
        self,
        search: str | None = None,
        entity_type: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        """List legal KG entities in the same shape as the generic KG service."""
        rag = await self._get_rag()
        storage = rag.chunk_entity_relation_graph

        try:
            all_nodes = await storage.get_all_nodes()
        except Exception as e:
            logger.error(f"Failed to get legal KG nodes for workspace {self.workspace_id}: {e}")
            return []

        entities = []
        for node in all_nodes:
            node_id = node.get("id", "")
            etype = node.get("entity_type", "Unknown")
            desc = node.get("description", "")

            if entity_type and etype.lower() != entity_type.lower():
                continue
            if search and search.lower() not in node_id.lower():
                continue

            try:
                degree = await storage.node_degree(node_id)
            except Exception:
                degree = 0

            entities.append({
                "name": node_id,
                "entity_type": etype,
                "description": desc,
                "degree": degree,
            })

        entities.sort(key=lambda e: e["degree"], reverse=True)
        return entities[offset:offset + limit]

    async def get_relationships(
        self,
        entity_name: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        """List legal KG relationships in the same shape as the generic KG service."""
        rag = await self._get_rag()
        storage = rag.chunk_entity_relation_graph

        try:
            all_edges = await storage.get_all_edges()
        except Exception as e:
            logger.error(f"Failed to get legal KG edges for workspace {self.workspace_id}: {e}")
            return []

        relationships = []
        for edge in all_edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")

            if entity_name and entity_name.lower() not in (src.lower(), tgt.lower()):
                continue

            relationships.append({
                "source": src,
                "target": tgt,
                "description": edge.get("description", ""),
                "keywords": edge.get("keywords", ""),
                "weight": float(edge.get("weight", 1.0)),
            })

        return relationships[:limit]

    async def get_graph_data(
        self,
        center_entity: str | None = None,
        max_depth: int = 3,
        max_nodes: int = 150,
    ) -> dict:
        """Export legal KG graph data for the existing frontend visualization."""
        rag = await self._get_rag()
        storage = rag.chunk_entity_relation_graph

        try:
            label = center_entity if center_entity else "*"
            kg = await storage.get_knowledge_graph(
                node_label=label,
                max_depth=max_depth,
                max_nodes=max_nodes,
            )
        except Exception as e:
            logger.error(f"Failed to get legal KG graph for workspace {self.workspace_id}: {e}")
            return {"nodes": [], "edges": [], "is_truncated": False}

        nodes = []
        for node in kg.nodes:
            props = node.properties if hasattr(node, "properties") else {}
            try:
                degree = await storage.node_degree(node.id)
            except Exception:
                degree = 0
            nodes.append({
                "id": node.id,
                "label": node.id,
                "entity_type": props.get("entity_type", "Unknown"),
                "degree": degree,
            })

        edges = []
        for edge in kg.edges:
            props = edge.properties if hasattr(edge, "properties") else {}
            edges.append({
                "source": edge.source,
                "target": edge.target,
                "label": props.get("description", "")[:80],
                "weight": float(props.get("weight", 1.0)),
            })

        return {
            "nodes": nodes,
            "edges": edges,
            "is_truncated": kg.is_truncated if hasattr(kg, "is_truncated") else False,
        }

    async def get_analytics(self) -> dict:
        """Compute legal KG analytics in the same schema as the generic service."""
        rag = await self._get_rag()
        storage = rag.chunk_entity_relation_graph

        try:
            all_nodes = await storage.get_all_nodes()
            all_edges = await storage.get_all_edges()
        except Exception as e:
            logger.error(f"Failed to get legal KG analytics for workspace {self.workspace_id}: {e}")
            return {
                "entity_count": 0,
                "relationship_count": 0,
                "entity_types": {},
                "top_entities": [],
                "avg_degree": 0.0,
            }

        entity_count = len(all_nodes)
        relationship_count = len(all_edges)

        type_counts: dict[str, int] = {}
        entities_with_degree = []
        for node in all_nodes:
            etype = node.get("entity_type", "Unknown")
            type_counts[etype] = type_counts.get(etype, 0) + 1
            try:
                degree = await storage.node_degree(node.get("id", ""))
            except Exception:
                degree = 0
            entities_with_degree.append({
                "name": node.get("id", ""),
                "entity_type": etype,
                "description": node.get("description", ""),
                "degree": degree,
            })

        entities_with_degree.sort(key=lambda e: e["degree"], reverse=True)
        top_entities = entities_with_degree[:10]
        avg_degree = (
            sum(e["degree"] for e in entities_with_degree) / entity_count
            if entity_count > 0
            else 0.0
        )

        return {
            "entity_count": entity_count,
            "relationship_count": relationship_count,
            "entity_types": type_counts,
            "top_entities": top_entities,
            "avg_degree": round(avg_degree, 2),
        }

    async def cleanup(self) -> None:
        """Finalize storages."""
        if self._rag:
            try:
                await self._rag.finalize_storages()
            except Exception:
                pass
            self._rag = None
            self._initialized = False

    def delete_project_data(self) -> None:
        """Delete all KG data for this workspace."""
        path = Path(self.working_dir)
        if path.exists():
            shutil.rmtree(path)
        self._rag = None
        self._initialized = False
        # Remove from cache so next access re-creates cleanly
        _kg_service_cache.pop(self.workspace_id, None)


# ---------------------------------------------------------------------------
# Per-workspace singleton cache — avoids re-loading LightRAG on every request
# ---------------------------------------------------------------------------

_kg_service_cache: dict[int, LegalKGService] = {}


def get_legal_kg_service(workspace_id: int) -> LegalKGService:
    """Return the cached LegalKGService for this workspace, creating if needed."""
    if workspace_id not in _kg_service_cache:
        _kg_service_cache[workspace_id] = LegalKGService(workspace_id=workspace_id)
    return _kg_service_cache[workspace_id]
