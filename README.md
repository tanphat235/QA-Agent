# QA Agent — Drawing Analyzer

Công cụ QA tự động cho bản vẽ kết cấu bê tông đúc sẵn (PDF). Upload bản vẽ, chọn các check cần chạy, hệ thống phân tích và trả báo cáo lỗi / cảnh báo theo từng nhóm (spelling, bending, rebar).

---

## Yêu cầu hệ thống

| Thành phần | Phiên bản |
|------------|-----------|
| Python | ≥ 3.13 |
| Poetry | để cài dependency backend |
| Node.js | ≥ 18 (cho frontend) |
| API key | `ANTHROPIC_API_KEY` (bắt buộc) |

---

## Cài đặt lần đầu

### 1. Clone repo và vào thư mục project

```bash
cd qa_agent
```

### 2. Cấu hình biến môi trường

Sao chép file mẫu và điền API key:

```bash
copy .env.example .env
```

Mở `.env` và thêm:

```env
ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Cài backend (Python)

```bash
poetry install
```

### 4. Cài frontend (React)

```bash
cd web
npm install
cd ..
```

---

## Khởi động ứng dụng

**Chạy đúng thứ tự** — mỗi service một cửa sổ terminal riêng:

| Bước | File | URL | Port |
|------|------|-----|------|
| 1 | `start_studio.bat` | LangGraph API | **2024** |
| 2 | `start_backend.bat` | FastAPI backend | **8001** |
| 3 | `start_frontend.bat` | Web UI (Vite) | **5173** |

Mở trình duyệt: **http://localhost:5173**

> LangGraph Studio (tùy chọn, để xem trace/debug graph):  
> https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024

### Khởi động thủ công (không dùng `.bat`)

```bash
# Terminal 1 — LangGraph
poetry run langgraph dev

# Terminal 2 — Backend
poetry run uvicorn qa_agent.server:app --host 0.0.0.0 --port 8001 --reload

# Terminal 3 — Frontend
cd web && npm run dev
```

---

## Hướng dẫn sử dụng Web UI

### Dashboard — Phân tích bản vẽ

1. **Upload PDF** — kéo thả hoặc bấm *Upload PDF File* (bản vẽ chính).
2. **Active Checks** — mở từng category (Spelling & Title Block, …), tick các sub-check cần chạy.
3. *(Tùy chọn)* **Supplementary Files**:
   - *Steel list PDF* — bật check `steel_list_check`.
   - *Overview plan PDF* — bật check `overview_plan_check`.
4. Bấm **Analyze** / **Re-Analyze** và chờ tiến trình hoàn tất.
5. Xem kết quả theo section: **Passed**, **Failed**, **Issues**.
6. Bấm **Highlight on PDF** để tải bản PDF có đánh dấu vị trí lỗi (nếu có).

### Define Rules — Tạo / sửa check

1. Sidebar → **Define Rules**.
2. Mở một check có sẵn → **Edit**, hoặc bấm **Add Check** để tạo rule mới.
3. Điền **Display Name**, **Description** (rule cho AI hoặc mô tả logic).
4. Với check mới: chọn **Category** (spell / bend / rebar).
5. **Requires Vision** — bật nếu check cần đọc trực tiếp từ PDF (model Sonnet); tắt = text-only (model Haiku, rẻ hơn).
6. Bấm **Save** — rule được lưu vào `QA AI Drawing/QA Knowledge/<domain>/<key>/<key>.md`.

Check user tạo mới tự bật **Debug Trace** — khi analyze, log backend in block `[trace][<check_key>]` để kiểm tra giá trị extract.

### Check History

Lịch sử các lần analyze được lưu trong trình duyệt (localStorage). Mở lại để xem báo cáo cũ mà không cần chạy lại.

---

## Các nhóm check

| Category | Mô tả | Trạng thái |
|----------|--------|------------|
| **spell** | Spelling & Title Block — chính tả, title block, mã cấu kiện, scale, … | Đang hoạt động |
| **bend** | Bending & Schedule — bảng uốn, lưới thép | Coming soon (UI) |
| **rebar** | Rebar Labels & Dims — nhãn cốt thép, kích thước | Coming soon (UI) |

Danh sách check trên Dashboard và Define Rules lấy từ cùng API `GET /api/checks` — không hardcode trong frontend.

---

## Check có logic Python (deterministic)

Một số user rule chạy bằng code Python (không gọi LLM), ví dụ:

| Check key | Nội dung |
|-----------|----------|
| `drawing_code` | So sánh mã cấu kiện góc trên-trái vs Drawing Title |
| `scale_check` | So sánh scale từng mặt cắt/ view với danh sách scale trong title block (`1:25`, `1:10`, `1:5`, …) |

Log debug khi analyze (cửa sổ `start_backend.bat` hoặc LangGraph):

```
[scale_check] title_block_scales=['1:25', '1:10', '1:5'] ...
[trace][scale_check] title_block_scales (allowed): ['1:25', '1:10', '1:5']
[trace][scale_check]   section[1] OK scale='1:25' ...
```

---

## Cấu trúc thư mục chính

```
qa_agent/
├── start_studio.bat      # LangGraph dev server (port 2024)
├── start_backend.bat     # FastAPI API (port 8001)
├── start_frontend.bat    # React UI (port 5173)
├── .env                  # API keys (không commit)
├── langgraph.json        # Cấu hình graph LangGraph
├── src/qa_agent/
│   ├── graph.py          # LangGraph pipeline
│   ├── server.py         # REST API + SSE analyze
│   ├── checks_registry.py
│   ├── extraction/       # Parse PDF + deterministic checks
│   └── nodes/            # spell_check, bend_check, rebar_check, …
├── web/                  # React + Vite frontend
└── QA AI Drawing/
    └── QA Knowledge/     # File .md định nghĩa từng check
        ├── spell/
        ├── bend/
        └── rebar/
```

Mỗi check là một file Markdown:

```
QA Knowledge/<domain>/<key>/<key>.md
```

Các section: `Display Name`, `Pass`, `Not Found`, `Requires Vision`, `Debug Trace`, `Description`, `Check Prompt`.

---

## API chính (backend :8001)

| Method | Endpoint | Mô tả |
|--------|----------|--------|
| `POST` | `/api/analyze` | Upload PDF + chạy graph (SSE stream) |
| `GET` | `/api/checks` | Danh sách check (built-in + user) |
| `POST` | `/api/checks` | Lưu / tạo check |
| `DELETE` | `/api/checks/{domain}/{key}` | Xóa user check |
| `GET` | `/api/extraction-fields` | Catalog field PDF cho Define Rules |
| `POST` | `/api/annotate` | PDF có highlight lỗi |

Frontend dev proxy `/api` → `http://localhost:8001` (xem `web/vite.config.ts`).

---