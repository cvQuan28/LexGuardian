# Technology Decisions Log

A record of significant architectural and technology choices made in LexGuardian, including the reasoning and alternatives considered. New entries go at the top.

---

## Decision Log Format

Each entry answers: What did we decide? Why? What did we reject and why? What are the known trade-offs?

---

## [2024-Q4] Migrate from ChromaDB to PostgreSQL + pgvector

**Decision:** Replace ChromaDB vector store with pgvector extension on the existing PostgreSQL database.

**Reasoning:**
- Eliminates a second database to operate. One PostgreSQL instance handles relational data and vector search.
- pgvector supports hybrid search (vector + full-text) natively, enabling BM25 + vector fusion in a single query.
- PostgreSQL's ACID transactions mean vector writes and document record updates are consistent.
- Simplifies Docker Compose (one less service to maintain).

**Rejected:** ChromaDB. Good for prototyping, but requires a separate deployment and doesn't support hybrid search without additional infrastructure.

**Trade-offs:**
- pgvector's approximate nearest-neighbor (ANN) search is slower than ChromaDB's HNSW for very large corpora (>10M vectors). Acceptable for LexGuardian's scale.
- Requires `CREATE EXTENSION vector;` on the PostgreSQL instance — handled in Docker Compose.

---

## [2024-Q4] Use Docling for Document Parsing

**Decision:** Use IBM's Docling library as the primary PDF/DOCX parser.

**Reasoning:**
- Docling converts PDFs to structured Markdown while preserving heading hierarchy, table structure, and figure positions.
- Enables accurate clause-level chunking because heading structure is preserved.
- Image extraction with page coordinates allows the Source Viewer to highlight the correct location.
- Better than PyPDF2/pdfplumber for complex Vietnamese legal documents with multi-column layouts.

**Rejected:**
- PyPDF2: No structural awareness, loses heading hierarchy.
- LlamaParse (cloud): External dependency, data privacy concern for legal documents.
- Adobe PDF Extract API: Cost, external dependency, overkill for MVP.

**Trade-offs:**
- Docling is slow (~30-60 seconds for a 50-page PDF). Mitigated by running as a background task.
- Large model download on first use (~2GB for Docling's OCR models). Acceptable in Docker setup.

---

## [2024-Q4] Use Google Gemini as Primary LLM (with Ollama fallback)

**Decision:** Gemini 2.5 Flash as default model, Gemini 2.5 Pro for contract risk analysis. Ollama for local development.

**Reasoning:**
- Gemini 2.5 Flash has excellent Vietnamese language understanding — critical for this market.
- Gemini's native PDF understanding could be used as a future enhancement.
- 2.5 Pro's extended context window (1M tokens) allows full-contract analysis without chunking.
- Ollama fallback enables development without API costs and air-gapped deployment.

**Rejected:**
- GPT-4o: Good quality but weaker Vietnamese, higher API cost.
- Anthropic Claude: Excellent quality but no multi-modal support for image captions at the time of this decision.

**Trade-offs:**
- Gemini API rate limits can be hit during batch analysis. Implement retry with exponential backoff.
- Ollama models (Gemma 12B) are significantly weaker than Gemini for complex legal reasoning. Test coverage should flag quality regressions.

---

## [2024-Q4] Use Vietnamese-Specific Embedding and Reranking Models

**Decision:** `AITeamVN/Vietnamese_Embedding` for embeddings and `AITeamVN/Vietnamese_Reranker` for cross-encoder reranking.

**Reasoning:**
- Generic multilingual models (e.g., `text-embedding-3-small`) underperform on Vietnamese legal text.
- AITeamVN models are trained specifically on Vietnamese corpus — significantly better semantic matching for legal terminology.
- The reranker dramatically improves precision: vector prefetch 20 candidates → reranker selects top 8.

**Rejected:** Multilingual-E5 (insufficient Vietnamese legal domain coverage), text-embedding-3-small (generic, English-biased).

**Trade-offs:**
- Models are large (~500MB each) and must be loaded into memory. They are initialized as singletons on startup.
- No English-only mode — all text is expected to have Vietnamese content. For bilingual contracts, quality degrades on the English portions.

---

## [2024-Q4] Token-Based Auth with Database Session Store

**Decision:** Implement auth with opaque tokens stored as bcrypt hashes in `auth_sessions` table (not JWT).

**Reasoning:**
- Tokens can be revoked server-side (important for legal tools where access control matters).
- No JWT secret rotation complexity.
- Simpler to implement and audit.
- Sessions persist across server restarts (stored in DB, not memory).

**Rejected:** JWT. Self-contained but cannot be revoked without a blacklist, which adds complexity.

**Trade-offs:**
- Every authenticated request requires a database lookup to validate the token. At scale, add a short-lived cache. Acceptable for current user volume.

---

## [2024-Q4] React 18 + Vite + TanStack Query + Zustand (No Redux)

**Decision:** Use TanStack Query for server state and Zustand for client UI state.

**Reasoning:**
- TanStack Query eliminates boilerplate for loading/error/caching of server data.
- Zustand is lightweight and co-located — stores are ~30 lines each, no boilerplate.
- No Redux needed at LexGuardian's current scale. If cross-store complexity grows, re-evaluate.

**Rejected:** Redux Toolkit (overkill), SWR (less capable than TanStack Query for mutations).

**Trade-offs:**
- Two state libraries increases learning curve slightly. Clear rule: server data in Query, UI state in Zustand. No exceptions.

---

## [2024-Q4] SSE (Server-Sent Events) for Streaming Chat

**Decision:** Use SSE (not WebSockets) for streaming LLM responses.

**Reasoning:**
- SSE is unidirectional (server → client), which matches the streaming response model.
- Simpler than WebSockets: no protocol upgrade, works through standard HTTP proxies (important with Nginx).
- Native browser `EventSource` API is well-supported.
- FastAPI's `StreamingResponse` has native SSE support.

**Rejected:** WebSockets (bidirectional overhead not needed), long polling (poor UX for streaming text).

**Trade-offs:**
- SSE connections can be terminated by HTTP proxies if inactive too long. Mitigated with heartbeat events every 15 seconds.
- Nginx requires `proxy_buffering off` for SSE routes. Configured in `nginx.conf`.

---

## [2025-Q1] Unified `/command` Endpoint (Planned)

**Decision:** Build a single `/api/v1/legal/command/{workspace_id}` endpoint that accepts any user input and routes internally.

**Reasoning:**
- Currently the frontend orchestrates: call `/route-intent` → based on result, call one of 4 different endpoints. This is backend intelligence leaking into the frontend.
- The frontend should not need to understand the routing logic. It should express intent and receive structured output.
- Enables future A/B testing of routing strategies without frontend changes.

**Trade-offs:**
- Single endpoint creates a potential complexity hotspot. Mitigated by keeping the endpoint thin (validate → delegate to `LegalCommandOrchestrator` service).
- SSE response format must include an `intent_detected` field so the frontend can transition to the correct UI view.

**Status:** Planned for Phase 2. Current `/route-intent` + individual endpoints remain for now.

---

## [Future] Alembic for Database Migrations

**Decision (future):** Move from inline `ALTER TABLE IF NOT EXISTS` in `main.py` to Alembic migrations.

**Reasoning:**
- Current approach works for development but is fragile in production (race conditions on startup, no rollback).
- Alembic provides versioned migrations, rollback support, and migration history.

**Status:** Deferred. Acceptable tech debt for now. Implement before first production deployment with real user data.

---

## Decision Principles

When making new technology decisions, follow these guidelines:

1. **User trust over developer convenience.** A slower but more reliable citation retrieval beats a faster but less accurate one.
2. **One infrastructure dependency over two.** If PostgreSQL can do it (pgvector, full-text search), don't add a separate service.
3. **Working code over perfect architecture.** Ship working features in NexusRAG's existing patterns; refactor toward clean architecture in the migration.
4. **Vietnamese-first.** All language-model and embedding choices must prioritize Vietnamese quality. English is secondary.
5. **Explicit feature flags over code deletion.** Keep `ENABLE_GENERIC_RAG_API`, `NEXUSRAG_ENABLE_KG` flags. Disable in production; keep in code for optional enablement.
