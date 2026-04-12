# Refactoring Template

Use this when cleaning up existing code in LexGuardian. Good refactoring improves clarity without changing behavior.

---

## Refactoring Brief

**Target:** [file(s) or component(s) to refactor]  
**Reason:** [why this needs to change]  
**Type:** [extraction / simplification / rename / decomposition / performance]  
**Risk level:** [Low / Medium / High — based on how much code depends on this]

---

## Current State Assessment

Before changing anything, document what exists:

**What this code does:** [functional description]  
**What's wrong with it:** [specific problems — not "it's messy", be precise]  
**What depends on it:** [list files/components that import or call this code]  
**Does it have tests?** [yes/no — if no, write tests BEFORE refactoring]

---

## Refactoring Goals

State clearly what "done" looks like:

- [ ] [specific measurable improvement, e.g., "ChatPanel.tsx is under 200 lines"]
- [ ] [specific measurable improvement, e.g., "legal_router.py has a single public function"]
- [ ] All existing tests still pass
- [ ] No behavior changes for users

---

## Common Refactoring Patterns in LexGuardian

### Frontend: Decomposing Large Components

NexusRAG's `ChatPanel.tsx` is a monolith (~1500 lines). The pattern for decomposing it:

```
ChatPanel.tsx (orchestration only)
├── ChatMessageList.tsx     (renders the conversation history)
├── ChatInputBar.tsx        (text input + mode controls)
├── StreamingAnswer.tsx     (renders the in-progress streaming response)
├── ThinkingTimeline.tsx    (already exists — keep as-is)
└── CitationChip.tsx        (inline citation rendering — extract this)
```

**Rule:** A component that exceeds ~200 lines is usually doing more than one thing. Split it.

**Safe decomposition steps:**
1. Identify the sub-responsibilities within the large component
2. Create the new sub-component file
3. Move the JSX and directly related state/handlers to the sub-component
4. Pass required data as typed props
5. Replace the original section with the new component
6. Run `pnpm type-check` — zero TypeScript errors required

### Backend: Extracting Service Functions

When a service file grows beyond ~400 lines, extract related functions into a focused helper module.

Example: `legal_agent_workflow.py` mixes intent routing, tool selection, and answer synthesis. Extract:
- `intent_classifier.py` — just the intent detection logic
- `tool_registry.py` — tool definitions and selection
- Keep `legal_agent_workflow.py` as the orchestration layer

**Safe extraction steps:**
1. Write a test that calls the public interface of the code you're about to extract
2. Move the function(s) to the new module
3. Update the import in the original file
4. Run the test — should still pass
5. Run `ruff check .` — zero errors required

### Renaming for Product Alignment

NexusRAG uses technical names that don't match the LexGuardian product language. Rename systematically:

| NexusRAG name | LexGuardian name | Scope |
|---|---|---|
| `KnowledgeBase` (DB model) | Keep as-is in DB layer | DB/backend |
| `workspace` (URL params) | Keep as-is in routes | API |
| `KnowledgeBasesPage` | `LibraryPage` | Frontend |
| `WorkspacePage` | Replaced by `AskPage` + `AnalyzePage` | Frontend |
| `DataPanel` | Removed | Frontend |
| `VisualPanel` | `ExplorePage` (separated) | Frontend |

**Rule:** Rename in the frontend UI layer (labels, page names, navigation). Keep backend identifiers stable to avoid migration complexity.

### Removing Technical Exposure

Identify and remove these patterns from frontend code:

```tsx
// REMOVE: Technical stats in the UI
<StatsBar
  totalChunks={ragStats?.total_chunks}
  vectorDimension={ragStats?.embedding_dimension}
  queryMode={queryMode}
/>

// REPLACE WITH: Nothing visible, or a simple "N documents ready" indicator

// REMOVE: Mode selector visible to user
<select value={queryMode} onChange={setQueryMode}>
  <option value="hybrid">Hybrid</option>
  <option value="vector_only">Vector Only</option>
</select>

// REPLACE WITH: Removed entirely — backend decides
```

---

## Pre-Refactoring Checklist

- [ ] Tests exist for the code being changed (write them first if not)
- [ ] I understand all the callers/importers of this code
- [ ] I have a clear statement of what behavior must NOT change
- [ ] I have run the existing tests and they pass

## Post-Refactoring Checklist

- [ ] All existing tests still pass
- [ ] `pnpm type-check` passes (frontend)
- [ ] `ruff check .` passes (backend)
- [ ] No new `// @ts-ignore` or `type: ignore` comments added
- [ ] The refactored code is measurably simpler (lines, cognitive complexity)
- [ ] Any removed UI elements were confirmed not needed by product vision
- [ ] Tech decision documented in `migrations/tech_decisions_log.md` if significant

---

## What Not to Refactor

Some technical debt in NexusRAG is worth keeping in the short term:

- **Auto-migration in `main.py` lifespan:** It's messy but idempotent and functional. Leave it until a proper migration tool (Alembic) is set up.
- **`chat_agent.py` SSE streaming logic:** Complex but working. Only refactor if adding new features requires it.
- **pgvector schema:** The `vector_chunks` table works. Don't touch the vector storage layer until you have a concrete need.
- **LLM provider abstraction:** Already well-structured. Don't change for its own sake.

**Rule:** If it works and isn't in the critical path of LexGuardian's user flows, leave it for now. Focus refactoring energy on the frontend (which needs a near-complete UX overhaul) and the API layer (which needs the unified `/command` endpoint).
