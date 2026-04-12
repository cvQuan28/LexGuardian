# 02 — System Architecture

## Overview

LexGuardian follows a **clean layered architecture** where each layer has a single responsibility and a clear interface. The frontend knows nothing about RAG internals. The API layer knows nothing about LLM providers. The legal services know nothing about HTTP.

```
┌─────────────────────────────────────────────────────────┐
│                      FRONTEND (React)                   │
│  Command Center → Intent expressed by user              │
│  Pages: Home, Ask, Analyze, Explore, Library            │
└────────────────────────┬────────────────────────────────┘
                         │ HTTPS / SSE
┌────────────────────────▼────────────────────────────────┐
│                   API LAYER (FastAPI)                   │
│  Thin route handlers — validate, auth, delegate         │
│  Routes: /command, /analyze-risk, /live-search, etc.    │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│              LEGAL INTELLIGENCE LAYER                   │
│  IntentRouter → classifies query intent                 │
│  LegalRAGService → hybrid retrieval + reranking         │
│  RiskAnalysisAgent → clause-level contract analysis     │
│  WebSearchService → Tavily + trusted legal domains      │
│  KnowledgeGraphService → entity relationship queries    │
└────────┬───────────────┬───────────────┬────────────────┘
         │               │               │
┌────────▼───┐  ┌────────▼───┐  ┌───────▼────────────────┐
│  LLM Layer │  │  Retrieval │  │   Storage              │
│  Gemini /  │  │  PGVector  │  │   PostgreSQL (primary) │
│  Ollama    │  │  BM25 index│  │   pgvector extension   │
│  provider  │  │  Reranker  │  │   Docling image cache  │
│  abstraction│  │  (cross-  │  │                        │
│            │  │  encoder)  │  │                        │
└────────────┘  └────────────┘  └────────────────────────┘
```

---

## Backend Architecture

### Entry Point: `app/main.py`
- FastAPI application with async lifespan
- Auto-creates/migrates database tables on startup (idempotent `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN IF NOT EXISTS`)
- Registers all route modules under `/api/v1` prefix
- Serves extracted document images as static files from `/static/doc-images`
- Global exception handler ensures JSON error responses

### API Layer: `app/api/`
Route modules are **thin**: they validate input (Pydantic schemas), check authentication, fetch the workspace, and delegate to services. They contain zero business logic.

| File | Purpose |
|---|---|
| `auth.py` | Login, logout, current user |
| `workspaces.py` | CRUD for KnowledgeBase (Matters/Briefs) |
| `documents.py` | Upload, delete, status polling, document list |
| `legal.py` | All legal AI endpoints (see API Contracts doc) |
| `conversations.py` | Conversation CRUD |
| `evaluations.py` | Internal eval/testing endpoints |
| `config.py` | Runtime config introspection (admin only) |
| `rag.py` | Generic RAG endpoints (feature-flagged via `ENABLE_GENERIC_RAG_API`) |
| `chat_agent.py` | SSE streaming chat endpoint |
| `router.py` | Aggregates all sub-routers under `api_router` |

### Core Layer: `app/core/`

| File | Purpose |
|---|---|
| `config.py` | Pydantic Settings — all env vars, feature flags, model names |
| `database.py` | Async SQLAlchemy engine + session factory |
| `deps.py` | FastAPI dependency injection: `get_db`, `get_current_user`, `get_workspace_for_user` |
| `security.py` | Password hashing (bcrypt), token generation/validation |
| `exceptions.py` | Custom exception types (`NotFoundError`, `AuthError`, etc.) |

### Data Models: `app/models/`
SQLAlchemy ORM models using modern `Mapped[T]` typed mapping syntax.

| Model | Table | Key Fields |
|---|---|---|
| `User` | `users` | `id`, `email`, `display_name`, `password_hash` |
| `AuthSession` | `auth_sessions` | `user_id`, `token_hash`, `expires_at` |
| `KnowledgeBase` | `knowledge_bases` | `user_id`, `name`, `description`, `system_prompt` |
| `Document` | `documents` | `workspace_id`, `status`, `chunk_count`, `markdown_content` |
| `DocumentImage` | `document_images` | `document_id`, `image_id`, `page_no`, `caption`, `file_path` |
| `DocumentTable` | `document_tables` | `document_id`, `content_markdown`, `num_rows`, `num_cols` |
| `Conversation` | `conversations` | `user_id`, `workspace_id`, `title` |
| `ChatMessage` | `chat_messages` | `conversation_id`, `role`, `content`, `sources`, `agent_steps` |
| `LegalSourceDocument` | `legal_sources` | `title`, `canonical_citation`, `document_type`, `effective_date` |

### Business Logic: `app/services/`

#### RAG Pipeline Services
| Service | Role |
|---|---|
| `deep_document_parser.py` | Docling-based PDF/DOCX → Markdown + image extraction |
| `chunker.py` | Semantic text chunking with token-size control |
| `embedder.py` | Sentence Transformer embeddings (Vietnamese model) |
| `vector_store.py` | pgvector CRUD — upsert, search, delete by workspace |
| `reranker.py` | Cross-encoder reranking (Vietnamese Reranker model) |
| `deep_retriever.py` | Hybrid retrieval: vector + BM25 → RRF fusion → rerank |
| `knowledge_graph_service.py` | LightRAG-style KG extraction and query |
| `nexus_rag_service.py` | Orchestrates full RAG pipeline (parse → chunk → embed → index) |

#### Legal Intelligence Services (`app/services/legal/`)
| Service | Role |
|---|---|
| `legal_router.py` | Domain detection: legal vs. general (keyword + regex + semantic) |
| `legal_retriever.py` | Hybrid BM25 + vector retrieval over legal corpus |
| `legal_rag_service.py` | Full RAG pipeline specialized for legal QA |
| `legal_reasoning.py` | LLM-based legal reasoning with grounding checks |
| `risk_analysis_agent.py` | **Core:** clause-by-clause contract risk analysis |
| `legal_agent_workflow.py` | Multi-step agentic legal Q&A with tool use |
| `clause_chunker.py` | Contract-aware chunking that respects clause boundaries |
| `contract_extractor.py` | Extract structured fields from contracts (parties, dates, values) |
| `web_search.py` | Tavily web search scoped to trusted Vietnamese legal domains |
| `legal_parser.py` | Specialised parsing for Vietnamese legal document structure |
| `legal_kg_service.py` | Knowledge graph operations on legal entity relationships |
| `legal_static_index_service.py` | Static corpus ingestion (law codes, decrees, circulars) |

#### LLM Abstraction (`app/services/llm/`)
The LLM layer is **provider-agnostic**. All LLM calls go through a base interface.

| File | Role |
|---|---|
| `base.py` | Abstract `LLMProvider` interface: `chat()`, `stream()`, `embed()` |
| `types.py` | Shared types: `LLMMessage`, `LLMImagePart`, `StreamChunk` |
| `gemini.py` | Google Gemini implementation (Gemini 2.5 Flash / Pro) |
| `ollama.py` | Local Ollama implementation |

**Rule:** Never import `gemini.py` or `ollama.py` directly from service code. Always use the factory function in `llm/__init__.py` which reads `settings.LLM_PROVIDER`.

---

## Frontend Architecture

### Routing: `App.tsx`
React Router v6 with three protected routes:
- `/` → `KnowledgeBasesPage` (Matter/Brief list — the "library")
- `/knowledge-bases/:workspaceId` or `/workspaces/:workspaceId` → `WorkspacePage` (main work surface)
- `/admin` → `AdminDashboard`

### State Management Strategy
Two levels of state:

**Server state** (TanStack Query): Documents, workspaces, chat history, conversations. Use `useQuery` + `useMutation`. Never duplicate server state in Zustand.

**UI/client state** (Zustand): Which document is selected in the viewer, which panel is open, theme preference, auth session. Zustand stores live in `src/stores/`.

### Key Stores
| Store | State |
|---|---|
| `authStore.ts` | `token`, `initialized`, session management |
| `workspaceStore.ts` | `selectedDoc`, `selectedLegalSource`, `riskReport` — what's shown in the right panel |
| `ragPanelStore.ts` | `activePanel` (viewer/gallery), `scrollToPage`, `scrollToHeading` |
| `useThemeStore.ts` | `theme` (light/dark) |

### Data Flow for Chat/Streaming
```
User types message
→ ChatPanel calls useRAGChatStream.sendMessage()
→ Hook opens SSE connection to /chat/{workspace_id}/stream
→ SSE events: status → thinking → sources → token (streamed) → complete
→ Each token appended to streamingContent (rAF-buffered for perf)
→ On complete: ChatMessage saved to server, added to local history
→ Citation click: workspaceStore.selectDoc() → right panel opens DocumentViewer at page
```

### API Client: `src/lib/api.ts`
A class-based client wrapping `fetch`. All methods return typed promises. Auth token is read from `localStorage` and injected into every request header. SSE streaming is handled separately via `EventSource` in `useRAGChatStream.ts`.

---

## Infrastructure

### Docker Compose (`docker-compose.yml`)
Three services:
- `backend` — FastAPI on port 8000
- `frontend` — Nginx serving Vite build, port 80
- `db` — PostgreSQL 16 with pgvector extension, port 5433

### Nginx (`nginx.conf`)
- Serves frontend static files
- Proxies `/api/v1/*` to the backend
- Handles SSE long-lived connections (proxy buffering disabled for streaming routes)

### Environment Variables (`.env`)
Critical variables:
```
DATABASE_URL=postgresql+asyncpg://...
LLM_PROVIDER=gemini
GOOGLE_AI_API_KEY=...
TAVILY_API_KEY=...
LEGAL_RISK_ANALYSIS_MODEL=gemini-2.5-pro
LLM_MODEL_FAST=gemini-2.5-flash
NEXUSRAG_EMBEDDING_MODEL=AITeamVN/Vietnamese_Embedding
NEXUSRAG_RERANKER_MODEL=AITeamVN/Vietnamese_Reranker
```

---

## Data Flow: Document Ingestion

```
User uploads PDF
→ POST /documents/upload/{workspace_id}
→ File saved to disk, Document record created (status: PENDING)
→ Background task triggered:
    1. deep_document_parser.py → Docling extracts Markdown + images + tables
    2. chunker.py → splits Markdown into semantic chunks
    3. embedder.py → generates embeddings for each chunk
    4. vector_store.py → upserts chunks into pgvector
    5. knowledge_graph_service.py → extracts entities + relationships (if KG enabled)
    6. Document status updated → INDEXED
→ Frontend polls GET /documents/workspace/{id} every 3s until status = indexed
```

---

## Data Flow: Contract Risk Analysis

```
User requests risk analysis on a document
→ POST /legal/analyze-risk/{workspace_id} {document_id: N}
→ legal.py handler → fetches Document, verifies status=indexed
→ risk_analysis_agent.py:
    1. Retrieves all clause chunks for the document from pgvector
    2. clause_chunker.py ensures clause boundaries are respected
    3. LLM (gemini-2.5-pro) analyzes each clause group:
       - identifies risk type (missing clause, unfavorable term, ambiguity)
       - assigns severity (CRITICAL / MEDIUM / LOW)
       - provides legal basis + suggested redline
    4. Aggregates into ContractRiskReport
→ Returns ContractRiskReport JSON
→ Frontend renders RiskAnalysisView
```

---

## Security Model

- Authentication: Token-based. Tokens stored as bcrypt hashes in `auth_sessions`. Tokens expire (configurable TTL).
- Authorization: All workspace operations are scoped through `get_workspace_for_user` dependency which verifies `user_id` ownership before returning the workspace.
- CORS: Configured in `main.py`, defaults to localhost dev ports. Production must set explicit allowed origins via env.
- No secrets in frontend code: API key, DB credentials all live server-side.
