# 🛡️ LexGuardian — Claude Code Entry Point

**Read this file first before touching any code.**

---

## What Is LexGuardian?

LexGuardian is an **AI Legal Copilot** built for legal professionals and business teams who need to analyze contracts, query the law, and verify answers with instant citations. It is not a RAG sandbox. It is not a developer tool. It is an intent-driven workspace that hides AI complexity and surfaces legal intelligence.

**Core promise:** "Analyze contracts, search the law, and verify answers with instant, pin-point citations — all in a beautifully clean workspace."

---

## Where to Start

| You want to… | Read this |
|---|---|
| Understand the product vision | [`01_product_vision.md`](./01_product_vision.md) |
| Understand the system architecture | [`02_architecture.md`](./02_architecture.md) |
| Understand the API contracts | [`03_api_contracts.md`](./03_api_contracts.md) |
| Understand the UI design system | [`04_ui_patterns.md`](./04_ui_patterns.md) |
| Start working on the project | [`05_development_workflow.md`](./05_development_workflow.md) |
| Write or run tests | [`06_testing_guide.md`](./06_testing_guide.md) |
| Understand who the users are | [`context/user_personas.md`](./context/user_personas.md) |
| Understand the key user flows | [`context/user_flows.md`](./context/user_flows.md) |
| Know the UX design rules | [`context/design_principles.md`](./context/design_principles.md) |
| Build a new feature | [`prompts/feature_development.md`](./prompts/feature_development.md) |
| Fix a bug | [`prompts/bug_fixing.md`](./prompts/bug_fixing.md) |
| Refactor existing code | [`prompts/refactoring.md`](./prompts/refactoring.md) |
| Understand what was learned from NexusRAG | [`migrations/from_nexusrag.md`](./migrations/from_nexusrag.md) |
| Understand major technology choices | [`migrations/tech_decisions_log.md`](./migrations/tech_decisions_log.md) |

---

## The Golden Rules

These rules govern every decision in LexGuardian. Violating them requires explicit justification in `migrations/tech_decisions_log.md`.

1. **Intent-first, not feature-first.** Every screen must let the user express intent in one action. No complex setup before the first value.

2. **Trust via proof.** Every AI statement must be linkable to its source. No floating claims. No anonymous assertions. If we can't cite it, we don't say it.

3. **Hide the machine.** Users do not see parsing logs, chunk counts, vector dimensions, or indexing timers. The AI runs invisibly. The user sees only results.

4. **No dead ends.** If the system cannot help, it must say so clearly and propose an alternative (web search, rephrase, contact a lawyer).

5. **One canonical API contract.** The frontend speaks to one intelligent endpoint per flow (`/command`, `/analyze-risk`, `/live-search`). The backend routes internally. The frontend does not orchestrate AI logic.

---

## Tech Stack (Quick Reference)

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy (async), PostgreSQL + pgvector |
| LLM | Google Gemini (primary), Ollama (local dev) |
| Embeddings | Sentence Transformers (Vietnamese), Gemini Embeddings |
| Document Parsing | Docling (PDF/DOCX → Markdown + images) |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Zustand, TanStack Query |
| Infra | Docker Compose, Nginx reverse proxy |

---

## Project Layout

```
LexGuardian/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI route handlers (thin layer)
│   │   ├── core/         # Config, DB, deps, security
│   │   ├── models/       # SQLAlchemy ORM models
│   │   ├── schemas/      # Pydantic request/response models
│   │   └── services/     # Business logic
│   │       ├── legal/    # All legal AI intelligence lives here
│   │       ├── llm/      # LLM provider abstraction
│   │       └── ...       # RAG pipeline services
│   └── data/
│       └── docling/      # Extracted document images (served as static)
├── frontend/
│   └── src/
│       ├── components/   # Reusable UI components
│       ├── pages/        # Route-level page components
│       ├── hooks/        # Data + stream hooks
│       ├── stores/       # Zustand global state
│       ├── lib/          # API client, utilities
│       └── types/        # TypeScript interfaces
└── .claude/              # ← You are here
```

---

## Current Development Status

LexGuardian is in **active rebuild** from NexusRAG. The backend services are largely reusable. The frontend requires a full UX overhaul aligned with the product vision. See [`migrations/from_nexusrag.md`](./migrations/from_nexusrag.md) for a detailed reuse map.

> **Before writing any code:** read `01_product_vision.md` and `02_architecture.md`. Before building a UI component: read `04_ui_patterns.md`. Before calling a new API: check `03_api_contracts.md`.
