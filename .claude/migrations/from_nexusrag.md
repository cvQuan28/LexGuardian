# Migration Guide: NexusRAG → LexGuardian

This document records what was learned from NexusRAG and provides a precise reuse map for the LexGuardian rebuild.

---

## What Was NexusRAG?

NexusRAG started as a developer-focused RAG (Retrieval-Augmented Generation) sandbox. It evolved through multiple pivots: generic document Q&A → Vietnamese legal corpus search → contract analysis → legal copilot. Each pivot added features without removing old ones. The result is a powerful but confusing system where the best features are buried under technical complexity.

**What NexusRAG did right:**
- Built a robust Vietnamese document processing pipeline (Docling + semantic chunking)
- Built a real hybrid retrieval system (BM25 + pgvector + cross-encoder reranking)
- Built a production-quality legal AI service layer (intent routing, grounded QA, risk analysis)
- Built an SSE streaming infrastructure with agent steps and thinking timelines
- Built a solid auth system (token-based, workspace-scoped)

**What NexusRAG did wrong:**
- Exposed the RAG pipeline mechanics in the primary UI
- Never committed to a specific user persona
- Mixed generic RAG features with legal-specific features without a clear boundary
- Frontend grew into a 3-column static grid that can't adapt to different user intents
- Technical naming throughout (workspaces, chunks, vectors, query modes)

---

## Component Reuse Map

### ✅ REUSE AS-IS — Backend Services (High Quality, High Value)

These are the core of LexGuardian's intelligence. Do not rewrite without strong reason.

| File | Quality | Notes |
|---|---|---|
| `app/services/legal/risk_analysis_agent.py` | ⭐⭐⭐⭐⭐ | The flagship feature. Well-structured. Keep and extend. |
| `app/services/legal/legal_router.py` | ⭐⭐⭐⭐⭐ | Excellent multi-layer intent detection. Reuse directly. |
| `app/services/legal/legal_retriever.py` | ⭐⭐⭐⭐ | Solid hybrid BM25+vector+rerank pipeline. Keep. |
| `app/services/legal/web_search.py` | ⭐⭐⭐⭐ | Tavily integration with domain filtering. Keep. |
| `app/services/legal/clause_chunker.py` | ⭐⭐⭐⭐ | Contract-aware chunking. Critical for risk analysis accuracy. |
| `app/services/legal/contract_extractor.py` | ⭐⭐⭐⭐ | Structured field extraction. Keep. |
| `app/services/deep_document_parser.py` | ⭐⭐⭐⭐⭐ | Docling integration. Excellent. Keep. |
| `app/services/embedder.py` | ⭐⭐⭐⭐ | Singleton sentence transformer. Keep. |
| `app/services/reranker.py` | ⭐⭐⭐⭐ | Cross-encoder reranking. Keep. |
| `app/services/vector_store.py` | ⭐⭐⭐⭐ | pgvector CRUD. Keep. |
| `app/services/chunker.py` | ⭐⭐⭐⭐ | Semantic chunking with token control. Keep. |
| `app/services/llm/` (all) | ⭐⭐⭐⭐⭐ | Provider abstraction is well-designed. Keep. |

### ✅ REUSE WITH MINOR CHANGES — Backend API Layer

| File | Changes Needed |
|---|---|
| `app/api/auth.py` | None. Rock-solid. |
| `app/api/workspaces.py` | Minor: rename `knowledge_bases` → `briefs` in response labels (not table names). |
| `app/api/documents.py` | None for core. Add: document re-indexing trigger endpoint. |
| `app/api/legal.py` | Add: unified `/command` endpoint. Remove: legacy routes if `LEGAL_LEGACY_INTERNAL_ROUTES_ENABLED` is set. |
| `app/api/conversations.py` | None. Well-structured. |
| `app/core/` (all) | No changes needed. |
| `app/models/` (all) | No structural changes. Add: `matters` alias if needed. |
| `app/schemas/` (all) | Keep. Add schemas for new `/command` endpoint. |
| `app/main.py` | Clean up: move auto-migration to proper Alembic eventually. Keep for now. |

### 🔄 REWRITE — Frontend (Complete UX Overhaul)

The frontend is the part that needs the most work. It is technically functional but architecturally wrong for LexGuardian's intent-first model.

| NexusRAG File | LexGuardian Replacement | Reason |
|---|---|---|
| `pages/WorkspacePage.tsx` | Split into `AskPage.tsx`, `AnalyzePage.tsx`, `ExplorePage.tsx` | The 3-mode page must become 3 intentional flows |
| `pages/KnowledgeBasesPage.tsx` | `LibraryPage.tsx` + `HomeCommandCenter.tsx` | Home screen is now the Command Center, not a list of workspaces |
| `components/rag/DataPanel.tsx` | **REMOVED** | Never show the technical data panel to users |
| `components/rag/StatsBar.tsx` | **REMOVED** | No technical stats in the UI |
| `components/rag/VisualPanel.tsx` | `pages/ExplorePage.tsx` (dark mode, secondary access) | Knowledge Graph is a power feature, not a default panel |
| `components/rag/ChatPanel.tsx` | Decompose into: `ChatMessageList`, `ChatInputBar`, `StreamingAnswer`, `CitationChip` | 1500+ line component, needs decomposition |
| `components/rag/KnowledgeGraphView.tsx` | Keep for ExplorePage, update visual design | Good functionality, wrong placement |
| `components/rag/SearchBar.tsx` | Replaced by `CommandBar.tsx` | CommandBar is more capable (file drop + text + suggestions) |
| `components/layout/AppShell.tsx` | Minimal changes — add route for HomeCommandCenter | Keep the shell pattern |
| `components/layout/Sidebar.tsx` | Update navigation labels only | Same structure, new product language |

### ✅ REUSE AS-IS — Frontend Infrastructure

| File | Quality | Notes |
|---|---|---|
| `hooks/useRAGChatStream.ts` | ⭐⭐⭐⭐⭐ | SSE streaming hook is excellent. Keep verbatim. |
| `hooks/useAuth.ts` | ⭐⭐⭐⭐ | Clean TanStack Query pattern. Keep. |
| `hooks/useWorkspaces.ts` | ⭐⭐⭐⭐ | Keep. Rename `workspaces` → `briefs` in display layer only. |
| `hooks/useConversations.ts` | ⭐⭐⭐⭐ | Clean. Keep. |
| `hooks/useChatHistory.ts` | ⭐⭐⭐⭐ | Clean. Keep. |
| `stores/authStore.ts` | ⭐⭐⭐⭐⭐ | Token management is solid. Keep. |
| `stores/workspaceStore.ts` | ⭐⭐⭐ | Keep but extend: add `riskReportItem` for selecting individual risk items |
| `stores/ragPanelStore.ts` | ⭐⭐⭐⭐ | Panel state management pattern is good. Keep the pattern. |
| `lib/api.ts` | ⭐⭐⭐⭐⭐ | Class-based API client is clean. Keep. Add new endpoint functions. |
| `lib/utils.ts` | ⭐⭐⭐⭐ | Keep. |
| `types/index.ts` | ⭐⭐⭐ | Keep all existing types. Add: `ContractRiskReport`, `RiskItem`, `CommandIntent`. |
| `components/rag/MemoizedMarkdown.tsx` | ⭐⭐⭐⭐⭐ | Optimized streaming markdown. Keep. |
| `components/rag/ThinkingTimeline.tsx` | ⭐⭐⭐⭐ | Good UX for agent reasoning display. Keep. |
| `components/rag/DocumentViewer.tsx` | ⭐⭐⭐⭐ | The source viewer is one of LexGuardian's key trust mechanisms. Keep. |
| `components/rag/DocumentCard.tsx` | ⭐⭐⭐ | Keep for LibraryPage. Minor styling updates. |
| `components/rag/UploadZone.tsx` | ⭐⭐⭐ | Keep as a sub-component of CommandBar. |
| `components/ui/` (all) | ⭐⭐⭐⭐ | shadcn-style primitives. Keep all. |

---

## Technical Debt Inventory

Issues inherited from NexusRAG, ordered by priority to address:

### Priority 1 — Blocks Product Vision
1. **No unified `/command` endpoint.** The frontend must currently orchestrate intent routing → retrieval → display. This is backend logic that leaked into the frontend.
2. **3-column static layout.** Cannot build the intent-first flows on top of this structure. Requires full page restructuring.
3. **WorkspacePage is a monolith.** 700+ lines mixing three different user intents (ask, analyze, explore).

### Priority 2 — User Trust Risk
4. **Technical stats visible in chat UI.** `StatsBar` and data panel stats are exposed. Must be removed.
5. **No "insufficient information" fallback.** If retrieval returns poor results, the LLM can hallucinate. The `LEGAL_GROUNDING_STRICT=true` flag helps but needs UI enforcement.

### Priority 3 — Code Quality
6. **Database migrations in `main.py`.** The lifespan handler does all schema management inline. Works but should move to Alembic for production safety.
7. **`ChatPanel.tsx` is ~1500 lines.** Should be decomposed into focused sub-components.
8. **Multiple SSE implementations.** `chat_agent.py` and the `legal.py` routes both implement SSE streaming. Should use a shared utility.

### Priority 4 — Nice to Have
9. **Vietnamese-only keyword lists in `legal_router.py`.** Good for Vietnamese contracts but needs extension for bilingual contracts.
10. **No pagination on document list.** Will become a problem for users with large document libraries.

---

## Migration Sequence

The recommended order of work:

1. **Foundation:** Set up LexGuardian project structure, copy backend as-is, set up CI
2. **Backend:** Add `/command` unified endpoint; clean up legacy routes
3. **Frontend - Infrastructure:** Copy hooks, stores, lib, types verbatim
4. **Frontend - Layout:** Build `HomeCommandCenter` and new page structure
5. **Frontend - Ask Flow:** Build `AskPage` with `StreamingAnswer` + `SourceViewer`
6. **Frontend - Analyze Flow:** Build `AnalyzePage` with `RiskReport` components
7. **Remove:** Delete `DataPanel`, `StatsBar`, NexusRAG-specific UI elements
8. **Polish:** Apply design system (serif fonts, ambient depth, risk severity colors)
9. **Explore Flow:** Add `ExplorePage` with Knowledge Graph (hidden until MVP complete)

---

## What to Tell the Next Developer

If you're joining this project after the initial migration, here's what you need to know:

1. The backend is largely the same as NexusRAG. The intelligence is in `app/services/legal/`. Start there to understand what the system can do.
2. The frontend is rebuilt for LexGuardian's UX model. Don't look at the old NexusRAG frontend patterns — they were intentionally not migrated.
3. When in doubt about a UI decision, open `04_ui_patterns.md` and `context/design_principles.md`.
4. When in doubt about an API decision, check `03_api_contracts.md` — the unified `/command` endpoint is the north star.
5. The test coverage is thin at migration time. Before changing anything critical, write the test first.
