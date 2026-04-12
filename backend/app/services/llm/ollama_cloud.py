# Ollama Cloud Provider based on official Ollama Python client

import os
from typing import AsyncGenerator, List
from ollama import Client
from app.services.llm.types import LLMMessage, LLMResult, StreamChunk


class OllamaCloudLLMProvider:
    def __init__(self, api_key: str, model: str = "gpt-oss:120b"):
        if not api_key:
            raise ValueError("Missing API Key for Ollama Cloud")

        self.api_key = api_key
        self.model = model
        self.client = Client(
            host="https://ollama.com",
            headers={"Authorization": f"Bearer {api_key}"}
        )

    # Convert framework messages → Ollama Cloud message format
    @staticmethod
    def _convert_messages(messages: List[LLMMessage]):
        result = []
        for m in messages:
            item = {
                "role": m.role,
                "content": m.content,
            }
            # Cloud API does NOT support images yet → ignore
            result.append(item)
        return result

    def complete(self, messages: List[LLMMessage], temperature=0.0, max_tokens=4096):
        ollama_messages = self._convert_messages(messages)

        response = self.client.chat(
            self.model,
            messages=ollama_messages,
            options={
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        )

        content = response["message"]["content"]
        return LLMResult(content=content)

    # Streaming version
    def stream(self, messages: List[LLMMessage], temperature=0.0, max_tokens=4096) -> AsyncGenerator[StreamChunk, None]:
        ollama_messages = self._convert_messages(messages)

        for part in self.client.chat(
            self.model,
            messages=ollama_messages,
            stream=True,
            options={
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        ):
            text = part["message"].get("content", "")
            if text:
                yield StreamChunk(type="text", text=text)

    # Async version using worker threads (client is sync)
    async def acomplete(self, messages: List[LLMMessage], temperature=0.0, max_tokens=4096):
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.complete(messages, temperature, max_tokens))

    async def astream(self, messages: List[LLMMessage], temperature=0.0, max_tokens=4096):
        import asyncio
        loop = asyncio.get_event_loop()

        def _generator():
            for chunk in self.stream(messages, temperature, max_tokens):
                yield chunk

        queue = asyncio.Queue()

        def run_sync():
            try:
                for item in _generator():
                    asyncio.run_coroutine_threadsafe(queue.put(item), loop)
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)

        import threading
        threading.Thread(target=run_sync, daemon=True).start()

        while True:
            item = await queue.get()
            if item is None:
                break
            yield item


# Embedding Provider for Ollama Cloud
class OllamaCloudEmbeddingProvider:
    def __init__(self, api_key: str, model="bge-m3"):
        if not api_key:
            raise ValueError("Missing API Key for Ollama Cloud")

        self.model = model
        self.client = Client(
            host="https://ollama.com",
            headers={"Authorization": f"Bearer {api_key}"}
        )

    def embed(self, texts: List[str]):
        # Cloud API uses client.embed
        response = self.client.embed(model=self.model, input=texts)
        return response["embeddings"]

    async def aembed(self, texts: List[str]):
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.embed(texts))

if __name__ == "__main__":
    # Simple manual test for Ollama Cloud
    import asyncio

    API_KEY = os.environ.get("OLLAMA_API_KEY")
    if not API_KEY:
        raise Exception("Please export OLLAMA_API_KEY before running test")

    provider = OllamaCloudLLMProvider(api_key=API_KEY, model="gpt-oss:120b")

    messages = [
        LLMMessage(role="user", content="Test Ollama Cloud: viết 1 câu tiếng Việt về AI."),
    ]

    print("=== Sync Test ===")
    result = provider.complete(messages)
    print("Sync Output:", result.content)

    print("\n=== Async Test ===")
    async def test_async():
        async for chunk in provider.astream(messages):
            print(chunk.text, end="", flush=True)
    asyncio.run(test_async())