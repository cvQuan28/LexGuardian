"""
Legal Metadata Graph — Phase 6 (Spec 06 Layer 2)
==================================================

Builds a programmatic, metadata-driven relationship graph on top of the
static legal corpus **without** running LightRAG entity extraction.

Responsibilities:
  - Maintain an in-memory / SQLite-backed NetworkX directed graph
    of LegalDocument nodes and typed edges:
      REPLACES, AMENDS, GUIDES_IMPLEMENTATION_OF, ISSUED_BY,
      BELONGS_TO_FIELD, REFERENCES
  - Populate edges from ChromaDB static-corpus metadata
    (canonical_citation, issuing_authority, field_tags, document_type)
  - Pattern-match document titles for known replacement/amendment keywords
  - Provide three query-time helpers (Spec 06 §Suggested API Helpers):
      find_related_statutes(document_id, relation_types) → list[dict]
      trace_implementation_chain(document_id)            → list[dict]
      get_effective_related_documents(query)             → list[dict]
  - Locate the active replacement when an expired document is retrieved

Design:
  - Storage: pure in-memory NetworkX DiGraph (re-built from ChromaDB on startup)
  - Thread-safe read access (graph is rebuilt once, read many times)
  - No write path after initial build; re-call build() to refresh
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Edge types (Spec 06 §Suggested Edge Types)
# ---------------------------------------------------------------------------
EDGE_REPLACES                  = "REPLACES"
EDGE_AMENDS                    = "AMENDS"
EDGE_GUIDES_IMPLEMENTATION_OF  = "GUIDES_IMPLEMENTATION_OF"
EDGE_ISSUED_BY                 = "ISSUED_BY"
EDGE_BELONGS_TO_FIELD          = "BELONGS_TO_FIELD"
EDGE_HAS_ARTICLE               = "HAS_ARTICLE"
EDGE_REFERENCES                = "REFERENCES"
EDGE_RELATED_TO_SUBJECT        = "RELATED_TO_SUBJECT"

# Node types (Spec 06 §Suggested Node Types)
NODE_LEGAL_DOCUMENT    = "LegalDocument"
NODE_ISSUING_AUTHORITY = "IssuingAuthority"
NODE_LEGAL_FIELD       = "LegalField"
NODE_ARTICLE           = "Article"

# Priority rank for document types (lower = higher authority)
_DOCTYPE_RANK = {"law": 1, "code": 1, "decree": 2, "circular": 3, "resolution": 3,
                 "decision": 4, "directive": 4, "other": 5}

# Regex patterns for detecting replacement/amendment signals in Vietnamese titles
_REPLACES_PATTERNS = [
    re.compile(r"thay thế[^\n]*?(nghị định|thông tư|luật|quyết định)\s+(số\s+)?[\d\/\-]+", re.IGNORECASE),
    re.compile(r"ban hành[^\n]*?thay thế\s+", re.IGNORECASE),
]
_AMENDS_PATTERNS = [
    re.compile(r"sửa đổi[^\n]*?(một số điều|điều \d+)", re.IGNORECASE),
    re.compile(r"bổ sung[^\n]*?(một số điều|điều \d+)", re.IGNORECASE),
]
_GUIDES_PATTERNS = [
    re.compile(r"hướng dẫn[^\n]*?(thi hành|thực hiện)", re.IGNORECASE),
    re.compile(r"quy định chi tiết[^\n]*?(một số điều|điều \d+)", re.IGNORECASE),
]
# Citation reference such as "Luật số 45/2019/QH14"
_CITATION_REF = re.compile(r"((?:luật|nghị định|thông tư|quyết định|nghị quyết)\s+(?:số\s+)?[\d\/\-\.]+(?:\/[\w]+)*)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Node / Edge data structures
# ---------------------------------------------------------------------------

@dataclass
class LegalDocumentNode:
    """Lightweight node representing a legal document in the metadata graph."""
    doc_id: str                       # ChromaDB chunk id or canonical_citation
    title: str = ""
    document_type: str = ""           # "law" | "decree" | "circular" etc.
    status: str = ""                  # "active" | "expired" | "superseded"
    issuing_authority: str = ""
    effective_date: str = ""
    canonical_citation: str = ""
    field_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_active(self) -> bool:
        return self.status.lower() == "active"

    @property
    def authority_rank(self) -> int:
        return _DOCTYPE_RANK.get(self.document_type.lower(), 5)


@dataclass
class LegalEdge:
    """A directed relationship between two LegalDocumentNodes."""
    source_id: str
    target_id: str
    relation: str                     # one of EDGE_* constants
    confidence: float = 1.0           # 1.0 = extracted from metadata; <1.0 = inferred
    note: str = ""                    # human-readable reason

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Main graph class
# ---------------------------------------------------------------------------

class LegalMetadataGraph:
    """
    Metadata-driven legal document relationship graph (Spec 06 Layer 2).

    Build from ChromaDB static index metadata:
        graph = LegalMetadataGraph()
        graph.build_from_chroma(collection)

    Or programmatically:
        graph.add_document(node)
        graph.add_edge(edge)

    Query:
        graph.find_related_statutes(doc_id, [EDGE_GUIDES_IMPLEMENTATION_OF])
        graph.trace_implementation_chain(doc_id)
        graph.get_effective_related_documents(query)
        graph.find_replacement(expired_doc_id)
    """

    def __init__(self):
        try:
            import networkx as nx
            self._g: nx.DiGraph = nx.DiGraph()
        except ImportError:
            raise ImportError(
                "networkx is required for LegalMetadataGraph. "
                "Install it with: pip install networkx"
            )
        self._nodes: dict[str, LegalDocumentNode] = {}
        self._built = False

    # ------------------------------------------------------------------
    # Build API
    # ------------------------------------------------------------------

    def add_document(self, node: LegalDocumentNode) -> None:
        """Add or update a document node."""
        self._nodes[node.doc_id] = node
        self._g.add_node(
            node.doc_id,
            title=node.title,
            document_type=node.document_type,
            status=node.status,
            issuing_authority=node.issuing_authority,
            canonical_citation=node.canonical_citation,
        )
        # Authority sub-node
        if node.issuing_authority:
            auth_id = f"authority::{node.issuing_authority}"
            self._g.add_node(auth_id, node_type=NODE_ISSUING_AUTHORITY)
            self._g.add_edge(node.doc_id, auth_id, relation=EDGE_ISSUED_BY)
        # Field sub-nodes
        for tag in node.field_tags:
            field_id = f"field::{tag}"
            self._g.add_node(field_id, node_type=NODE_LEGAL_FIELD)
            self._g.add_edge(node.doc_id, field_id, relation=EDGE_BELONGS_TO_FIELD)

    def add_edge(self, edge: LegalEdge) -> None:
        """Add a directed relationship edge."""
        if edge.source_id not in self._g:
            self._g.add_node(edge.source_id)
        if edge.target_id not in self._g:
            self._g.add_node(edge.target_id)
        self._g.add_edge(
            edge.source_id, edge.target_id,
            relation=edge.relation,
            confidence=edge.confidence,
            note=edge.note,
        )

    def build_from_chroma(self, vector_store) -> int:
        """
        Populate the metadata graph from a PGVector VectorStore.

        Reads all documents, creates nodes and infers edges from:
          - document_type hierarchy (law → decree → circular)
          - title-based regex for REPLACES / AMENDS / GUIDES
          - canonical_citation cross-references
          - issuing_authority and field_tags

        Args:
            vector_store: VectorStore instance pointing to the static collection.

        Returns:
            Total number of document nodes added.
        """
        logger.info("[MetadataGraph] Building from PGVector static corpus …")
        total = 0

        all_metas: list[dict] = []

        try:
            result = vector_store.get_all()
            all_metas = result.get("metadatas", []) or []
        except Exception as e:
            logger.error(f"[MetadataGraph] PGVector read failed: {e}")
            return 0

        # Deduplicate by canonical_citation (prefer first occurrence)
        seen_citations: dict[str, LegalDocumentNode] = {}
        doc_nodes: list[LegalDocumentNode] = []

        for meta in all_metas:
            citation = meta.get("canonical_citation", "")
            doc_id = citation or meta.get("document_id", "") or meta.get("chunk_id", "")
            if not doc_id:
                continue
            if doc_id in seen_citations:
                continue

            tags_raw = meta.get("field_tags", "")
            tags = [t.strip() for t in tags_raw.split("|") if t.strip()] if tags_raw else []

            node = LegalDocumentNode(
                doc_id=doc_id,
                title=meta.get("title", ""),
                document_type=meta.get("document_type", ""),
                status=meta.get("status", ""),
                issuing_authority=meta.get("issuing_authority", ""),
                effective_date=meta.get("effective_date", ""),
                canonical_citation=citation,
                field_tags=tags,
            )
            seen_citations[doc_id] = node
            doc_nodes.append(node)
            self.add_document(node)
            total += 1

        # Second pass: infer relationship edges
        self._infer_edges(doc_nodes)

        self._built = True
        logger.info(
            f"[MetadataGraph] Built: {total} documents, {self._g.number_of_edges()} edges."
        )
        return total

    def _infer_edges(self, nodes: list[LegalDocumentNode]) -> None:
        """
        Infer typed edges from document metadata patterns.

        Rules:
          1. Title contains REPLACES pattern → REPLACES edge (target found by citation ref)
          2. Title contains AMENDS pattern → AMENDS edge
          3. Title contains GUIDES pattern + doc_type in {circular, decision} → GUIDES_IMPLEMENTATION_OF
          4. Lower-authority document references a higher-authority citation
             → GUIDES_IMPLEMENTATION_OF edge
        """
        # Build citation lookup for fast reference resolution
        citation_idx: dict[str, str] = {}
        for node in nodes:
            if node.canonical_citation:
                citation_idx[node.canonical_citation.lower()] = node.doc_id
            # Also index short id variants (last segment after /)
            short = node.canonical_citation.rsplit("/", 1)[-1].lower()
            citation_idx[short] = node.doc_id

        inferred = 0
        for node in nodes:
            title = node.title.lower()
            doc_type = node.document_type.lower()

            # ── REPLACES ────────────────────────────────────────────────
            for pat in _REPLACES_PATTERNS:
                if pat.search(title):
                    refs = _CITATION_REF.findall(node.title)
                    for ref in refs:
                        target_id = citation_idx.get(ref.lower())
                        if target_id and target_id != node.doc_id:
                            self.add_edge(LegalEdge(
                                source_id=node.doc_id, target_id=target_id,
                                relation=EDGE_REPLACES, confidence=0.9,
                                note=f"Inferred from title: '{ref}'",
                            ))
                            inferred += 1

            # ── AMENDS ──────────────────────────────────────────────────
            for pat in _AMENDS_PATTERNS:
                if pat.search(title):
                    refs = _CITATION_REF.findall(node.title)
                    for ref in refs:
                        target_id = citation_idx.get(ref.lower())
                        if target_id and target_id != node.doc_id:
                            self.add_edge(LegalEdge(
                                source_id=node.doc_id, target_id=target_id,
                                relation=EDGE_AMENDS, confidence=0.85,
                                note=f"Inferred from title: '{ref}'",
                            ))
                            inferred += 1

            # ── GUIDES_IMPLEMENTATION_OF ─────────────────────────────────
            if doc_type in {"circular", "decision", "directive"} or any(
                p.search(title) for p in _GUIDES_PATTERNS
            ):
                refs = _CITATION_REF.findall(node.title)
                for ref in refs:
                    target_id = citation_idx.get(ref.lower())
                    if target_id and target_id != node.doc_id:
                        target_node = self._nodes.get(target_id)
                        # Only guide higher-authority documents
                        if target_node and target_node.authority_rank < node.authority_rank:
                            self.add_edge(LegalEdge(
                                source_id=node.doc_id, target_id=target_id,
                                relation=EDGE_GUIDES_IMPLEMENTATION_OF, confidence=0.8,
                                note=f"Guidance circular for '{ref}'",
                            ))
                            inferred += 1

        logger.info(f"[MetadataGraph] Inferred {inferred} relationship edges.")

    # ------------------------------------------------------------------
    # Query API (Spec 06 §Suggested API Helpers)
    # ------------------------------------------------------------------

    def find_related_statutes(
        self,
        document_id: str,
        relation_types: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Find all documents related to `document_id` via the given edge types.

        Per Spec 06 query-time rules:
          - If law retrieved → fetch implementing decrees/circulars
          - If expired → locate replacement

        Args:
            document_id: Source document canonical_citation or doc_id.
            relation_types: Edge types to follow (default: all).

        Returns:
            List of {"doc_id", "title", "relation", "status", "document_type", "note"} dicts.
        """
        if document_id not in self._g:
            logger.debug(f"[MetadataGraph.find_related] '{document_id}' not in graph.")
            return []

        relation_types = relation_types or [
            EDGE_GUIDES_IMPLEMENTATION_OF, EDGE_REPLACES, EDGE_AMENDS, EDGE_REFERENCES,
        ]
        results: list[dict] = []

        # Outgoing edges (this → others)
        for src, tgt, data in self._g.out_edges(document_id, data=True):
            rel = data.get("relation", "")
            if rel in relation_types:
                node = self._nodes.get(tgt, LegalDocumentNode(doc_id=tgt))
                results.append({
                    "doc_id": tgt,
                    "title": node.title,
                    "relation": rel,
                    "status": node.status,
                    "document_type": node.document_type,
                    "canonical_citation": node.canonical_citation,
                    "note": data.get("note", ""),
                    "confidence": data.get("confidence", 1.0),
                })

        # Incoming edges for GUIDES_IMPLEMENTATION_OF (find guidance circulars)
        if EDGE_GUIDES_IMPLEMENTATION_OF in relation_types:
            for src, tgt, data in self._g.in_edges(document_id, data=True):
                if data.get("relation") == EDGE_GUIDES_IMPLEMENTATION_OF:
                    node = self._nodes.get(src, LegalDocumentNode(doc_id=src))
                    results.append({
                        "doc_id": src,
                        "title": node.title,
                        "relation": f"IS_GUIDED_BY",
                        "status": node.status,
                        "document_type": node.document_type,
                        "canonical_citation": node.canonical_citation,
                        "note": data.get("note", ""),
                        "confidence": data.get("confidence", 1.0),
                    })

        # Sort: active first, then by authority rank
        results.sort(key=lambda x: (
            0 if x.get("status", "").lower() == "active" else 1,
            _DOCTYPE_RANK.get(x.get("document_type", "").lower(), 5),
        ))
        return results

    def trace_implementation_chain(self, document_id: str) -> list[dict]:
        """
        Trace the full implementation chain for a given document.

        Follows GUIDES_IMPLEMENTATION_OF edges upstream AND downstream:
          Law → (guided by) → Decree → (guided by) → Circular

        Args:
            document_id: Starting document id.

        Returns:
            Ordered list of documents from highest to lowest authority.
        """
        if document_id not in self._g:
            return []

        visited: set[str] = set()
        chain: list[dict] = []

        def _traverse(node_id: str, depth: int = 0) -> None:
            if node_id in visited or depth > 6:
                return
            visited.add(node_id)
            node = self._nodes.get(node_id)
            if node:
                chain.append({
                    "doc_id": node_id,
                    "title": node.title,
                    "document_type": node.document_type,
                    "status": node.status,
                    "canonical_citation": node.canonical_citation,
                    "depth": depth,
                })
            # Walk outgoing GUIDES edges
            for src, tgt, data in self._g.out_edges(node_id, data=True):
                if data.get("relation") == EDGE_GUIDES_IMPLEMENTATION_OF:
                    _traverse(tgt, depth + 1)
            # Walk incoming GUIDES edges (circulars guiding this law)
            for src, tgt, data in self._g.in_edges(node_id, data=True):
                if data.get("relation") == EDGE_GUIDES_IMPLEMENTATION_OF:
                    _traverse(src, depth + 1)

        _traverse(document_id)

        # Sort by authority rank (law first)
        chain.sort(key=lambda x: _DOCTYPE_RANK.get(x.get("document_type", "").lower(), 5))
        return chain

    def get_effective_related_documents(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[dict]:
        """
        Find effective (active-status) documents related to a text query.

        Matches query tokens against:
          - document titles
          - issuing authority names
          - field tags
        Only returns documents with status="active".

        Args:
            query: Free-text query (Vietnamese or English).
            max_results: Max number of results to return.

        Returns:
            List of dicts sorted by authority rank then relevance.
        """
        tokens = set(t.lower().strip(",.?!") for t in query.split() if len(t) >= 3)
        if not tokens:
            return []

        scored: list[tuple[float, LegalDocumentNode]] = []

        for node in self._nodes.values():
            if not node.is_active:
                continue
            text = " ".join([
                node.title.lower(),
                node.issuing_authority.lower(),
                " ".join(node.field_tags).lower(),
            ])
            hit_count = sum(1 for t in tokens if t in text)
            if hit_count > 0:
                score = hit_count / len(tokens)
                scored.append((score, node))

        scored.sort(key=lambda x: (-x[0], x[1].authority_rank))

        return [
            {
                "doc_id": node.doc_id,
                "title": node.title,
                "document_type": node.document_type,
                "status": node.status,
                "canonical_citation": node.canonical_citation,
                "issuing_authority": node.issuing_authority,
                "field_tags": node.field_tags,
                "relevance_score": round(score, 3),
            }
            for score, node in scored[:max_results]
        ]

    def find_replacement(self, expired_doc_id: str) -> Optional[dict]:
        """
        Find the active document that replaces an expired one.

        Semantic:  new_doc --REPLACES--> expired_doc
        So we need INCOMING edges on expired_doc_id with relation=REPLACES.

        Returns:
            Dict of the active replacement or None if unknown.
        """
        if expired_doc_id not in self._g:
            return None

        # Check incoming: new_doc → REPLACES → expired_doc_id
        for src, tgt, data in self._g.in_edges(expired_doc_id, data=True):
            if data.get("relation") == EDGE_REPLACES:
                node = self._nodes.get(src)
                if node and node.is_active:
                    return {
                        "doc_id": src,
                        "title": node.title,
                        "document_type": node.document_type,
                        "status": node.status,
                        "canonical_citation": node.canonical_citation,
                        "note": data.get("note", ""),
                    }

        # Fallback: check outgoing (old_doc declared its replacement)
        for src, tgt, data in self._g.out_edges(expired_doc_id, data=True):
            if data.get("relation") == EDGE_REPLACES:
                node = self._nodes.get(tgt)
                if node and node.is_active:
                    return {
                        "doc_id": tgt,
                        "title": node.title,
                        "document_type": node.document_type,
                        "status": node.status,
                        "canonical_citation": node.canonical_citation,
                        "note": data.get("note", ""),
                    }
        return None

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Return graph statistics."""
        edge_types: dict[str, int] = {}
        for _, _, data in self._g.edges(data=True):
            rel = data.get("relation", "UNKNOWN")
            edge_types[rel] = edge_types.get(rel, 0) + 1

        active = sum(1 for n in self._nodes.values() if n.is_active)
        expired = sum(1 for n in self._nodes.values() if n.status.lower() == "expired")

        return {
            "total_nodes": len(self._nodes),
            "total_edges": self._g.number_of_edges(),
            "active_documents": active,
            "expired_documents": expired,
            "edge_type_counts": edge_types,
        }

    def is_built(self) -> bool:
        return self._built


# ---------------------------------------------------------------------------
# Module-level singleton (shared across requests)
# ---------------------------------------------------------------------------

_global_graph: Optional[LegalMetadataGraph] = None


def get_legal_metadata_graph() -> LegalMetadataGraph:
    """Return the module-level LegalMetadataGraph singleton."""
    global _global_graph
    if _global_graph is None:
        _global_graph = LegalMetadataGraph()
    return _global_graph


async def build_legal_metadata_graph(static_index_service) -> LegalMetadataGraph:
    """
    Build the global metadata graph from the static legal index.

    Call once at application startup (or after new ingestion).

    Args:
        static_index_service: LegalStaticIndexService instance.

    Returns:
        Populated LegalMetadataGraph.
    """
    import asyncio
    graph = get_legal_metadata_graph()
    if graph.is_built():
        logger.info("[MetadataGraph] Already built, skipping rebuild.")
        return graph

    try:
        vector_store = static_index_service._vector_store
        # Run blocking PGVector scan in thread pool
        n = await asyncio.to_thread(graph.build_from_chroma, vector_store)
        logger.info(f"[MetadataGraph] Build complete: {n} documents.")
    except Exception as e:
        logger.error(f"[MetadataGraph] Build failed: {e}")

    return graph
