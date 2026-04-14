# LexGuardian — AI Legal Copilot

LexGuardian là trợ lý pháp lý AI dành cho thị trường Việt Nam. Hệ thống hỗ trợ **hỏi đáp tài liệu pháp lý** (hợp đồng, văn bản nội bộ) và **tư vấn pháp luật trực tuyến** (tra cứu luật, nghị định, thông tư) với nguồn trả lời có trích dẫn rõ ràng.

---

## Tính năng chính

| Tính năng | Mô tả |
|---|---|
| **Hỏi đáp tài liệu** | Upload PDF/DOCX, đặt câu hỏi, nhận câu trả lời có trích dẫn chính xác |
| **Tư vấn pháp luật** | Tra cứu văn bản pháp luật Việt Nam + live search Tavily khi cần |
| **Phân tích rủi ro hợp đồng** | Phát hiện điều khoản rủi ro, thiếu sót, đánh giá mức độ nguy hiểm |
| **Hybrid Retrieval** | BM25 + Vector (PGVector) + Knowledge Graph (LightRAG) + Cross-encoder Reranker |
| **Streaming SSE** | Câu trả lời được stream token từng chữ, hiển thị ngay lập tức |
| **Knowledge Graph** | Trích xuất quan hệ pháp lý tự động từ tài liệu (bên, nghĩa vụ, quyền, phạt) |
| **Lịch sử hội thoại** | Lưu và khôi phục hội thoại theo workspace |
| **Multi-LLM** | Hỗ trợ Google Gemini và Ollama (chạy local) |

---

## Kiến trúc

```
Frontend (React + TypeScript + Tailwind)
    │  SSE streaming / REST API
    ▼
Backend (FastAPI + Python 3.11)
    ├── Auth            — PBKDF2 password hash, session token
    ├── Chat Agent      — Semi-agentic loop (force_search + tool-calling)
    ├── Legal RAG       — LegalRAGService orchestrator
    │       ├── Legal Parser     (Docling)
    │       ├── Clause Chunker
    │       ├── Legal Retriever  (BM25 + PGVector + LightRAG KG + Reranker)
    │       ├── Legal Reasoning  (LLM grounding layer)
    │       └── Web Search       (Tavily — live legal search fallback)
    └── Storage
            ├── PostgreSQL + pgvector  (documents, vectors, chat history)
            └── LightRAG              (Knowledge Graph — file-based graphml)
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Tailwind CSS, Vite, TanStack Query |
| Backend | FastAPI, Python 3.11, SQLAlchemy async, Pydantic v2 |
| Database | PostgreSQL 15 + pgvector extension |
| Embedding | `AITeamVN/Vietnamese_Embedding` (1024-dim, sentence-transformers) |
| Reranker | `AITeamVN/Vietnamese_Reranker` (cross-encoder) |
| KG | LightRAG (graphml file-based, per-workspace singleton) |
| Document parsing | Docling (PDF, DOCX, images) |
| LLM | Google Gemini 2.5 Flash / Ollama (local) |
| Live search | Tavily API |
| Reverse proxy | Nginx |
| Containerization | Docker + Docker Compose |

---

## Yêu cầu hệ thống

- Docker & Docker Compose v2+
- 8 GB RAM (16 GB khuyến nghị cho mô hình embedding local)
- 5 GB disk (models + data)
- API key: Google AI (Gemini) và/hoặc Tavily

---

## Cài đặt nhanh (Docker)

```bash
# 1. Clone repo
git clone https://github.com/cvQuan28/LexGuardian.git
cd LexGuardian

# 2. Cấu hình môi trường
cp .env.example .env
# Chỉnh sửa .env: điền GOOGLE_AI_API_KEY, TAVILY_API_KEY, POSTGRES_PASSWORD

# 3. Khởi động
docker compose up -d

# 4. Truy cập
# Frontend: http://localhost:5174
# Backend API: http://localhost:8080/docs
```

---

## Cài đặt môi trường phát triển (Local)

### Yêu cầu
- Python 3.11+, conda khuyến nghị
- Node.js 20+
- PostgreSQL 15 với pgvector extension

### Backend

```bash
# Tạo môi trường
conda create -n gen_ai python=3.11
conda activate gen_ai

# Cài dependencies
pip install -r backend/requirements.txt

# Cấu hình .env
cp .env.example .env
# Điền DATABASE_URL, GOOGLE_AI_API_KEY, TAVILY_API_KEY

# Khởi động PostgreSQL (hoặc dùng Docker)
docker compose up postgres -d

# Chạy backend
cd backend
python run.py
# API chạy tại http://localhost:8080
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# UI chạy tại http://localhost:5174
```

---

## Biến môi trường

| Biến | Bắt buộc | Mô tả |
|---|---|---|
| `GOOGLE_AI_API_KEY` | Có (Gemini) | Google AI API key |
| `TAVILY_API_KEY` | Có (tư vấn pháp luật) | Tavily search API key |
| `DATABASE_URL` | Có | PostgreSQL connection string |
| `POSTGRES_PASSWORD` | Có (Docker) | Mật khẩu PostgreSQL |
| `LLM_PROVIDER` | Không | `gemini` (mặc định) hoặc `ollama` |
| `OLLAMA_HOST` | Ollama | URL của Ollama server |
| `OLLAMA_MODEL` | Ollama | Tên model Ollama (vd: `gemma3:12b`) |
| `NEXUSRAG_ENABLE_KG` | Không | Bật/tắt Knowledge Graph (mặc định: `true`) |
| `LEGAL_STATIC_INDEX_ENABLED` | Không | Bật index luật tĩnh (mặc định: `false`) |
| `CORS_ORIGINS` | Production | Danh sách domain cho phép (JSON array) |

Xem đầy đủ tại [`.env.example`](.env.example).

---

## Chạy Tests

```bash
conda activate gen_ai
cd backend
pip install pytest pytest-asyncio
python -m pytest tests/ -v
```

Bộ test hiện tại gồm **50 unit tests** không cần DB hay LLM:
- `test_security.py` — Password hashing, session tokens
- `test_auth.py` — Auth business logic
- `test_legal_retriever.py` — RRF fusion, metadata scoring, reranker, mode isolation
- `test_legal_rag_service.py` — skip_reasoning flag, query_deep routing, KG singleton

---

## API chính

| Endpoint | Mô tả |
|---|---|
| `POST /api/v1/auth/register` | Đăng ký |
| `POST /api/v1/auth/login` | Đăng nhập |
| `POST /api/v1/chat/{workspace_id}/stream` | Chat SSE streaming |
| `GET /api/v1/chat/{workspace_id}/history` | Lịch sử chat |
| `POST /api/v1/documents/upload/{workspace_id}` | Upload tài liệu |
| `GET /api/v1/documents/{workspace_id}` | Danh sách tài liệu |
| `GET /health` | Health check |

Tài liệu API đầy đủ: `http://localhost:8080/docs`

---

## Bảo mật

- Mật khẩu: PBKDF2-SHA256, 120.000 iterations, salt ngẫu nhiên 16 bytes
- Session token: `secrets.token_urlsafe(32)`, lưu dạng SHA-256 hash
- Workspace isolation: mỗi user chỉ truy cập được workspace của mình
- File upload: allowlist extension, giới hạn kích thước, tên file UUID ngẫu nhiên
- Rate limiting: 30 req/min (chat), 10 req/min (login), 5 req/min (register)
- CORS: chỉ cho phép origin được cấu hình

---

## License

MIT
