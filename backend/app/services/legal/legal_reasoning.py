"""
Legal Reasoning Layer
======================

Post-retrieval reasoning for legal documents:
  1. Groups related clauses by type (obligations, penalties, rights)
  2. Runs structured LLM reasoning with dedicated legal prompts
  3. Enforces strict grounding — returns "Insufficient information" when
     the retrieved context does not support the answer

Reasoning modes:
  - legal_qa       : Answer a question strictly from retrieved clauses
  - risk_analysis  : Identify and rate risks across clauses
  - obligation_map : Map obligations and rights per party
  - clause_compare : Compare two clauses for conflicts/similarities
  - missing_clause : Detect absent standard clauses
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.services.llm import get_llm_provider
from app.services.llm.types import LLMMessage
from app.services.legal.prompt_utils import fill_prompt_placeholders
from app.services.models.legal_document import (
    LegalCitedClause,
    LegalRetrievalResult,
    RiskItem,
    ContractRiskReport,
    ClauseComparison,
    MissingClause,
    ObligationSummary,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Standard clauses that should exist in most contracts
# ---------------------------------------------------------------------------
STANDARD_CLAUSES = [
    ("termination", "Termination / Chấm dứt hợp đồng — conditions under which the contract may be terminated"),
    ("force_majeure", "Force Majeure / Bất khả kháng — events that excuse non-performance"),
    ("governing_law", "Governing Law / Luật điều chỉnh — which law governs the contract"),
    ("dispute_resolution", "Dispute Resolution / Giải quyết tranh chấp — how disputes are resolved"),
    ("confidentiality", "Confidentiality / Bảo mật — obligations to protect information"),
    ("limitation_of_liability", "Limitation of Liability / Giới hạn trách nhiệm — cap on damages"),
    ("indemnification", "Indemnification / Bồi thường — obligation to compensate losses"),
    ("intellectual_property", "IP / Quyền sở hữu trí tuệ — ownership of IP created/used"),
    ("payment_terms", "Payment Terms / Điều khoản thanh toán — how and when payment is made"),
    ("representations_warranties", "Representations & Warranties — factual statements and promises"),
]


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_LEGAL_QA_PROMPT = """You are a precise legal analysis assistant.
You MUST answer the question using ONLY the retrieved clauses below.

STRICT RULES:
1. If the clauses do not provide sufficient information to answer the question, respond EXACTLY with:
   "INSUFFICIENT_INFORMATION: [brief explanation of what is missing]"
2. Do NOT add any information from your own training data.
3. Cite each clause used using its ID in brackets, e.g. [clause_id].
4. Identify any obligations, rights, or penalties relevant to the question.
5. Highlight any ambiguities or potential risks you observe.

Retrieved Clauses:
{context}

Question: {question}

Answer (cite specific clauses):"""


_RISK_ANALYSIS_PROMPT = """You are a senior legal risk analyst reviewing a contract.
Analyze the following clauses and identify ALL significant legal risks.

For each risk, respond STRICTLY in this JSON format (array of objects):
[
  {{
    "clause_id": "...",
    "clause_reference": "Article X / Section Y",
    "risk_level": "high|medium|low",
    "risk_type": "unlimited_liability|ambiguous_obligation|missing_penalty|one_sided_termination|...",
    "description": "Plain-language description of the risk",
    "recommendation": "Specific change or addition to mitigate this risk"
  }}
]

Contract Clauses:
{context}

Parties: {parties}

Respond ONLY with the JSON array. No additional text."""


_OBLIGATION_SUMMARY_PROMPT = """You are a legal analyst summarizing obligations for the party: {party}

From the following contract clauses, extract ALL:
1. OBLIGATIONS — what {party} MUST do (shall, must, phải)
2. RIGHTS — what {party} MAY do (may, has the right, có quyền)
3. PENALTIES — what happens if {party} breaches an obligation

Respond STRICTLY in this JSON format:
{{
  "obligations": [
    {{"clause_id": "...", "clause_reference": "...", "obligation_text": "...", "deadline": "..."}}
  ],
  "rights": [
    {{"clause_id": "...", "clause_reference": "...", "right_text": "..."}}
  ],
  "penalties": [
    {{"clause_id": "...", "clause_reference": "...", "penalty_text": "..."}}
  ],
  "summary": "Two-sentence summary of {party}'s position in this contract"
}}

Contract Clauses:
{context}

Respond ONLY with the JSON object. No additional text."""


_CLAUSE_COMPARE_PROMPT = """Compare the following two contract clauses and identify:
1. Similarities
2. Differences
3. Conflicts (where they contradict each other)
4. Risk assessment

Clause A (ID: {clause_a_id}):
{clause_a_text}

Clause B (ID: {clause_b_id}):
{clause_b_text}

Respond STRICTLY in this JSON format:
{{
  "similarities": ["..."],
  "differences": ["..."],
  "conflicts": ["..."],
  "recommendation": "...",
  "analysis": "Full analysis paragraph"
}}

Respond ONLY with the JSON object."""


_MISSING_CLAUSE_PROMPT = """You are a legal expert reviewing a contract for missing standard clauses.

The contract contains the following clause types:
{detected_types}

From the list of standard clauses below, identify which are MISSING or INADEQUATELY covered:
{standard_list}

For each missing clause, respond in this JSON format (array):
[
  {{
    "clause_type": "...",
    "description": "What this clause normally covers",
    "risk_if_missing": "Legal risk if this clause is absent",
    "suggested_text": "One-sentence suggested clause placeholder"
  }}
]

Respond ONLY with the JSON array."""


# ---------------------------------------------------------------------------
# Main reasoning class
# ---------------------------------------------------------------------------

class LegalReasoningLayer:
    """
    Post-retrieval legal reasoning step.

    Takes retrieved clauses and a task type, runs structured LLM reasoning,
    and enforces strict grounding (no hallucination).
    """

    def __init__(self):
        self.provider = get_llm_provider()

    async def legal_qa(
        self,
        question: str,
        retrieval_result: LegalRetrievalResult,
    ) -> tuple[str, bool]:
        """
        Answer a legal question from retrieved clauses.

        Returns:
            (answer: str, is_grounded: bool)
            If insufficient context: answer = "Insufficient information..."
        """
        context = retrieval_result.format_context()

        if not retrieval_result.clauses:
            return (
                "Insufficient information: No relevant clauses were found in the document "
                "to answer this question.",
                False,
            )

        prompt = fill_prompt_placeholders(_LEGAL_QA_PROMPT, context=context, question=question)
        response = await self._call_llm(prompt)

        # Grounding check
        if response.strip().startswith("INSUFFICIENT_INFORMATION"):
            return response.strip(), False

        return response.strip(), True

    async def analyze_contract_risk(
        self,
        context: str,
        document_id: int,
        document_name: str,
        parties: list[str],
        governing_law: str,
        detected_clause_types: list[str],
    ) -> ContractRiskReport:
        """
        Run full contract risk analysis.

        Steps:
          1. LLM risk identification across all clauses
          2. Missing clause detection
          3. Assemble report with overall risk level
        """
        # Step 1: Risk identification
        prompt = fill_prompt_placeholders(
            _RISK_ANALYSIS_PROMPT,
            context=context,
            parties=", ".join(parties) if parties else "Unknown",
        )

        raw_risks = await self._call_llm(prompt)
        risks = self._parse_risk_json(raw_risks)

        # Step 2: Missing clauses
        missing = await self._detect_missing_clauses_from_types(detected_clause_types)

        # Step 3: Overall risk level
        high_count = sum(1 for r in risks if r.risk_level == "high")
        medium_count = sum(1 for r in risks if r.risk_level == "medium")
        if high_count >= 2:
            overall = "high"
        elif high_count >= 1 or medium_count >= 3:
            overall = "medium"
        else:
            overall = "low"

        # Step 4: Summary
        summary_prompt = (
            f"Summarize in 3 sentences the main risks found in this contract.\n"
            f"Parties: {', '.join(parties)}\n"
            f"Missing clauses: {', '.join(c.clause_type for c in missing)}\n"
            f"Top risks:\n"
            + "\n".join(f"- [{r.risk_level.upper()}] {r.description}" for r in risks[:5])
        )
        summary = await self._call_llm(summary_prompt)

        return ContractRiskReport(
            document_id=document_id,
            document_name=document_name,
            overall_risk_level=overall,
            risks=risks,
            parties_identified=parties,
            governing_law=governing_law,
            summary=summary.strip(),
            missing_clauses=[c.clause_type for c in missing],
        )

    async def compare_clauses(
        self,
        clause_a: LegalCitedClause,
        clause_b: LegalCitedClause,
    ) -> ClauseComparison:
        """Compare two clauses and return structured analysis."""
        prompt = fill_prompt_placeholders(
            _CLAUSE_COMPARE_PROMPT,
            clause_a_id=str(clause_a.clause.clause_id),
            clause_a_text=clause_a.clause.text,
            clause_b_id=str(clause_b.clause.clause_id),
            clause_b_text=clause_b.clause.text,
        )
        raw = await self._call_llm(prompt)

        import json
        try:
            data = json.loads(raw.strip())
            return ClauseComparison(
                clause_a_id=clause_a.clause.clause_id,
                clause_b_id=clause_b.clause.clause_id,
                clause_a_text=clause_a.clause.text,
                clause_b_text=clause_b.clause.text,
                similarities=data.get("similarities", []),
                differences=data.get("differences", []),
                conflicts=data.get("conflicts", []),
                recommendation=data.get("recommendation", ""),
                analysis=data.get("analysis", ""),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse clause comparison JSON: {e}")
            return ClauseComparison(
                clause_a_id=clause_a.clause.clause_id,
                clause_b_id=clause_b.clause.clause_id,
                clause_a_text=clause_a.clause.text,
                clause_b_text=clause_b.clause.text,
                similarities=[],
                differences=[],
                conflicts=[],
                recommendation="",
                analysis=raw.strip(),
            )

    async def detect_missing_clauses(
        self,
        detected_clause_types: list[str],
    ) -> list[MissingClause]:
        """Identify standard clauses missing from a contract."""
        return await self._detect_missing_clauses_from_types(detected_clause_types)

    async def summarize_obligations(
        self,
        party: str,
        retrieval_result: LegalRetrievalResult,
    ) -> ObligationSummary:
        """Summarize obligations, rights, and penalties for a specific party."""
        context = retrieval_result.format_context()
        prompt = fill_prompt_placeholders(_OBLIGATION_SUMMARY_PROMPT, party=party, context=context)
        raw = await self._call_llm(prompt)

        import json
        try:
            data = json.loads(raw.strip())
            return ObligationSummary(
                party=party,
                document_id=(
                    retrieval_result.clauses[0].clause.document_id
                    if retrieval_result.clauses else 0
                ),
                obligations=data.get("obligations", []),
                rights=data.get("rights", []),
                penalties=data.get("penalties", []),
                summary=data.get("summary", ""),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse obligation summary JSON: {e}")
            return ObligationSummary(
                party=party,
                document_id=0,
                obligations=[],
                rights=[],
                penalties=[],
                summary=raw.strip(),
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _call_llm(self, prompt: str) -> str:
        """Call the configured LLM provider."""
        try:
            messages = [LLMMessage(role="user", content=prompt)]
            return await self.provider.acomplete(
                messages, temperature=0.0, max_tokens=4096
            )
        except Exception as e:
            logger.error(f"LLM call failed in LegalReasoningLayer: {e}")
            raise

    async def _detect_missing_clauses_from_types(
        self, detected_types: list[str]
    ) -> list[MissingClause]:
        """Use LLM to identify missing standard clauses."""
        detected_str = ", ".join(detected_types) if detected_types else "none detected"
        standard_list = "\n".join(
            f"- {ctype}: {desc}" for ctype, desc in STANDARD_CLAUSES
        )
        prompt = fill_prompt_placeholders(
            _MISSING_CLAUSE_PROMPT,
            detected_types=detected_str,
            standard_list=standard_list,
        )
        raw = await self._call_llm(prompt)

        import json
        try:
            data = json.loads(raw.strip())
            return [
                MissingClause(
                    clause_type=item.get("clause_type", ""),
                    description=item.get("description", ""),
                    risk_if_missing=item.get("risk_if_missing", ""),
                    suggested_text=item.get("suggested_text", ""),
                )
                for item in data
                if isinstance(item, dict)
            ]
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Failed to parse missing clauses JSON: {e}")
            return []

    @staticmethod
    def _parse_risk_json(raw: str) -> list[RiskItem]:
        """Parse JSON risk array from LLM output."""
        import json

        # Strip any markdown code fences
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned

        try:
            data = json.loads(cleaned)
            risks = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                risks.append(RiskItem(
                    clause_id=item.get("clause_id", ""),
                    clause_reference=item.get("clause_reference", ""),
                    risk_level=item.get("risk_level", "low"),
                    risk_type=item.get("risk_type", "unknown"),
                    description=item.get("description", ""),
                    recommendation=item.get("recommendation", ""),
                ))
            return risks
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Failed to parse risk JSON: {e}\nRaw: {raw[:300]}")
            return []
