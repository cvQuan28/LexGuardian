# 03 — API Contracts

All endpoints are prefixed with `/api/v1`. Authentication via `Authorization: Bearer <token>` header is required on all routes except `/auth/login` and `/auth/register`.

---

## Authentication

### `POST /auth/register`
```json
Request:  { "email": "string", "password": "string", "display_name": "string" }
Response: { "token": "string", "user": { "id": int, "email": "string", "display_name": "string" } }
```

### `POST /auth/login`
```json
Request:  { "email": "string", "password": "string" }
Response: { "token": "string", "user": { "id": int, "email": "string", "display_name": "string" } }
```

### `GET /auth/me`
```json
Response: { "id": int, "email": "string", "display_name": "string", "created_at": "ISO8601" }
```

### `POST /auth/logout`
```json
Response: 204 No Content
```

---

## Workspaces (Matters / Briefs)

### `GET /workspaces`
Returns all workspaces for the authenticated user.
```json
Response: [{ "id": int, "name": "string", "description": "string|null", "document_count": int, "indexed_count": int, "created_at": "ISO8601" }]
```

### `POST /workspaces`
```json
Request:  { "name": "string", "description": "string?" }
Response: { "id": int, "name": "string", ... }
```

### `GET /workspaces/{workspace_id}`
### `PATCH /workspaces/{workspace_id}`
```json
Request:  { "name": "string?", "description": "string?", "system_prompt": "string|null?" }
```
### `DELETE /workspaces/{workspace_id}`

---

## Documents

### `POST /documents/upload/{workspace_id}`
Multipart form upload. Triggers background ingestion pipeline.
```
Content-Type: multipart/form-data
Field: file (PDF, DOCX, TXT, MD)
Response: { "id": int, "filename": "string", "status": "pending", ... }
```

### `GET /documents/workspace/{workspace_id}`
```json
Response: [{ "id": int, "filename": "string", "status": "pending|parsing|processing|indexing|indexed|failed", "chunk_count": int, "page_count": int, "image_count": int, "table_count": int, "processing_time_ms": int }]
```

### `DELETE /documents/{document_id}`

### `GET /documents/{document_id}/images`
Returns extracted images with captions.
```json
Response: [{ "image_id": "uuid", "page_no": int, "caption": "string", "width": int, "height": int, "url": "/static/doc-images/..." }]
```

---

## Legal Intelligence Endpoints

These are the core product APIs. The frontend primarily talks to these.

### `POST /legal/route-intent/{workspace_id}` — Intent Classification
Classifies a user query to determine how it should be handled. The Command Center uses this to decide which flow to trigger.
```json
Request:
{
  "query": "string",
  "conversation_history": [{"role": "user|assistant", "content": "string"}]?
}

Response:
{
  "intent": "LEGAL_QA | CONTRACT_QUERY | LIVE_SEARCH | VALIDITY_CHECK | GENERAL",
  "confidence": 0.0-1.0,
  "signals": ["string"],
  "suggested_action": "string",
  "domain": "legal | general"
}
```

### `POST /legal/query/{workspace_id}` — Legal QA (Grounded)
Answers a legal question using documents in the workspace. Strict grounding: returns "Insufficient information" if no reliable source found.
```json
Request:
{
  "question": "string",
  "document_ids": [int]?,
  "top_k": 8?,
  "conversation_history": [{"role": "string", "content": "string"}]?
}

Response:
{
  "answer": "string",
  "sources": [
    {
      "source_file": "string",
      "document_id": int|null,
      "page_no": int|null,
      "heading_path": ["string"],
      "formatted": "string",
      "content_preview": "string",
      "score": float
    }
  ],
  "grounded": bool,
  "confidence": float
}
```

### `POST /legal/live-search/{workspace_id}` — Trusted Web Search
Searches trusted Vietnamese legal websites (thuvienphapluat.vn, vbpl.vn, chinhphu.vn, luatvietnam.vn) via Tavily.
```json
Request:
{
  "query": "string",
  "max_results": 5?,
  "include_domains": ["string"]?
}

Response:
{
  "results": [
    {
      "title": "string",
      "url": "string",
      "content": "string",
      "score": float,
      "published_date": "string|null"
    }
  ],
  "synthesized_answer": "string",
  "query_used": "string"
}
```

### `POST /legal/analyze-risk/{workspace_id}` — Contract Risk Analysis ⭐
The most important endpoint. Performs clause-by-clause risk analysis on an indexed document.
```json
Request:
{
  "document_id": int,
  "party_perspective": "party_a | party_b | neutral"?,
  "focus_areas": ["payment", "termination", "liability", "ip", "confidentiality"]?
}

Response:
{
  "document_id": int,
  "document_name": "string",
  "overall_risk_score": "CRITICAL | HIGH | MEDIUM | LOW",
  "summary": "string",
  "risk_items": [
    {
      "id": "string",
      "clause_reference": "string",
      "original_text": "string",
      "risk_type": "MISSING_CLAUSE | UNFAVORABLE_TERM | AMBIGUITY | NON_COMPLIANT | IMBALANCED",
      "severity": "CRITICAL | MEDIUM | LOW",
      "title": "string",
      "explanation": "string",
      "legal_basis": "string",
      "suggested_redline": "string|null",
      "affected_party": "string"
    }
  ],
  "missing_standard_clauses": ["string"],
  "extracted_fields": {
    "parties": [{"name": "string", "role": "string"}],
    "contract_value": "string|null",
    "effective_date": "string|null",
    "termination_date": "string|null",
    "governing_law": "string|null",
    "payment_terms": "string|null"
  }
}
```

### `POST /legal/check-validity/{workspace_id}` — Legal Document Validity
Checks whether a legal document (law, decree, circular) is still in effect.
```json
Request:  { "document_id": int?, "query": "string?" }
Response: { "is_valid": bool, "status": "active|expired|amended|replaced", "explanation": "string", "replaced_by": "string|null", "effective_date": "string", "expiry_date": "string|null" }
```

### `POST /legal/compare-clauses/{workspace_id}` — Clause Comparison
Compares two clause texts and identifies differences, risks, and recommendations.
```json
Request:
{
  "clause_a": "string",
  "clause_b": "string",
  "context": "string?"
}
Response:
{
  "differences": ["string"],
  "risks_in_a": ["string"],
  "risks_in_b": ["string"],
  "recommendation": "string",
  "preferred_clause": "a | b | neither"
}
```

### `POST /legal/missing-clauses/{workspace_id}` — Missing Clause Detection
Identifies standard clauses that are absent from a contract.
```json
Request:  { "document_id": int, "contract_type": "service | sale | lease | nda | employment"? }
Response: { "missing_clauses": [{ "clause_type": "string", "importance": "required|recommended", "description": "string", "suggested_text": "string" }] }
```

### `POST /legal/obligations/{workspace_id}` — Obligation Summary
Extracts and summarizes obligations for each party.
```json
Request:  { "document_id": int, "party_name": "string?" }
Response: { "obligations_by_party": { "party_name": [{ "obligation": "string", "deadline": "string|null", "penalty": "string|null", "clause_ref": "string" }] } }
```

---

## Chat Streaming

### `POST /chat/{workspace_id}/stream` — SSE Streaming Chat
Server-Sent Events endpoint. The body is sent as a query parameter or in the request body depending on configuration.

```json
Request:
{
  "message": "string",
  "conversation_id": int|null,
  "history": [{"role": "user|assistant", "content": "string"}],
  "enable_thinking": bool,
  "assistant_mode": "ask | agent | legal",
  "document_ids": [int]|null,
  "force_search": bool
}
```

SSE Event types (each line: `data: <JSON>\n\n`):
```
status:         { "step": "string", "detail": "string" }
thinking:       { "text": "string" }
sources:        { "sources": [ChatSourceChunk] }
images:         { "image_refs": [ChatImageRef] }
token:          { "text": "string" }
token_rollback: {}
complete:       { "answer": "string", "sources": [...], "message_id": "string", "agent_steps": [...] }
error:          { "message": "string" }
```

---

## Conversations

### `GET /conversations/{workspace_id}` — List conversations for workspace
### `POST /conversations/{workspace_id}` — Create conversation
```json
Request:  { "title": "string?" }
Response: { "id": int, "title": "string", "created_at": "ISO8601" }
```
### `GET /conversations/{workspace_id}/{conversation_id}/messages` — Chat history
### `PATCH /conversations/{workspace_id}/{conversation_id}` — Update title
### `DELETE /conversations/{workspace_id}/{conversation_id}`

---

## Error Format

All errors follow FastAPI's standard format:
```json
{
  "detail": "string | [{loc: [...], msg: string, type: string}]"
}
```

Common HTTP codes:
- `400` — Bad request (invalid input)
- `401` — Not authenticated
- `403` — Forbidden (wrong user for resource)
- `404` — Resource not found
- `422` — Validation error (Pydantic)
- `500` — Internal server error (check server logs)

---

## The LexGuardian Command Contract (Proposed)

For LexGuardian's Command Center, the ideal API is a **unified intent endpoint** that the frontend calls for any user input, and the backend routes appropriately:

### `POST /legal/command/{workspace_id}` *(to be built)*
```json
Request:
{
  "input": "string",          // the user's raw text or intent
  "document_id": int|null,    // if a document is attached/focused
  "conversation_id": int|null
}

Response (streamed SSE):
{
  "intent_detected": "ASK | ANALYZE | EXPLORE | SEARCH",
  "routing_explanation": "string",
  // then standard SSE events per intent type...
}
```

This collapses `route-intent` + `query` + `live-search` into a single call, removing frontend orchestration logic. The backend's `IntentRouter` makes all routing decisions.
