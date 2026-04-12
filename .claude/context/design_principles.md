# Design Principles

Six principles that govern every UX and UI decision in LexGuardian. When in doubt, return to these.

---

## 1. Trust via Proof

**The principle:** Legal professionals do not trust AI blindly. Every AI statement must have a clickable link to a source document. No source, no statement.

**In practice:**
- Every factual claim in an answer is followed by a citation chip: `[Doc A, p.12]`
- Citations are clickable. One click. Zero friction. The source opens at the exact location.
- If the system cannot ground an answer, it says "I couldn't find reliable information on this" — never a confident but unsourced assertion.
- Risk analysis items always include `original_text` (the exact clause) alongside the AI's interpretation.

**Anti-patterns to avoid:**
- Answers that end with "based on general legal principles..." with no document reference
- Sources listed at the bottom of a long answer that the user has to scroll to
- Grayed-out citation chips that don't open anything

---

## 2. No Dead Ends

**The principle:** If the system cannot help, it must say so clearly and propose a concrete next step.

**In practice:**
- When retrieval fails: "I couldn't find relevant information. Would you like me to search trusted legal websites?"
- When a document is corrupted: specific error message + specific fix suggestion ("Try converting to PDF first")
- When a question is ambiguous: ask one targeted clarifying question, not a list
- When a law has been repealed: tell the user what replaced it and offer to analyze the replacement

**Anti-patterns to avoid:**
- Blank screens after failed operations
- Generic "An error occurred" messages
- Successful-seeming responses that contain no usable information

---

## 3. Hide the Machine

**The principle:** The AI pipeline is invisible. Users interact with outcomes, not infrastructure.

**In practice:**
- No chunk counts, vector dimensions, or model names in the UI
- No parsing progress bars with technical step names ("Docling extracting...", "Embedding batch 3/12...")
- Document processing shows a single progress indicator: "Preparing your document..." → "Ready"
- The Knowledge Graph is hidden by default. It is a power-user tool accessible via explicit "Explore" action, not a default panel.
- Query modes (hybrid, vector, BM25) are never exposed to the user. The system picks the right one.

**Anti-patterns to avoid:**
- Displaying the RAG mode selector in the chat interface
- Showing indexing statistics anywhere in the primary flow
- Loading states that reveal implementation details

---

## 4. Intent First, Not Feature First

**The principle:** The UI is organized around what users want to accomplish, not what the system can do.

**In practice:**
- The entry point is a Command Bar that accepts any input — text, questions, files — and the system figures out the right flow. Users don't choose "mode" before they know what they want.
- Navigation labels are user-intent language: "My Briefs" (not "Workspaces"), "Review Contract" (not "Run Analysis"), "Ask the Law" (not "Semantic Search")
- Primary actions are verbs that describe the outcome: "Analyze Risks", "Ask a Question", "Explore Relationships"

**Anti-patterns to avoid:**
- Navigation that reflects backend architecture ("RAG Retrieval", "KG Query", "Vector Store")
- Requiring users to configure before getting value
- Feature menus instead of user-goal menus

---

## 5. Tonal Architecture over Borders

**The principle:** Visual hierarchy is created through background color shifts and typography — not lines, boxes, or borders.

**In practice:**
- The page background is `bg-surface-lowest` (near-white)
- Content panels sit on `bg-surface-low`
- Elevated UI elements (modals, floating panels) use `bg-surface-mid`
- Borders are used only for interactive states (focus ring, selected state, active input)
- Separators between sections use a background color change, not a horizontal rule

**Anti-patterns to avoid:**
- Thick dividing lines between content zones
- Card grids with heavy borders for every item
- Multiple border colors creating visual noise

---

## 6. Quiet Authority

**The principle:** The interface must feel authoritative and precise without being cold or intimidating. It should feel like a professional legal workspace, not a developer tool.

**In practice:**
- Serif font (Newsreader or similar) for AI-generated legal text — this is the most important typographic choice. It makes answers feel like considered legal opinions, not chatbot output.
- Sans-serif for all navigation, labels, and UI chrome
- Reserved use of color — only for risk severity and primary actions. The majority of the interface is black text on white/light-grey.
- Animations are minimal and purposeful: the Source Viewer slides in (not fades), indicating spatial relationship with the content
- Tone of AI responses: formal but clear, never casual, never apologetic

**Anti-patterns to avoid:**
- Bright, saturated color palettes
- Emoji or casual language in AI responses
- Excessive animation or transition effects
- UI that looks like a developer dashboard

---

## The UX Litmus Test

Before shipping any UI change, ask:

1. **Can a first-time user express their intent within 10 seconds of landing?** If not, simplify the entry point.
2. **Can a user verify any AI claim without leaving the current view?** If not, the citation is broken.
3. **Does this UI expose how the AI works, or what it can do for the user?** If the former, hide the machine.
4. **Would this feel appropriate in a printed legal brief?** If not, reconsider the typography, density, or tone.
5. **What does the user do if this fails?** If there's no clear next step, add one.
