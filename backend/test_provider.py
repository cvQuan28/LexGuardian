import asyncio
from app.core.config import settings
from app.services.llm.__init__ import get_llm_provider
from app.services.llm.types import LLMMessage


async def main():
    print(f"[TEST ENV] LLM_PROVIDER: {settings.LLM_PROVIDER}")
    print(f"[TEST ENV] OLLAMA_HOST: {settings.OLLAMA_HOST}")
    print(f"[TEST ENV] OLLAMA_MODEL: {settings.OLLAMA_MODEL}")

    try:
        print("\n--- Khởi tạo LLM Provider ---")
        llm = get_llm_provider()

        print(f"Provider Type: {type(llm).__name__}")

        msg = LLMMessage(role="user", content="Xin chào, bạn là ai?")

        print("\n--- Gọi astream (Async Streaming) ---")
        # Dùng astream thay vì acomplete để nhận từng token (giống test của bạn)
        async for chunk in llm.astream([msg]):
            if chunk.type == "text":
                print(chunk.text, end="", flush=True)

        print("\n\n=> Gọi astream thành công!")

    except Exception as e:
        print(f"\n[ERROR] Ngoại lệ xảy ra: {e}")

if __name__ == "__main__":
    import sys
    sys.path.append("backend")
    asyncio.run(main())
