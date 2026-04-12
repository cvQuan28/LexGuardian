# Backend Temp / Legacy Inventory

Thư mục này là nơi ghi nhận các thành phần legacy hoặc internal utility chưa nên xoá ngay.

## Mục tiêu

- Không xoá/move mạnh tay các file backend cũ khi chưa có kiểm chứng import/runtime.
- Giảm rủi ro làm gãy các compatibility path của hệ thống hiện tại.
- Tạo inventory rõ ràng trước khi thực hiện cleanup thật.

## Nhóm cần xem xét ở vòng cleanup sau

### Internal / admin-like legal endpoints trong `backend/app/api/legal.py`

Các route dưới đây hiện không thuộc core product flow `Ask / Review / Explore`:

- `/legal/extract-fields/{workspace_id}`
- `/legal/build-kg-relationships/{workspace_id}`
- `/legal/static/stats`
- `/legal/static/ingest-record`
- `/legal/static/ingest-dataset`
- `/legal/static/query`

Hướng xử lý sau:

- hoặc chuyển sang namespace `/legal/internal/*`
- hoặc gom vào router admin riêng
- hoặc ẩn sau feature flag

Hiện đã có hướng chuẩn hóa:

- `LEGAL_INTERNAL_API_ENABLED`
- `LEGAL_LEGACY_INTERNAL_ROUTES_ENABLED`

### Service modules cần audit usage kỹ trước khi move

- `backend/app/services/legal/legal_dataset_ingestor.py`
- `backend/app/services/legal/legal_chunk_augmentor.py`
- `backend/app/services/legal/static_indexer.py`
- `backend/app/services/legal/static_retriever.py`
- `backend/app/services/legal/legal_evaluator.py`

Lý do chưa move ngay:

- một số file còn được import lười trong runtime hoặc route internal
- move sớm có thể gây lỗi import khó phát hiện

## Nguyên tắc cleanup

- Chỉ move/xoá khi đã có:
  - import graph rõ ràng
  - route ownership rõ ràng
  - smoke test compile/import pass
- Ưu tiên `deprecate + inventory` trước `delete`.
