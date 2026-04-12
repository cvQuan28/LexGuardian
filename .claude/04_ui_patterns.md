# 04 — UI Patterns & Frontend Standards

## Design Philosophy

LexGuardian's UI is built on one principle: **Quiet Authority**. The interface must feel like a finalized, printed legal brief — precise, trustworthy, and uncluttered. It earns trust through visual restraint, not visual complexity.

Key design language references (from `frontend/UI_Example/lexguardian_elite/DESIGN.md`):
- Serif font for legal answer text (Newsreader or similar) — adds gravitas
- Sans-serif for UI chrome and navigation
- Ambient depth through background color shifts, not borders
- Color palette: white/light-grey surfaces, one accent color (primary), semantic colors for risk levels

---

## Layout Architecture

### The Three Canvas States

LexGuardian's main workspace has three visual states, not a static grid layout:

**State 1: Command Center (Entry)**
- Centered input bar, full width, minimal chrome
- Recent items below the bar
- No sidebars, no panels, no complexity

**State 2: Answer View (Ask Flow)**
- 60% left: conversation thread
- 40% right: Source Viewer (slides in when citation clicked)
- Source Viewer shows exact document page/paragraph highlighted

**State 3: Risk Analysis View (Analyze Flow)**
- Full-width structured report
- Risk items color-coded by severity: Critical (red), Medium (amber), Low (blue)
- Clicking a risk item opens the clause in the right Source Viewer
- Side panel: detailed explanation + suggested redline

**Never:** Show all three panels simultaneously. Progressive disclosure — only what the user needs, when they need it.

---

## Component Hierarchy

```
App
├── AppShell                    # Sidebar + TopBar wrapper
│   ├── Sidebar                 # Navigation (collapsed/expanded responsive)
│   └── TopBar                  # Workspace name, user menu
└── Pages
    ├── HomeCommandCenter       # NEW: the unified entry point
    ├── AskPage                 # Chat + Source Viewer layout
    ├── AnalyzePage             # Risk report view
    ├── ExplorePage             # Knowledge graph (secondary)
    └── LibraryPage             # Document management (formerly KnowledgeBasesPage)
```

---

## Component Conventions

### Naming
- Pages: `PascalCase` ending in `Page` (e.g., `AskPage.tsx`)
- Components: `PascalCase` (e.g., `CitationChip.tsx`)
- Hooks: `camelCase` starting with `use` (e.g., `useLegalStream.ts`)
- Stores: `camelCase` ending in `Store` (e.g., `workspaceStore.ts`)
- Types: `PascalCase` in `src/types/index.ts`

### File Structure
```
src/
├── components/
│   ├── command/        # Command Center components
│   ├── ask/            # Ask flow components
│   ├── analyze/        # Risk analysis components
│   ├── explore/        # Graph exploration components
│   ├── shared/         # Shared: CitationChip, SourceViewer, DocumentCard
│   ├── layout/         # AppShell, Sidebar, TopBar
│   └── ui/             # Primitive: Button, Input, Card (shadcn-based)
├── pages/              # Route-level components
├── hooks/              # All data and stream hooks
├── stores/             # Zustand stores (UI state only)
├── lib/                # api.ts, utils.ts
└── types/              # index.ts — all TypeScript types
```

### The Rule of One Responsibility
Each component does one thing. A component that renders a list does not also fetch data. A component that shows a loading state does not also manage the request.

Data flows down via props. Events flow up via callbacks. Server state lives in TanStack Query. UI state lives in Zustand.

---

## Key Reusable Components

### `CitationChip`
Renders an inline citation like `[Doc A, p.12]`. Clickable — opens Source Viewer at that location.
```tsx
<CitationChip
  citation={{ source_file: "...", document_id: 1, page_no: 12, formatted: "Doc A, p.12" }}
  onOpen={(citation) => openSourceViewer(citation)}
/>
```

### `SourceViewer`
The right-panel document viewer. Opens from a citation or a risk item. Shows the document with the cited passage highlighted. Supports page navigation.
```tsx
<SourceViewer
  document={selectedDoc}
  scrollToPage={scrollToPage}
  scrollToHeading={scrollToHeading}
  onClose={() => closeViewer()}
/>
```

### `RiskBadge`
Severity indicator. Use only the four defined severity levels.
```tsx
<RiskBadge severity="CRITICAL" />   // red
<RiskBadge severity="MEDIUM" />     // amber
<RiskBadge severity="LOW" />        // blue
<RiskBadge severity="INFO" />       // grey
```

### `StreamingAnswer`
Renders a streaming LLM response. Uses `StreamingMarkdown` (already built in NexusRAG) for efficient token-by-token rendering with rAF batching.
```tsx
<StreamingAnswer
  content={streamingContent}
  isStreaming={isStreaming}
  sources={pendingSources}
  onCitationClick={(citation) => openSourceViewer(citation)}
/>
```

### `CommandBar`
The central input on the home screen. Handles text, drag-and-drop files, @mention documents. Single point of user intent expression.
```tsx
<CommandBar
  placeholder="Ask LexGuardian anything or drop a contract here..."
  onSubmit={(text, attachedFiles) => handleCommand(text, attachedFiles)}
  suggestions={["Review NDA", "Search SEC statutes", "What does Clause 5 mean?"]}
/>
```

---

## Styling Conventions

### Tailwind Usage
Use only Tailwind utility classes. No custom CSS unless absolutely necessary. All custom design tokens are defined as Tailwind config extensions (colors, border-radius, shadows).

### Color Semantic Tokens
Never use raw color values. Always use semantic tokens:
```
bg-surface-lowest     // page background (near-white)
bg-surface-low        // card/panel background
bg-surface-mid        // elevated surfaces
bg-primary            // primary action color
text-foreground       // primary text
text-muted-foreground // secondary/helper text
border-subtle         // light borders (use sparingly)
```

### Risk Severity Colors
```
risk-critical: text-red-700 bg-red-50 border-red-200
risk-medium:   text-amber-700 bg-amber-50 border-amber-200
risk-low:      text-blue-700 bg-blue-50 border-blue-200
risk-info:     text-gray-600 bg-gray-50 border-gray-200
```

### Typography
- Legal answer text: `font-serif text-base leading-7` (Newsreader)
- UI labels: `font-sans text-sm`
- Headings: `font-sans font-semibold`
- Code/clause text: `font-mono text-sm`

---

## State Patterns

### Loading States
Every async operation shows a skeleton, never a spinner alone. Skeletons match the shape of the content they replace.

```tsx
// Good: content-aware skeleton
{isLoading ? <RiskReportSkeleton /> : <RiskReport data={report} />}

// Bad: generic spinner
{isLoading ? <Loader2 className="animate-spin" /> : <RiskReport data={report} />}
```

### Error States
Errors are shown inline near the failed action, not in a global toast only. The toast is supplementary.

```tsx
// Good: inline error with action
{error && (
  <ErrorMessage
    message={error.message}
    action={{ label: "Try again", onClick: retry }}
  />
)}
```

### Empty States
Empty states must suggest a next action. Never show a blank screen.
```tsx
// Home with no briefs
<EmptyState
  icon={<Scale />}
  title="Your briefs will appear here"
  description="Create a new brief or drop a contract to get started."
  action={{ label: "Create Brief", onClick: handleCreateBrief }}
/>
```

---

## Streaming Pattern

All streaming hooks follow this interface:
```typescript
interface StreamHookResult {
  status: "idle" | "streaming" | "complete" | "error";
  streamingContent: string;
  pendingSources: Source[];
  agentSteps: AgentStep[];
  isStreaming: boolean;
  error: string | null;
  send: (input: StreamInput) => Promise<Result | null>;
  cancel: () => void;
  reset: () => void;
}
```

The hook manages the `AbortController`, rAF token buffering, and SSE event parsing. Components only see the derived state.

---

## Accessibility

- All interactive elements have `aria-label` when the label is icon-only
- All modal dialogs use `role="dialog"` with focus trap
- Color is never the only indicator of meaning (always pair color with icon or text for risk levels)
- Keyboard navigation supported on all primary flows (Tab, Enter, Escape)

---

## What NOT to Do

- Do not show technical internals in the UI (chunk counts, vector dimensions, model names, parsing logs)
- Do not build feature-first UI components. Build around user intent.
- Do not use more than 2 type sizes on one screen
- Do not use heavy borders as visual separators — use background color shifts instead
- Do not use `localStorage` for application data — that is the API's job
- Do not add a loading state that lasts more than 100ms without showing skeleton UI
