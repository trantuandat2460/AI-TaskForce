# KMS v5.4 — Backend chạy thật (local, stdlib-only)

Cổng tri thức an toàn cho VSI: triển khai **thật** cấu trúc v5.4 — control-plane
(đăng nhập + menu theo vai trò) tách khỏi data-plane (`authorize()`), **PEP hai
giai đoạn**, query-rewrite, session state, kế thừa phân loại, re-authorize-on-replay,
orchestrator tất định và audit hash-chain. Chỉ dùng **thư viện chuẩn Python** —
không cần `pip`, chạy được trong môi trường chặn mạng/air-gapped.

> Câu trả lời của trợ lý hiện là **StubLLM tất định** (offline). Trọng tâm bản
> này là *hạ tầng kiểm soát truy cập + dữ liệu bền vững*. Cắm LLM thật: xem mục
> "Cắm LLM" bên dưới.

## Chạy nhanh
```bash
cd kms_backend
python run.py            # lần đầu tự seed (users + documents + ingest), rồi mở server
#   → http://127.0.0.1:8077
```
Tuỳ chọn: `python run.py --seed` (seed lại) · `python run.py --reset` (xoá DB rồi seed lại).

Yêu cầu: **Python 3.9+**. Không cài gì thêm.

### Tài khoản demo (mật khẩu = tên đăng nhập)
| user | vai trò | clearance | dùng để minh hoạ |
|---|---|---|---|
| `admin1` | ADMIN | C3 | thấy mọi dữ liệu, trang Dữ liệu/Nạp tài liệu/giả mạo audit |
| `eng_pd1` | ENGINEER | C3 | truy cập C3 core-ip, dự án SOVRA |
| `lead_dv` | LEADER | C3 | xem hồ sơ nhân sự cấp dưới (ReBAC) |
| `pm1` | PM | C2 | bị chặn IP/spec → fail-closed |
| `hr1` | HR | C2 | nhân sự theo mục đích HR |

## Cấu trúc thư mục (code tách bạch khỏi dữ liệu)
```
kms_backend/
├── run.py                  # điểm chạy: seed (nếu cần) + khởi động server
├── requirements.txt        # (rỗng — chỉ stdlib)
├── config/
│   └── settings.py         # MỌI cấu hình: đường dẫn, cổng, TTL, vai trò, LLM…
├── kms_app/                # ── TOÀN BỘ MÃ NGUỒN ──
│   ├── server.py           # HTTP server + middleware phiên (fail-closed)
│   ├── db.py               # schema SQLite + kết nối + helper Row↔dict
│   ├── seed.py             # tạo users + ghi documents mẫu + ingest
│   ├── security/           # passwords (PBKDF2) · sessions · pdp · pep · audit
│   ├── ingestion/          # permissions(front-matter) · chunking(parent/child) · store(docling→chunk→upsert)
│   ├── retrieval/          # search (keyword/overlap, lọc stopword)
│   ├── conversation/       # store · state(A12) · rewrite(A13)
│   ├── orchestrator/       # registry(task contract) · tasks(chạy tất định)
│   ├── llm/                # client (StubLLM ↔ HTTP vLLM/Viettel AI)
│   └── web/                # render(HTML/CSS) · routes(handler + pipeline mỗi lượt)
├── data/                   # ── TOÀN BỘ DỮ LIỆU RUNTIME (xem được) ──
│   ├── kms.db              # SQLite — mở bằng trình xem bất kỳ
│   ├── documents/          # kho nguồn .md (public|internal|confidential), có front-matter phân loại
│   ├── uploads/            # file thô trước khi ingest
│   └── exports/            # audit.csv xuất ra ở đây
└── tests/
    └── test_pdp.py         # 17 self-test: 6 lý do DENY + ALLOW + PEP + chuỗi audit + replay
```

## Nhìn thấy dữ liệu khi nhập
Ba cách, đều thật:
1. **File SQLite**: mở `data/kms.db` bằng *DB Browser for SQLite* / `sqlite3 data/kms.db` → xem mọi bảng (`documents`, `chunks`, `conversations`, `messages`, `message_citations`, `conversation_state`, `audit_logs`).
2. **Trong giao diện**: đăng nhập `admin1` → trang **Dữ liệu (xem bảng)** liệt kê mọi bảng và số dòng. Chat / chạy PDP / ingest rồi quay lại để thấy bản ghi mới.
3. **Kho tài liệu**: mở các file trong `data/documents/**/*.md` — mỗi file có *front-matter* khai báo `data_class`, `kind`, `owner_project`, `required_tags`… nên bạn thấy ngay phân loại.

### Thêm tài liệu mới
1. Tạo file `.md` trong `data/documents/<public|internal|confidential>/` với front-matter, ví dụ:
   ```markdown
   ---
   doc_id: R-100
   data_class: C3
   kind: SPEC_DETAIL
   owner_project: SOVRA
   required_tags: core-ip
   permission_group: vsi_confidential
   sensitive_level: restricted
   ---
   # Tiêu đề tài liệu
   ## Mục
   Nội dung…
   ```
2. Vào giao diện (admin) → **Nạp tài liệu** → *Reingest toàn bộ*. Ingest idempotent qua 2 fingerprint (content/permission): chỉ tài liệu mới/đổi mới được re-chunk.

## Mô hình bảo mật (tóm tắt)
- **authorize() 8 bước** (fail-closed, chặn sớm): credential → DCM gate `min(clearance,limit)` → ABAC tags → cô lập dự án → scope phòng (Foundry) → ReBAC nhân sự → trần vai trò. Đủ 6 lý do DENY có thể tái hiện ở trang **Kiểm tra quyền (PDP)**.
- **PEP-1** lọc thô theo `permission_group` (rẻ) → **PEP-2** `authorize()` lại từng tài nguyên (defense-in-depth).
- **max_data_class**: hội thoại kế thừa mức cao nhất của chunk đã trích (highest-wins).
- **Re-authorize-on-replay**: mở lại hội thoại cũ → từng trích dẫn được cấp quyền lại theo quyền *hiện tại*; hạ quyền ⇒ trích dẫn C3 bị ẩn.
- **Audit**: `current = SHA-256(payload + previous_hash)` + HMAC; `tests/test_pdp.py` và trang Nhật ký minh hoạ verify bắt được giả mạo.

## Triển khai lên server thật
Trong `config/settings.py`:
- `HOST = "0.0.0.0"` (hoặc giữ 127.0.0.1 sau reverse proxy), `PORT` tuỳ ý.
- Đặt sau **reverse proxy HTTPS** (nginx) → bật `COOKIE_SECURE = True`.
- Trỏ `DATA_DIR` sang **volume bền vững** (mount riêng) để dữ liệu không mất khi cập nhật mã.
- Thay `DEMO_AUTH = False` và nối **SSO/OIDC** của VSI (thay `_do_login` trong `kms_app/server.py`); bảng `users` giữ nguyên RBAC/ABAC.
- Chạy như dịch vụ: `systemd` (ExecStart=`python /opt/kms/run.py`) hoặc trong container. Server dùng `ThreadingHTTPServer`; với tải cao hơn đặt sau nginx và chạy nhiều tiến trình theo cổng.
- Sao lưu: chỉ cần backup `data/` (gồm `kms.db` + `documents/` + `secret.key`). **Giữ bí mật `secret.key`** (khoá HMAC chuỗi audit).

## Cắm LLM thật (thay StubLLM)
Trong `config/settings.py`: `LLM_BACKEND = "http"`, đặt `LLM_HTTP_URL` + `LLM_MODEL`.
`kms_app/llm/client.py` gọi endpoint OpenAI-compatible. **Ràng buộc lane**: routes
chọn `lane="C3_AIRGAP"` khi `max_data_class==C3` → phải trỏ tới vLLM **in-lane**;
chỉ `≤C2` mới được dùng uplink Viettel AI (thực thi P17 — C3 không bao giờ egress).
Tương tự, query-rewrite của hội thoại C3 cũng phải chạy bằng mô hình in-lane.

## Lộ trình lên kiến trúc đầy đủ (LLD)
Bản này là *reference chạy được*. Khi lên production theo LLD: thay tầng `chunks`
(SQLite) bằng **Qdrant** + **vLLM** embed/rerank, đặt **docling** thật vào
`ingestion/store.py:docling_to_markdown()` (PDF→markdown, offline trong lane), và
nối MCP tools (jira/gitlab) cho orchestrator. Hợp đồng `authorize()`/PEP/audit
giữ nguyên — chỉ thay tầng lưu trữ/suy luận.
