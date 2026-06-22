# KMS v5.62 — Lớp Quản lý Dự án (PM) trên nền v5.6 · bản đã phản biện

**VSI KMS · Project Management Layer — Thiết kế v0.2 (đã build & verified)**

> Bản này thay thế `KMS-PM-Design-v0.1.md`. Nó tiếp thu **hội đồng phản biện** (xem
> `KMS-PM-Design-v0.1_REVIEW.md`) và sửa từng phát hiện W1–W14. Khác biệt cốt lõi so với
> v0.1: **không còn quảng cáo "tái dùng nguyên vẹn"** cho phần thực thi quyền GHI — đó là
> thành phần **MỚI** (`kms_app/pm/authz.py`, write-PEP) được tách bạch tường minh. Mọi
> tuyên bố ở đây đều **khớp với mã nguồn chạy được** trong `KMS-v5.62_app/` và được
> chứng minh bằng self-test (`tests/test_pm.py`, 29/29 PASS; regression `test_pdp.py` 35/35 PASS).

---

## 0. Đính chính nền tảng (căn theo APP thật, không theo bản .md)

Phản biện v0.1 đối chiếu với *tài liệu* `KMS-v5.6.md`. Nhưng bản **hiện thực** `KMS-v5.6_app`
đã có sẵn một số thứ mà tài liệu .md không mô tả. v5.62 căn theo **app**:

| Điểm v0.1 bị nghi "viện dẫn sai" | Thực tế trong `KMS-v5.6_app` | Kết luận v5.62 |
|---|---|---|
| `authorize()` không tồn tại | **CÓ** — `security/pdp.py`, hàm `authorize()` 8 bước, nhưng **chỉ cho ĐỌC** | Tái dùng cho READ; **viết MỚI** write-PEP cho GHI (W1) |
| role enum PM/LEADER/ENGINEER/ADMIN không có | **CÓ** — `settings.ROLE_KINDS` + `users.role` | Hợp lệ; ánh xạ role↔project_role giữ nguyên |
| `documents.created_by/folder_id` không có | **CÓ** trong `db.py` schema | Hợp lệ |
| "workspace"/"spell check" không có | **CÓ** — `ingestion/workspace.py`, `ingestion/quality.py` | Hợp lệ |
| SQLite "đồng nhất v5.6" sai (v5.6 là Postgres) | App **là SQLite** | v5.62 giữ **SQLite** — *đúng* với app (W6 hạ cấp) |
| ADMIN bypass | App: ADMIN vượt **trần kind + scope phòng**, KHÔNG vượt credential/DCM/air-gap | v5.62: ADMIN = **break-glass có audit, có giới hạn** (W2) |

Tên task-contract đúng trong app là **`review_weekly_report`** (không phải `review_report`); v5.62 thêm `compile_project_progress` cạnh nó.

---

## 1. Bảng xử lý phản biện (W1–W14 → thay đổi cụ thể → bằng chứng)

| # | Phát hiện phản biện | Thay đổi trong v5.62 | Module | Self-test |
|---|---|---|---|---|
| **W1** | `authorize()` chỉ phân quyền ĐỌC; phía GHI chưa có cơ chế | **write-PEP MỚI** `authorize_action(actor, action, ctx)` với bảng *action × tiền-điều-kiện*; KHÔNG gọi là "tái dùng" | `pm/authz.py` | "PM tạo dự án ALLOW / ENGINEER DENY_ROLE_GLOBAL / non-member DENY_NOT_MEMBER" |
| **W2** | "ADMIN (bypass) như v5.6" — leo thang đặc quyền | ADMIN = **break-glass CÓ AUDIT, có giới hạn**: vượt project_role nhưng vẫn bị trần phân loại; không chạm credential/air-gap C3 | `pm/authz.py` (`role_gate` ghi "break-glass") | thể hiện trong trace; air-gap do PEP đọc giữ |
| **W3** | RTBF/retention không phủ bảng PM mới | `task_comments.mentions_json` (NER→DPIA) + `redacted` + action `redact_comment` (steward) | `pm/store.py` `add_comment`/`redact_comment` | "PII→DPIA" badge khi mention |
| **W4** | `connector_items`/`comment` thiếu cột phân loại | Thêm `data_class`+`permission_group`+`owner_project` vào `connector_items`; comment **kế thừa** `data_class` của task | `db.py`, `pm/connectors/base.py`, `pm/store.py` | "mọi item connector đều có data_class = 0 NULL" |
| **W5** | viện dẫn workspace/spell/manages/folder_id | Đối chiếu app: các thứ này **có thật** (mục 0) | — | regression `test_pdp` 35/35 |
| **W6** | "SQLite đồng nhất v5.6 (Postgres)" mâu thuẫn | App là SQLite ⇒ v5.62 dùng **chung instance SQLite**, mở rộng cùng `db.py` | `db.py` | app khởi động + seed OK |
| **W7** | race / lost-update | Cột `tasks.version` + **compare-and-swap** optimistic-lock; xung đột ⇒ từ chối "tải lại" | `pm/store.py` `_cas` | "cập nhật 2 (version cũ) bị từ chối · XUNG ĐỘT" |
| **W8** | highest-wins nhốt tiến độ vào C3 im lặng | Promote = sàn cứng `max_data_class`; **cảnh báo** khi nâng C3 + nút **xuất bản ≤C2 (lược nguồn C3)** | `pm/progress.py` (`cap_class`, `elevated_c3`) | đường `?run=shared` redact về C2 |
| **W9** | engineer không biết được giao việc/comment | **Inbox in-app** (không email): giao việc/comment/đổi-trạng-thái + "Công việc của tôi" | `pm/notify.py`, `/pm/inbox` | seed tạo 9 notification |
| **W10** | "tái dùng nguyên vẹn" cơ chế chưa-live | Đổi sang **"phụ thuộc có điều kiện"**: write-PEP tách MỚI; audit/PEP/corpus là cơ chế app đã hiện thực (chạy được) | toàn lớp | audit chain INTACT sau mọi thao tác PM |
| **W11** | vòng đời review không người duyệt · engineer-scope mâu thuẫn · "phạm vi Leader" mơ hồ | **Read = project-scoped** (mọi member thấy mọi task); **Write hẹp** (PM/LEADER, hoặc ENGINEER-assignee); **review→done cần PM/LEADER (SoD)**; assignee phải là member; "phạm vi Leader" = dự án Leader là member | `pm/authz.py` | "SoD DENY_SOD" + "ENGINEER KHÔNG đổi task người khác" + "giao non-member DENY_ASSIGNEE_NOT_MEMBER" |
| **biên dịch** | "tất định" đánh tráo schema↔nội dung; LLM phá determinism | **Không LLM**: aggregate = phép đếm; risks = rule-derived ⇒ tất định **nội dung** | `pm/progress.py` | "2 lần cùng input ⇒ cùng NỘI DUNG" |
| **W12–14** | DR/observability/error-UX/bootstrap/cache lifecycle | Bootstrap: PM tạo dự án ⇒ tự thành PM-member; mọi GHI vào audit (observability đường ghi); deny trả thông điệp + decision-trace; *(DR/cache-TTL: xem §9 "còn nợ")* | `pm/store.py`, `pm/web.py` | "create_project ⇒ creator=PM member" |

---

## 2. Kiến trúc (đặt trên v5.6, KHÔNG trùng lặp bảo mật)

```
        Trình duyệt (PM · Leader · Engineer)
                  │
        server.py (phiên · fail-closed)  ── routes.dispatch
                  │
   ┌──────────────┼──────────────────────────────────────────────┐
   │ pm/ (MỚI · v5.62)              │ KMS core v5.6 (TÁI DÙNG)     │
   │ • authz.py  ← WRITE-PEP (mới)  │ • pdp.authorize() ← READ     │
   │ • store.py  (CRUD + CAS lock)  │ • pep (PEP kép · corpus/lane)│
   │ • connectors/ (stub pluggable) │ • audit hash-chain           │
   │ • progress.py (contract+OKF)   │ • ingestion/store (OKF)      │
   │ • notify.py (inbox)            │ • scanners (secret/NER)      │
   │ • web.py (trang /pm/*)         │ • render/shell · workspace   │
   └──────────────┬────────────────┴──────────────────────────────┘
                  │ connectors (stub, read-only, scope min(caller,SA))
        ┌─────────▼──────────┐
        │ Jira / GitLab mock │  ← seeded · điểm cắm REST (chỉ ≤C2 egress)
        └────────────────────┘
```

**Hai PEP, hai trách nhiệm rạch ròi:**
- **READ-PEP** = `pdp.authorize()` (v5.6, 8 bước) — tái dùng nguyên vẹn cho việc *đọc* tài
  nguyên PM. PM resource dùng `kind="METADATA"` (trung tính với trần kind-doc) nên ranh giới
  thực thi là **membership + phân loại**, không phải trần kind.
- **WRITE-PEP** = `pm/authz.authorize_action()` (MỚI) — cho mọi *mutation*.

---

## 3. Mô hình dữ liệu (đã hiện thực — `db.py`)

7 bảng mới: `projects · project_members · tasks · task_comments · connector_items ·
progress_snapshots · notifications`. Điểm khác v0.1 (sửa phản biện):

- `tasks.version INTEGER` — optimistic-lock (W7); `tasks.approved_by` — ai duyệt review→done (W11).
- `task_comments.data_class` — kế thừa task (W4); `.mentions_json` (NER→DPIA, W3); `.redacted` (RTBF).
- `connector_items.data_class / permission_group / owner_project / status / quarantine_reason` (W4).
- `project_members.added_by / added_at` (audit thay đổi thành viên).
- `progress_snapshots.max_data_class / schema_version` (sàn cứng + tương thích ngược payload).

## 4. Write-PEP — bảng action × tiền-điều-kiện (`pm/authz.py`)

| action | Cổng vai trò | Tiền-điều-kiện thêm |
|---|---|---|
| create_project | global ∈ {PM, ADMIN} | data_class ≤ clearance |
| add_member / close_project | project_role = PM | close: không còn task chưa-done |
| create_task | project_role ∈ {PM, LEADER} | data_class ≤ **trần dự án** ≤ clearance |
| assign_task | {PM, LEADER} | **assignee phải là member** (W11) |
| change_status | {PM, LEADER}, hoặc ENGINEER-assignee | **review→done ⇒ buộc PM/LEADER (SoD, W11)** |
| comment | mọi member {PM, LEADER, ENGINEER} | comment kế thừa data_class task |
| compile_progress / export_progress / fetch_connector | {PM, LEADER} | nguồn lọc qua READ-PEP người chạy |
| redact_comment | PM (steward) | RTBF |

Fail-closed mặc định; ADMIN = break-glass có audit. Mọi mutation ghi `audit_logs` (kể cả deny ⇒ `near_miss=1`).

## 5. Phân quyền đọc vs ghi (giải mâu thuẫn W11)

- **ĐỌC = project-scoped, nhất quán:** mọi thành viên thấy **mọi** task/comment/progress của
  dự án mình; task C3 vẫn ẩn khỏi thành viên ≤C2 (qua `can_read` = READ-PEP).
- **GHI = hẹp:** PM/LEADER toàn quyền trong dự án; ENGINEER chỉ trên task **được giao**.
- ⇒ `đọc ⊇ comment ⊇ sửa-task-của-mình` — không còn nghịch lý "comment lên task không xem được".

## 6. Connector (P8 sửa)

Read-only · scope = **min(clearance người gọi, service-account C2)** ⇒ confused-deputy: kỹ sư
C3 vẫn không kéo được item C3 (SA chặn ở C2). Mỗi item mang `data_class`; secret/PII trong
payload ⇒ **quarantine** (scanner S5). Chỉ `≤ EGRESS_MAX_CLASS` được rời enclave (ràng buộc cho
REST production; bản này offline). Điểm cắm: `connectors/jira.py`, `gitlab.py` giữ nguyên chữ ký.

## 7. Biên dịch tiến độ (P9/P10 sửa) — task-contract `compile_project_progress`

- **Tất định THẬT (không LLM):** `aggregate` = đếm task theo trạng thái + %done; `assess` =
  rule-derived (quá hạn / blocked / chờ duyệt). Chạy 2 lần cùng input + cùng ngày ⇒ **cùng nội dung**.
- Nguồn (tasks + connector_items + PROGRESS_REPORT) lọc qua READ-PEP của **người chạy**.
- **Promote OKF:** `max_data_class` làm **sàn cứng**; ghi `.md` (`data/documents/progress/`) → `ingest_all`
  ⇒ concept trích dẫn được, versioned. **W8:** nếu chạm C3, cảnh báo + cho xuất bản bản **≤C2 (lược nguồn C3)**.

## 8. Trang web mới (`/pm/*`, nav "Dự án")

`/pm/projects` · `/pm/project?id=` · `/pm/board?project=` (kanban) · `/pm/task?id=` (chi tiết +
comment + đổi trạng thái + giao việc, mang `version` cho CAS) · `/pm/progress?project=` (biên dịch +
promote + bản ≤C2) · `/pm/connectors?project=` (sync + quarantine) · `/pm/inbox`. Khi một hành động
bị từ chối, trang hiển thị **decision-trace của write-PEP** (minh hoạ fail-closed).

## 9. Bằng chứng chạy được & phần còn nợ (no silent caps)

**Đã verify (KMS-v5.62_app):**
- `tests/test_pm.py` **29/29 PASS** · `tests/test_pdp.py` **35/35 PASS** (regression).
- Web (curl): hr1 non-member → `/pm/projects` rỗng + `/pm/board` 403; ENGINEER review→done → `DENY_SOD`;
  đổi task người khác → `DENY_ROLE_PROJECT`; version cũ → `XUNG ĐỘT`; promote → OKF `PROG-…md` ingest
  12 chunks; **chuỗi audit INTACT** sau toàn bộ thao tác PM (8 loại action).

**Còn nợ (chưa làm trong v0.2 — nêu rõ để không hiểu nhầm là đã phủ kín):**
- **DR/backup** chính thức (ngoài việc `data/` bền vững) — W12.
- **Cache-TTL/purge** cho `connector_items` (hiện sync idempotent, chưa có chính sách hết hạn).
- **RTBF hard-delete lan truyền** mới ở mức `redact_comment` thủ công, chưa nối chuỗi xoá toàn cục.
- Connector vẫn **stub offline** (chưa REST thật, đúng phạm vi air-gapped).
- Đồng thời mới chống **lost-update mức task** (chưa CAS cho membership/comment).

---

## 10. Lộ trình kế thừa P13 (đã khoá theo gate nền)

GĐ1 dự án+RBAC → GĐ2 task+comment+**write-PEP** → GĐ3 connector(stub) → GĐ4 biên dịch(tất định) →
GĐ5 OKF export. **Toàn bộ slice đã hiện thực & self-test** trong `KMS-v5.62_app`; GĐ "REST connector
thật" giữ ngoài phạm vi (điểm cắm sẵn sàng, chỉ ≤C2 egress).

_Build: `cd KMS-v5.62_app/kms_backend && python run.py` → http://127.0.0.1:8077 (tài khoản demo mật khẩu = tên đăng nhập; pm1/lead_dv/eng_pd1 là thành viên dự án mẫu)._
