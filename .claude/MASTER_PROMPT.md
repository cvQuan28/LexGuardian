# 🛡️ LexGuardian — Master Development Prompt for Claude Code

> **Dùng file này như entry point cho mỗi session Claude Code.**  
> Đọc toàn bộ file này trước khi làm bất cứ điều gì.

---

## 📌 BỐI CẢNH DỰ ÁN

Bạn là một Senior Full-Stack Engineer đang xây dựng **LexGuardian** — một AI Legal Copilot chuyên về phân tích hợp đồng, tra cứu pháp luật, và xác minh câu trả lời với trích dẫn nguồn chính xác.

### Thông tin quan trọng

| Item | Giá trị |
|---|---|
| **Dự án mới (làm việc tại đây)** | `/Users/quanai/Documents/myproject/gen_ai/LexGuardian` |
| **Nguồn tham khảo (NexusRAG)** | `/Users/quanai/Documents/myproject/gen_ai/NexusRAG` |
| **GitHub repo** | `https://github.com/cvQuan28/LexGuardian` |
| **Tài liệu kiến trúc** | `/Users/quanai/Documents/myproject/gen_ai/LexGuardian/.claude/` |

### Trước khi bắt đầu bất kỳ task nào

1. Đọc `.claude/00_READ_ME_FIRST.md` để nắm golden rules
2. Đọc `.claude/01_product_vision.md` để hiểu sản phẩm
3. Đọc file liên quan đến task (architecture, API contracts, UI patterns...)
4. Kiểm tra phase hiện tại trong file này và **CHỈ làm task của phase đó**

---

## 🗺️ TỔNG QUAN CÁC PHASE

```
Phase 0: Khởi tạo dự án & Git setup          [~2 giờ]
Phase 1: Backend Foundation                   [~1 ngày]
Phase 2: Frontend Core — Command Center & Ask [~2 ngày]
Phase 3: Frontend Analyze — Contract Risk UI  [~2 ngày]
Phase 4: Tích hợp & Polish                   [~1 ngày]
Phase 5: Testing & Production Readiness       [~1 ngày]
```

**Phase hiện tại:** Phase 0 ← Bắt đầu từ đây

---

---

# PHASE 0: Khởi Tạo Dự Án & Git Setup

## Mục tiêu
Tạo cấu trúc dự án LexGuardian sạch, khởi tạo Git với GitHub remote, và copy toàn bộ backend từ NexusRAG sang (vì backend đã production-ready và chỉ cần refactor nhỏ ở frontend).

## Tasks

### Task 0.1 — Khởi tạo cấu trúc thư mục

```bash
# Chạy từ /Users/quanai/Documents/myproject/gen_ai/LexGuardian
mkdir -p backend frontend docs scripts

# Khởi tạo Git
git init
git remote add origin https://github.com/cvQuan28/LexGuardian.git

# Tạo .gitignore
cat > .gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
dist/
*.egg
.pytest_cache/
.ruff_cache/
system.log
*.log

# Node
node_modules/
dist/
.pnpm-store/

# Environment
.env
.env.*
!.env.example

# Data & models
backend/data/
*.bin
*.safetensors

# OS
.DS_Store
Thumbs.db

# IDE
.vscode/
.idea/
EOF
```

### Task 0.2 — Copy Backend từ NexusRAG

```bash
SOURCE=/Users/quanai/Documents/myproject/gen_ai/NexusRAG
TARGET=/Users/quanai/Documents/myproject/gen_ai/LexGuardian

# Copy backend (không copy __pycache__, data, venv)
rsync -av --progress \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.venv' \
  --exclude='data/' \
  --exclude='system.log' \
  "$SOURCE/backend/" "$TARGET/backend/"

# Copy infrastructure files
cp "$SOURCE/docker-compose.yml" "$TARGET/"
cp "$SOURCE/docker-compose.services.yml" "$TARGET/"
cp "$SOURCE/Dockerfile.backend" "$TARGET/"
cp "$SOURCE/nginx.conf" "$TARGET/"
cp "$SOURCE/setup.sh" "$TARGET/"
```

### Task 0.3 — Cập nhật app name trong backend

Thay tất cả reference "NexusRAG" và "LegalNexus" thành "LexGuardian":

```python
# backend/app/core/config.py
APP_NAME: str = "LexGuardian"

# backend/app/main.py — cập nhật title và description
app = FastAPI(
    title="LexGuardian",
    description="LexGuardian — AI Legal Copilot for contract analysis and legal research",
    version="1.0.0",
    ...
)
```

### Task 0.4 — Tạo file .env.example

```bash
cat > /Users/quanai/Documents/myproject/gen_ai/LexGuardian/.env.example << 'EOF'
# ==========================================
# LexGuardian Environment Configuration
# Copy this file to .env and fill in values
# ==========================================

# App
APP_NAME=LexGuardian
DEBUG=false

# Database (PostgreSQL + pgvector)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/lexguardian

# LLM Provider: "gemini" | "ollama"
LLM_PROVIDER=gemini

# Google Gemini (required for full features)
GOOGLE_AI_API_KEY=your_gemini_api_key_here

# Model configuration
LLM_MODEL_FAST=gemini-2.5-flash
LEGAL_RISK_ANALYSIS_MODEL=gemini-2.5-pro

# Ollama (for local development without API key)
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=gemma3:12b

# Live web search (required for LIVE_SEARCH intent)
TAVILY_API_KEY=your_tavily_api_key_here

# Feature flags
ENABLE_GENERIC_RAG_API=false
NEXUSRAG_ENABLE_KG=true
NEXUSRAG_ENABLE_IMAGE_CAPTIONING=true
AUTO_CREATE_TABLES=true

# CORS
CORS_ORIGINS=["http://localhost:5174","http://localhost:3000"]
EOF
```

### Task 0.5 — Tạo cấu trúc Frontend mới (KHÔNG copy từ NexusRAG)

```bash
cd /Users/quanai/Documents/myproject/gen_ai/LexGuardian

# Khởi tạo React + Vite + TypeScript
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install

# Install dependencies (copy từ NexusRAG nhưng thêm mới)
npm install \
  @tanstack/react-query \
  zustand \
  react-router-dom \
  tailwindcss @tailwindcss/typography \
  autoprefixer postcss \
  lucide-react \
  sonner \
  framer-motion \
  react-markdown remark-gfm remark-math rehype-katex katex \
  clsx tailwind-merge

# Dev dependencies
npm install -D \
  @types/react @types/react-dom \
  eslint @typescript-eslint/eslint-plugin \
  prettier

# Setup Tailwind
npx tailwindcss init -p
```

### Task 0.6 — Commit ban đầu

```bash
cd /Users/quanai/Documents/myproject/gen_ai/LexGuardian
git add .
git commit -m "feat: initial LexGuardian project setup with NexusRAG backend"
git branch -M main
git push -u origin main
```

---

## ✅ Acceptance Criteria Phase 0

Chạy checklist này để xác nhận Phase 0 hoàn thành:

```bash
# Test 1: Cấu trúc thư mục đúng
[ -d "backend/app" ] && echo "PASS: backend exists" || echo "FAIL: backend missing"
[ -d "frontend/src" ] && echo "PASS: frontend exists" || echo "FAIL: frontend missing"
[ -f ".gitignore" ] && echo "PASS: .gitignore exists" || echo "FAIL"
[ -f ".env.example" ] && echo "PASS: .env.example exists" || echo "FAIL"

# Test 2: Git remote đúng
git remote get-url origin | grep "LexGuardian" && echo "PASS: git remote correct" || echo "FAIL"

# Test 3: Backend có thể chạy
cd backend && pip install -r requirements.txt -q
python -c "from app.main import app; print('PASS: backend imports OK')"

# Test 4: App name đã được cập nhật
grep -r "LexGuardian" backend/app/core/config.py | grep "APP_NAME" \
  && echo "PASS: app name updated" || echo "FAIL: still says NexusRAG"

# Test 5: Không có credentials trong git
git log --all --full-history -- "*.env" | grep -c "commit" | \
  { read n; [ "$n" -eq 0 ] && echo "PASS: no .env in git" || echo "FAIL: .env committed!"; }
```

**Phase 0 hoàn thành khi: TẤT CẢ 5 tests đều PASS.**

---

---

# PHASE 1: Backend Foundation

## Mục tiêu
Làm sạch backend, thêm unified `/command` endpoint, và verify toàn bộ legal AI pipeline hoạt động đúng.

## Tasks

### Task 1.1 — Verify Backend Stack hoạt động

```bash
# Start PostgreSQL với pgvector
docker compose -f docker-compose.services.yml up -d

# Start backend
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Test health
curl http://localhost:8000/health
# Expected: {"status": "healthy"}

curl http://localhost:8000/ready  
# Expected: {"status": "ready"}

curl http://localhost:8000/docs
# Expected: Swagger UI loads (200)
```

### Task 1.2 — Thêm Unified Command Endpoint

Tạo file `backend/app/api/command.py`:

```python
"""
LexGuardian Command API
========================
Unified entry point: nhận user input bất kỳ, detect intent, route đến đúng service.

Đây là endpoint chính mà Command Center frontend gọi.

Intent types:
  - ASK_DOCUMENT    → Legal QA từ documents trong workspace
  - ASK_LAW         → Live search trên legal databases  
  - ANALYZE_RISK    → Contract risk analysis
  - CHECK_VALIDITY  → Kiểm tra văn bản pháp luật còn hiệu lực không
  - GENERAL         → General conversation
"""
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from app.core.deps import get_current_user, get_db, get_workspace_for_user
from app.models.user import User
from app.models.knowledge_base import KnowledgeBase
from app.services.legal.legal_router import LegalDomainRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/command", tags=["command"])

class CommandRequest(BaseModel):
    input: str
    document_id: Optional[int] = None
    conversation_id: Optional[int] = None
    conversation_history: list[dict] = []

class CommandResponse(BaseModel):
    intent: str          # ASK_DOCUMENT | ASK_LAW | ANALYZE_RISK | CHECK_VALIDITY | GENERAL
    confidence: float
    suggested_action: str
    signals: list[str]
    domain: str

@router.post("/detect-intent/{workspace_id}", response_model=CommandResponse)
async def detect_intent(
    workspace_id: int,
    body: CommandRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace: KnowledgeBase = Depends(get_workspace_for_user),
):
    """
    Phân tích input của user và trả về intent + suggested action.
    Frontend dùng endpoint này để quyết định hiển thị UI nào.
    """
    domain_router = LegalDomainRouter()
    result = domain_router.detect_domain(body.input)

    # Map domain detection → LexGuardian intent
    if body.document_id:
        intent = "ASK_DOCUMENT"
        suggested_action = "query_document"
    elif result.domain == "legal" and result.confidence >= 0.7:
        # Check for specific intent signals
        validity_keywords = ["còn hiệu lực", "hết hiệu lực", "expired", "still valid", "in force"]
        if any(kw in body.input.lower() for kw in validity_keywords):
            intent = "CHECK_VALIDITY"
            suggested_action = "check_validity"
        else:
            intent = "ASK_LAW"
            suggested_action = "live_search"
    elif result.domain == "legal":
        intent = "ASK_DOCUMENT"
        suggested_action = "query_workspace"
    else:
        intent = "GENERAL"
        suggested_action = "general_chat"

    return CommandResponse(
        intent=intent,
        confidence=result.confidence,
        suggested_action=suggested_action,
        signals=result.signals,
        domain=result.domain,
    )
```

Đăng ký vào `app/api/router.py`:
```python
from app.api.command import router as command_router
api_router.include_router(command_router)
```

### Task 1.3 — Tắt các feature flags không cần thiết

Trong `.env`, set:
```
ENABLE_GENERIC_RAG_API=false
```

Trong `app/api/router.py`, verify flag được respect đúng.

### Task 1.4 — Kiểm tra Legal Pipeline end-to-end

Viết script test thủ công:

```bash
# 1. Đăng ký user test
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@lex.vn","password":"test123456","display_name":"Test"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

echo "Token: $TOKEN"

# 2. Tạo workspace
WS_ID=$(curl -s -X POST http://localhost:8000/api/v1/workspaces \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Test Brief"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

echo "Workspace ID: $WS_ID"

# 3. Test intent detection
curl -s -X POST "http://localhost:8000/api/v1/command/detect-intent/$WS_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"input":"Hợp đồng có điều khoản phạt vi phạm như thế nào?"}' \
  | python3 -m json.tool

# 4. Test live search
curl -s -X POST "http://localhost:8000/api/v1/legal/live-search/$WS_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"Luật đất đai 2024 có hiệu lực từ khi nào?","max_results":3}' \
  | python3 -m json.tool
```

---

## ✅ Acceptance Criteria Phase 1

```bash
BASE="http://localhost:8000/api/v1"
TOKEN="<lấy từ login>"
WS_ID="<lấy từ tạo workspace>"

# Test 1: Health endpoints
curl -sf "$BASE/../health" | grep "healthy" && echo "PASS: health" || echo "FAIL: health"
curl -sf "$BASE/../ready" | grep "ready" && echo "PASS: ready" || echo "FAIL: ready"

# Test 2: Auth flow hoạt động
curl -sf -X POST "$BASE/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"test@lex.vn","password":"test123456"}' | grep "token" \
  && echo "PASS: auth" || echo "FAIL: auth"

# Test 3: Intent detection endpoint tồn tại và trả đúng schema
INTENT_RESP=$(curl -sf -X POST "$BASE/command/detect-intent/$WS_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"input":"Điều khoản thanh toán như thế nào?"}')
echo "$INTENT_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'intent' in d, 'missing intent'
assert 'confidence' in d, 'missing confidence'
assert d['intent'] in ['ASK_DOCUMENT','ASK_LAW','ANALYZE_RISK','CHECK_VALIDITY','GENERAL'], 'invalid intent'
print('PASS: intent detection schema correct')
" || echo "FAIL: intent detection"

# Test 4: Legal domain detection accuracy
LEGAL_QUERY="Hợp đồng có điều khoản phạt vi phạm bao nhiêu phần trăm?"
RESP=$(curl -sf -X POST "$BASE/command/detect-intent/$WS_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"input\":\"$LEGAL_QUERY\"}")
DOMAIN=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['domain'])")
[ "$DOMAIN" = "legal" ] && echo "PASS: legal domain detection" || echo "FAIL: expected legal, got $DOMAIN"

# Test 5: Document upload hoạt động
# (upload một file PDF mẫu)
curl -sf -X POST "$BASE/documents/upload/$WS_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/test_contract.pdf" | grep '"status"' \
  && echo "PASS: document upload" || echo "FAIL: document upload"

# Test 6: Risk analysis endpoint tồn tại (schema check)
curl -sf -X POST "$BASE/legal/analyze-risk/$WS_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"document_id": 99999}' | grep -v "Internal server error" \
  && echo "PASS: analyze-risk endpoint exists" || echo "FAIL"

# Test 7: SSE chat stream (kiểm tra header)
curl -sf -N -X POST "$BASE/chat/$WS_ID/stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Hello","history":[],"enable_thinking":false}' \
  --max-time 5 | head -5 | grep "data:" \
  && echo "PASS: SSE streaming" || echo "FAIL: SSE streaming"
```

**Phase 1 hoàn thành khi: Test 1, 2, 3, 4, 7 PASS. Test 5 PASS nếu có file PDF. Test 6 trả 404 hoặc error document không tồn tại (không phải 500).**

---

---

# PHASE 2: Frontend Core — Command Center & Ask Flow

## Mục tiêu
Xây dựng giao diện LexGuardian từ đầu: Command Center (home page), Ask flow với streaming answer và Source Viewer. Đây là trái tim của UX intent-first.

## Design System Setup

### Task 2.1 — Cấu hình Tailwind & Design Tokens

```typescript
// frontend/tailwind.config.js
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Semantic surface tokens (light mode)
        surface: {
          lowest: "#FAFAFA",
          low: "#F4F4F5",
          mid: "#EBEBEC",
        },
        primary: {
          DEFAULT: "#1a1a2e",  // Deep navy — authority
          foreground: "#ffffff",
        },
        risk: {
          critical: "#DC2626",
          medium: "#D97706",
          low: "#2563EB",
          info: "#6B7280",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        serif: ["Newsreader", "Georgia", "serif"],  // Cho legal text
        mono: ["JetBrains Mono", "monospace"],
      },
      boxShadow: {
        ambient: "0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06)",
      },
      borderRadius: {
        "2xl": "1rem",
        "3xl": "1.5rem",
      },
    },
  },
};
```

### Task 2.2 — Cấu trúc Frontend

```
frontend/src/
├── components/
│   ├── ui/               # Primitives: Button, Input, Badge, Card, Skeleton
│   ├── layout/           # AppShell, Sidebar, TopBar
│   ├── command/          # CommandBar, IntentChip, SuggestionList
│   ├── ask/              # StreamingAnswer, CitationChip, SourceViewer
│   │                      ThinkingTimeline (copy từ NexusRAG)
│   ├── analyze/          # RiskReport, RiskItem, RiskBadge, ClauseViewer
│   └── shared/           # EmptyState, ErrorBoundary, DocumentCard
├── pages/
│   ├── CommandCenterPage.tsx   # Home / Entry point
│   ├── AskPage.tsx             # Chat + Source viewer
│   ├── AnalyzePage.tsx         # Contract risk analysis
│   ├── LibraryPage.tsx         # Document management
│   └── LoginPage.tsx
├── hooks/
│   ├── useAuth.ts
│   ├── useWorkspaces.ts
│   ├── useDocuments.ts
│   ├── useConversations.ts
│   ├── useLegalStream.ts      # Adapted từ useRAGChatStream
│   └── useCommand.ts          # Gọi /command/detect-intent
├── stores/
│   ├── authStore.ts
│   ├── workspaceStore.ts      # selectedDoc, riskReport, panel state
│   └── themeStore.ts
├── lib/
│   ├── api.ts
│   └── utils.ts
└── types/
    └── index.ts
```

### Task 2.3 — Copy & Adapt các file tái sử dụng từ NexusRAG

Các file copy trực tiếp (không thay đổi hoặc thay đổi rất ít):
```bash
NEXUS_SRC=/Users/quanai/Documents/myproject/gen_ai/NexusRAG/frontend/src

# Hooks
cp "$NEXUS_SRC/hooks/useAuth.ts" ./src/hooks/
cp "$NEXUS_SRC/hooks/useChatHistory.ts" ./src/hooks/
cp "$NEXUS_SRC/hooks/useConversations.ts" ./src/hooks/
cp "$NEXUS_SRC/hooks/useWorkspaces.ts" ./src/hooks/
cp "$NEXUS_SRC/hooks/useRAGChatStream.ts" ./src/hooks/useLegalStream.ts

# Stores
cp "$NEXUS_SRC/stores/authStore.ts" ./src/stores/
cp "$NEXUS_SRC/stores/workspaceStore.ts" ./src/stores/

# Lib
cp "$NEXUS_SRC/lib/api.ts" ./src/lib/
cp "$NEXUS_SRC/lib/utils.ts" ./src/lib/

# Types
cp "$NEXUS_SRC/types/index.ts" ./src/types/

# Components — ThinkingTimeline và MemoizedMarkdown là reusable
cp "$NEXUS_SRC/components/rag/ThinkingTimeline.tsx" ./src/components/ask/
cp "$NEXUS_SRC/components/rag/MemoizedMarkdown.tsx" ./src/components/ask/
cp "$NEXUS_SRC/components/rag/DocumentViewer.tsx" ./src/components/ask/SourceViewer.tsx
```

### Task 2.4 — CommandCenterPage.tsx

Đây là home page. Quy tắc thiết kế:
- Màn hình trắng, tối giản
- Một CommandBar lớn ở giữa
- 2-3 suggestion chips bên dưới
- Recent briefs (workspace) bên dưới nữa

```tsx
// frontend/src/pages/CommandCenterPage.tsx
// - Centered layout, full height
// - CommandBar component ở giữa màn hình
// - Suggestion chips: "Review NDA", "Tra cứu luật đất đai", "Phân tích hợp đồng"
// - Recent briefs list bên dưới (dùng useWorkspaces hook)
// - Drop zone cho PDF (triggers Analyze flow)
// - Khi user submit: gọi /command/detect-intent → redirect đến đúng page
```

### Task 2.5 — AskPage.tsx (Chat + Source Viewer)

Layout 60/40:
- Left (60%): Conversation thread
  - Mỗi AI message: serif font, citation chips inline
  - ThinkingTimeline nếu đang processing
  - ChatInputBar ở dưới cùng
- Right (40%): SourceViewer — chỉ hiện khi click citation
  - Slides in từ phải với animation
  - Shows document tại đúng trang/đoạn được cite
  - Đoạn text được highlight

### Task 2.6 — CitationChip Component

```tsx
// frontend/src/components/ask/CitationChip.tsx
// - Hiển thị: [filename, p.N]
// - Click → mở SourceViewer tại page đó
// - Màu neutral, underline on hover
// - Accessible: role="button", aria-label
```

---

## ✅ Acceptance Criteria Phase 2

### Test bằng Browser (manual)

```
Test 2.1: Command Center loads
  → Truy cập http://localhost:5174
  → Login thành công
  → Thấy màn hình trắng với CommandBar ở giữa
  → Không thấy: chunk counts, vector stats, query mode selector
  EXPECTED: Clean command center hiển thị đúng

Test 2.2: Intent suggestion đúng
  → Gõ "Hợp đồng có điều khoản gì về phạt vi phạm?"
  → System detect intent = ASK_DOCUMENT hoặc ASK_LAW
  → Hiển thị intent chip phù hợp
  EXPECTED: Intent chip visible, phản ánh đúng loại câu hỏi

Test 2.3: Ask flow hoạt động
  → Tạo Brief, upload PDF contract
  → Gõ câu hỏi về contract
  → Thấy streaming answer với citation chips
  EXPECTED: Answer streams, [filename, p.N] chips visible

Test 2.4: Citation click mở Source Viewer
  → Click vào một citation chip [Doc, p.5]
  → Right panel slides in (animation)
  → Document mở đúng trang
  EXPECTED: Source viewer opens tại đúng page

Test 2.5: Empty state đúng
  → Tạo Brief rỗng, hỏi câu hỏi bất kỳ
  → System không hallucinate
  → Hiển thị: "Không tìm thấy thông tin liên quan..."
  → Offer: "Tìm kiếm trên web pháp luật?"
  EXPECTED: No dead end, clear next action offered

Test 2.6: Mobile responsive (resize to 768px)
  → Sidebar collapse
  → Command bar vẫn usable
  → Source viewer overlay (không bị cut)
  EXPECTED: Responsive layout works
```

### Test bằng TypeScript
```bash
cd frontend
npm run type-check
# EXPECTED: 0 errors

npm run lint
# EXPECTED: 0 errors (hoặc chỉ warnings)
```

**Phase 2 hoàn thành khi: Tests 2.1, 2.2, 2.3, 2.4, 2.5 PASS bằng browser + TypeScript 0 errors.**

---

---

# PHASE 3: Frontend Analyze — Contract Risk Analysis UI

## Mục tiêu
Xây dựng flow phân tích hợp đồng: upload → processing → risk report view với color-coded risk items, clause viewer, và source verification.

## Tasks

### Task 3.1 — Upload & Intent Detection khi drop file

Trên CommandCenterPage:
```
User drag & drop PDF
→ File upload tự động trigger
→ Modal/banner: "Tôi thấy bạn đã upload hợp đồng. Bạn muốn:"
  [Phân tích Rủi ro] [Tóm tắt Nghĩa vụ] [Trích xuất Điều khoản chính]
→ User chọn "Phân tích Rủi ro"
→ Navigate to AnalyzePage với document context
```

### Task 3.2 — AnalyzePage.tsx

Layout:
```
┌─────────────────────────────────────────────┐
│ RISK SCORECARD                              │
│ 🔴 Critical: 2  🟡 Medium: 4  🔵 Low: 1    │
│ Overall: HIGH RISK                           │
├─────────────────────────────────────────────┤
│ [Termination Clause]          CRITICAL ▼    │
│ Counterparty can exit with 7-day notice.    │
│ Standard minimum is 30 days under VN law.  │
│ Original: "...trong vòng 7 ngày làm việc..."│
│ Suggestion: Đổi thành 30 ngày              │
│ [Xem điều khoản gốc] [Chấp nhận redline]   │
├─────────────────────────────────────────────┤
│ [Payment Terms]               MEDIUM  ▼    │
│ ...                                         │
├─────────────────────────────────────────────┤
│ Thiếu điều khoản tiêu chuẩn:               │
│ • Force Majeure  • IP Ownership             │
└─────────────────────────────────────────────┘
```

### Task 3.3 — RiskItem Component

```tsx
// frontend/src/components/analyze/RiskItem.tsx
interface RiskItemProps {
  item: {
    id: string;
    title: string;
    severity: "CRITICAL" | "MEDIUM" | "LOW";
    risk_type: string;
    original_text: string;
    explanation: string;
    legal_basis: string;
    suggested_redline: string | null;
    clause_reference: string;
  };
  onViewClause: (text: string, reference: string) => void;
}

// Behavior:
// - Collapsed by default, click header để expand
// - Severity badge với màu đúng (red/amber/blue)
// - Original text trong box có style document
// - Suggested redline với diff-style (struck-through original, green new)
// - "Xem điều khoản gốc" → mở SourceViewer tại clause
```

### Task 3.4 — RiskScorecard Component

```tsx
// Top summary card
// - Overall risk level với màu tương ứng
// - Count badge cho mỗi severity level
// - Progress bar hoặc visual indicator
// - "Xuất báo cáo" button (future feature, disabled for now)
```

### Task 3.5 — Processing State

```tsx
// Khi contract đang được phân tích:
// - KHÔNG hiển thị: "Docling parsing...", "Embedding batch 3/12..."
// - HIỂN THỊ: Elegant loading animation + "Đang phân tích hợp đồng..."
// - Progress indicator nhẹ nhàng (không technical)
// Timeout: nếu > 60s không có kết quả → error state với retry
```

---

## ✅ Acceptance Criteria Phase 3

```
Test 3.1: Drop file → Intent modal xuất hiện
  → Drag PDF vào CommandBar
  → Upload starts automatically  
  → Modal: "Bạn muốn làm gì với hợp đồng này?"
  → 3 options visible
  EXPECTED: Smooth upload + intent detection UX

Test 3.2: Processing state không reveal internals
  → Click "Phân tích Rủi ro"
  → Thấy: "Đang phân tích hợp đồng..." với animation đẹp
  → KHÔNG thấy: "Docling", "chunks", "embeddings", model names
  EXPECTED: Clean processing UI

Test 3.3: Risk report renders đúng
  → Analysis complete (dùng document đã index)
  → Thấy: Risk Scorecard với count theo severity
  → Thấy: Ít nhất 1 risk item có title, explanation, original_text
  → Risk items sorted by severity (CRITICAL first)
  EXPECTED: Complete risk report display

Test 3.4: Risk item expand/collapse
  → Click vào risk item header
  → Item expands, hiện original_text và explanation
  → Click lại → collapse
  EXPECTED: Accordion behavior đúng

Test 3.5: "Xem điều khoản gốc" mở đúng vị trí
  → Click [Xem điều khoản gốc] trên một risk item
  → SourceViewer slides in từ phải
  → Document opens, clause được highlight
  EXPECTED: Source verification works

Test 3.6: Missing clauses section visible
  → Cuối risk report
  → Danh sách các điều khoản tiêu chuẩn còn thiếu
  EXPECTED: Missing clauses displayed

Test 3.7: API error handling
  → Disconnect database giữa chừng
  → UI hiển thị: "Phân tích thất bại. Thử lại?"
  → Retry button hoạt động
  EXPECTED: Graceful error handling
```

**Phase 3 hoàn thành khi: Tests 3.1–3.6 PASS. Test 3.7 PASS (thủ công).**

---

---

# PHASE 4: Integration & Polish

## Mục tiêu
Kết nối tất cả các flow, thêm Library page, polish UX, và đảm bảo toàn bộ product vision được implement.

## Tasks

### Task 4.1 — LibraryPage.tsx (Document Management)

```
- List tất cả documents trong brief
- Status badge (pending / processing / indexed / failed)
- Click document → mở trong SourceViewer
- Delete document với confirm dialog
- Bulk actions: select multiple, delete all selected
- Search/filter documents
```

### Task 4.2 — Brief Management (Sidebar)

```
- List tất cả briefs của user
- Create new brief
- Rename brief (inline edit)
- Delete brief với confirm
- Brief icon + name + document count
- Active brief highlighted
```

### Task 4.3 — Sidebar Navigation

```
Navigation items (theo product language, không theo backend):
- 🏠 Home (Command Center)
- 📋 My Briefs (Brief list)
- 📚 Library (Document list cho brief hiện tại)
- 🔬 Research (Explore/KG - ẩn, chỉ hiện khi có feature flag)
```

### Task 4.4 — Toast Notifications System

```
Sử dụng sonner library:
- Upload success: "Đã upload thành công. Đang phân tích..."
- Analysis complete: "Phân tích hoàn tất. X rủi ro được phát hiện."
- Error: "Không thể kết nối. Vui lòng thử lại."
- NO technical toasts: không hiển thị "Indexing complete (247 chunks)"
```

### Task 4.5 — Typography Implementation

```css
/* Import Newsreader font (serif cho legal text) */
@import url('https://fonts.googleapis.com/css2?family=Newsreader:ital,wght@0,400;0,600;1,400&family=Inter:wght@300;400;500;600&display=swap');

/* Legal answer text: dùng font-serif class */
.legal-answer-text {
  font-family: 'Newsreader', serif;
  font-size: 1rem;
  line-height: 1.75;
}
```

### Task 4.6 — Dark Mode (Basic)

```
- Toggle ở TopBar
- Dark: bg-gray-950, text-gray-100
- Legal text vẫn readable với dark serif
- Source Viewer có dark mode
```

### Task 4.7 — Git commit từng task

```bash
# Commit message convention:
git commit -m "feat(library): add document management page with status badges"
git commit -m "feat(sidebar): implement brief navigation with CRUD"
git commit -m "style: apply Newsreader serif font for legal answer text"
git commit -m "feat(toast): add product-language toast notifications"
git push
```

---

## ✅ Acceptance Criteria Phase 4

```
Test 4.1: Full user journey — New Brief → Upload → Ask
  Bước 1: Login → Command Center
  Bước 2: Tạo Brief "Test Contract Review"
  Bước 3: Upload hợp đồng PDF
  Bước 4: Click "Phân tích Rủi ro" 
  Bước 5: Xem risk report, click một risk item
  Bước 6: Xem clause gốc trong Source Viewer
  Bước 7: Quay lại Command Center, gõ câu hỏi về contract
  Bước 8: Nhận answer với citation, click citation
  Bước 9: Source Viewer opens tại đúng trang
  EXPECTED: Toàn bộ 9 bước hoạt động smooth, 0 lỗi hiện lên

Test 4.2: Product language không có technical terms
  → Kiểm tra tất cả UI text: title, buttons, toasts, empty states
  → KHÔNG được có: "chunks", "vectors", "embedding", "indexing", 
    model names, "workspace" (dùng "brief"), technical stats
  EXPECTED: 0 technical terms visible to user

Test 4.3: Responsive design
  → Thử trên 1440px, 1024px, 768px
  → Sidebar collapse đúng
  → Source Viewer không bị overflow
  → CommandBar usable trên mọi kích thước
  EXPECTED: Functional trên tất cả breakpoints

Test 4.4: Dark mode
  → Toggle dark mode
  → Tất cả text readable
  → Risk colors vẫn phân biệt được (không quá nhạt)
  → Source Viewer trong dark mode
  EXPECTED: Readable dark mode

Test 4.5: Performance
  → Upload document 5MB
  → Ask 5 câu hỏi liên tiếp
  → Risk analysis trên document đã indexed
  → Browser không bị chậm / memory leak
  EXPECTED: Responsive UI trong suốt quá trình
```

**Phase 4 hoàn thành khi: Test 4.1 và 4.2 PASS. Tests 4.3, 4.4, 4.5 PASS.**

---

---

# PHASE 5: Testing & Production Readiness

## Mục tiêu
Viết automated tests, kiểm tra security, optimize performance, và chuẩn bị deploy.

## Tasks

### Task 5.1 — Backend Tests

```bash
cd backend
pip install pytest pytest-asyncio httpx --break-system-packages

# Chạy test suite
pytest tests/ -v --tb=short

# Coverage report
pytest tests/ --cov=app --cov-report=term-missing
```

Viết tests cho:
```python
# tests/api/test_auth.py      — register, login, logout, me
# tests/api/test_workspaces.py — CRUD workspaces
# tests/api/test_documents.py  — upload, status, delete
# tests/api/test_command.py    — intent detection accuracy
# tests/api/test_legal.py      — legal QA grounding check
# tests/services/test_legal_router.py — domain detection với Vietnamese queries
```

### Task 5.2 — Frontend TypeScript Strict Mode

```json
// tsconfig.json
{
  "compilerOptions": {
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noImplicitReturns": true
  }
}
```

```bash
cd frontend
npm run type-check
# Target: 0 errors
```

### Task 5.3 — Security Checklist

```bash
# 1. Kiểm tra .env không được commit
git log --all --full-history -- .env | wc -l
# Expected: 0

# 2. Kiểm tra không có hardcoded secrets
grep -r "API_KEY\|SECRET\|PASSWORD" frontend/src/ --include="*.ts" --include="*.tsx"
# Expected: 0 matches (hoặc chỉ environment variable references)

# 3. Check CORS config
curl -I -X OPTIONS http://localhost:8000/api/v1/auth/login \
  -H "Origin: http://malicious-site.com" \
  -H "Access-Control-Request-Method: POST"
# Expected: No Access-Control-Allow-Origin: http://malicious-site.com

# 4. Verify auth on all legal endpoints
curl -X POST http://localhost:8000/api/v1/legal/query/1 \
  -H "Content-Type: application/json" \
  -d '{"question":"test"}'
# Expected: 401 Unauthorized (NO Bearer token)

# 5. Verify workspace isolation
# User A không thể access workspace của User B
```

### Task 5.4 — Docker Build Test

```bash
# Test full Docker build
cd /Users/quanai/Documents/myproject/gen_ai/LexGuardian
docker compose build
docker compose up -d

# Verify tất cả services healthy
docker compose ps
# Expected: backend, frontend, db — all "running"

# Test qua Nginx (port 80)
curl http://localhost:80/health
curl http://localhost:80/api/v1/health
```

### Task 5.5 — README.md

Tạo README.md tại root với:
```markdown
# LexGuardian 🛡️

AI Legal Copilot for contract analysis and legal research.

## Features
## Quick Start  
## Architecture
## Development
## Environment Variables
## Contributing
```

### Task 5.6 — Final Git & Push

```bash
git add .
git commit -m "feat: complete LexGuardian MVP — command center, ask flow, risk analysis"
git tag v0.1.0 -m "MVP release — Phase 5 complete"
git push origin main
git push origin v0.1.0
```

---

## ✅ Acceptance Criteria Phase 5 — FINAL CHECKLIST

```bash
# === BACKEND TESTS ===
cd backend
pytest tests/api/ -v
# EXPECTED: Tất cả tests PASS (minimum: auth, workspaces, command, legal)

# === FRONTEND ===
cd frontend
npm run type-check
# EXPECTED: 0 TypeScript errors

npm run lint
# EXPECTED: 0 ESLint errors

npm run build
# EXPECTED: Build succeeds, no warnings về bundle size > 500kb

# === DOCKER ===
docker compose up --build -d
docker compose ps | grep "Up"
# EXPECTED: 3 services Up (backend, frontend, db)

curl -sf http://localhost:80/
# EXPECTED: 200 OK (frontend serves)

curl -sf http://localhost:80/api/v1/health
# EXPECTED: {"status":"healthy"}

# === SECURITY ===
git log --all -- .env | wc -l
# EXPECTED: 0 (không có .env trong git history)

# === GIT ===
git remote get-url origin
# EXPECTED: https://github.com/cvQuan28/LexGuardian

git log --oneline | head -10
# EXPECTED: Clean commit history với conventional commits

git tag | grep v0.1
# EXPECTED: v0.1.0 tag tồn tại
```

**Phase 5 hoàn thành khi: TẤT CẢ checks PASS. LexGuardian v0.1.0 MVP được tag và push lên GitHub.**

---

---

# APPENDIX: QUYẾT ĐỊNH KỸ THUẬT NHANH

## Khi gặp vấn đề, dùng quyết định sau:

| Tình huống | Quyết định |
|---|---|
| Cần thêm dependency frontend | pnpm install, không dùng CDN |
| LLM call bị chậm | Kiểm tra model, không swap sang model khác không hỏi |
| Database schema cần thay đổi | Dùng ALTER TABLE IF NOT EXISTS trong main.py |
| Component > 200 lines | Tách thành sub-components |
| User thấy technical info | Xóa ngay, không để lại sau |
| API trả lỗi 500 | Log chi tiết ở backend, trả thông báo chung cho frontend |
| Cần tạo file mới | Luôn kiểm tra `.claude/04_ui_patterns.md` trước |

## Không được làm (Hard Rules)

❌ Hiển thị chunk counts, vector dimensions trong UI  
❌ Để user chọn query mode (hybrid/vector/BM25)  
❌ Commit file `.env` hoặc API keys  
❌ Tạo component > 300 lines mà không tách  
❌ Trả về AI answer không có source nếu `LEGAL_GROUNDING_STRICT=true`  
❌ Import trực tiếp `gemini.py` hoặc `ollama.py` từ service code  
❌ Dùng `localStorage` cho application data (chỉ auth token)  
❌ Hard-code URL, port, hoặc model name vào code (dùng env/config)  

## Convention nhanh

```python
# Backend: async everywhere
async def my_handler(db: AsyncSession = Depends(get_db)):
    result = await db.execute(...)  # luôn await

# Backend: logger, không print
logger = logging.getLogger(__name__)
logger.info("Processing document %s", doc_id)  # không dùng print()

# Frontend: typed props luôn
interface Props { item: RiskItem; onSelect: (id: string) => void; }

# Frontend: error boundaries cho async
const { data, error, isLoading } = useQuery(...)
if (isLoading) return <Skeleton />;
if (error) return <ErrorState message={error.message} />;
```

---

*Tài liệu đầy đủ tại `/Users/quanai/Documents/myproject/gen_ai/LexGuardian/.claude/`*  
*Repo: https://github.com/cvQuan28/LexGuardian*
