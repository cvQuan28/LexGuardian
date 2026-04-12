"""
Risk analysis agent for legal contract consultation.

Workflow:
  1. Parse an uploaded contract file (PDF/TXT/MD)
  2. Extract key clauses: penalty / indemnity, termination, confidentiality
  3. Generate clause-specific statutory queries
  4. Search both the static legal corpus and live trusted legal websites
  5. Compare the clause against retrieved legal basis using a strong LLM
  6. Return a structured risk report with citations and revision advice
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings
from app.services.legal.contract_extractor import ContractFieldExtractor, ContractFields
from app.services.legal.legal_parser import LegalDocumentParser
from app.services.legal.legal_static_index_service import LegalStaticIndexService
from app.services.legal.web_search import LegalWebSearchResult, LegalWebSearcher
from app.services.llm import get_llm_provider
from app.services.llm.types import LLMMessage
from app.services.models.legal_document import LegalClause

logger = logging.getLogger(__name__)


@dataclass
class LegalBasisCitation:
    citation: str
    excerpt: str
    source_type: str                   # "static" | "web"
    source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RiskClauseFinding:
    clause_type: str
    clause_reference: str
    clause_text: str
    status: str                        # "Tuân thủ" | "Rủi ro" | "Vi phạm"
    legal_basis: list[LegalBasisCitation] = field(default_factory=list)
    revision_advice: str = ""
    reasoning: str = ""
    comparison_question: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["legal_basis"] = [item.to_dict() for item in self.legal_basis]
        return payload


@dataclass
class RiskAnalysisReport:
    document_name: str
    document_type: str
    findings: list[RiskClauseFinding] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_name": self.document_name,
            "document_type": self.document_type,
            "findings": [item.to_dict() for item in self.findings],
            "summary": self.summary,
        }


class RiskAnalysisAgent:
    """
    Legal consultation agent for clause-level contract risk analysis.

    The agent is built to work even when some subsystems are unavailable:
      - static retriever is lazy-loaded
      - live web search is lazy-loaded
      - LLM comparison is attempted first, then falls back to deterministic checks
    """

    KEY_CLAUSE_LABELS = {
        "penalty": "Bồi thường / Phạt vi phạm",
        "indemnity": "Bồi thường / Phạt vi phạm",
        "termination": "Chấm dứt",
        "confidentiality": "Bảo mật",
    }

    def __init__(
        self,
        *,
        workspace_id: int = 0,
        static_index_service: Optional[LegalStaticIndexService] = None,
        web_searcher: Optional[LegalWebSearcher] = None,
        llm_provider: Any | None = None,
        parser: Optional[LegalDocumentParser] = None,
    ):
        self.workspace_id = workspace_id
        self._static_index_service = static_index_service
        self._web_searcher = web_searcher
        self._llm_provider = llm_provider
        self._parser = parser
        self._field_extractor = ContractFieldExtractor()

    async def analyze_file(
        self,
        file_path: str,
        *,
        document_id: int = 0,
        document_name: str = "",
    ) -> RiskAnalysisReport:
        path = Path(file_path)
        parser = self._get_parser()
        parse_result = parser.parse(
            file_path=path,
            document_id=document_id or 0,
            original_filename=document_name or path.name,
        )
        return await self.analyze_markdown(
            markdown_text=parse_result.markdown,
            clauses=parse_result.clauses,
            document_name=document_name or path.name,
            document_type=parse_result.document_type or "",
        )

    async def analyze_markdown(
        self,
        *,
        markdown_text: str,
        clauses: Optional[list[LegalClause]] = None,
        document_name: str = "",
        document_type: str = "",
    ) -> RiskAnalysisReport:
        if clauses is None:
            parser = self._get_parser()
            clauses = parser._extract_clauses(  # internal helper reuse for raw markdown fallback
                markdown=markdown_text,
                document_id=0,
                source_file=document_name or "contract.md",
            )

        contract_fields = self._field_extractor.extract(markdown_text)
        key_clauses = self._select_key_clauses(clauses)
        if len(key_clauses) < 2:
            fallback_clauses = self._split_markdown_sections(markdown_text, document_name or "contract")
            merged = clauses + fallback_clauses
            key_clauses = self._select_key_clauses(merged)

        findings: list[RiskClauseFinding] = []
        for clause in key_clauses:
            query_bundle = self._build_queries(clause, markdown_text, contract_fields)
            static_hits = self._retrieve_static(query_bundle)
            web_hits = await self._retrieve_web(query_bundle)
            finding = await self._assess_clause(
                clause=clause,
                markdown_text=markdown_text,
                contract_fields=contract_fields,
                static_hits=static_hits,
                web_hits=web_hits,
                query_bundle=query_bundle,
            )
            findings.append(finding)

        summary = self._build_summary(findings, document_name or "contract")
        return RiskAnalysisReport(
            document_name=document_name or "contract",
            document_type=document_type or "contract",
            findings=findings,
            summary=summary,
        )

    def _select_key_clauses(self, clauses: list[LegalClause]) -> list[LegalClause]:
        selected: list[LegalClause] = []
        seen_ids: set[str] = set()
        seen_signatures: set[tuple[str, str]] = set()

        for clause in clauses:
            key = self._classify_key_clause(clause)
            signature = (key, self._compact_text(clause.text, 160).lower())
            if key and clause.clause_id not in seen_ids and signature not in seen_signatures:
                selected.append(clause)
                seen_ids.add(clause.clause_id)
                seen_signatures.add(signature)

        selected.sort(key=lambda item: (self._clause_priority(item), item.clause_id))
        return selected[:8]

    def _split_markdown_sections(self, markdown_text: str, source_file: str) -> list[LegalClause]:
        sections = re.split(r"(?=^##\s+(?:Article|Điều)\s+\d+)", markdown_text, flags=re.MULTILINE)
        synthetic: list[LegalClause] = []
        for idx, section in enumerate(sections):
            chunk = section.strip()
            if len(chunk) < 60:
                continue
            first_line = chunk.splitlines()[0].strip()
            synthetic.append(LegalClause(
                clause_id=f"synthetic_{idx}",
                document_id=0,
                source_file=source_file,
                text=chunk,
                article=first_line.replace("##", "").strip(),
                clause_type=self._infer_clause_type_from_text(chunk),
                index_scope="case",
                canonical_citation=source_file,
            ))
        return synthetic

    def _infer_clause_type_from_text(self, text: str) -> str:
        lowered = text.lower()
        if any(token in lowered for token in ("confidential", "bảo mật", "non-disclosure")):
            return "confidentiality"
        if any(token in lowered for token in ("termination", "chấm dứt", "terminate")):
            return "termination"
        if any(token in lowered for token in ("penalty", "phạt", "bồi thường", "indemn")):
            return "penalty"
        return "other"

    def _classify_key_clause(self, clause: LegalClause) -> str:
        text = f"{clause.text} {clause.article} {clause.clause}".lower()
        if clause.clause_type == "confidentiality" or any(token in text for token in ("bảo mật", "confidential", "non-disclosure", "secret")):
            return "confidentiality"
        if clause.clause_type == "termination" or any(token in text for token in ("chấm dứt", "đơn phương chấm dứt", "terminate", "termination")):
            return "termination"
        if any(token in text for token in ("bồi thường", "indemn", "phạt vi phạm", "penalty", "liquidated damages")) or clause.clause_type == "penalty":
            if "bồi thường" in text or "indemn" in text:
                return "indemnity"
            return "penalty"
        return ""

    def _clause_priority(self, clause: LegalClause) -> int:
        kind = self._classify_key_clause(clause)
        priority = {
            "penalty": 0,
            "indemnity": 1,
            "termination": 2,
            "confidentiality": 3,
        }
        return priority.get(kind, 99)

    def _build_queries(
        self,
        clause: LegalClause,
        markdown_text: str,
        contract_fields: ContractFields,
    ) -> list[str]:
        clause_kind = self._classify_key_clause(clause)
        sector = self._infer_sector(markdown_text)
        compact_text = self._compact_text(clause.text, 220)
        queries: list[str] = []

        penalty_rate = self._extract_penalty_rate(clause.text) or self._extract_penalty_rate(contract_fields.penalty_rate)
        if clause_kind in {"penalty", "indemnity"}:
            queries.append("Điều 301 Luật Thương mại 2005 phạt vi phạm không quá 8% giá trị phần nghĩa vụ hợp đồng bị vi phạm")
            if sector == "xây dựng":
                queries.append("hợp đồng xây dựng phạt vi phạm mức tối đa bao nhiêu Luật Xây dựng")
            if penalty_rate:
                queries.append(
                    f"mức phạt vi phạm {penalty_rate:.1f}% có trái Điều 301 Luật Thương mại 2005 không"
                )

        if clause_kind == "termination":
            queries.append("điều kiện đơn phương chấm dứt hợp đồng theo pháp luật việt nam")
        if clause_kind == "confidentiality":
            queries.append("nghĩa vụ bảo mật thông tin trong hợp đồng theo pháp luật việt nam")

        queries.extend([
            compact_text,
            f"{self.KEY_CLAUSE_LABELS.get(clause_kind, clause_kind)} trong hợp đồng {sector}",
        ])

        deduped: list[str] = []
        seen: set[str] = set()
        for query in queries:
            normalized = query.strip()
            if normalized and normalized not in seen:
                deduped.append(normalized)
                seen.add(normalized)
        return deduped[:5]

    def _retrieve_static(self, queries: list[str]) -> list[LegalClause]:
        try:
            static_index = self._get_static_index_service()
        except Exception as exc:
            logger.warning("RiskAnalysisAgent static retrieval unavailable: %s", exc)
            return []

        results: list[LegalClause] = []
        seen: set[str] = set()
        for query in queries[:3]:
            embedding = static_index.embedder.embed_query(query)
            cited = static_index.query_statutes(embedding, n_results=4)
            for item in cited:
                clause = item.clause
                if clause.clause_id not in seen:
                    results.append(clause)
                    seen.add(clause.clause_id)
        return results[:6]

    async def _retrieve_web(self, queries: list[str]) -> list[LegalWebSearchResult]:
        try:
            web_searcher = self._get_web_searcher()
        except Exception as exc:
            logger.warning("RiskAnalysisAgent web search unavailable: %s", exc)
            return []

        results: list[LegalWebSearchResult] = []
        seen: set[str] = set()
        for query in queries[:3]:
            try:
                items = await web_searcher.search(query, max_results=4, topic="general", include_raw_content=False)
            except Exception as exc:
                logger.warning("RiskAnalysisAgent web query failed for %s: %s", query, exc)
                continue
            for item in items:
                if item.url not in seen:
                    results.append(item)
                    seen.add(item.url)
        return results[:6]

    async def _assess_clause(
        self,
        *,
        clause: LegalClause,
        markdown_text: str,
        contract_fields: ContractFields,
        static_hits: list[LegalClause],
        web_hits: list[LegalWebSearchResult],
        query_bundle: list[str],
    ) -> RiskClauseFinding:
        clause_kind = self._classify_key_clause(clause)
        comparison_question = self._build_comparison_question(clause, clause_kind)
        heuristic = self._rule_based_assessment(
            clause=clause,
            markdown_text=markdown_text,
            contract_fields=contract_fields,
            static_hits=static_hits,
            web_hits=web_hits,
            comparison_question=comparison_question,
        )

        llm_assessment = await self._llm_compare_clause(
            clause=clause,
            comparison_question=comparison_question,
            static_hits=static_hits,
            web_hits=web_hits,
        )

        if heuristic and heuristic.status == "Vi phạm":
            return heuristic
        if llm_assessment is not None:
            return llm_assessment
        if heuristic is not None:
            return heuristic

        legal_basis = self._build_legal_basis(static_hits, web_hits)
        return RiskClauseFinding(
            clause_type=self.KEY_CLAUSE_LABELS.get(clause_kind, clause_kind or "Điều khoản"),
            clause_reference=clause.format_reference(),
            clause_text=self._compact_text(clause.text, 500),
            status="Rủi ro",
            legal_basis=legal_basis,
            revision_advice="Rà soát lại điều khoản với luật hiện hành trước khi ký.",
            reasoning="Không đủ tín hiệu rõ ràng để kết luận tuân thủ hoàn toàn, nhưng điều khoản nên được kiểm tra pháp lý sâu hơn.",
            comparison_question=comparison_question,
        )

    def _rule_based_assessment(
        self,
        *,
        clause: LegalClause,
        markdown_text: str,
        contract_fields: ContractFields,
        static_hits: list[LegalClause],
        web_hits: list[LegalWebSearchResult],
        comparison_question: str,
    ) -> Optional[RiskClauseFinding]:
        clause_kind = self._classify_key_clause(clause)
        sector = self._infer_sector(markdown_text)
        penalty_rate = self._extract_penalty_rate(clause.text) or self._extract_penalty_rate(contract_fields.penalty_rate)

        if clause_kind in {"penalty", "indemnity"} and penalty_rate and penalty_rate > 8.0:
            legal_basis = [
                LegalBasisCitation(
                    citation="Điều 301 Luật Thương mại 2005",
                    excerpt="Mức phạt đối với vi phạm nghĩa vụ hợp đồng hoặc tổng mức phạt đối với nhiều vi phạm do các bên thỏa thuận trong hợp đồng, nhưng không quá 8% giá trị phần nghĩa vụ hợp đồng bị vi phạm.",
                    source_type="heuristic",
                )
            ]
            legal_basis.extend(self._build_legal_basis(static_hits, web_hits))
            return RiskClauseFinding(
                clause_type=self.KEY_CLAUSE_LABELS.get(clause_kind, clause_kind),
                clause_reference=clause.format_reference(),
                clause_text=self._compact_text(clause.text, 500),
                status="Vi phạm",
                legal_basis=legal_basis,
                revision_advice=(
                    "Giảm mức phạt vi phạm xuống không quá 8% giá trị phần nghĩa vụ bị vi phạm "
                    "hoặc tách bạch thiệt hại thực tế với chế tài phạt."
                ),
                reasoning=(
                    f"Điều khoản đặt mức phạt {penalty_rate:.1f}% vượt ngưỡng 8% thường được áp dụng "
                    f"theo Điều 301 Luật Thương mại 2005 cho hợp đồng thương mại{self._sector_suffix(sector)}."
                ),
                comparison_question=comparison_question,
            )

        if clause_kind == "confidentiality" and "vĩnh viễn" in clause.text.lower():
            return RiskClauseFinding(
                clause_type=self.KEY_CLAUSE_LABELS[clause_kind],
                clause_reference=clause.format_reference(),
                clause_text=self._compact_text(clause.text, 500),
                status="Rủi ro",
                legal_basis=self._build_legal_basis(static_hits, web_hits),
                revision_advice="Giới hạn thời hạn bảo mật, phạm vi thông tin mật và ngoại lệ sử dụng hợp pháp.",
                reasoning="Điều khoản bảo mật có dấu hiệu quá rộng hoặc thiếu giới hạn hợp lý.",
                comparison_question=comparison_question,
            )

        return None

    async def _llm_compare_clause(
        self,
        *,
        clause: LegalClause,
        comparison_question: str,
        static_hits: list[LegalClause],
        web_hits: list[LegalWebSearchResult],
    ) -> Optional[RiskClauseFinding]:
        try:
            llm = self._get_llm_provider()
        except Exception as exc:
            logger.warning("RiskAnalysisAgent LLM unavailable: %s", exc)
            return None

        static_context = "\n\n".join(
            f"[STATIC] {self._format_static_citation(item)}\n{self._compact_text(item.text, 500)}"
            for item in static_hits[:4]
        ) or "(none)"
        web_context = "\n\n".join(
            f"[WEB] {item.title}\nURL: {item.url}\n{self._compact_text(item.content, 400)}"
            for item in web_hits[:4]
        ) or "(none)"

        prompt = f"""
Bạn là senior legal risk analyst.

Hãy đánh giá điều khoản hợp đồng sau theo câu hỏi so sánh pháp lý:
{comparison_question}

Điều khoản hợp đồng:
{clause.text}

Nguồn luật tĩnh:
{static_context}

Nguồn web pháp lý:
{web_context}

Trả về JSON duy nhất:
{{
  "status": "Tuân thủ|Rủi ro|Vi phạm",
  "reasoning": "...",
  "revision_advice": "...",
  "legal_basis": [
    {{"citation":"...","excerpt":"...","source_type":"static|web","source_url":"..."}}
  ]
}}
""".strip()

        raw = await llm.acomplete(
            [LLMMessage(role="user", content=prompt)],
            temperature=0.0,
            max_tokens=1200,
        )
        try:
            payload = self._parse_json_object(str(raw))
        except Exception as exc:
            logger.warning("RiskAnalysisAgent could not parse LLM JSON: %s", exc)
            return None

        legal_basis = []
        for item in payload.get("legal_basis", []) if isinstance(payload.get("legal_basis"), list) else []:
            if not isinstance(item, dict):
                continue
            legal_basis.append(LegalBasisCitation(
                citation=str(item.get("citation", "")).strip(),
                excerpt=str(item.get("excerpt", "")).strip(),
                source_type=str(item.get("source_type", "")).strip() or "static",
                source_url=str(item.get("source_url", "")).strip(),
            ))

        if not legal_basis:
            legal_basis = self._build_legal_basis(static_hits, web_hits)

        return RiskClauseFinding(
            clause_type=self.KEY_CLAUSE_LABELS.get(self._classify_key_clause(clause), "Điều khoản"),
            clause_reference=clause.format_reference(),
            clause_text=self._compact_text(clause.text, 500),
            status=str(payload.get("status", "Rủi ro")).strip() or "Rủi ro",
            legal_basis=legal_basis,
            revision_advice=str(payload.get("revision_advice", "")).strip(),
            reasoning=str(payload.get("reasoning", "")).strip(),
            comparison_question=comparison_question,
        )

    def _build_legal_basis(
        self,
        static_hits: list[LegalClause],
        web_hits: list[LegalWebSearchResult],
    ) -> list[LegalBasisCitation]:
        citations: list[LegalBasisCitation] = []
        for clause in static_hits[:2]:
            citations.append(LegalBasisCitation(
                citation=self._format_static_citation(clause),
                excerpt=self._compact_text(clause.text, 240),
                source_type="static",
                source_url="",
            ))
        ranked_web_hits = sorted(
            web_hits,
            key=lambda item: (
                -self._web_hit_priority(item),
                -item.score,
            ),
        )
        for item in ranked_web_hits[:2]:
            citations.append(LegalBasisCitation(
                citation=item.title,
                excerpt=self._compact_text(item.content, 240),
                source_type="web",
                source_url=item.url,
            ))
        return citations

    def _build_comparison_question(self, clause: LegalClause, clause_kind: str) -> str:
        if clause_kind in {"penalty", "indemnity"}:
            return "Điều khoản này có trái quy định về phạt vi phạm hoặc bồi thường thiệt hại trong pháp luật thương mại/xây dựng không?"
        if clause_kind == "termination":
            return "Điều khoản này có trái quy định về điều kiện và quyền đơn phương chấm dứt hợp đồng không?"
        if clause_kind == "confidentiality":
            return "Điều khoản này có trái hoặc thiếu giới hạn cần thiết theo quy định về bảo mật thông tin không?"
        return "Điều khoản này có trái quy định pháp luật hiện hành không?"

    def _build_summary(self, findings: list[RiskClauseFinding], document_name: str) -> str:
        violation_count = sum(1 for item in findings if item.status == "Vi phạm")
        risk_count = sum(1 for item in findings if item.status == "Rủi ro")
        compliant_count = sum(1 for item in findings if item.status == "Tuân thủ")
        return (
            f"Báo cáo tư vấn cho {document_name}: "
            f"{violation_count} điều khoản vi phạm, "
            f"{risk_count} điều khoản rủi ro, "
            f"{compliant_count} điều khoản tuân thủ."
        )

    def _get_parser(self) -> LegalDocumentParser:
        if self._parser is None:
            self._parser = LegalDocumentParser(workspace_id=self.workspace_id or 0)
        return self._parser

    def _get_static_index_service(self) -> LegalStaticIndexService:
        if self._static_index_service is None:
            self._static_index_service = LegalStaticIndexService()
        return self._static_index_service

    def _get_web_searcher(self) -> LegalWebSearcher:
        if self._web_searcher is None:
            self._web_searcher = LegalWebSearcher()
        return self._web_searcher

    def _get_llm_provider(self):
        if self._llm_provider is None:
            if settings.LLM_PROVIDER.lower() == "gemini" and settings.GOOGLE_AI_API_KEY:
                from app.services.llm.gemini import GeminiLLMProvider
                self._llm_provider = GeminiLLMProvider(
                    api_key=settings.GOOGLE_AI_API_KEY,
                    model=settings.LEGAL_RISK_ANALYSIS_MODEL or settings.LLM_MODEL_FAST,
                    thinking_level=settings.LLM_THINKING_LEVEL,
                )
            else:
                self._llm_provider = get_llm_provider()
        return self._llm_provider

    def _format_static_citation(self, clause: LegalClause) -> str:
        return clause.canonical_citation or clause.title or clause.format_reference()

    def _infer_sector(self, markdown_text: str) -> str:
        lowered = markdown_text.lower()
        if any(token in lowered for token in ("xây dựng", "thi công", "construction", "công trình")):
            return "xây dựng"
        if any(token in lowered for token in ("mua bán", "hàng hóa", "sale of goods", "thương mại")):
            return "thương mại"
        return "hợp đồng"

    @staticmethod
    def _compact_text(value: str, limit: int) -> str:
        normalized = re.sub(r"\s+", " ", (value or "").strip())
        return normalized[:limit]

    @staticmethod
    def _extract_penalty_rate(value: str) -> float:
        if not value:
            return 0.0
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", value)
        if not match:
            return 0.0
        return float(match.group(1).replace(",", "."))

    @staticmethod
    def _sector_suffix(sector: str) -> str:
        if not sector or sector == "hợp đồng":
            return ""
        return f" trong lĩnh vực {sector}"

    @staticmethod
    def _web_hit_priority(item: LegalWebSearchResult) -> int:
        haystack = f"{item.title} {item.content}".lower()
        score = 0
        if "điều 301" in haystack:
            score += 5
        if "luật thương mại" in haystack:
            score += 4
        if "8%" in haystack:
            score += 3
        if "luật xây dựng" in haystack:
            score += 3
        if "thuvienphapluat.vn" in item.url:
            score += 2
        return score

    @staticmethod
    def _parse_json_object(raw: str) -> dict[str, Any]:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(lines[1:-1]).strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end >= start:
            cleaned = cleaned[start:end + 1]
        payload = json.loads(cleaned)
        if not isinstance(payload, dict):
            raise ValueError("Expected JSON object")
        return payload
