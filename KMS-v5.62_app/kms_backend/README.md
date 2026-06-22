# KMS v5.62 — Backend chạy thật + Lớp Quản lý Dự án (PM) (local, stdlib-only)

Cổng tri thức có phân quyền cho VSI: triển khai **thật** cấu trúc v5.6 — control-plane
(đăng nhập + menu theo vai trò) tách khỏi data-plane (`authorize()`), **PEP kép**
(PEP-1 metadata + PEP-2 per-resource), **named-corpus isolation + lane routing**,
**phễu truy xuất 5 lớp + RRF**, **concept graph** (related/impact qua PEP), **scanner
credential/NER ở ingest** (fail-closed quarantine), query-rewrite, session state,
kế thừa phân loại (highest-wins), re-authorize-on-replay, orchestrator tất định và
audit hash-chain. Chỉ dùng **thư viện chuẩn Python** — không cần `pip`, chạy được
trong môi trường chặn mạng / air-gapped.

> **v5.62 thêm Lớp PM** (`kms_app/pm/`) theo thiết kế **KMS-v5.62.md** — đã tiếp thu hội
> đồng phản biện (`KMS-PM-Design-v0.1_REVIEW.md`). Bổ sung mới quan trọng nhất là
> **write-PEP** (`pm/authz.py`): nền v5.6 chỉ có `authorize()` cho ĐỌC; lớp PM thêm
> phân quyền cho mọi hành động GHI (tạo dự án · giao việc · đổi trạng thái · comment ·
> biên dịch tiến độ). Kèm: optimistic-lock chống lost-update, connector Jira/GitLab (stub)
> có data_class + scope min(caller,SA), biên dịch tiến độ **tất định (không LLM)** → OKF,
> và inbox in-app. Xem `tests/test_pm.py` (29 self-test).

> Sinh từ thiết kế **KMS-v5.6.md / KMS-v5.62.md** bằng skill `vsi_design_to_app`. Câu trả
> lời của trợ lý là **StubLLM tất định** (offline); trọng tâm bản này là *hạ tầng kiểm
> soát truy cập + dữ liệu bền vững*. Cắm LLM thật: xem mục "Cắm LLM".

## Chạy nhanh
```bash
cd kms_backend
python run.py            # lần đầu tự seed (users + OKF documents + ingest), rồi mở server
#   (nếu 'python' không có, dùng: python3 run.py)
#   → http://127.0.0.1:8077
```
Tuỳ chọn: `python run.py --seed` (seed lại) · `python run.py --reset` (xoá DB rồi seed lại).
Self-test: `python -m tests.test_pdp` (35) · `python -m tests.test_pm` (29 — write-PEP/lock/connector/isolation).
(Windows: đặt `set PYTHONUTF8=1` để in được tiếng Việt ra console.)

Yêu cầu: **Python 3.9+**. Không cài gì thêm.

### Tài khoản demo (mật khẩu = tên đăng nhập)
| user | vai trò | clearance | vai trò dự án mẫu | dùng để minh hoạ |
|---|---|---|---|---|
| `admin1` | ADMIN | C3 | (break-glass) | thấy mọi dữ liệu; trang Dữ liệu/Nạp tài liệu/giả mạo audit |
| `eng_pd1` | ENGINEER | C3 | ENGINEER | task được giao; review→done bị chặn (SoD); kanban |
| `lead_dv` | LEADER | C3 | LEADER | tạo/giao task; duyệt review→done; biên dịch tiến độ |
| `pm1` | PM | C2 | PM (chủ dự án) | tạo dự án + gán thành viên; connector sync; promote OKF |
| `hr1` | HR | C2 | (không thành viên) | minh hoạ **non-member → 403 / liệt kê rỗng** |

### Thử nhanh lớp PM (v5.62)
1. `pm1` → **Dự án** → mở `PRJ-SOVRA_KMS` → **Bảng công việc** (kanban 5 cột).
2. `eng_pd1` → **Hộp thư** (được giao việc) → mở task của mình, đổi `doing→review` (OK); thử
   `review→done` → **DENY_SOD** (chỉ PM/LEADER duyệt).
3. `hr1` → **Dự án** rỗng; mở `/pm/board?project=PRJ-SOVRA_KMS` → **403** (non-member, fail-closed).
4. `pm1` → **Connector** → Sync → item Jira C3 **vắng mặt** (scope min(caller,SA)); commit có khoá → **quarantine**.
5. `pm1` → **Tiến độ** → Biên dịch (tất định) → **Promote ra OKF** → vào **Tài nguyên** thấy concept `PROG-…` trích dẫn được.

## Cấu trúc thư mục (code tách bạch khỏi dữ liệu)
```
kms_backend/
├── run.py                  # điểm chạy: seed (nếu cần) + khởi động server
├── requirements.txt        # (rỗng — chỉ stdlib)
├── config/
│   └── settings.py         # MỌI cấu hình: paths, port, CORPORA + LANE_REACHES, funnel, scanner, LLM…
├── kms_app/                # ── TOÀN BỘ MÃ NGUỒN ──
│   ├── server.py           # HTTP server + middleware phiên (fail-closed)
│   ├── db.py               # schema SQLite (documents+corpus/lane/status, chunks, concept_links…) + helper
│   ├── seed.py             # users + OKF documents mẫu (vsi_ frontmatter) + ingest
│   ├── security/           # passwords · sessions · pdp(authorize 8 bước) · pep(PEP kép + corpus_reachable) · audit · accounts(quản trị user)
│   ├── ingestion/          # permissions(OKF vsi_) · scanners(secret+NER) · chunking · store(scan→chunk→upsert→graph)
│   ├── retrieval/          # search — phễu 5 lớp: ACCESS→FACET→RANK(RRF)→RERANK→(GRAPH ở routes)
│   ├── graph/              # concept — related/impact 1–2 hop, MỌI traversal qua PEP
│   ├── conversation/       # store · state · rewrite
│   ├── orchestrator/       # registry(task contract) · tasks(tất định)
│   ├── llm/                # client (StubLLM ↔ HTTP vLLM/Viettel AI, lane-aware)
│   └── web/                # render(HTML/CSS + nav) · routes(pipeline mỗi lượt + trang Đồ thị)
├── data/                   # ── TOÀN BỘ DỮ LIỆU RUNTIME (xem được) ──
│   ├── kms.db              # SQLite — mở bằng trình xem bất kỳ
│   ├── documents/          # kho OKF .md (public|internal|confidential), front-matter vsi_*
│   ├── uploads/  exports/  # file thô / audit.csv
└── tests/test_pdp.py       # 30 self-test: 6 DENY + ALLOW + PEP + corpus reach + scanner + OKF + audit + replay
```

## Bản đồ S(thiết kế) → module(code)
| Mục thiết kế v5.6 | Module |
|---|---|
| S3 Mô hình bảo mật — PEP kép, corpus/lane, fail-closed | `security/pep.py`, `security/pdp.py`, `config/settings.py` (CORPORA/LANE_REACHES) |
| S4 Mô hình tri thức — OKF vsi_ frontmatter, quy tắc tách đôi | `ingestion/permissions.py` |
| S5 Pipeline ingest — scanner tầng-1, quarantine | `ingestion/scanners.py`, `ingestion/store.py` |
| S6 Truy xuất — phễu 5 lớp + RRF | `retrieval/search.py` (+ GRAPH EXPAND ở `web/routes.py`) |
| S7 Đồ thị tri thức — related/impact qua PEP | `graph/concept.py`, trang `/graph` |
| S8 Điều phối tác vụ — task contract tất định | `orchestrator/` |

## Nhìn thấy dữ liệu khi nhập
1. **File SQLite**: `sqlite3 data/kms.db` → mọi bảng (`documents` có `corpus_id/lane/status`, `chunks`, `concept_links`, `conversations`, `messages`, `message_citations`, `conversation_state`, `audit_logs`).
2. **Giao diện**: `admin1` → **Dữ liệu (xem bảng)**; **Tài nguyên** (cột corpus + status quarantine); **Đồ thị tri thức** (related/impact).
3. **Kho OKF**: mở `data/documents/**/*.md` — front-matter `vsi_*` khai báo phân loại + corpus + cạnh `related`.

### Thêm tài liệu OKF mới
```markdown
---
doc_id: R-100
vsi_data_class: C3
vsi_corpus_id: corpus_c3
vsi_kind: SPEC_DETAIL
vsi_owner_project: SOVRA
vsi_required_tags: core-ip
vsi_permission_group: vsi_confidential
related: R-002, R-004
---
# Tiêu đề concept
Nội dung… liên kết tới [[R-004]].
```
Vào (admin) → **Nạp tài liệu** → *Reingest toàn bộ*. Ingest idempotent qua 2 fingerprint
(content/permission). **Fail-closed**: thiếu/sai `vsi_data_class` → quarantine + mặc định C3;
concept C3 trỏ corpus ≤C2 → từ chối; scanner bắt credential/PII chưa gắn cờ → quarantine.

## Mô hình bảo mật (tóm tắt)
- **authorize() 8 bước** (fail-closed, chặn sớm): credential → DCM gate `min(clearance,limit)` → ABAC tags → cô lập dự án → scope phòng (Foundry) → ReBAC nhân sự → trần vai trò. Đủ 6 lý do DENY tái hiện ở trang **Kiểm tra quyền (PDP)**.
- **PEP kép**: **PEP-1** lọc thô theo `permission_group` + **corpus reachable** (lane) — corpus C3 *vắng mặt* khi truy vấn ngoài enclave (air-gap defense-in-depth). **PEP-2** `authorize()` lại từng tài nguyên.
- **Phễu 5 lớp (S6)**: ACCESS FILTER → FACET NARROW → RANK (dense ║ lexical, trộn **RRF**) → RERANK (1 lần) → GRAPH EXPAND (qua PEP).
- **Concept graph (S7)**: related = đi xuôi cạnh; impact = đảo chiều. Cạnh tới concept ngoài quyền **bị drop hoàn toàn** — không tên, không số đếm (đồ thị không phải cửa hậu).
- **max_data_class**: hội thoại kế thừa mức cao nhất chunk đã trích (highest-wins).
- **Re-authorize-on-replay**: mở lại hội thoại cũ → từng trích dẫn được cấp quyền lại theo quyền *hiện tại*; hạ quyền ⇒ trích dẫn C3 bị ẩn.
- **Audit**: `current = SHA-256(payload + previous_hash)` + HMAC; trang Nhật ký + `tests/test_pdp.py` minh hoạ verify bắt được giả mạo.

## Tải lên & thư mục — workspace người dùng (mọi user)
Mọi người dùng (không chỉ admin) vào **Tải lên & thư mục** (`/workspace`): tự **tạo thư mục**
và **upload tài liệu trong hierarchy của mình**. Fail-closed:
- **data_class ≤ clearance** (PM C2 không tạo được C3); **permission_group ∈ groups**; **owner_project ∈ projects**.
- **Quét bảo mật trước khi index**: secret-scanner thấy credential → **chặn upload**; NER nghi PII mà
  *chưa khai cờ* → **quarantine** chờ Data Steward (không tự phân loại — đúng S3).
- **Kiểm chính tả/chất lượng** (`ingestion/quality.py`): lỗi lặp từ / sai chính tả phổ biến / ký tự lặp →
  cảnh báo; phải sửa hoặc tick *“bỏ qua cảnh báo”* mới upload.
- File ghi xuống `data/documents/<folder>/…md` (OKF frontmatter) rồi ingest — filesystem vẫn là nguồn-chân-lý.
- Mọi thao tác (`create_folder` / `upload_document`) vào **audit hash-chain**.

Admin **Nạp tài liệu** (`/ingest`) vẫn là công cụ *reingest toàn bộ*. `tests/test_pdp.py` có 35 self-test
(gồm hierarchy upload + spell check).

## Quản trị tài khoản (ADMIN-only)
Đăng nhập `admin1` → **Quản trị tài khoản** (`/users`): **tạo / sửa / xoá** người dùng và **gán quyền**
(role · clearance · permission_group · tags ABAC · dự án · manages · HR-purpose). Fail-closed: nhóm
quyền/clearance/vai trò ngoài tập hợp lệ bị từ chối; **không xoá được chính mình hay ADMIN cuối cùng**
(chống tự khoá); xoá user thu hồi luôn phiên đang mở. Mọi thao tác ghi **audit hash-chain**
(`admin:create_user` / `admin:update_user` / `admin:delete_user`).

## Kịch bản nên thử
1. `eng_pd1` hỏi *“Mô hình phân quyền DCM hoạt động thế nào?”* → trace 5 lớp; GRAPH EXPAND thêm concept C3 liên quan; badge hội thoại leo C3.
2. `pm1` hỏi cùng câu → ACCESS FILTER chỉ giữ doc ≤C2 (corpus_c3 vắng mặt) → PEP-2 chặn → **fail-closed**.
3. **Đồ thị tri thức** với `eng_pd1` chọn `R-003` → thấy `R-004` (cross-corpus C2→C3); với `pm1` → đích C3 **drop sạch**.
4. **Tài nguyên**: thấy `R-010/R-015/R-016` ở trạng thái **quarantine** (cờ credential / secret-scanner / NER-PII).
5. **Nhật ký** → Verify; (admin) Giả mạo một dòng → chuỗi **ĐỨT**.

## Triển khai lên server thật
Trong `config/settings.py`: `HOST="0.0.0.0"` sau reverse proxy HTTPS (bật `COOKIE_SECURE=True`);
trỏ `DATA_DIR` sang volume bền vững; `DEMO_AUTH=False` + nối **SSO/OIDC** (thay `_do_login`);
chạy như `systemd`/container. Sao lưu chỉ cần `data/` (gồm `kms.db` + `documents/` + `secret.key` —
**giữ bí mật `secret.key`**, khoá HMAC chuỗi audit).

## Cắm LLM thật (thay StubLLM)
`LLM_BACKEND="http"`, đặt `LLM_HTTP_URL` + `LLM_MODEL`. **Ràng buộc lane (S3)**: routes chọn
`lane="C3_AIRGAP"` khi `max_data_class==C3` → phải trỏ tới vLLM **in-lane**; chỉ `≤C2` mới dùng
uplink Viettel AI (C3 không bao giờ egress). Query-rewrite hội thoại C3 cũng chạy in-lane.

## Lộ trình lên kiến trúc đầy đủ (LLD)
Bản này là *reference chạy được*. Khi lên production: thay tầng `chunks` (SQLite) bằng **Qdrant**
+ **vLLM** embed/rerank; đặt **docling** thật vào `ingestion/store.py:docling_to_markdown()`
(PDF→markdown offline trong lane); nâng `concept_links` lên **ReBAC/graph engine** khi cần truy
vấn quan hệ sâu; nối **MCP tools** (jira/gitlab) cho orchestrator. Hợp đồng
`authorize()`/PEP/corpus/audit giữ nguyên — chỉ thay tầng lưu trữ/suy luận.
