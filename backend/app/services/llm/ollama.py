"""
Ollama LLM & Embedding Providers
==================================
Concrete implementations using the ``ollama`` Python library for local models.
"""
from __future__ import annotations

import json
import logging
import re
from typing import AsyncGenerator, Optional

import numpy as np

from app.services.llm.base import EmbeddingProvider, LLMProvider
from app.services.llm.types import LLMMessage, LLMResult, StreamChunk

logger = logging.getLogger(__name__)

# Regex to strip <think>...</think> blocks from model output
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


class OllamaLLMProvider(LLMProvider):
    """Local Ollama text/multimodal generation."""

    def __init__(self, host: str = "http://localhost:11434", model: str = "gemma3:12b", api_key: str = ""):
        self._host = host
        self._model = model
        self._api_key = api_key
        self._thinking_supported: bool | None = None  # lazy probe

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_ollama_messages(
        messages: list[LLMMessage],
        system_prompt: Optional[str] = None,
    ) -> list[dict]:
        """Convert LLMMessage list to Ollama message dicts."""
        result: list[dict] = []

        if system_prompt:
            result.append({"role": "system", "content": system_prompt})

        for msg in messages:
            entry: dict = {"role": msg.role, "content": msg.content}
            if msg.images:
                # Ollama accepts raw bytes in the 'images' field
                entry["images"] = [img.data for img in msg.images]
            result.append(entry)

        return result

    @staticmethod
    def _extract_content(response, keep_thinking: bool = False) -> str | LLMResult:
        """Extract usable text from Ollama response.

        Handles edge cases:
        - ``content`` is empty but ``thinking`` field has the answer
        - ``content`` contains embedded ``<think>...</think>`` blocks

        When *keep_thinking* is True, returns an LLMResult with the
        thinking text preserved separately.
        """
        content = response.message.content or ""
        thinking = getattr(response.message, "thinking", None) or ""

        # Strip <think>...</think> blocks from content
        if "<think>" in content:
            content = _THINK_RE.sub("", content).strip()

        # Fallback: if content is still empty, check thinking field
        if not content:
            if thinking:
                logger.warning(
                    "Ollama response.content is empty but thinking has %d chars — "
                    "using thinking as fallback", len(thinking)
                )
                content = _THINK_RE.sub("", thinking).strip()

        if keep_thinking:
            return LLMResult(content=content, thinking=thinking)
        return content

    def _get_client_kwargs(self) -> dict:
        kwargs = {"host": self._host}
        if self._api_key:
            kwargs["headers"] = {"Authorization": f"Bearer {self._api_key}"}
        return kwargs

    # ------------------------------------------------------------------
    # LLMProvider interface
    # ------------------------------------------------------------------

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        think: bool = False,
    ) -> str | LLMResult:
        import ollama

        ollama_msgs = self._to_ollama_messages(messages, system_prompt)
        use_think = think and self.supports_thinking()

        try:
            client = ollama.Client(**self._get_client_kwargs())
            response = client.chat(
                model=self._model,
                messages=ollama_msgs,
                options={"temperature": temperature, "num_predict": max_tokens},
                think=use_think,
            )
            result = self._extract_content(response, keep_thinking=use_think)
            content = result.content if isinstance(result, LLMResult) else result
            if not content:
                logger.warning(
                    "Ollama complete() returned empty | model=%s | "
                    "content=%r | thinking=%r",
                    self._model,
                    response.message.content,
                    getattr(response.message, "thinking", None),
                )
            return result
        except Exception as e:
            logger.error(f"Ollama LLM call failed: {e}", exc_info=True)
            return LLMResult(content="") if use_think else ""

    async def acomplete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        think: bool = False,
    ) -> str | LLMResult:
        """Native async via ollama.AsyncClient (better than to_thread)."""
        import ollama

        ollama_msgs = self._to_ollama_messages(messages, system_prompt)
        use_think = think and self.supports_thinking()

        try:
            client = ollama.AsyncClient(**self._get_client_kwargs())
            response = await client.chat(
                model=self._model,
                messages=ollama_msgs,
                options={"temperature": temperature, "num_predict": max_tokens},
                think=use_think,
            )
            result = self._extract_content(response, keep_thinking=use_think)
            content = result.content if isinstance(result, LLMResult) else result
            if not content:
                logger.warning(
                    "Ollama acomplete() returned empty | model=%s | "
                    "content=%r | thinking=%r",
                    self._model,
                    response.message.content,
                    getattr(response.message, "thinking", None),
                )
            return result
        except Exception as e:
            logger.error(f"Ollama async LLM call failed: {e}", exc_info=True)
            return LLMResult(content="") if use_think else ""

    async def astream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        think: bool = False,
        tools: list | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Streaming generation via Ollama's async stream API.

        Tool calls are detected via <tool_call>...</tool_call> tags in output.
        Uses a state machine to buffer tool call JSON before yielding.
        """
        import ollama

        ollama_msgs = self._to_ollama_messages(messages, system_prompt)
        use_think = think and self.supports_thinking()

        try:
            client = ollama.AsyncClient(**self._get_client_kwargs())
            stream = await client.chat(
                model=self._model,
                messages=ollama_msgs,
                options={"temperature": temperature, "num_predict": max_tokens},
                stream=True,
                think=use_think,
            )

            # State machine for <tool_call> detection with buffer
            text_buffer = ""
            in_tool_call = False
            tool_call_tag = "<tool_call>"
            tool_close_tag = "</tool_call>"

            async for chunk in stream:
                thinking = getattr(chunk.message, "thinking", None) or ""
                content = chunk.message.content or ""

                if thinking:
                    yield StreamChunk(type="thinking", text=thinking)

                if not content:
                    continue

                text_buffer += content

                while text_buffer:
                    if in_tool_call:
                        if tool_close_tag in text_buffer:
                            match = re.search(
                                r"<tool_call>(.*?)</tool_call>",
                                text_buffer,
                                re.DOTALL,
                            )
                            if match:
                                try:
                                    tool_data = json.loads(match.group(1).strip())
                                    yield StreamChunk(
                                        type="function_call",
                                        function_call={
                                            "name": tool_data.get("name", ""),
                                            "args": tool_data.get("arguments", {}),
                                        },
                                    )
                                except json.JSONDecodeError:
                                    logger.warning("Failed to parse tool call JSON: %s", match.group(1))
                                    # Fallback yield as text if bad json
                                    yield StreamChunk(type="text", text=text_buffer[:text_buffer.find(tool_close_tag) + len(tool_close_tag)])
                            else:
                                # Should not happen if tag is present, but fallback
                                yield StreamChunk(type="text", text=text_buffer[:text_buffer.find(tool_close_tag) + len(tool_close_tag)])
                            
                            # Resume matching text after </tool_call>
                            after = text_buffer.split(tool_close_tag, 1)[1]
                            text_buffer = after
                            in_tool_call = False
                        else:
                            # Still buffering tool call
                            break
                    else:
                        if tool_call_tag in text_buffer:
                            before, rest = text_buffer.split(tool_call_tag, 1)
                            if before:
                                cleaned = _THINK_RE.sub("", before)
                                if cleaned:
                                    yield StreamChunk(type="text", text=cleaned)
                            in_tool_call = True
                            text_buffer = tool_call_tag + rest
                        else:
                            # Safe to yield if it doesn't end with a partial tag
                            # Check partial tags at the end of text_buffer
                            partial_match = False
                            for i in range(1, len(tool_call_tag) + 1):
                                if text_buffer.endswith(tool_call_tag[:i]):
                                    partial_match = True
                                    safe_text = text_buffer[:-i]
                                    if safe_text:
                                        cleaned = _THINK_RE.sub("", safe_text)
                                        if cleaned:
                                            yield StreamChunk(type="text", text=cleaned)
                                    text_buffer = text_buffer[-i:]
                                    break
                            
                            if not partial_match:
                                cleaned = _THINK_RE.sub("", text_buffer)
                                if cleaned:
                                    yield StreamChunk(type="text", text=cleaned)
                                text_buffer = ""
                            break

            if text_buffer:
                cleaned = _THINK_RE.sub("", text_buffer)
                if cleaned:
                    yield StreamChunk(type="text", text=cleaned)

        except Exception as e:
            logger.error(f"Ollama streaming failed: {e}", exc_info=True)
            yield StreamChunk(type="text", text="")

    def supports_vision(self) -> bool:
        # Vision support depends on the model (e.g. qwen3-vl, llava, etc.)
        # We return True and let the model handle it; if the model doesn't
        # support vision, the Ollama API will return an error gracefully.
        return True

    def supports_thinking(self) -> bool:
        """Detect if the model supports thinking mode via a probe call."""
        if self._thinking_supported is not None:
            return self._thinking_supported

        import ollama

        try:
            client = ollama.Client(**self._get_client_kwargs())
            response = client.chat(
                model=self._model,
                messages=[{"role": "user", "content": "Hi"}],
                options={"num_predict": 2},
                think=True,
            )
            # If we get here without error, thinking is supported
            thinking = getattr(response.message, "thinking", None) or ""
            self._thinking_supported = True
            logger.info(
                f"Ollama thinking probe: model={self._model} supported=True "
                f"(thinking={len(thinking)} chars)"
            )
        except Exception as e:
            self._thinking_supported = False
            logger.info(f"Ollama thinking probe: model={self._model} supported=False ({e})")

        return self._thinking_supported


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Local Ollama text embedding."""

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "bge-m3",
        api_key: str = "",
    ):
        self._host = host
        self._model = model
        self._api_key = api_key
        self._dimension: Optional[int] = None

    def _get_client_kwargs(self) -> dict:
        kwargs = {"host": self._host}
        if self._api_key:
            kwargs["headers"] = {"Authorization": f"Bearer {self._api_key}"}
        return kwargs

    def _detect_dimension(self) -> int:
        """Detect embedding dimension by running a probe."""
        import ollama

        try:
            client = ollama.Client(**self._get_client_kwargs())
            result = client.embed(model=self._model, input=["dimension probe"])
            dim = len(result.embeddings[0])
            logger.info(f"Detected Ollama embedding dimension: {dim} for model {self._model}")
            return dim
        except Exception as e:
            logger.warning(f"Failed to detect embedding dimension: {e}, defaulting to config")
            from app.core.config import settings
            return settings.KG_EMBEDDING_DIMENSION

    @staticmethod
    def _sanitize_texts(texts: list[str]) -> list[str]:
        """Clean texts to prevent Ollama embedding NaN errors.

        Some texts (empty, special chars only, extremely long) cause
        bge-m3 via Ollama to return NaN embeddings or 500 errors.
        """
        sanitized = []
        for t in texts:
            t = t.strip()
            if not t:
                t = "[empty]"
            # Truncate extremely long texts (>8192 tokens ≈ 32k chars)
            if len(t) > 32000:
                t = t[:32000]
            sanitized.append(t)
        return sanitized

    def embed_sync(self, texts: list[str]) -> np.ndarray:
        import ollama

        clean = self._sanitize_texts(texts)
        try:
            client = ollama.Client(**self._get_client_kwargs())
            result = client.embed(model=self._model, input=clean)
            arr = np.array(result.embeddings, dtype=np.float32)
            # Guard NaN — replace with zeros
            if np.any(np.isnan(arr)):
                logger.warning("Ollama embed_sync produced NaN values — replacing with zeros")
                arr = np.nan_to_num(arr, nan=0.0)
            return arr
        except Exception as e:
            logger.error(f"Ollama embedding failed: {e}")
            dim = self.get_dimension()
            return np.zeros((len(texts), dim), dtype=np.float32)

    async def embed(self, texts: list[str]) -> np.ndarray:
        """Native async embedding via ollama.AsyncClient."""
        import ollama

        clean = self._sanitize_texts(texts)
        try:
            client = ollama.AsyncClient(**self._get_client_kwargs())
            result = await client.embed(model=self._model, input=clean)
            arr = np.array(result.embeddings, dtype=np.float32)
            # Guard NaN — replace with zeros
            if np.any(np.isnan(arr)):
                logger.warning("Ollama async embed produced NaN values — replacing with zeros")
                arr = np.nan_to_num(arr, nan=0.0)
            return arr
        except Exception as e:
            logger.error(f"Ollama async embedding failed: {e}")
            dim = self.get_dimension()
            return np.zeros((len(texts), dim), dtype=np.float32)

    def get_dimension(self) -> int:
        if self._dimension is None:
            self._dimension = self._detect_dimension()
        return self._dimension
