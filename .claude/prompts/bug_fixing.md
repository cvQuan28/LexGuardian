# Bug Fixing Template

Use this when investigating and fixing a bug in LexGuardian.

---

## Bug Report

**Title:** [Short description]  
**Reported by:** [who / where: user report / test failure / internal finding]  
**Severity:** [Critical / High / Medium / Low]  
**Affects:** [Ask flow / Analyze flow / Explore flow / Auth / Ingestion / Other]

---

## Reproduction Steps

1. Start from: [specific page/state]
2. Do: [exact action]
3. Expected: [what should happen]
4. Actual: [what actually happens]
5. Frequency: [always / intermittent / specific condition]

---

## Diagnosis Checklist

Work through these systematically before writing any code:

### 1. Identify the layer
- [ ] Is this a **frontend rendering bug**? (wrong display, broken interaction)
- [ ] Is this a **data bug**? (wrong data returned from API)
- [ ] Is this a **backend service bug**? (wrong computation, wrong retrieval)
- [ ] Is this a **streaming/SSE bug**? (connection drops, malformed events)
- [ ] Is this an **ingestion pipeline bug**? (document stuck, not indexed)

### 2. Check the logs
```bash
# Backend logs
docker compose logs -f backend | grep ERROR

# Or locally
tail -f system.log | grep -E "ERROR|WARNING"
```

### 3. Check the API response directly
```bash
# Test the failing endpoint directly (bypasses frontend)
curl -X POST http://localhost:8000/api/v1/[endpoint] \
  -H "Authorization: Bearer [token]" \
  -H "Content-Type: application/json" \
  -d '[request body]'
```

### 4. Check the database state
```sql
-- Check document status
SELECT id, filename, status, error_message FROM documents WHERE id = [N];

-- Check vector chunks for a document
SELECT COUNT(*), AVG(length(content)) FROM vector_chunks WHERE document_id = [N];
```

### 5. Identify the exact code location
The most common bug locations by symptom:

| Symptom | Look in |
|---|---|
| Citation chip doesn't open source viewer | `workspaceStore.ts` → `selectDoc()`, `DocumentViewer.tsx` |
| SSE stream drops mid-response | `useRAGChatStream.ts` → AbortController cleanup |
| Wrong answer, no sources | `legal_retriever.py` → retrieval quality, `legal_reasoning.py` → grounding check |
| Document stuck in "processing" | `nexus_rag_service.py` → background task error handling |
| Risk analysis returns empty | `risk_analysis_agent.py` → clause chunk retrieval |
| Login token not persisting | `authStore.ts` → `localStorage` read/write |
| Wrong workspace accessed | `deps.py` → `get_workspace_for_user()` ownership check |

---

## Root Cause

**File:** `[path/to/file.py or .tsx]`  
**Line(s):** [approximate line numbers]  
**Root cause:**

> [One paragraph explaining WHY the bug exists, not just what is wrong]

---

## Fix Plan

Describe the fix before implementing it. Get a review if the fix touches:
- Authentication or authorization logic
- The ingestion pipeline
- The LLM prompt templates
- Database schema

**Proposed fix:**
```python
# Before
[broken code]

# After
[fixed code]
```

**Why this fix is correct:** [reasoning]  
**What it doesn't break:** [other behaviors that depend on this code]

---

## Regression Test

Write a test that would have caught this bug before it reached production:

```python
# tests/api/test_[affected_area].py
async def test_[bug_description_that_should_not_happen]():
    # Reproduce the exact condition that caused the bug
    ...
    # Assert the correct behavior
    assert ...
```

---

## Validation Checklist

- [ ] Bug no longer reproduces following the reproduction steps
- [ ] Related functionality still works (regression check)
- [ ] Test added that would catch this bug in CI
- [ ] If this was a data integrity bug: verify existing data is not corrupted
- [ ] If this was a security bug: check if it affected production data, report appropriately

---

## Common Bugs and Their Fixes

### SSE stream doesn't close properly
**Symptom:** Multiple streams running, memory leak over time  
**Fix:** Ensure `AbortController.abort()` is called in useEffect cleanup  
```typescript
useEffect(() => {
  return () => { abortControllerRef.current?.abort(); };
}, []);
```

### Citation page number is off by one
**Symptom:** Source viewer opens to wrong page  
**Fix:** Check if `page_no` is 0-indexed or 1-indexed in DocumentViewer vs the stored value. Normalize at the store layer, not the component.

### Document indexing silently fails
**Symptom:** Document shows "indexed" but has 0 chunks in pgvector  
**Fix:** Check `nexus_rag_service.py` background task exception handling. Ensure exceptions in the background task update `document.status = FAILED` and log `document.error_message`.

### Risk analysis returns generic risks, not clause-specific
**Symptom:** Risk items have no `original_text`, generic explanations  
**Fix:** Check `risk_analysis_agent.py` — ensure clause chunks are retrieved by document_id before calling the LLM, not just from the full workspace vector store.

### Auth token not working after restart
**Symptom:** Users get logged out unexpectedly  
**Fix:** Check `auth_sessions.expires_at` vs server time. Ensure token validation uses UTC consistently.
