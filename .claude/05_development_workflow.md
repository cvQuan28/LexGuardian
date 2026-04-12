# 05 — Development Workflow

## Initial Setup

### Prerequisites
- Python 3.11+
- Node.js 20+ (use `.nvmrc` in `frontend/`)
- Docker + Docker Compose
- A `.env` file at project root (copy `.env.example` and fill in keys)

### First-time Setup
```bash
# 1. Start infrastructure (PostgreSQL + pgvector)
docker compose -f docker-compose.services.yml up -d

# 2. Backend
cd backend
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Run migrations (auto-runs on startup, but verify manually)
uvicorn app.main:app --reload --port 8000

# 3. Frontend
cd frontend
nvm use                      # uses .nvmrc
pnpm install
pnpm dev                     # starts on http://localhost:5174
```

### Full Docker Development
```bash
docker compose up --build
# Backend: http://localhost:8000
# Frontend: http://localhost:80
# API docs: http://localhost:8000/docs
```

---

## Environment Configuration

Key `.env` variables for development:

```bash
# Database (local PostgreSQL via Docker)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/nexusrag

# LLM — use gemini for full feature support, ollama for offline dev
LLM_PROVIDER=gemini
GOOGLE_AI_API_KEY=your_key_here

# For contract risk analysis (uses the pro model)
LEGAL_RISK_ANALYSIS_MODEL=gemini-2.5-pro

# Live web search
TAVILY_API_KEY=your_key_here

# Feature flags
DEBUG=true
ENABLE_GENERIC_RAG_API=true
NEXUSRAG_ENABLE_KG=true
AUTO_CREATE_TABLES=true
```

For offline/local development without API keys:
```bash
LLM_PROVIDER=ollama
OLLAMA_MODEL=gemma3:12b
TAVILY_API_KEY=   # leave empty, live search will be disabled
```

---

## Working on Backend

### Adding a New API Endpoint

1. Define the Pydantic request/response schema in `app/schemas/`
2. Write the service logic in `app/services/` (or `app/services/legal/` for legal features)
3. Add the route handler in the relevant `app/api/` file — keep it thin (validate → delegate → return)
4. Register the router in `app/api/router.py` if it's a new router
5. Test via the auto-generated Swagger docs at `http://localhost:8000/docs`

### Adding a New Service

Services live in `app/services/`. For legal features, they go in `app/services/legal/`.

Naming conventions:
- Class names: `PascalCase` (e.g., `RiskAnalysisAgent`)
- Module names: `snake_case` (e.g., `risk_analysis_agent.py`)
- All services that call LLMs must use the provider abstraction:
  ```python
  from app.services.llm import get_llm_provider
  llm = get_llm_provider()
  response = await llm.chat(messages)
  ```

### Database Changes

Database schema is managed via inline SQL in `app/main.py`'s lifespan handler using idempotent patterns:
```sql
CREATE TABLE IF NOT EXISTS new_table (...);
ALTER TABLE existing_table ADD COLUMN IF NOT EXISTS new_column TEXT;
CREATE INDEX IF NOT EXISTS ix_table_column ON table(column);
```

**Important:** Never drop columns or tables in the auto-migration. Write a separate migration script for destructive changes.

### Async Rules

All database operations must be `async`. Use `AsyncSession` everywhere.
```python
# Good
async def get_document(db: AsyncSession, doc_id: int) -> Document:
    result = await db.execute(select(Document).where(Document.id == doc_id))
    return result.scalar_one_or_none()

# Bad — sync SQLAlchemy in async context will deadlock
document = db.query(Document).filter_by(id=doc_id).first()
```

---

## Working on Frontend

### Adding a New Page

1. Create `src/pages/NewPage.tsx`
2. Add the route in `App.tsx`
3. Add navigation link in `Sidebar.tsx`
4. Create a TanStack Query hook in `src/hooks/` for any data this page needs

### Adding a New Component

1. Decide: Is it a shared primitive? → `components/ui/`. Is it specific to a flow? → `components/ask/`, `components/analyze/`, etc.
2. Create the component file
3. Export from the folder's `index.ts` if applicable
4. Add types to `src/types/index.ts` if new types are needed

### Adding a New API Call

1. Add the typed function to `src/lib/api.ts` using the `api` client:
   ```typescript
   export const analyzeRisk = (workspaceId: number, documentId: number) =>
     api.post<ContractRiskReport>(`/legal/analyze-risk/${workspaceId}`, { document_id: documentId });
   ```
2. Wrap it in a TanStack Query hook:
   ```typescript
   export function useAnalyzeRisk(workspaceId: number) {
     return useMutation({
       mutationFn: ({ documentId }: { documentId: number }) =>
         analyzeRisk(workspaceId, documentId),
     });
   }
   ```

### Zustand Store Rules

- Stores are for **UI state only**: which panel is open, scroll position, selected item, theme
- Never store API response data in Zustand — that belongs in TanStack Query cache
- Store files: one store per concern, co-located logic (state + actions together)
- Always use `create<T>` with typed state interface

---

## Git Workflow

### Branch Naming
```
feature/command-center-ui
fix/citation-scroll-not-working
refactor/legal-router-confidence-scoring
chore/update-gemini-model-version
```

### Commit Convention
```
feat: add unified command bar with intent detection
fix: SSE stream not closing on component unmount
refactor: extract CitationChip from ChatPanel
chore: upgrade gemini SDK to 0.8
docs: document analyze-risk API contract
```

### Before Opening a PR
- [ ] Backend: `ruff check .` passes (linting)
- [ ] Backend: `pytest tests/` passes (if tests exist)
- [ ] Frontend: `pnpm type-check` passes (TypeScript)
- [ ] Frontend: `pnpm lint` passes (ESLint)
- [ ] No hardcoded secrets or API keys in code
- [ ] No `console.log` left in production code
- [ ] New API endpoint has corresponding type in `src/types/index.ts`

---

## Common Development Tasks

### Test the risk analysis pipeline manually
```bash
# After uploading a document, get its ID from the response
curl -X POST http://localhost:8000/api/v1/legal/analyze-risk/1 \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"document_id": 2}'
```

### Re-index a document
```bash
# Delete and re-upload, or call the reindex endpoint if implemented
DELETE /documents/{doc_id}  # removes from DB and pgvector
POST /documents/upload/{workspace_id}  # re-upload
```

### Check what's in the vector store
```sql
-- Connect to PostgreSQL (docker exec -it <container> psql -U postgres nexusrag)
SELECT document_id, COUNT(*) as chunks
FROM vector_chunks
GROUP BY document_id;
```

### View backend logs
```bash
docker compose logs -f backend
# Or locally: tail -f system.log
```

---

## Performance Notes

- The embedding model (`AITeamVN/Vietnamese_Embedding`) is large (~500MB). It loads once on startup. Do not instantiate it per-request.
- The reranker model is similarly loaded once. Both are cached as singletons.
- For development, set `NEXUSRAG_ENABLE_IMAGE_CAPTIONING=false` and `NEXUSRAG_ENABLE_TABLE_CAPTIONING=false` to speed up document ingestion.
- SSE streaming connections time out after 30s of inactivity by default. The backend sends a heartbeat every 15s to keep connections alive.
