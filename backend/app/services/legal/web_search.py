"""
Live legal web search over Tavily.

This module is intended for LIVE_SEARCH flows where the system needs to:
  - find recent statutory sources on trusted legal/government domains
  - check whether a document is still effective
  - return direct source URLs for user-facing citations
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


@dataclass
class LegalWebSearchResult:
    title: str
    url: str
    content: str = ""
    raw_content: str = ""
    domain: str = ""
    score: float = 0.0
    published_date: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LegalValidityCheckResult:
    doc_title: str
    status: str
    reasoning: str
    source_url: str = ""
    source_title: str = ""
    source_domain: str = ""
    source_snippet: str = ""
    matched_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LegalWebSearcher:
    """Trusted-domain Tavily wrapper for live legal search."""

    DEFAULT_DOMAINS = [
        "thuvienphapluat.vn",
        "vbpl.vn",
        "luatvietnam.vn",
        "chinhphu.vn",
    ]

    _DOMAIN_PRIORITY = {
        "thuvienphapluat.vn": 0,
        "vbpl.vn": 1,
        "luatvietnam.vn": 2,
        "chinhphu.vn": 3,
    }

    _EXPIRED_PATTERNS = [
        re.compile(r"\bhết hiệu lực(?: toàn bộ| thi hành)?\b", re.IGNORECASE),
        re.compile(r"\bbị thay thế\b", re.IGNORECASE),
        re.compile(r"\bđã được thay thế\b", re.IGNORECASE),
        re.compile(r"\bsuperseded\b", re.IGNORECASE),
        re.compile(r"\breplaced\b", re.IGNORECASE),
    ]
    _ACTIVE_PATTERNS = [
        re.compile(r"\bcòn hiệu lực\b", re.IGNORECASE),
        re.compile(r"\bđang có hiệu lực\b", re.IGNORECASE),
        re.compile(r"\bin force\b", re.IGNORECASE),
        re.compile(r"\beffective\b", re.IGNORECASE),
    ]

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        allowed_domains: Optional[list[str]] = None,
        timeout_seconds: float = 20.0,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.api_key = api_key or settings.TAVILY_API_KEY
        self.allowed_domains = allowed_domains or list(settings.LEGAL_WEB_SEARCH_DOMAINS)
        self.timeout_seconds = timeout_seconds
        self._client = client

    async def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        topic: str = "general",
        include_raw_content: bool = False,
    ) -> list[LegalWebSearchResult]:
        """Search trusted legal domains and return normalized results with URLs."""
        payload = {
            "query": query,
            "topic": topic,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_domains": self.allowed_domains,
            "include_answer": False,
            "include_raw_content": include_raw_content,
        }
        data = await self._post_search(payload)
        normalized = [
            self._normalize_result(item)
            for item in data.get("results", []) or []
        ]
        filtered = [item for item in normalized if item.url]
        return self._sort_results(filtered)

    async def check_validity(self, doc_title: str) -> LegalValidityCheckResult:
        """
        Inspect live search snippets to infer whether a legal document is still effective.

        The method biases toward trusted domains and the freshest results. If a result from
        thuvienphapluat.vn is available, it will usually be ranked first for user-facing linking.
        """
        search_queries = [
            f"\"{doc_title}\" \"hết hiệu lực\"",
            f"\"{doc_title}\" \"còn hiệu lực áp dụng đến khi nào\"",
            f"\"{doc_title}\" \"bị thay thế\"",
            f"\"{doc_title}\" (\"còn hiệu lực\" OR \"hết hiệu lực\" OR \"bị thay thế\" OR \"được thay thế\")",
        ]
        results: list[LegalWebSearchResult] = []
        seen_urls: set[str] = set()
        for query in search_queries:
            query_results = await self.search(
                query,
                max_results=5,
                topic="general",
                include_raw_content=True,
            )
            for item in query_results:
                if item.url and item.url not in seen_urls:
                    results.append(item)
                    seen_urls.add(item.url)

        if not results:
            return LegalValidityCheckResult(
                doc_title=doc_title,
                status="unknown",
                reasoning="No trusted live-search result was returned for this document title.",
            )

        best = self._pick_best_validity_result(results, doc_title=doc_title)
        haystack = self._build_haystack(best)
        expired_keywords = self._find_keywords(haystack, self._EXPIRED_PATTERNS)
        active_keywords = self._find_keywords(haystack, self._ACTIVE_PATTERNS)

        if expired_keywords:
            status = "expired"
            reasoning = (
                "The latest trusted snippet indicates the document has expired or has been replaced."
            )
            matched_keywords = expired_keywords
        elif active_keywords:
            status = "active"
            reasoning = "The latest trusted snippet indicates the document is still in force."
            matched_keywords = active_keywords
        else:
            status = "unknown"
            reasoning = (
                "Trusted results were found, but the returned snippet did not clearly state whether the document is active."
            )
            matched_keywords = []

        return LegalValidityCheckResult(
            doc_title=doc_title,
            status=status,
            reasoning=reasoning,
            source_url=best.url,
            source_title=best.title,
            source_domain=best.domain,
            source_snippet=(best.content or best.raw_content)[:500],
            matched_keywords=matched_keywords,
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _post_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise ValueError("TAVILY_API_KEY is required for LegalWebSearcher")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        if self._client is not None:
            response = await self._client.post(TAVILY_SEARCH_URL, json=payload, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(TAVILY_SEARCH_URL, json=payload, headers=headers)

        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected Tavily response shape")
        return data

    def _normalize_result(self, item: dict[str, Any]) -> LegalWebSearchResult:
        url = str(item.get("url", "")).strip()
        domain = self._extract_domain(url)
        return LegalWebSearchResult(
            title=str(item.get("title", "")).strip(),
            url=url,
            content=str(item.get("content", "")).strip(),
            raw_content=str(item.get("raw_content", "") or "").strip(),
            domain=domain,
            score=float(item.get("score", 0.0) or 0.0),
            published_date=str(item.get("published_date", "") or item.get("published_at", "") or "").strip(),
        )

    def _sort_results(self, results: list[LegalWebSearchResult]) -> list[LegalWebSearchResult]:
        return sorted(
            results,
            key=lambda item: (
                self._domain_priority(item.domain),
                -self._published_timestamp(item.published_date),
                -item.score,
            ),
        )

    def _pick_best_validity_result(
        self,
        results: list[LegalWebSearchResult],
        doc_title: str = "",
    ) -> LegalWebSearchResult:
        scored = sorted(
            results,
            key=lambda item: (
                -self._title_match_score(doc_title, item),
                -self._has_validity_signal(self._build_haystack(item)),
                self._domain_priority(item.domain),
                -self._published_timestamp(item.published_date),
                -item.score,
            ),
        )
        return scored[0]

    def _build_haystack(self, result: LegalWebSearchResult) -> str:
        return "\n".join(
            part for part in [
                result.title,
                result.content,
                result.raw_content[:1500] if result.raw_content else "",
            ]
            if part
        )

    def _find_keywords(self, text: str, patterns: list[re.Pattern[str]]) -> list[str]:
        matches: list[str] = []
        for pattern in patterns:
            found = pattern.search(text)
            if found:
                match = found.group(0).strip()
                if match not in matches:
                    matches.append(match)
        return matches

    def _has_validity_signal(self, text: str) -> int:
        if self._find_keywords(text, self._EXPIRED_PATTERNS):
            return 2
        if self._find_keywords(text, self._ACTIVE_PATTERNS):
            return 1
        return 0

    def _title_match_score(self, doc_title: str, result: LegalWebSearchResult) -> int:
        if not doc_title:
            return 0
        doc_tokens = self._normalize_tokens(doc_title)
        haystack_tokens = self._normalize_tokens(" ".join([result.title, result.url]))
        overlap = len(doc_tokens & haystack_tokens)
        exact_phrase = self._normalize_text(doc_title) in self._normalize_text(result.title)
        return overlap + (3 if exact_phrase else 0)

    def _domain_priority(self, domain: str) -> int:
        return self._DOMAIN_PRIORITY.get(domain, len(self._DOMAIN_PRIORITY) + 1)

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip().lower())

    @classmethod
    def _normalize_tokens(cls, value: str) -> set[str]:
        normalized = cls._normalize_text(value)
        return {
            token for token in re.split(r"[^0-9a-zàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]+", normalized)
            if len(token) >= 2
        }

    @staticmethod
    def _extract_domain(url: str) -> str:
        if not url:
            return ""
        return urlparse(url).netloc.lower().removeprefix("www.")

    @staticmethod
    def _published_timestamp(value: str) -> float:
        if not value:
            return 0.0
        normalized = value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).timestamp()
        except ValueError:
            return 0.0


_legal_web_searcher_instance: Optional[LegalWebSearcher] = None


def get_legal_web_searcher() -> LegalWebSearcher:
    global _legal_web_searcher_instance
    if _legal_web_searcher_instance is None:
        _legal_web_searcher_instance = LegalWebSearcher()
    return _legal_web_searcher_instance
