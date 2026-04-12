from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache
from pathlib import Path

# Find .env file - check project root first, fallback for Docker
_candidate = Path(__file__).resolve().parent.parent.parent.parent / ".env"
ENV_FILE = str(_candidate) if _candidate.exists() else ".env"


class Settings(BaseSettings):
    # App
    APP_NAME: str = "LexGuardian"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    APP_DOMAIN: str = "legal"
    ENABLE_GENERIC_RAG_API: bool = True

    # Base directory (backend folder)
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5433/lexguardian")

    # LLM Provider: "gemini" | "ollama"
    LLM_PROVIDER: str = Field(default="gemini")

    # Google AI
    GOOGLE_AI_API_KEY: str = Field(default="")

    # Ollama
    OLLAMA_HOST: str = Field(default="http://localhost:11434")
    OLLAMA_API_KEY: str = Field(default="")
    OLLAMA_MODEL: str = Field(default="gemma3:12b")
    OLLAMA_ENABLE_THINKING: bool = Field(default=False)

    # LLM (fast model for chat + KG extraction — used when provider=gemini)
    LLM_MODEL_FAST: str = Field(default="gemini-2.5-flash")

    # Thinking level for Gemini 3.x+ models: "minimal" | "low" | "medium" | "high"
    # Gemini 2.5 uses thinking_budget_tokens instead (auto-detected)
    LLM_THINKING_LEVEL: str = Field(default="medium")

    # Max output tokens for LLM chat responses (includes thinking tokens)
    # Gemini 3.1 Flash-Lite supports up to 65536
    LLM_MAX_OUTPUT_TOKENS: int = Field(default=8192)

    # KG Embedding provider (can differ from LLM provider)
    KG_EMBEDDING_PROVIDER: str = Field(default="gemini")
    KG_EMBEDDING_MODEL: str = Field(default="gemini-embedding-001")
    KG_EMBEDDING_DIMENSION: int = Field(default=3072)

    # Vector Store: PGVector (uses DATABASE_URL — no separate config needed)
    # ChromaDB has been replaced by pgvector extension on PostgreSQL

    # NexusRAG Pipeline
    NEXUSRAG_ENABLED: bool = True
    NEXUSRAG_ENABLE_KG: bool = True
    NEXUSRAG_ENABLE_IMAGE_EXTRACTION: bool = True
    NEXUSRAG_ENABLE_IMAGE_CAPTIONING: bool = True
    NEXUSRAG_ENABLE_TABLE_CAPTIONING: bool = True
    NEXUSRAG_MAX_TABLE_MARKDOWN_CHARS: int = 8000
    NEXUSRAG_CHUNK_MAX_TOKENS: int = 512
    NEXUSRAG_KG_QUERY_TIMEOUT: float = 30.0
    NEXUSRAG_KG_CHUNK_TOKEN_SIZE: int = 1200
    NEXUSRAG_KG_LANGUAGE: str = "Vietnamese"
    NEXUSRAG_KG_ENTITY_TYPES: list[str] = [
        "Organization", "Person", "Product", "Location", "Event",
        "Financial_Metric", "Technology", "Date", "Regulation",
    ]
    NEXUSRAG_DEFAULT_QUERY_MODE: str = "hybrid"
    NEXUSRAG_DOCLING_IMAGES_SCALE: float = 2.0
    NEXUSRAG_MAX_IMAGES_PER_DOC: int = 50
    NEXUSRAG_ENABLE_FORMULA_ENRICHMENT: bool = True

    # NexusRAG Retrieval Quality
    NEXUSRAG_EMBEDDING_MODEL: str = "AITeamVN/Vietnamese_Embedding"
    NEXUSRAG_RERANKER_MODEL: str = "AITeamVN/Vietnamese_Reranker"
    NEXUSRAG_VECTOR_PREFETCH: int = 20
    NEXUSRAG_RERANKER_TOP_K: int = 8
    NEXUSRAG_MIN_RELEVANCE_SCORE: float = 0.15

    # Legal AI Pipeline
    LEGAL_ENABLED: bool = True
    LEGAL_MIN_CLAUSE_CHARS: int = 50         # minimum characters for a valid clause
    LEGAL_MAX_CLAUSE_CHARS: int = 3000       # max chars before splitting a clause
    LEGAL_BM25_ENABLED: bool = True          # enable BM25 keyword search
    LEGAL_BM25_PREFETCH: int = 20            # BM25 results before RRF fusion
    LEGAL_VECTOR_PREFETCH: int = 20          # vector results before RRF fusion
    LEGAL_TOP_K: int = 8                     # final top-K after reranking
    # return "Insufficient information" if not grounded
    LEGAL_GROUNDING_STRICT: bool = True
    LEGAL_KG_LANGUAGE: str = "Vietnamese"    # KG entity extraction language
    LEGAL_STATIC_INDEX_ENABLED: bool = False
    LEGAL_STATIC_COLLECTION_NAME: str = "legal_static_global"
    LEGAL_STATIC_BATCH_SIZE: int = 100
    LEGAL_STATIC_INGEST_MAX_DOCS: int = 0    # 0 = no explicit limit
    LEGAL_STATIC_KG_DOC_TYPES: list[str] = [
        "law", "code", "decree", "circular",
    ]
    LEGAL_ONLY_ACTIVE_BY_DEFAULT: bool = True
    # Phase 2: Summary-Augmented Chunking (SAC) for static corpus
    # enable LLM-based summaries for static chunks
    LEGAL_CHUNK_AUGMENT_ENABLED: bool = False
    LEGAL_CHUNK_AUGMENT_MAX_TOKENS: int = 200    # max tokens per summary call
    LEGAL_RISK_ANALYSIS_MODEL: str = Field(default="gemini-2.5-pro")
    TAVILY_API_KEY: str = Field(default="")
    LEGAL_WEB_SEARCH_DOMAINS: list[str] = [
        "thuvienphapluat.vn",
        "vbpl.vn",
        "luatvietnam.vn",
        "chinhphu.vn",
    ]
    LEGAL_INTERNAL_API_ENABLED: bool = True
    LEGAL_LEGACY_INTERNAL_ROUTES_ENABLED: bool = True
    # Cấu hình đường dẫn tới kho luật tĩnh
    STATIC_LEGAL_DB_PATH: str = "backend/data/static_legal_data"
    STATIC_COLLECTION_NAME: str = "legal_static_global"

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:5174", "http://localhost:3000"]

    model_config = {
        "env_file": str(ENV_FILE),
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
