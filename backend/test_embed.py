import asyncio
from app.core.config import settings
from app.services.llm.__init__ import get_embedding_provider

async def main():
    print(f"[TEST ENV] KG_EMBEDDING_PROVIDER: {settings.KG_EMBEDDING_PROVIDER}")
    print(f"[TEST ENV] OLLAMA_HOST: {settings.OLLAMA_HOST}")
    print(f"[TEST ENV] OLLAMA_API_KEY: {settings.OLLAMA_API_KEY[:5]}...")
    
    emb = get_embedding_provider()
    print("Testing embed...")
    res = await emb.embed(["test"])
    print(f"Shape: {res.shape}")

if __name__ == "__main__":
    asyncio.run(main())
