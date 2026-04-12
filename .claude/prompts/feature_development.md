# Feature Development Template

Copy this template when starting work on a new LexGuardian feature. Fill in each section before writing code.

---

## Feature Brief

**Feature name:** [e.g., Obligation Summary View]  
**Requested by / referenced in:** [product_vision.md §3, user_flows.md Flow 2]  
**Which user persona does this serve?** [Linh / Minh / Hoa / all]  
**Which user intent does this serve?** [Ask / Analyze / Explore / Library]

---

## Problem Statement

What specific problem does this feature solve? Write from the user's perspective.

> Example: "When Linh uploads a service agreement, she needs to quickly identify all payment obligations without reading the entire 40-page document. Currently, she has to read the full text and manually extract each obligation clause."

---

## Success Criteria

How will we know this feature is working correctly?

- [ ] The user can trigger this feature within [N] clicks from the Command Center
- [ ] The output shows a source citation for every obligation listed
- [ ] If no obligations are found, the system says so clearly and suggests a next step
- [ ] The feature works on contracts written in Vietnamese and English
- [ ] Response time is under [N] seconds

---

## User Flow

Map the exact steps a user takes. Reference `context/user_flows.md` for format.

```
1. User is on [page/state]
2. User does [action]
3. System does [response/transition]
4. User sees [output]
5. User can do [next action]
```

---

## API Contract

What endpoint(s) does this feature require?

**If using an existing endpoint:** specify which one and confirm the request/response schema matches your UI needs. See `03_api_contracts.md`.

**If a new endpoint is needed:**
```
Method: POST
Path: /legal/[new-endpoint]/{workspace_id}
Request:
{
  "field_name": "type"
}
Response:
{
  "field_name": "type"
}
```

---

## UI Specification

**Layout:** Which canvas state does this feature live in? (Command Center / Answer View / Risk Analysis View / New)

**Components needed:**
- [ ] New component: `[ComponentName].tsx` — [what it renders]
- [ ] Existing component: `[ComponentName].tsx` — [what changes]

**States this component must handle:**
- `loading` — [what to show]
- `empty` — [what to show, what action to offer]
- `populated` — [what to show]
- `error` — [what to show, what action to offer]

**Does this feature need a new Zustand store state?** [yes/no, if yes specify what]

---

## Backend Implementation Plan

Which service handles the logic?

- [ ] Existing service: `app/services/legal/[service].py` — [what to add/change]
- [ ] New service: `app/services/legal/[new_service].py` — [what it does]

**LLM usage:**
- Does this require an LLM call? [yes/no]
- Which model? (default: `settings.LLM_MODEL_FAST`, or `settings.LEGAL_RISK_ANALYSIS_MODEL` for complex analysis)
- Approximate token usage per call: [estimate]

**Database changes:**
- Does this require a new table? [yes/no, if yes define schema]
- Does this require a new column? [yes/no, specify table + column]

---

## Testing Plan

**Backend tests to write:**
- [ ] `tests/api/test_[feature].py` — API contract test
- [ ] `tests/services/test_[service].py` — Service logic test

**Frontend tests to write:**
- [ ] `src/__tests__/components/[Component].test.tsx`

**Manual testing checklist:**
- [ ] Happy path with a real contract
- [ ] Empty state (document with no relevant content)
- [ ] Error state (service unavailable)
- [ ] Performance: does it complete in reasonable time on a 50-page document?

---

## Out of Scope

Explicitly list what this feature does NOT include (prevents scope creep):

- Does not include [X]
- Does not modify [Y]
- Will be addressed in follow-up: [Z]

---

## Checklist Before Opening PR

- [ ] All success criteria met
- [ ] New types added to `src/types/index.ts`
- [ ] New API endpoint documented in `03_api_contracts.md`
- [ ] Tests written and passing
- [ ] `pnpm type-check` passes
- [ ] No technical internals exposed in the UI (see design principles)
- [ ] Every AI output in this feature has a citation mechanism
