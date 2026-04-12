"""
Intent router for legal chat flows.

This router sits in front of heavier legal services and decides which path
should execute next:

  - INTERNAL_RECALL: basic legal recall from the internal corpus
  - LIVE_SEARCH: questions about newly issued laws or effectiveness checks
  - CONTRACT_RISK: contract review for user-uploaded documents

The implementation is intentionally lazy:
  - classification uses fast heuristics first
  - LLM disambiguation is loaded only for borderline cases
  - downstream heavy services are created only when the winning intent is known
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Sequence

logger = logging.getLogger(__name__)


class LegalIntent(str, Enum):
    """Supported legal intents for the backend legal assistant."""

    INTERNAL_RECALL = "INTERNAL_RECALL"
    LIVE_SEARCH = "LIVE_SEARCH"
    CONTRACT_RISK = "CONTRACT_RISK"


@dataclass
class RouterMessage:
    """Normalized chat message used by the router."""

    role: str
    content: str


@dataclass
class IntentRouterResult:
    """Structured router result with JSON-friendly serialization helpers."""

    intent: LegalIntent
    reasoning: str
    suggested_tools: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["intent"] = self.intent.value
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


ServiceLoader = Callable[[], Any]


class IntentRouterAgent:
    """
    Lightweight planner for legal requests.

    The router does not eagerly construct heavy services. Instead:
      1. score the request with string/rule heuristics
      2. optionally use a lazy LLM fallback if the scores are ambiguous
      3. expose resolve_service(intent) so the caller can lazily instantiate
         only the execution path required by the predicted intent
    """

    _LIVE_SEARCH_PATTERNS = (
        re.compile(r"\b(mới nhất|mới ban hành|vừa ban hành|latest|newly issued)\b", re.IGNORECASE),
        re.compile(r"\b(còn hiệu lực|hết hiệu lực|hiệu lực|effective|validity|in force)\b", re.IGNORECASE),
        re.compile(r"\b(đã bị thay thế|bị thay thế|superseded|replaced|amended)\b", re.IGNORECASE),
        re.compile(r"\b(hiện nay|hiện tại|bây giờ|today|current|currently|now)\b", re.IGNORECASE),
        re.compile(r"\b(tháng trước|tuần trước|năm nay|năm ngoái|hôm nay|gần đây|recent|recently|last month|last week)\b", re.IGNORECASE),
        re.compile(r"\b(ban hành|issued|promulgated)\b", re.IGNORECASE),
        re.compile(r"\b(nghị định|thông tư|quyết định|nghị quyết|luật)\s+số\b", re.IGNORECASE),
        re.compile(r"\b(luật|bộ luật|nghị định|thông tư|nghị quyết|quyết định)\b[^\n]{0,80}\b(19|20)\d{2}\b", re.IGNORECASE),
    )

    _CONTRACT_RISK_PATTERNS = (
        re.compile(r"\b(phân tích|review|soát xét|đánh giá)\b[^\n]{0,40}\b(hợp đồng|contract)\b", re.IGNORECASE),
        re.compile(r"\b(rủi ro hợp đồng|contract risk|điều khoản bất lợi)\b", re.IGNORECASE),
        re.compile(r"\b(file|pdf|docx|upload|tải lên|đính kèm|văn bản này|hợp đồng này)\b", re.IGNORECASE),
        re.compile(r"\b(bên a|bên b|party a|party b|termination clause|penalty clause)\b", re.IGNORECASE),
    )

    _INTERNAL_RECALL_PATTERNS = (
        re.compile(r"\b(quy định|quy định gì|thế nào|là gì|điều kiện|nguyên tắc)\b", re.IGNORECASE),
        re.compile(r"\b(luật|bộ luật|nghị định|thông tư|quyền|nghĩa vụ|trách nhiệm)\b", re.IGNORECASE),
    )

    _SHORT_FOLLOW_UP_PATTERN = re.compile(
        r"^(còn|thế còn|vậy còn|nếu vậy|trường hợp này|cái này|văn bản này|hợp đồng này|nó)\b",
        re.IGNORECASE,
    )

    _INTENT_TOOLS: dict[LegalIntent, list[str]] = {
        LegalIntent.INTERNAL_RECALL: [
            "internal_recall_service",
            "legal_rag_service.legal_query",
        ],
        LegalIntent.LIVE_SEARCH: [
            "live_search_service",
            "legal_effectiveness_checker",
        ],
        LegalIntent.CONTRACT_RISK: [
            "contract_risk_service",
            "legal_rag_service.analyze_contract_risk",
            "legal_agent_workflow",
        ],
    }

    def __init__(
        self,
        *,
        llm_provider_factory: Optional[Callable[[], Any]] = None,
        internal_recall_loader: Optional[ServiceLoader] = None,
        live_search_loader: Optional[ServiceLoader] = None,
        contract_risk_loader: Optional[ServiceLoader] = None,
    ):
        self._llm_provider_factory = llm_provider_factory or self._get_default_llm_provider
        self._llm = None
        self._service_loaders: dict[LegalIntent, Optional[ServiceLoader]] = {
            LegalIntent.INTERNAL_RECALL: internal_recall_loader,
            LegalIntent.LIVE_SEARCH: live_search_loader,
            LegalIntent.CONTRACT_RISK: contract_risk_loader,
        }
        self._service_cache: dict[LegalIntent, Any] = {}

    async def route(
        self,
        question: str,
        chat_history: Optional[Sequence[str | dict[str, Any] | RouterMessage]] = None,
    ) -> dict[str, Any]:
        """Return the routing decision in the JSON shape requested by the product."""
        result = await self.classify(question=question, chat_history=chat_history)
        return result.to_dict()

    async def classify(
        self,
        question: str,
        chat_history: Optional[Sequence[str | dict[str, Any] | RouterMessage]] = None,
    ) -> IntentRouterResult:
        """Classify a request using heuristics first, then a lazy LLM fallback."""
        history = self._normalize_history(chat_history)
        standalone_question = self._build_standalone_question(question, history)
        scores = self._score_intents(standalone_question, history)
        best_intent, best_score = max(scores.items(), key=lambda item: item[1])
        sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        runner_up_score = sorted_scores[1][1]

        if best_score <= 1 or (best_score - runner_up_score) <= 1:
            llm_result = await self._classify_with_llm(
                question=standalone_question,
                chat_history=history,
            )
            if llm_result is not None:
                return llm_result

        reasoning = self._build_reasoning(best_intent, standalone_question, history, scores)
        return IntentRouterResult(
            intent=best_intent,
            reasoning=reasoning,
            suggested_tools=self._INTENT_TOOLS[best_intent],
        )

    def resolve_service(self, intent: LegalIntent | str) -> Any:
        """
        Lazily instantiate the heavy service bound to an intent.

        This keeps the router cheap during classification. A service is created
        only if the caller explicitly resolves the chosen path.
        """
        normalized_intent = LegalIntent(intent)
        if normalized_intent in self._service_cache:
            return self._service_cache[normalized_intent]

        loader = self._service_loaders.get(normalized_intent)
        if loader is None:
            return None

        service = loader()
        self._service_cache[normalized_intent] = service
        logger.debug("IntentRouterAgent lazy-loaded service for intent=%s", normalized_intent.value)
        return service

    def peek_service_status(self) -> dict[str, bool]:
        """Small debugging helper to confirm lazy loading behavior in tests."""
        return {
            intent.value: intent in self._service_cache
            for intent in LegalIntent
        }

    def _normalize_history(
        self,
        chat_history: Optional[Sequence[str | dict[str, Any] | RouterMessage]],
    ) -> list[RouterMessage]:
        if not chat_history:
            return []

        normalized: list[RouterMessage] = []
        for item in chat_history:
            if isinstance(item, RouterMessage):
                content = (item.content or "").strip()
                if content:
                    normalized.append(RouterMessage(role=item.role or "user", content=content))
                continue

            if isinstance(item, str):
                content = item.strip()
                if content:
                    normalized.append(RouterMessage(role="user", content=content))
                continue

            if isinstance(item, dict):
                content = str(item.get("content", "")).strip()
                if content:
                    normalized.append(
                        RouterMessage(
                            role=str(item.get("role", "user")),
                            content=content,
                        )
                    )
        return normalized[-12:]

    def _build_standalone_question(
        self,
        question: str,
        history: list[RouterMessage],
    ) -> str:
        current = question.strip()
        if not current:
            return ""

        if not history or len(current.split()) > 12:
            return current

        if not self._SHORT_FOLLOW_UP_PATTERN.search(current):
            return current

        for message in reversed(history):
            if message.role.lower() not in {"user", "assistant"}:
                continue
            prior = message.content.strip()
            if prior:
                return f"{prior}\nFollow-up question: {current}"

        return current

    def _score_intents(
        self,
        question: str,
        history: list[RouterMessage],
    ) -> dict[LegalIntent, int]:
        combined = "\n".join([msg.content for msg in history[-4:]] + [question]).lower()
        scores = {
            LegalIntent.INTERNAL_RECALL: 0,
            LegalIntent.LIVE_SEARCH: 0,
            LegalIntent.CONTRACT_RISK: 0,
        }

        for pattern in self._LIVE_SEARCH_PATTERNS:
            if pattern.search(combined):
                scores[LegalIntent.LIVE_SEARCH] += 2

        for pattern in self._CONTRACT_RISK_PATTERNS:
            if pattern.search(combined):
                scores[LegalIntent.CONTRACT_RISK] += 2

        for pattern in self._INTERNAL_RECALL_PATTERNS:
            if pattern.search(combined):
                scores[LegalIntent.INTERNAL_RECALL] += 1

        if any(token in combined for token in ("điều", "khoản", "điểm", "article", "clause")):
            scores[LegalIntent.INTERNAL_RECALL] += 1
            scores[LegalIntent.CONTRACT_RISK] += 1

        if any(token in combined for token in ("upload", "tải lên", "đính kèm", ".pdf", ".docx")):
            scores[LegalIntent.CONTRACT_RISK] += 3

        if any(token in combined for token in ("hiệu lực", "còn hiệu lực", "hết hiệu lực", "thay thế", "mới ban hành")):
            scores[LegalIntent.LIVE_SEARCH] += 3

        if any(token in combined for token in ("mới nhất", "ban hành", "tháng trước", "tuần trước", "gần đây", "last month", "recently")):
            scores[LegalIntent.LIVE_SEARCH] += 2

        if re.search(
            r"\b(luật|bộ luật|nghị định|thông tư|nghị quyết|quyết định)\b[^\n]{0,80}\b(19|20)\d{2}\b",
            combined,
            re.IGNORECASE,
        ):
            scores[LegalIntent.LIVE_SEARCH] += 3

        if len(question.split()) <= 8 and re.search(
            r"^(luật|bộ luật|nghị định|thông tư|nghị quyết|quyết định)\b",
            question.strip(),
            re.IGNORECASE,
        ):
            scores[LegalIntent.LIVE_SEARCH] += 1

        if scores[LegalIntent.CONTRACT_RISK] == 0 and scores[LegalIntent.LIVE_SEARCH] == 0:
            scores[LegalIntent.INTERNAL_RECALL] += 2

        return scores

    def _build_reasoning(
        self,
        intent: LegalIntent,
        question: str,
        history: list[RouterMessage],
        scores: dict[LegalIntent, int],
    ) -> str:
        history_hint = ""
        if history:
            history_hint = " Chat history was used to rewrite a short follow-up into a standalone question."

        if intent == LegalIntent.CONTRACT_RISK:
            return (
                "The request references an uploaded contract, contract clauses, or review/risk language, "
                "so it should go through the contract-risk workflow instead of plain legal recall."
                f"{history_hint} Scores={{{', '.join(f'{k.value}:{v}' for k, v in scores.items())}}}."
            )

        if intent == LegalIntent.LIVE_SEARCH:
            return (
                "The request asks about recency, issuance, replacement, or legal effectiveness status, "
                "which requires a live-search/effectiveness path rather than only the internal static corpus."
                f"{history_hint} Scores={{{', '.join(f'{k.value}:{v}' for k, v in scores.items())}}}."
            )

        return (
            "The request looks like a basic legal recall question about rules, definitions, or obligations "
            "without clear signals that a live status check or contract-risk workflow is needed."
            f"{history_hint} Scores={{{', '.join(f'{k.value}:{v}' for k, v in scores.items())}}}."
        )

    async def _classify_with_llm(
        self,
        *,
        question: str,
        chat_history: list[RouterMessage],
    ) -> Optional[IntentRouterResult]:
        """
        Lazy LLM fallback for borderline cases.

        The provider is not created unless heuristics are ambiguous.
        """
        try:
            llm = self._get_llm()
        except Exception as exc:
            logger.warning("IntentRouterAgent could not initialize LLM fallback: %s", exc)
            return None

        history_text = "\n".join(
            f"{message.role}: {message.content}"
            for message in chat_history[-6:]
        ) or "(empty)"

        prompt = f"""
You are an intent router for a Vietnamese legal assistant.

Choose exactly one intent:
- INTERNAL_RECALL: hỏi luật cơ bản, giải thích quy định, nghĩa vụ, điều kiện
- LIVE_SEARCH: hỏi luật mới ban hành, kiểm tra văn bản còn hiệu lực hay đã bị thay thế
- CONTRACT_RISK: phân tích rủi ro hợp đồng người dùng tải lên

Return JSON only:
{{"intent":"...","reasoning":"...","suggested_tools":["..."]}}

Chat history:
{history_text}

Question:
{question}
""".strip()

        try:
            from app.services.llm.types import LLMMessage

            raw = await llm.acomplete(
                [LLMMessage(role="user", content=prompt)],
                temperature=0.0,
                max_tokens=300,
            )
            payload = self._parse_json_object(str(raw))
            intent = LegalIntent(str(payload.get("intent", "")).strip())
            reasoning = str(payload.get("reasoning", "")).strip() or "LLM fallback classified the request."
            suggested_tools = payload.get("suggested_tools")
            if not isinstance(suggested_tools, list) or not suggested_tools:
                suggested_tools = self._INTENT_TOOLS[intent]
            return IntentRouterResult(
                intent=intent,
                reasoning=reasoning,
                suggested_tools=[str(tool) for tool in suggested_tools],
            )
        except Exception as exc:
            logger.warning("IntentRouterAgent LLM fallback failed: %s", exc)
            return None

    def _get_llm(self) -> Any:
        if self._llm is None:
            self._llm = self._llm_provider_factory()
            logger.debug("IntentRouterAgent lazy-loaded LLM fallback provider")
        return self._llm

    @staticmethod
    def _get_default_llm_provider() -> Any:
        from app.services.llm import get_llm_provider

        return get_llm_provider()

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
            raise ValueError("Intent router payload must be a JSON object")
        return payload


_router_instance: Optional[IntentRouterAgent] = None


def get_intent_router_agent() -> IntentRouterAgent:
    """Process-wide singleton for the legal intent router."""
    global _router_instance
    if _router_instance is None:
        _router_instance = IntentRouterAgent()
    return _router_instance
