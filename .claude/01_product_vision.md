# 01 — Product Vision

## What We're Building

LexGuardian is an **AI Legal Copilot** — not a document search tool, not a RAG sandbox, not an enterprise knowledge base. It is a professional workspace where lawyers, contract managers, and business teams express legal intent and receive grounded, citeable answers.

The user experience is closer to talking to a brilliant junior lawyer who has read every document, remembers every clause, and always shows their work — than to using a search engine.

---

## The Core Value Proposition

> "Analyze contracts, search the law, and verify answers with instant, pin-point citations — all in a beautifully clean workspace."

The three words that matter: **Analyze. Search. Verify.**

---

## The Three Primary Use Cases

These are not features. They are user intents that the system must detect and serve.

### 1. Ask (Legal Q&A)
The user has a legal question. It may be about an uploaded contract, a Vietnamese regulation, or a general legal principle. The system finds the answer, grounds it in source documents or live legal databases, and presents it with clickable citations that open the exact source location.

**Example user input:** "When does the Land Law 2013 expire and what replaced it?"
**Expected system behavior:** Route to `LIVE_SEARCH` intent → retrieve from trusted legal sources (thuvienphapluat.vn, vbpl.vn) → answer with inline citation → right panel opens the source document to the exact clause.

### 2. Analyze (Contract Review)
The user uploads a contract. The system parses it, understands the clauses, identifies risks (missing protections, unfavorable terms, ambiguous language), and presents a structured risk report with severity levels, the AI's legal basis, and suggested redlines.

**Example user input:** Drop a PDF on the home screen → click "Analyze Risks"
**Expected system behavior:** `POST /legal/analyze-risk/{workspace_id}` → stream a structured `ContractRiskReport` with `RiskItem[]` grouped by severity → render as color-coded risk view with inline clause comparison.

### 3. Explore (Legal Research)
The user needs to go deeper — trace entity relationships across cases, understand what laws govern a specific obligation, or map the history of a regulation. This is the Knowledge Graph mode, hidden by default, accessed only when the user consciously requests deeper investigation.

**Example user input:** Click "Inspect" button on an entity in an answer → graph view opens
**Expected system behavior:** KG query for entity relationships → dark-mode interactive graph → clickable nodes that re-route to Q&A for any node.

---

## What Has Changed from NexusRAG

NexusRAG was a **developer tool** masquerading as a legal product. It surfaced the RAG pipeline mechanics (parsing status, chunk counts, vector dimensions, query mode selectors) in the main UI. This was valuable for building and debugging but confusing and trust-eroding for real users.

LexGuardian hides all of that and is organized around **what users want to accomplish**, not around what the system does internally.

| NexusRAG | LexGuardian |
|---|---|
| Workspaces (technical silos) | Matters / Briefs (professional containers) |
| 3-column layout (Data / Chat / Visual) | Intent-driven Command Center |
| Exposed query mode selector (hybrid / vector) | Invisible routing, one smart input |
| Parsing stats visible in the UI | Background processing, no visible logs |
| Knowledge Graph as a default panel | KG hidden, accessed via "Explore" action |
| Generic chat interface | Mode-specific views (Ask / Analyze / Explore) |
| Document checkboxes for selection | Conversational @mention for documents |

---

## What We Are NOT Building

- Not a general-purpose chatbot. LexGuardian is specialized for legal work.
- Not a document management system. That is a secondary tab, not the product.
- Not an enterprise search engine. We surface answers, not document lists.
- Not an AI writing assistant. We analyze and explain; we do not draft (yet).

---

## The Product Positioning

**For:** Lawyers, contract managers, compliance teams, and business professionals in Vietnam (initially) who work with legal documents.

**Against:** Manually reading contracts, asking colleagues, using generic Google searches for legal answers.

**Unique advantage:** Every answer is grounded in exact source locations with one-click verification. This creates trust that generic AI chatbots cannot.

---

## The Future Vision

LexGuardian scales from an individual tool to a **firm-wide legal operating system**:

- **Phase 1 (Now):** Individual copilot — contract review, legal Q&A, citation verification.
- **Phase 2:** Cross-matter intelligence — LexGuardian remembers risk decisions from past contracts and applies them to new ones.
- **Phase 3:** Proactive drafting — generate first-draft clauses based on user's risk profile and past accepted redlines.
- **Phase 4:** Collaborative platform — multiple lawyers, shared briefs, tracked revisions, audit trail.

Every technical decision today must support this trajectory. Do not build dead-ends.
