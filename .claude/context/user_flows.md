# User Flows

The five core user journeys in LexGuardian. Each flow has a clear trigger, a sequence of system states, and a defined success condition.

---

## Flow 1: New Contract Review (Analyze)

**Trigger:** User has a contract they need to review before signing or sending to counterparty.  
**Success:** User can see every risk, understand the legal basis, and export redlines or share findings.

```
1. User lands on Command Center (Home page)

2. User drags and drops contract PDF onto the command bar
   → System detects file upload
   → System asks: "I see you uploaded an agreement.
     What would you like to do?"
     [Analyze Risks] [Summarize Obligations] [Extract Key Terms]

3. User clicks "Analyze Risks"
   → Brief "Analyzing contract..." loading state (no technical logs)
   → Background: POST /documents/upload → ingestion → POST /legal/analyze-risk

4. Risk Analysis View appears:
   ┌─────────────────────────────────────────────┐
   │ RISK SCORECARD                              │
   │ 🔴 2 Critical  🟡 4 Medium  🔵 1 Low        │
   ├─────────────────────────────────────────────┤
   │ [CRITICAL] Termination for Convenience      │
   │ Counterparty can terminate with 7 days      │
   │ notice. Standard minimum is 30 days.        │
   │ Original: "...7 ngày làm việc..."            │
   │ Suggestion: Change to 30 ngày làm việc      │
   │ [View Clause] [Accept Redline]              │
   ├─────────────────────────────────────────────┤
   │ [MEDIUM] Ambiguous IP Ownership...          │
   └─────────────────────────────────────────────┘

5. User clicks "View Clause" on a risk item
   → Right panel slides open to the document at the exact clause location
   → Clause is highlighted in the document
   → Left panel shows AI explanation and legal basis

6. User clicks "Accept Redline"
   → Clause suggestion saved to a redline export
   → (Future: download as marked-up DOCX)
```

**Backend calls in this flow:**
1. `POST /documents/upload/{workspace_id}`
2. Poll `GET /documents/workspace/{workspace_id}` until status = indexed
3. `POST /legal/analyze-risk/{workspace_id}` with `{document_id: N}`

---

## Flow 2: Legal Question Answering (Ask)

**Trigger:** User has a specific legal question, either about an uploaded document or about the law in general.  
**Success:** User receives a grounded answer with clickable sources they can verify.

```
1. User is on Command Center or in an active Brief
   → Types: "When does the Land Law 2013 expire and what replaced it?"

2. System detects intent: LIVE_SEARCH (no document needed, asks about legislation)
   → Brief "Searching legal databases..." status
   → Background: POST /legal/route-intent → POST /legal/live-search

3. Answer appears in the conversation thread:
   ┌──────────────────────────────────────────────┐
   │ The 2013 Land Law (Law No. 45/2013/QH13)     │
   │ expired on December 31, 2024, replaced by    │
   │ the 2024 Land Law (Law No. 31/2024/QH15)     │
   │ effective January 1, 2025. [thuvienphapluat] │
   └──────────────────────────────────────────────┘

4. User clicks [thuvienphapluat] citation chip
   → Right panel opens with the source document
   → The relevant paragraph is highlighted

5. User asks a follow-up: "What are the key changes?"
   → System maintains conversation context
   → New answer streams with citations from the same source(s)
```

**Backend calls in this flow:**
1. `POST /legal/route-intent/{workspace_id}` — classify intent
2. `POST /legal/live-search/{workspace_id}` OR `POST /legal/query/{workspace_id}` depending on intent
3. (Optional) `GET /documents/{doc_id}` to open source in viewer

---

## Flow 3: Document Q&A (Ask with Uploaded Document)

**Trigger:** User wants to ask specific questions about an already-uploaded contract or policy document.  
**Success:** User receives grounded answers from the specific document, with exact page references.

```
1. User opens a Brief that has indexed documents
   → Types: "What are our payment obligations under the service agreement?"
   → (Optional) Mentions: "@Vendor_Agreement.pdf when is payment due?"

2. System detects: CONTRACT_QUERY intent, searches the specific document
   → Retrieves relevant clauses from pgvector
   → Reranks, generates grounded answer

3. Answer appears with inline citations:
   "Payment is due within 30 days of invoice, per Clause 5.2.
   A late fee of 0.5% per month applies after that. [Vendor_Agreement.pdf, p.8]"

4. User clicks the citation
   → Source Viewer opens to page 8, Clause 5.2 highlighted
```

**Backend calls in this flow:**
1. `POST /chat/{workspace_id}/stream` with `assistant_mode: "legal"` and `document_ids: [N]`

---

## Flow 4: Validity Check (Ask about Law Status)

**Trigger:** User has referenced a law or regulation and wants to know if it's still in effect.  
**Success:** Clear yes/no answer with the current status, replacement (if any), and source.

```
1. User types: "Is Circular 39/2014/TT-NHNN still valid?"

2. System detects: VALIDITY_CHECK intent
   → POST /legal/check-validity/{workspace_id} {query: "Circular 39/2014/TT-NHNN"}

3. Response:
   "Circular 39/2014/TT-NHNN was REPLACED by Circular 06/2023/TT-NHNN,
   effective from September 1, 2023. The 2014 circular is no longer in force.
   [Source: vbpl.vn]"

4. System offers: "Would you like me to summarize the key changes in the
   2023 replacement?"
```

---

## Flow 5: Deep Research (Explore — Advanced)

**Trigger:** User wants to understand the legal relationships between entities across documents and laws — e.g., how a specific company's regulatory history looks, or which laws govern overlapping obligations.  
**Success:** User has a visual map of entity relationships they can navigate and drill into.

```
1. User receives an answer mentioning "Decree 10/2021/ND-CP"
   → Clicks "Explore" or "Inspect" action button next to the entity

2. System transitions to Explore (Knowledge Graph) view:
   → Dark-mode graph visualization
   → Node: "Decree 10/2021/ND-CP" at center
   → Connected to: "Ministry of Finance", "Tax obligations", "Article 15"
   → Lines show relationship type: governs, amends, supersedes, references

3. User clicks the "Ministry of Finance" node
   → Side panel: shows all documents and laws issued by this entity

4. User clicks "Ask about this" on a relationship
   → Returns to Ask flow with the entity pre-filled in context
```

---

## Flow Transitions

Users can move between flows without losing context:

- **Analyze → Ask:** From a risk item, ask "Why is this standard in contracts?"
- **Ask → Analyze:** From an answer, "Analyze this specific clause I found"
- **Ask → Explore:** From an entity in an answer, click "Explore relationships"
- **Explore → Ask:** From a graph node, "Ask about this"

The system always preserves the current Brief (workspace) context across flow transitions.

---

## Error Handling Flows

### Document Ingestion Failure
```
Upload → Parsing fails (unsupported file, corrupted PDF)
→ Status shows "Failed to process"
→ Error message: specific reason (not a generic error)
→ Suggestion: "Try converting to PDF first" or "Check if file is encrypted"
→ Option to re-upload
```

### No Relevant Information Found
```
User asks question → Retrieval finds nothing relevant
→ System does NOT hallucinate an answer
→ Response: "I couldn't find relevant information in your Brief.
  Would you like me to search trusted legal websites instead?"
→ [Yes, search the web] [Rephrase my question]
```

### Live Search Unavailable (no Tavily key)
```
User asks about legislation → System cannot perform live search
→ Response: "Live legal search is not available.
  I can only answer from documents in your Brief."
→ If Brief has relevant docs: answers from those
→ If not: honest "insufficient information"
```
