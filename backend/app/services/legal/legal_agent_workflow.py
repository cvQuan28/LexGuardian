"""
Phase 5: Agentic Contract Risk Analysis Workflow
=================================================
Multi-step, multi-role workflow for contract risk analysis.

Per Spec 05, bốn vai trò agent được triển khai tuần tự:
  1. ExtractAgent       — trích xuất điều khoản cốt lõi + xác định chủ đề rủi ro
  2. StatutorySearchAgent — tìm văn bản luật liên quan từ kho tĩnh (STATIC_ONLY)
  3. ComparisonAgent    — so sánh hợp đồng với luật, phát hiện xung đột và thiếu sót
  4. RiskAuditorAgent   — kiểm tra hiệu lực, loại bỏ/đánh dấu tài liệu đã hết hạn

File được tích hợp ngược lại LegalRAGService qua method analyze_contract_risk().
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.core.config import settings
from app.services.embedder import EmbeddingService, get_embedding_service
from app.services.llm import get_llm_provider
from app.services.llm.types import LLMMessage
from app.services.legal.prompt_utils import fill_prompt_placeholders
from app.services.models.legal_document import (
    LegalClause,
    LegalCitedClause,
    LegalRetrievalResult,
    RetrievalMode,
    RiskItem,
    ContractRiskReport,
    MissingClause,
    LegalFindingEvidence,
)

logger = logging.getLogger(__name__)


def _coerce_str_list(val) -> list[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x) for x in val if x is not None]
    if isinstance(val, dict):
        return [str(k) for k in val.keys()]
    if isinstance(val, str):
        return [val] if val.strip() else []
    return [str(val)]

# ---------------------------------------------------------------------------
# Risk taxonomy (Spec 05 §Minimum Risk Taxonomy)
# ---------------------------------------------------------------------------
RISK_TAXONOMY = [
    "illegal_or_potentially_invalid_clause",
    "unlimited_liability",
    "ambiguous_obligation",
    "missing_termination_clause",
    "missing_penalty_clause",
    "missing_governing_law_clause",
    "payment_term_risk",
    "deadline_risk",
    "indemnity_risk",
    "dispute_resolution_risk",
]

# Standard clauses that any commercial contract should have
_STANDARD_CLAUSE_TYPES = {
    "termination", "force_majeure", "governing_law", "dispute_resolution",
    "confidentiality", "limitation_of_liability", "indemnification",
    "payment_terms", "intellectual_property",
}

# ---------------------------------------------------------------------------
# Intermediate data structures
# ---------------------------------------------------------------------------

@dataclass
class ExtractAgentOutput:
    """Output of ExtractAgent."""
    clauses: list[LegalClause]
    risk_topics: list[str]        # e.g. ["penalty rate", "termination conditions"]
    parties: list[str]
    governing_law: str
    detected_clause_types: set[str] = field(default_factory=set)


@dataclass
class StatutoryMatch:
    """A statute matched to a risk topic."""
    topic: str
    cited_clause: LegalCitedClause
    relevance_reason: str = ""


@dataclass
class ComparisonFinding:
    """One comparison result between a contract clause and statute."""
    case_clause_id: str
    case_clause_ref: str
    case_clause_text: str
    statutory_clause_ids: list[str]
    statutory_refs: list[str]
    risk_level: str               # "high" | "medium" | "low"
    risk_type: str
    description: str
    recommendation: str
    confidence: float             # 0–1


@dataclass
class AuditedFinding:
    """Output of RiskAuditorAgent for one ComparisonFinding."""
    finding: ComparisonFinding
    evidence: LegalFindingEvidence
    kept: bool                    # False = discarded (no active statutory support)
    discard_reason: str = ""


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_EXTRACT_CLAUSES_PROMPT = """\
You are a legal analyst extracting key clauses from a Vietnamese/English contract.

For each significant clause, return a JSON array of objects:
[
  {{
    "clause_id": "...",
    "article": "...",
    "clause_type": "one of obligation|right|penalty|termination|payment|indemnity|governing_law|dispute_resolution|force_majeure|confidentiality|definition|other",
    "text": "...",
    "parties_mentioned": ["..."]
  }}
]

CONTRACT (first 6000 chars):
{text}

Return ONLY the JSON array. No markdown fences."""

_RISK_TOPICS_PROMPT = """\
Given the following contract clause summary, list the top risk topics that should be
searched in Vietnamese legal statutes. Return a JSON array of short topic strings in Vietnamese.

Example: ["lãi suất chậm thanh toán", "điều khoản phạt vi phạm", "chấm dứt hợp đồng đơn phương"]

Clause types detected: {clause_types}
Parties: {parties}

Return ONLY the JSON array."""

_COMPARISON_PROMPT = """\
You are a senior legal analyst comparing a contract against applicable Vietnamese statutes.

CONTRACT CLAUSES:
{case_context}

APPLICABLE STATUTES:
{statutory_context}

Identify ALL conflicts, risks, or disadvantageous terms. For each finding, respond in JSON:
[
  {{
    "case_clause_id": "...",
    "case_clause_ref": "...",
    "case_clause_text": "first 200 chars of clause",
    "statutory_clause_ids": ["..."],
    "statutory_refs": ["..."],
    "risk_level": "high|medium|low",
    "risk_type": "one of {taxonomy}",
    "description": "explanation of the risk",
    "recommendation": "specific revision guidance",
    "confidence": 0.0 to 1.0
  }}
]

Return ONLY the JSON array.""".format(
    case_context="{case_context}",
    statutory_context="{statutory_context}",
    taxonomy="|".join(RISK_TAXONOMY),
)


# ---------------------------------------------------------------------------
# Agent 1: ExtractAgent
# ---------------------------------------------------------------------------

class ExtractAgent:
    """
    Trích xuất điều khoản cốt lõi từ hợp đồng và suy ra các chủ đề rủi ro.
    Tái sử dụng ContractFieldExtractor cho các trường cấu trúc cứng.
    """

    def __init__(self, llm_provider=None):
        self._llm = llm_provider or get_llm_provider()

    async def run(self, document_id: int, markdown_text: str) -> ExtractAgentOutput:
        """Extract key clauses and risk topics from contract markdown."""
        # 1. LLM-based clause extraction
        clauses = await self._extract_clauses(document_id, markdown_text)

        # 2. Derive risk topics from clause types + text
        detected_types = {c.clause_type for c in clauses if c.clause_type}
        parties = list({p for c in clauses for p in c.parties_mentioned})
        topics = await self._derive_risk_topics(detected_types, parties)

        # 3. Governing law (simple heuristic from clause types + text)
        governing_law = ""
        for c in clauses:
            if c.clause_type == "governing_law":
                governing_law = c.text[:120]
                break

        logger.info(
            f"[ExtractAgent] doc={document_id}: {len(clauses)} clauses, "
            f"{len(topics)} risk topics, parties={parties}"
        )
        return ExtractAgentOutput(
            clauses=clauses,
            risk_topics=topics,
            parties=parties,
            governing_law=governing_law,
            detected_clause_types=detected_types,
        )

    async def _extract_clauses(self, document_id: int, text: str) -> list[LegalClause]:
        prompt = fill_prompt_placeholders(_EXTRACT_CLAUSES_PROMPT, text=text[:6000])
        raw = await self._call_llm(prompt)
        try:
            data = _parse_json(raw)
            clauses = []
            for i, item in enumerate(data if isinstance(data, list) else []):
                clauses.append(LegalClause(
                    clause_id=str(item.get("clause_id") or f"c{i}"),
                    document_id=document_id,
                    source_file=f"doc_{document_id}",
                    text=str(item.get("text", "")),
                    article=str(item.get("article", "")),
                    clause_type=str(item.get("clause_type", "other")),
                    parties_mentioned=item.get("parties_mentioned", []),
                    index_scope="case",
                ))
            return clauses
        except Exception as e:
            logger.warning(f"[ExtractAgent] clause parse failed: {e}")
            return []

    async def _derive_risk_topics(self, clause_types: set[str], parties: list[str]) -> list[str]:
        prompt = fill_prompt_placeholders(
            _RISK_TOPICS_PROMPT,
            clause_types=", ".join(clause_types) or "unknown",
            parties=", ".join(parties) or "unknown",
        )
        raw = await self._call_llm(prompt)
        try:
            topics = _parse_json(raw)
            return topics if isinstance(topics, list) else []
        except Exception as e:
            logger.warning(f"[ExtractAgent] topic derivation failed: {e}")
            # Fallback: map clause types to generic topics
            return [c.replace("_", " ") for c in clause_types]

    async def _call_llm(self, prompt: str) -> str:
        messages = [LLMMessage(role="user", content=prompt)]
        return await self._llm.acomplete(messages, temperature=0.0, max_tokens=2048)


# ---------------------------------------------------------------------------
# Agent 2: StatutorySearchAgent
# ---------------------------------------------------------------------------

class StatutorySearchAgent:
    """
    Tìm văn bản luật liên quan đến từng chủ đề rủi ro từ kho tĩnh.
    Sử dụng LegalRetriever với routing_mode=STATIC_ONLY.
    """

    def __init__(self, retriever):
        self._retriever = retriever

    async def run(
        self,
        risk_topics: list[str],
        top_k_per_topic: int = 4,
    ) -> list[StatutoryMatch]:
        """Search static index for statutes relevant to each risk topic."""
        all_matches: list[StatutoryMatch] = []

        # Fan out: each topic → vector search (run concurrently)
        tasks = [
            self._search_topic(topic, top_k_per_topic)
            for topic in risk_topics[:10]  # cap at 10 topics
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for topic, result in zip(risk_topics, results):
            if isinstance(result, Exception):
                logger.warning(f"[StatutorySearchAgent] topic '{topic}' failed: {result}")
                continue
            all_matches.extend(result)

        logger.info(
            f"[StatutorySearchAgent] {len(risk_topics)} topics → {len(all_matches)} statute matches"
        )
        return all_matches

    async def _search_topic(self, topic: str, top_k: int) -> list[StatutoryMatch]:
        retrieval: LegalRetrievalResult = await self._retriever.query(
            question=topic,
            top_k=top_k,
            routing_mode=RetrievalMode.STATIC_ONLY,
            static_statuses=["active"],   # prefer effective statutes
        )
        matches = []
        for cited in retrieval.clauses:
            matches.append(StatutoryMatch(
                topic=topic,
                cited_clause=cited,
                relevance_reason=(
                    f"Similarity {cited.score:.2f} — "
                    f"{cited.clause.canonical_citation or cited.clause.title}"
                ),
            ))
        return matches


# ---------------------------------------------------------------------------
# Agent 3: ComparisonAgent
# ---------------------------------------------------------------------------

class ComparisonAgent:
    """
    So sánh từng điều khoản hợp đồng với văn bản luật liên quan.
    Phát hiện: xung đột, điều khoản bất lợi, điều khoản thiếu.
    """

    def __init__(self, llm_provider=None):
        self._llm = llm_provider or get_llm_provider()

    async def run(
        self,
        extract_output: ExtractAgentOutput,
        statutory_matches: list[StatutoryMatch],
    ) -> list[ComparisonFinding]:
        """Compare case clauses against matched statutes."""
        if not extract_output.clauses or not statutory_matches:
            logger.warning("[ComparisonAgent] No clauses or statutes to compare.")
            return []

        # Build context strings
        case_context = _format_clauses_context(extract_output.clauses[:20])
        statutory_context = _format_statutes_context(statutory_matches[:20])

        prompt = fill_prompt_placeholders(
            _COMPARISON_PROMPT,
            case_context=case_context,
            statutory_context=statutory_context,
        )
        raw = await self._call_llm(prompt)

        findings = []
        try:
            data = _parse_json(raw)
            for item in (data if isinstance(data, list) else []):
                if not isinstance(item, dict):
                    continue
                findings.append(ComparisonFinding(
                    case_clause_id=str(item.get("case_clause_id", "")),
                    case_clause_ref=str(item.get("case_clause_ref", "")),
                    case_clause_text=str(item.get("case_clause_text", ""))[:400],
                    statutory_clause_ids=_coerce_str_list(item.get("statutory_clause_ids", [])),
                    statutory_refs=_coerce_str_list(item.get("statutory_refs", [])),
                    risk_level=item.get("risk_level", "medium"),
                    risk_type=item.get("risk_type", "ambiguous_obligation"),
                    description=str(item.get("description", "")),
                    recommendation=str(item.get("recommendation", "")),
                    confidence=float(item.get("confidence", 0.5)),
                ))
        except Exception as e:
            logger.warning(f"[ComparisonAgent] parse failed: {e}")

        # Also detect structurally missing clauses (no LLM call)
        missing_types = _STANDARD_CLAUSE_TYPES - extract_output.detected_clause_types
        for mtype in missing_types:
            findings.append(ComparisonFinding(
                case_clause_id="",
                case_clause_ref="(missing)",
                case_clause_text="",
                statutory_clause_ids=[],
                statutory_refs=[],
                risk_level="medium",
                risk_type=f"missing_{mtype}_clause",
                description=f"The contract does not appear to contain a '{mtype}' clause.",
                recommendation=f"Add a standard '{mtype}' clause to reduce legal exposure.",
                confidence=0.9,
            ))

        logger.info(f"[ComparisonAgent] {len(findings)} findings identified.")
        return findings

    async def _call_llm(self, prompt: str) -> str:
        messages = [LLMMessage(role="user", content=prompt)]
        return await self._llm.acomplete(messages, temperature=0.0, max_tokens=4096)


# ---------------------------------------------------------------------------
# Agent 4: RiskAuditorAgent
# ---------------------------------------------------------------------------

class RiskAuditorAgent:
    """
    Kiểm tra hiệu lực của nguồn luật cho từng phát hiện rủi ro.
    Loại bỏ các phát hiện chỉ dựa trên văn bản đã hết hiệu lực
    trừ khi người dùng yêu cầu phân tích lịch sử.
    """

    def run(
        self,
        findings: list[ComparisonFinding],
        statutory_matches: list[StatutoryMatch],
        allow_inactive: bool = False,
    ) -> tuple[list[AuditedFinding], list[AuditedFinding]]:
        """
        Audit all findings against statute effectiveness.

        Returns:
            (validated_findings, discarded_findings)
        """
        # Build a lookup: clause_id -> status
        status_map: dict[str, str] = {}
        for sm in statutory_matches:
            cid = sm.cited_clause.clause.clause_id
            status_map[cid] = (sm.cited_clause.clause.status or "").lower()

        validated: list[AuditedFinding] = []
        discarded: list[AuditedFinding] = []

        for finding in findings:
            statuses = [status_map.get(cid, "unknown") for cid in finding.statutory_clause_ids]
            has_active = any(s == "active" for s in statuses)
            all_inactive = bool(statuses) and all(s in {"expired", "superseded"} for s in statuses)
            no_statute = not finding.statutory_clause_ids

            keep = True
            discard_reason = ""
            fallback_used = False

            if all_inactive and not allow_inactive:
                keep = False
                discard_reason = (
                    "All supporting statutes are expired or superseded. "
                    "Run with allow_inactive=True for historical analysis."
                )
            elif no_statute:
                # Structural missing-clause findings have no statute — keep them
                fallback_used = False

            support_level = (
                "strong" if has_active else
                "partial" if not all_inactive and statuses else
                "inferred" if no_statute else
                "none"
            )

            evidence = LegalFindingEvidence(
                case_clause_id=finding.case_clause_id,
                statutory_clause_ids=finding.statutory_clause_ids,
                statutory_statuses=statuses,
                support_level=support_level,
                audit_passed=keep and (has_active or no_statute),
                fallback_used=fallback_used,
                fallback_note=discard_reason if fallback_used else "",
            )

            audited = AuditedFinding(
                finding=finding,
                evidence=evidence,
                kept=keep,
                discard_reason=discard_reason,
            )

            if keep:
                validated.append(audited)
            else:
                discarded.append(audited)

        logger.info(
            f"[RiskAuditorAgent] {len(validated)} validated, {len(discarded)} discarded."
        )
        return validated, discarded


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class LegalAgentWorkflow:
    """
    Orchestrates the four-agent pipeline per Spec 05.

    Usage (via LegalRAGService):
        workflow = LegalAgentWorkflow(retriever=self.retriever)
        report = await workflow.analyze_contract_risk(
            workspace_id=ws_id,
            document_id=doc_id,
            markdown_text=md,
        )
    """

    def __init__(
        self,
        retriever,                    # LegalRetriever instance
        llm_provider=None,
    ):
        _llm = llm_provider or get_llm_provider()
        self.extract_agent = ExtractAgent(llm_provider=_llm)
        self.statutory_agent = StatutorySearchAgent(retriever=retriever)
        self.comparison_agent = ComparisonAgent(llm_provider=_llm)
        self.auditor_agent = RiskAuditorAgent()

    async def analyze_contract_risk(
        self,
        workspace_id: int,
        document_id: int,
        markdown_text: str,
        document_name: str = "",
        allow_inactive_statutes: bool = False,
    ) -> ContractRiskReport:
        """
        Multi-step contract risk analysis (Spec 05 pipeline).

        Steps:
          1. ExtractAgent       — clause extraction + risk topics
          2. StatutorySearchAgent — search static legal index per topic
          3. ComparisonAgent    — compare contract vs statutes
          4. RiskAuditorAgent   — validate findings against effectiveness
          5. Assemble ContractRiskReport
        """
        logger.info(
            f"[LegalAgentWorkflow] START doc={document_id} workspace={workspace_id}"
        )

        # ── Step 1: Extract ──────────────────────────────────────────
        extract_output = await self.extract_agent.run(document_id, markdown_text)

        # ── Step 2: Statutory Search ─────────────────────────────────
        statutory_matches = await self.statutory_agent.run(
            risk_topics=extract_output.risk_topics,
            top_k_per_topic=4,
        )

        # ── Step 3: Compare ─────────────────────────────────────────
        findings = await self.comparison_agent.run(extract_output, statutory_matches)

        # ── Step 4: Audit ────────────────────────────────────────────
        validated, discarded = self.auditor_agent.run(
            findings=findings,
            statutory_matches=statutory_matches,
            allow_inactive=allow_inactive_statutes,
        )

        # ── Step 5: Assemble report ──────────────────────────────────
        risk_items = _build_risk_items(validated)
        missing_types = _STANDARD_CLAUSE_TYPES - extract_output.detected_clause_types
        overall = _compute_overall_risk(risk_items)

        summary_lines = [
            f"Phân tích hợp đồng {document_name or document_id} phát hiện "
            f"{len(risk_items)} rủi ro ({overall}).",
        ]
        if discarded:
            summary_lines.append(
                f"{len(discarded)} phát hiện bị loại bỏ do văn bản hết hiệu lực."
            )
        if missing_types:
            summary_lines.append(
                f"Các điều khoản còn thiếu: {', '.join(sorted(missing_types))}."
            )

        report = ContractRiskReport(
            document_id=document_id,
            document_name=document_name,
            overall_risk_level=overall,
            risks=risk_items,
            parties_identified=extract_output.parties,
            governing_law=extract_output.governing_law,
            summary=" ".join(summary_lines),
            missing_clauses=sorted(missing_types),
        )

        logger.info(
            f"[LegalAgentWorkflow] DONE doc={document_id}: "
            f"{len(risk_items)} risks [{overall}], "
            f"{len(discarded)} discarded, {len(missing_types)} missing clauses"
        )
        return report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_json(raw: str):
    """Strip markdown fences and parse JSON."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned
    return json.loads(cleaned)


def _format_clauses_context(clauses: list[LegalClause]) -> str:
    parts = []
    for c in clauses:
        parts.append(
            f"[{c.clause_id}] {c.article} ({c.clause_type})\n{c.text[:500]}"
        )
    return "\n\n".join(parts)


def _format_statutes_context(matches: list[StatutoryMatch]) -> str:
    parts = []
    for m in matches:
        c = m.cited_clause.clause
        ref = c.canonical_citation or c.title or c.clause_id
        parts.append(
            f"[{c.clause_id}] {ref} (status={c.status})\n{c.text[:400]}"
        )
    return "\n\n".join(parts)


def _build_risk_items(audited: list[AuditedFinding]) -> list[RiskItem]:
    items = []
    for af in audited:
        f = af.finding
        items.append(RiskItem(
            clause_id=f.case_clause_id,
            clause_reference=f.case_clause_ref,
            risk_level=f.risk_level,
            risk_type=f.risk_type,
            description=f.description,
            recommendation=f.recommendation,
        ))
    return items


def _compute_overall_risk(risks: list[RiskItem]) -> str:
    high = sum(1 for r in risks if r.risk_level == "high")
    medium = sum(1 for r in risks if r.risk_level == "medium")
    if high >= 2:
        return "high"
    if high >= 1 or medium >= 3:
        return "medium"
    return "low"
