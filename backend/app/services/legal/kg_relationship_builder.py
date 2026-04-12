"""
Knowledge Graph Relationship Builder
======================================

Fixes the root cause of "0 relationships" in the KG:
LightRAG's entity extraction runs, but relationship extraction
fails when entity types don't match the text patterns.

This module provides TWO strategies:

Strategy A — Rule-based triplet extraction (instant, deterministic):
  Pattern: Subject [RELATION_KEYWORD] Object
  Example: "Bên A phải thanh toán cho Bên B"
  → (Bên A, phải_thanh_toán, Bên B)

Strategy B — LLM-based triplet extraction (accurate, slower):
  Sends clause text to LLM with structured output prompt.
  Returns list of (subject, predicate, object) triplets.

Both strategies output:
  KGRelationship list → can be stored in NetworkX / LightRAG graph

Also provides: build_relationship_text(clauses) → text with relationship
  markers injected, which dramatically helps LightRAG extract relationships
  on the NEXT ingestion.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)


# Relation type constants (mirrors Spec 06 edge types used by LegalMetadataGraph)
RELATION_REPLACES                 = "REPLACES"
RELATION_AMENDS                   = "AMENDS"
RELATION_GUIDES_IMPLEMENTATION_OF = "GUIDES_IMPLEMENTATION_OF"
RELATION_REFERENCES               = "REFERENCES"


# ===========================================================================
# Data model
# ===========================================================================

@dataclass
class KGRelationship:
    """A single (subject, predicate, object) triplet."""
    subject: str
    predicate: str             # relation type
    object: str
    clause_id: str = ""        # source clause
    clause_reference: str = "" # e.g. "Article 5 > 5.2"
    confidence: float = 1.0
    source: str = "rule"       # "rule" or "llm"

    def to_dict(self) -> dict:
        return asdict(self)

    def to_text(self) -> str:
        """Render as natural language for KG injection."""
        return f"{self.subject} {self.predicate} {self.object}"


# ===========================================================================
# Strategy A — Rule-based extraction
# ===========================================================================

# Vietnamese obligation patterns
# Format: (regex, predicate_label)
_VN_OBLIGATION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(.{5,50})\s+phải\s+(.{5,80})", re.IGNORECASE), "phải_thực_hiện"),
    (re.compile(r"(.{5,50})\s+có nghĩa vụ\s+(.{5,80})", re.IGNORECASE), "có_nghĩa_vụ"),
    (re.compile(r"(.{5,50})\s+cam kết\s+(.{5,80})", re.IGNORECASE), "cam_kết"),
    (re.compile(r"(.{5,50})\s+thanh toán\s+(.{5,80})", re.IGNORECASE), "thanh_toán"),
    (re.compile(r"(.{5,50})\s+giao\s+(.{5,80})", re.IGNORECASE), "giao_hàng"),
    (re.compile(r"(.{5,50})\s+bồi thường\s+(.{5,80})", re.IGNORECASE), "bồi_thường"),
    (re.compile(r"(.{5,50})\s+chịu trách nhiệm\s+(.{5,80})", re.IGNORECASE), "chịu_trách_nhiệm"),
]

# Vietnamese right/permission patterns
_VN_RIGHT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(.{5,50})\s+có quyền\s+(.{5,80})", re.IGNORECASE), "có_quyền"),
    (re.compile(r"(.{5,50})\s+được phép\s+(.{5,80})", re.IGNORECASE), "được_phép"),
    (re.compile(r"(.{5,50})\s+có thể\s+(.{5,80})", re.IGNORECASE), "có_thể"),
]

# Penalty patterns
_VN_PENALTY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(.{5,50})\s+(?:sẽ bị|phải nộp)\s+phạt\s+(.{5,80})", re.IGNORECASE), "bị_phạt"),
    (re.compile(r"(.{5,50})\s+phạt vi phạm\s+(.{5,80})", re.IGNORECASE), "phạt_vi_phạm"),
    (re.compile(r"mức phạt[^\n]{0,30}(?:là|bằng)\s+(.{5,80})", re.IGNORECASE), "mức_phạt"),
]

# Payment/transfer relations
_VN_PAYMENT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(.{5,50})\s+(?:trả|thanh toán|chuyển khoản)\s+(.{5,80})\s+(?:cho|đến)\s+(.{5,50})", re.IGNORECASE), "thanh_toán_cho"),
]

# Known entity anchors to clean extracted subjects/objects
_PARTY_ANCHORS = re.compile(
    r"(bên\s+[abAB]|bên\s+thứ\s+(?:nhất|hai|ba)|bên\s+(?:mua|bán|thuê|cho thuê)|"
    r"party\s+[ab]|the\s+(?:seller|buyer|supplier|client|contractor|owner))",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Phase 6: Static-document relation patterns (document-level, not clause-level)
# ---------------------------------------------------------------------------
# Format: (compiled_pattern, relation_type)
_STATIC_RELATION_PATTERNS: list[tuple[re.Pattern, str]] = [
    # REPLACES
    (re.compile(r"thay thế[^\n]*?(nghị định|thông tư|luật|quyết định)", re.IGNORECASE), RELATION_REPLACES),
    (re.compile(r"hết hiệu lực[^\n]*?(kể từ|khi|ngày)", re.IGNORECASE), RELATION_REPLACES),
    # AMENDS
    (re.compile(r"sửa đổi[^\n]*?(?:một số điều|điều \d+)", re.IGNORECASE), RELATION_AMENDS),
    (re.compile(r"bổ sung[^\n]*?(?:một số điều|điều \d+)", re.IGNORECASE), RELATION_AMENDS),
    # GUIDES_IMPLEMENTATION_OF
    (re.compile(r"hướng dẫn[^\n]*?(?:thi hành|thực hiện)", re.IGNORECASE), RELATION_GUIDES_IMPLEMENTATION_OF),
    (re.compile(r"quy định chi tiết[^\n]*?(?:một số điều|điều \d+)", re.IGNORECASE), RELATION_GUIDES_IMPLEMENTATION_OF),
    # REFERENCES
    (re.compile(r"căn cứ[^\n]*?(nghị định|thông tư|luật|quyết định)\s+(?:số\s+)?[\d\/\-]+", re.IGNORECASE), RELATION_REFERENCES),
]


class RuleBasedRelationshipExtractor:
    """
    Extract subject-predicate-object triplets from a single clause
    using deterministic regex patterns.

    Advantages:
      - Instant (no LLM call)
      - No API cost
      - Deterministic and auditable

    Limitations:
      - Only captures patterns it knows about
      - May miss complex/multi-sentence relations
    """

    def extract_from_clause(
        self,
        text: str,
        clause_id: str = "",
        clause_reference: str = "",
    ) -> list[KGRelationship]:
        """Extract all relationships from a single clause text."""
        relationships: list[KGRelationship] = []
        sentences = self._split_sentences(text)

        for sentence in sentences:
            rels = self._extract_from_sentence(sentence, clause_id, clause_reference)
            relationships.extend(rels)

        return relationships

    def extract_from_clauses(
        self,
        clauses: list[dict],
    ) -> list[KGRelationship]:
        """
        Extract relationships from a list of clause dicts.

        Args:
            clauses: [{"clause_id": "...", "text": "...", "article": "...", "clause": "..."}]
        """
        all_rels: list[KGRelationship] = []
        for clause in clauses:
            rels = self.extract_from_clause(
                text=clause.get("text", ""),
                clause_id=clause.get("clause_id", ""),
                clause_reference=f"{clause.get('article','')} {clause.get('clause','')}".strip(),
            )
            all_rels.extend(rels)
        return all_rels

    def _extract_from_sentence(
        self, sentence: str, clause_id: str, clause_ref: str
    ) -> list[KGRelationship]:
        rels: list[KGRelationship] = []

        all_patterns = (
            [(p, pred, "obligation") for p, pred in _VN_OBLIGATION_PATTERNS] +
            [(p, pred, "right") for p, pred in _VN_RIGHT_PATTERNS] +
            [(p, pred, "penalty") for p, pred in _VN_PENALTY_PATTERNS]
        )

        for pat, predicate, _ in all_patterns:
            m = pat.search(sentence)
            if m:
                groups = m.groups()
                if len(groups) >= 2:
                    subject = self._clean_entity(groups[0])
                    obj = self._clean_entity(groups[1])
                    if subject and obj and subject != obj:
                        rels.append(KGRelationship(
                            subject=subject,
                            predicate=predicate,
                            object=obj[:80],
                            clause_id=clause_id,
                            clause_reference=clause_ref,
                            confidence=0.85,
                            source="rule",
                        ))

        # Payment triplets (3 groups: payer, amount, receiver)
        for pat, predicate in _VN_PAYMENT_PATTERNS:
            m = pat.search(sentence)
            if m and len(m.groups()) >= 3:
                subject = self._clean_entity(m.group(1))
                obj_amount = self._clean_entity(m.group(2))
                receiver = self._clean_entity(m.group(3))
                if subject and receiver:
                    rels.append(KGRelationship(
                        subject=subject,
                        predicate=predicate,
                        object=f"{obj_amount} → {receiver}"[:80],
                        clause_id=clause_id,
                        clause_reference=clause_ref,
                        confidence=0.9,
                        source="rule",
                    ))

        return rels

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split clause text into sentences."""
        sentences = re.split(r'(?<=[.!?;])\s+', text)
        return [s.strip() for s in sentences if len(s.strip()) > 10]

    @staticmethod
    def _clean_entity(raw: str) -> str:
        """Trim extracted entity text to the most informative part."""
        raw = raw.strip()
        # Keep only up to first sentence terminator
        raw = re.split(r'[.!?;,]', raw)[0].strip()
        # Prefer party anchor if present
        anchor = _PARTY_ANCHORS.search(raw)
        if anchor:
            return anchor.group(0).strip().title()
        # Return first 60 chars
        return raw[:60].strip()

    def extract_static_relations(
        self,
        doc_id: str,
        title: str,
        preamble: str = "",
    ) -> list[KGRelationship]:
        """
        Phase 6: Extract document-level relations (REPLACES / AMENDS / GUIDES / REFERENCES)
        from a legal statute's title and preamble text.

        These relations are used to populate LegalMetadataGraph edges in addition to
        the pattern-based inference already done in `_infer_edges()`.

        Args:
            doc_id:   Canonical citation or internal document id.
            title:    Document title (usually short, e.g. "Thông tư 09/2024/TT-BTC").
            preamble: Optional preamble text (first 1000 chars of body).

        Returns:
            List of KGRelationship with subject=doc_id and object=cited_ref.
        """
        text = f"{title}\n{preamble[:1000]}"
        rels: list[KGRelationship] = []

        for pattern, relation in _STATIC_RELATION_PATTERNS:
            if pattern.search(text):
                # Extract citation references from the matched segment
                from app.services.legal.legal_metadata_graph import _CITATION_REF
                refs = _CITATION_REF.findall(text)
                if refs:
                    for ref in refs[:3]:  # cap at 3 per pattern
                        rels.append(KGRelationship(
                            subject=doc_id,
                            predicate=relation,
                            object=ref.strip()[:80],
                            clause_id=doc_id,
                            clause_reference=title[:80],
                            confidence=0.80,
                            source="rule_static",
                        ))
                else:
                    # Signal detected but no specific citation; use a generic object
                    rels.append(KGRelationship(
                        subject=doc_id,
                        predicate=relation,
                        object="[unresolved]",
                        clause_id=doc_id,
                        clause_reference=title[:80],
                        confidence=0.50,
                        source="rule_static",
                    ))

        return rels


# ===========================================================================
# Strategy B — LLM-based extraction
# ===========================================================================

_LLM_TRIPLET_PROMPT = """Extract legal relationships from this contract clause as JSON triplets.

For each relationship, return:
  - "subject": who performs the action (entity name)
  - "predicate": the relationship type (use snake_case from list below)
  - "object": what/who the action targets

Allowed predicate types:
  has_obligation, has_right, must_pay, must_deliver, imposes_penalty,
  governed_by, references, has_deadline, is_responsible_for, has_liability_cap

Clause text:
{text}

Return ONLY a JSON array. Example:
[
  {{"subject": "Bên A", "predicate": "must_pay", "object": "Bên B"}},
  {{"subject": "Điều 5", "predicate": "has_obligation", "object": "Bên A"}}
]

If no clear relationships exist, return: []"""


class LLMRelationshipExtractor:
    """
    Uses an LLM to extract relationship triplets from clause text.
    Higher accuracy than rule-based, but slower and costs API credits.

    Best used for:
      - Complex multi-party clauses
      - Penalty/consequence clauses
      - Cross-reference detection
    """

    def __init__(self, llm_provider):
        self.llm_provider = llm_provider

    async def extract_from_clause(
        self,
        text: str,
        clause_id: str = "",
        clause_reference: str = "",
    ) -> list[KGRelationship]:
        """Extract relationships from a single clause using LLM."""
        from app.services.llm.types import LLMMessage

        if len(text) < 30:
            return []

        try:
            prompt = _LLM_TRIPLET_PROMPT.format(text=text[:800])
            messages = [LLMMessage(role="user", content=prompt)]
            raw = await self.llm_provider.acomplete(
                messages, temperature=0.0, max_tokens=512
            )

            raw = raw.strip()
            if raw.startswith("```"):
                raw = "\n".join(raw.split("\n")[1:-1])

            data = json.loads(raw)
            if not isinstance(data, list):
                return []

            rels = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                subj = item.get("subject", "").strip()
                pred = item.get("predicate", "").strip()
                obj = item.get("object", "").strip()
                if subj and pred and obj:
                    rels.append(KGRelationship(
                        subject=subj[:80],
                        predicate=pred[:50],
                        object=obj[:80],
                        clause_id=clause_id,
                        clause_reference=clause_reference,
                        confidence=0.92,
                        source="llm",
                    ))
            return rels

        except Exception as e:
            logger.warning(f"LLM triplet extraction failed: {e}")
            return []

    async def extract_from_clauses_batch(
        self,
        clauses: list[dict],
        max_concurrent: int = 3,
    ) -> list[KGRelationship]:
        """
        Extract from multiple clauses concurrently.
        Limits concurrency to avoid rate limits.
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _extract_one(clause: dict) -> list[KGRelationship]:
            async with semaphore:
                return await self.extract_from_clause(
                    text=clause.get("text", ""),
                    clause_id=clause.get("clause_id", ""),
                    clause_reference=f"{clause.get('article','')} {clause.get('clause','')}".strip(),
                )

        results = await asyncio.gather(*[_extract_one(c) for c in clauses])
        all_rels: list[KGRelationship] = []
        for rels in results:
            all_rels.extend(rels)
        return all_rels


# ===========================================================================
# Relationship text injection (for LightRAG re-ingestion)
# ===========================================================================

def build_relationship_enriched_text(
    markdown: str,
    relationships: list[KGRelationship],
) -> str:
    """
    Inject extracted relationship triplets into the document markdown
    as structured annotations.

    This dramatically improves LightRAG's relationship extraction on
    the NEXT ingestion because the triplets are expressed in a clear
    Subject → Predicate → Object format that LightRAG's LLM recognizes.

    Example output:
        [LEGAL_RELATIONSHIP]: Bên A --has_obligation--> thanh toán đúng hạn
        [LEGAL_RELATIONSHIP]: Điều 5 --imposes_penalty--> Bên A

    Args:
        markdown: Original contract markdown
        relationships: Extracted relationships

    Returns:
        Enriched markdown with relationship block appended
    """
    if not relationships:
        return markdown

    lines = [
        "",
        "## LEGAL_RELATIONSHIPS_INDEX",
        "The following relationships were extracted from this contract:",
        "",
    ]

    for rel in relationships:
        lines.append(
            f"[LEGAL_RELATIONSHIP]: {rel.subject} --{rel.predicate}--> {rel.object}"
            + (f" [source: {rel.clause_reference}]" if rel.clause_reference else "")
        )

    return markdown + "\n".join(lines)


# ===========================================================================
# Combined extractor (Rule first, LLM for remainder)
# ===========================================================================

class HybridRelationshipExtractor:
    """
    Combines rule-based and LLM-based extraction.

    Strategy:
      1. Run rule-based extraction on all clauses (fast, free)
      2. For clauses where rule-based found 0 relationships,
         run LLM extraction (only on penalty/obligation clauses)
    """

    def __init__(self, llm_provider=None):
        self.rule_extractor = RuleBasedRelationshipExtractor()
        self.llm_extractor = LLMRelationshipExtractor(llm_provider) if llm_provider else None

    async def extract(
        self,
        clauses: list[dict],
        use_llm_for_empty: bool = True,
        priority_types: Optional[list[str]] = None,
    ) -> list[KGRelationship]:
        """
        Extract relationships from all clauses.

        Args:
            clauses: [{"clause_id", "text", "article", "clause", "clause_type"}]
            use_llm_for_empty: Use LLM on clauses where rule-based found nothing
            priority_types: Clause types to prioritize for LLM ("penalty", "obligation")

        Returns:
            All extracted relationships
        """
        priority_types = priority_types or ["penalty", "obligation", "payment"]

        # Step 1: Rule-based extraction on everything
        rule_rels = self.rule_extractor.extract_from_clauses(clauses)
        rule_by_clause = {r.clause_id for r in rule_rels}

        all_rels = list(rule_rels)

        # Step 2: LLM fallback for empty clauses (priority types only)
        if use_llm_for_empty and self.llm_extractor:
            llm_candidates = [
                c for c in clauses
                if (c.get("clause_id", "") not in rule_by_clause
                    and c.get("clause_type", "") in priority_types
                    and len(c.get("text", "")) > 50)
            ]

            if llm_candidates:
                logger.info(
                    f"KG hybrid extractor: {len(llm_candidates)} clauses sent to LLM"
                )
                llm_rels = await self.llm_extractor.extract_from_clauses_batch(
                    llm_candidates, max_concurrent=3
                )
                all_rels.extend(llm_rels)

        logger.info(
            f"KG relationship extraction complete: {len(all_rels)} relationships "
            f"(rule={len(rule_rels)}, llm={len(all_rels)-len(rule_rels)})"
        )
        return all_rels
