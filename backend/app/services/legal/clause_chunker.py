"""
Legal Clause Chunker
=====================

Replaces the generic RecursiveCharacterTextSplitter strategy with
clause-aware chunking:

  - Each LegalClause = one chunk.  No splitting mid-clause.
  - For very long clauses (> MAX_CLAUSE_TOKENS), splits only at
    paragraph boundaries within the clause (not word boundaries).
  - Returns ChromaDB-ready ids, embeddings, documents, metadatas.

Design principle:
  The atomic retrieval unit is the clause, not an arbitrary N-char window.
  This guarantees that obligation/penalty text is never split across two chunks.
"""
from __future__ import annotations

import logging
from typing import NamedTuple

from app.services.models.legal_document import LegalClause, LegalParseResult

logger = logging.getLogger(__name__)

# Maximum characters for a single clause chunk before paragraph-level splitting
MAX_CLAUSE_CHARS = 3000


class ClauseChunk(NamedTuple):
    """A clause chunk ready for embedding and indexing."""
    chunk_id: str
    content: str          # text for embedding (header + body)
    metadata: dict        # ChromaDB-compatible flat dict
    clause: LegalClause   # original clause reference


class ClauseChunker:
    """
    Converts a LegalParseResult into a flat list of ClauseChunk objects.

    Algorithm:
      1. For each LegalClause in the parse result:
           a. If its text length <= MAX_CLAUSE_CHARS → emit as-is
           b. If its text length >  MAX_CLAUSE_CHARS → split at
              paragraph breaks, preserving header context in each sub-chunk
      2. Build a unique chunk_id = "legal_{doc_id}_clause_{clause_id}_p{part}"
      3. Populate metadata compatible with the existing vector store schema
    """

    def __init__(self, max_clause_chars: int = MAX_CLAUSE_CHARS):
        self.max_clause_chars = max_clause_chars

    def chunk(self, parse_result: LegalParseResult) -> list[ClauseChunk]:
        """
        Convert a LegalParseResult into clause-level chunks.

        Args:
            parse_result: Output from LegalDocumentParser.parse()

        Returns:
            List of ClauseChunk objects, preserving clause boundaries
        """
        chunks: list[ClauseChunk] = []

        for clause in parse_result.clauses:
            clause_chunks = self._process_clause(clause)
            chunks.extend(clause_chunks)

        logger.info(
            f"ClauseChunker: {len(parse_result.clauses)} clauses → "
            f"{len(chunks)} chunks for doc {parse_result.document_id}"
        )
        return chunks

    def _process_clause(self, clause: LegalClause) -> list[ClauseChunk]:
        """
        Convert a single LegalClause into one or more chunks.
        If the clause is long, split at paragraph boundaries.
        """
        text = clause.to_chunk_text()

        if len(text) <= self.max_clause_chars:
            return [self._make_chunk(clause, text, part=0, total_parts=1)]

        # Split long clause at paragraph boundaries (double newline)
        parts = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks = []
        buf = ""
        part_idx = 0
        paragraphs_to_emit = []

        for para in parts:
            if len(buf) + len(para) + 2 <= self.max_clause_chars:
                buf = (buf + "\n\n" + para).strip()
            else:
                if buf:
                    paragraphs_to_emit.append(buf)
                buf = para

        if buf:
            paragraphs_to_emit.append(buf)

        total = len(paragraphs_to_emit)
        for idx, content in enumerate(paragraphs_to_emit):
            # Prepend header context to sub-chunks
            header = " > ".join(filter(None, [clause.article, clause.clause, clause.point]))
            if header and not content.startswith(header):
                content = f"{header} (continued):\n{content}"
            chunks.append(self._make_chunk(clause, content, part=idx, total_parts=total))

        return chunks

    @staticmethod
    def _make_chunk(
        clause: LegalClause,
        content: str,
        part: int,
        total_parts: int,
    ) -> ClauseChunk:
        """Build a ClauseChunk from a clause and its content."""
        chunk_id = f"legal_{clause.document_id}_clause_{clause.clause_id}_p{part}"
        metadata = clause.to_metadata()
        # Override chunk_index to be unique across parts
        metadata["chunk_index"] = clause.chunk_index * 100 + part
        metadata["total_parts"] = total_parts
        metadata["part_index"] = part

        return ClauseChunk(
            chunk_id=chunk_id,
            content=content,
            metadata=metadata,
            clause=clause,
        )


def chunk_legal_document(parse_result: LegalParseResult) -> list[ClauseChunk]:
    """Convenience function: chunk a LegalParseResult with default settings."""
    return ClauseChunker().chunk(parse_result)
