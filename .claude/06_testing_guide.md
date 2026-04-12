# 06 — Testing Guide

## Testing Philosophy

LexGuardian's testing strategy prioritizes **contract tests** over unit tests and **integration tests** over both. The most important things to test are the boundaries: API contracts, LLM output grounding, and citation accuracy. Internal implementation details (how a service computes a score) matter less than whether the end result is correct and trustworthy.

> **Rule:** If a bug would cause a user to receive a legal answer without a citation, or an incorrect risk assessment, it must be caught by an automated test.

---

## Test Structure

```
backend/
└── tests/
    ├── conftest.py              # Shared fixtures: test DB, mock LLM, test client
    ├── api/
    │   ├── test_auth.py         # Auth endpoint contracts
    │   ├── test_workspaces.py   # Workspace CRUD
    │   ├── test_documents.py    # Upload, status, delete
    │   └── test_legal.py        # Legal AI endpoint contracts ⭐
    ├── services/
    │   ├── test_legal_router.py # Intent classification accuracy
    │   ├── test_risk_analysis.py # Risk report correctness
    │   ├── test_retriever.py    # Retrieval quality
    │   └── test_chunker.py     # Clause boundary preservation
    └── integration/
        └── test_ingestion_pipeline.py  # End-to-end document ingestion

frontend/
└── src/
    └── __tests__/
        ├── hooks/
        │   └── useRAGChatStream.test.ts
        └── components/
            ├── CitationChip.test.tsx
            └── RiskBadge.test.tsx
```

---

## Backend Testing

### Running Tests
```bash
cd backend
pytest tests/ -v                          # all tests
pytest tests/api/test_legal.py -v        # specific file
pytest tests/ -k "risk" -v               # tests matching keyword
pytest tests/ --cov=app --cov-report=html  # with coverage
```

### Core Fixtures (`conftest.py`)

```python
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from app.main import app
from app.core.database import engine, Base, AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User
from app.models.knowledge_base import KnowledgeBase

@pytest_asyncio.fixture(scope="function")
async def db():
    """Creates a fresh test database for each test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest_asyncio.fixture
async def client(db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

@pytest_asyncio.fixture
async def auth_headers(client):
    """Returns auth headers for a test user."""
    await client.post("/api/v1/auth/register", json={
        "email": "test@lex.vn",
        "password": "testpass123",
        "display_name": "Test User"
    })
    res = await client.post("/api/v1/auth/login", json={
        "email": "test@lex.vn", "password": "testpass123"
    })
    token = res.json()["token"]
    return {"Authorization": f"Bearer {token}"}

@pytest_asyncio.fixture
async def workspace(client, auth_headers):
    res = await client.post("/api/v1/workspaces",
        headers=auth_headers,
        json={"name": "Test Brief"}
    )
    return res.json()

@pytest.fixture
def mock_llm():
    """Mocks the LLM provider to avoid real API calls."""
    with patch("app.services.llm.get_llm_provider") as mock:
        provider = AsyncMock()
        provider.chat.return_value = "Mocked LLM response"
        provider.stream.return_value = async_generator(["token1", "token2"])
        mock.return_value = provider
        yield provider
```

### Testing API Contracts

```python
# tests/api/test_legal.py
import pytest
from httpx import AsyncClient

async def test_analyze_risk_returns_correct_schema(client, auth_headers, workspace, mock_llm):
    """The risk analysis response must match the ContractRiskReport schema."""
    ws_id = workspace["id"]

    # Upload a test document
    with open("tests/fixtures/sample_contract.pdf", "rb") as f:
        res = await client.post(
            f"/api/v1/documents/upload/{ws_id}",
            headers=auth_headers,
            files={"file": ("contract.pdf", f, "application/pdf")}
        )
    doc_id = res.json()["id"]

    # Trigger risk analysis
    res = await client.post(
        f"/api/v1/legal/analyze-risk/{ws_id}",
        headers=auth_headers,
        json={"document_id": doc_id}
    )

    assert res.status_code == 200
    body = res.json()

    # Verify schema contract
    assert "overall_risk_score" in body
    assert body["overall_risk_score"] in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    assert "risk_items" in body
    assert isinstance(body["risk_items"], list)

    for item in body["risk_items"]:
        assert "severity" in item
        assert item["severity"] in ["CRITICAL", "MEDIUM", "LOW"]
        assert "original_text" in item
        assert "explanation" in item
        assert len(item["original_text"]) > 0  # must have source text

async def test_legal_qa_requires_grounded_answer(client, auth_headers, workspace, mock_llm):
    """Legal QA must not return an answer without at least one source."""
    ws_id = workspace["id"]
    mock_llm.chat.return_value = "The contract expires on December 31, 2024."

    res = await client.post(
        f"/api/v1/legal/query/{ws_id}",
        headers=auth_headers,
        json={"question": "When does the contract expire?"}
    )

    body = res.json()
    if body.get("grounded"):
        # If the system claims the answer is grounded, sources must exist
        assert len(body["sources"]) > 0, "Grounded answer must have sources"
    else:
        # If not grounded, the answer must indicate insufficient information
        assert "insufficient" in body["answer"].lower() or \
               "không đủ" in body["answer"].lower()
```

### Testing Intent Classification

```python
# tests/services/test_legal_router.py
import pytest
from app.services.legal.legal_router import LegalDomainRouter

router = LegalDomainRouter()

@pytest.mark.parametrize("query,expected_domain,min_confidence", [
    ("Mức phạt vi phạm điều khoản là bao nhiêu?", "legal", 0.7),
    ("Hợp đồng có giá trị bao nhiêu đồng?", "legal", 0.8),
    ("When does the force majeure clause apply?", "legal", 0.7),
    ("What's the weather like today?", "general", 0.6),
    ("Tell me a joke", "general", 0.8),
])
def test_domain_detection(query, expected_domain, min_confidence):
    result = router.detect_domain(query)
    assert result.domain == expected_domain, f"Expected {expected_domain} for: {query}"
    assert result.confidence >= min_confidence
```

### Testing the RAG Pipeline Quality

For retrieval quality, use benchmark queries with known expected sources:

```python
# tests/services/test_retriever.py
RETRIEVAL_BENCHMARK = [
    {
        "query": "Điều khoản phạt vi phạm",
        "document": "tests/fixtures/sample_contract.pdf",
        "expected_chunk_contains": "phạt vi phạm",
        "min_score": 0.6
    },
]

async def test_retrieval_returns_relevant_chunks(indexed_workspace):
    for case in RETRIEVAL_BENCHMARK:
        results = await retriever.retrieve(case["query"], workspace_id=indexed_workspace)
        assert len(results) > 0
        top = results[0]
        assert top.score >= case["min_score"]
        assert case["expected_chunk_contains"] in top.content.lower()
```

---

## Frontend Testing

### Running Tests
```bash
cd frontend
pnpm test                    # vitest watch mode
pnpm test:run                # single run
pnpm type-check              # TypeScript check
pnpm lint                    # ESLint
```

### Testing CitationChip (Component)
```tsx
// src/__tests__/components/CitationChip.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { CitationChip } from "@/components/shared/CitationChip";

describe("CitationChip", () => {
  const citation = {
    source_file: "contract.pdf",
    document_id: 1,
    page_no: 12,
    heading_path: ["Section 3", "Payment Terms"],
    formatted: "contract.pdf, p.12"
  };

  it("renders the formatted citation text", () => {
    render(<CitationChip citation={citation} onOpen={jest.fn()} />);
    expect(screen.getByText(/contract.pdf, p.12/i)).toBeInTheDocument();
  });

  it("calls onOpen when clicked", () => {
    const onOpen = jest.fn();
    render(<CitationChip citation={citation} onOpen={onOpen} />);
    fireEvent.click(screen.getByRole("button"));
    expect(onOpen).toHaveBeenCalledWith(citation);
  });
});
```

### Testing Streaming Hook (Integration)
```typescript
// src/__tests__/hooks/useRAGChatStream.test.ts
import { renderHook, act } from "@testing-library/react";
import { useRAGChatStream } from "@/hooks/useRAGChatStream";

// Mock SSE server
const mockSSEServer = () => { /* ... */ };

it("accumulates tokens from SSE stream", async () => {
  const { result } = renderHook(() => useRAGChatStream(1));

  await act(async () => {
    result.current.sendMessage("Test query", [], false, null, false, "ask");
  });

  expect(result.current.streamingContent).toContain("expected text");
  expect(result.current.pendingSources.length).toBeGreaterThan(0);
});
```

---

## Manual Testing Checklist

Before any release, manually verify these critical flows:

### Ask Flow
- [ ] Type a question → answer streams with inline citation chips
- [ ] Click a citation chip → right panel opens to correct page
- [ ] Click outside source viewer → panel closes gracefully
- [ ] Type a question with no relevant documents → system responds with "insufficient information" + suggestion

### Analyze Flow
- [ ] Drop a PDF on the command center → processing starts (no raw logs visible)
- [ ] Processing completes → risk report appears with severity-coded items
- [ ] Click a CRITICAL risk item → left panel highlights clause, right panel shows explanation
- [ ] Risk report shows missing standard clauses section

### Edge Cases
- [ ] Upload a non-PDF file → appropriate error message
- [ ] Query in English on Vietnamese legal corpus → still retrieves relevant results
- [ ] Very long contract (50+ pages) → ingestion completes without timeout
- [ ] Network disconnect mid-stream → error state shown, retry available

---

## Eval Suite (Legal Quality)

For ongoing quality measurement, maintain a fixed eval set:

```bash
# Run the eval suite against the live backend
python scripts/run_evals.py --eval-set tests/evals/legal_qa_benchmark.json

# Output: precision, recall, grounding rate, latency
```

The eval JSON format:
```json
[
  {
    "id": "eval_001",
    "question": "Mức phạt vi phạm thanh toán là bao nhiêu?",
    "document": "sample_vendor_agreement.pdf",
    "expected_contains": ["phạt", "5%", "thanh toán"],
    "must_be_grounded": true,
    "max_latency_ms": 5000
  }
]
```

**Target metrics:**
- Grounding rate (answers with source): ≥ 95%
- Retrieval precision@3: ≥ 0.80
- Risk detection recall (CRITICAL items): ≥ 0.90
- P95 response latency: ≤ 8 seconds
