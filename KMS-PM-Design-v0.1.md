# Thiết kế Module Quản lý Dự án (PM) trên KMS v5.6 · v0.1

**VSI KMS · Project Management Layer — Tài liệu thiết kế (chưa code)**

_Lớp quản lý dự án đặt TRÊN nền KMS v5.6: lead engineer quản lý task · tài nguyên · đặc tả · báo cáo; báo cáo & code đến từ **Git/Jira** (connector stub, pluggable); KMS **biên dịch tiến độ dự án**; kỹ sư **giao tiếp theo task**; phân quyền cho **PM · Leader · Engineer**; kết quả **ghi ra file MD (OKF)**._

> Bản này là **thiết kế để duyệt trước khi build**. Phạm vi build (đã chốt): *toàn bộ slice* gồm Projects · Tasks · Task-comments · Git/Jira stub connectors · biên dịch tiến độ · export OKF `.md`. Tích hợp Git/Jira là **stub offline có điểm cắm** (giữ air-gapped), không gọi API thật.

---

## Tóm tắt điều hành

Lớp PM biến KMS từ "kho tri thức có phân quyền" thành "kho tri thức **gắn với công việc**": mỗi mẩu tri thức (spec, report, task note) sống trong ngữ cảnh một **dự án** và một **task** có chủ, có trạng thái, có quyền. Lớp này **không phát minh lại bảo mật** — nó tái dùng nguyên vẹn identity/RBAC/ABAC, `authorize()`, PEP kép, corpus/lane, audit hash-chain, OKF và workspace của KMS v5.6. Dữ liệu từ Git/Jira được nạp qua **connector** (bản này: stub tất định, có điểm cắm cho API thật qua uplink đã duyệt) và **được phân quyền y như mọi tài nguyên khác**. KMS biên dịch **tiến độ dự án** bằng một **task-contract tất định** (giống `review_weekly_report`), rồi **ghi ra một OKF concept `.md`** để tiến độ trở thành tri thức trích dẫn được, versioned trong git. Mọi thao tác đọc/ghi đi qua PEP và để lại vết audit.

## P1 · Mục tiêu & phạm vi

**Làm được gì:**
- PM tạo/đóng **dự án**, gán thành viên và vai trò trong dự án.
- Leader quản lý **task** thuộc phạm vi mình: tạo, giao việc, đổi trạng thái, gắn spec/tài nguyên.
- Engineer cập nhật task của mình và **trao đổi theo task** (comment).
- Liên kết **đặc tả/tài nguyên** (OKF documents v5.6) vào dự án/task.
- Nạp **report & code** từ Git/Jira (connector) và **biên dịch tiến độ** tổng hợp.
- **Ghi tiến độ ra MD** (OKF concept) — tri thức trích dẫn được.

**Ngoài phạm vi bản v0.1:** chỉnh sửa real-time đồng thời, Gantt/biểu đồ nâng cao, thông báo email, gọi API Git/Jira thật (chỉ để điểm cắm).

**Đối tượng:** PM (quản trị dự án), Leader (điều phối task + duyệt báo cáo), Engineer (thực thi + trao đổi).

## P2 · Kiến trúc tổng thể — đặt trên KMS v5.6

Lớp PM là **các bảng + trang + 2 task-contract mới**, dùng lại toàn bộ guardrail có sẵn:

```
        Trình duyệt (PM · Leader · Engineer)
                  │
        ChatUI/Proxy (bộ não)  ── PEP kép · audit · context-fencing (KMS v5.6)
                  │
   ┌──────────────┼───────────────────────────────────────────────┐
   │ PM module (MỚI)            │ KMS core (TÁI DÙNG)               │
   │ • projects/tasks/comments  │ • users · authorize() · corpus    │
   │ • progress compiler (task) │ • documents/OKF · workspace       │
   │ • OKF export of progress   │ • audit hash-chain · retrieval    │
   └──────────────┬─────────────┴───────────────────────────────────┘
                  │ connectors (stub, pluggable)
        ┌─────────▼──────────┐
        │ Jira / GitLab cache │  ← seeded mock (bản v0.1) · điểm cắm API thật
        └────────────────────┘
```

**Nguyên tắc tái dùng (không trùng lặp bảo mật):** mọi tài nguyên PM (task, comment, connector item, progress snapshot) là một **resource** có thuộc tính quyền và **đi qua `authorize()`** y như documents. Không có đường tắt nào bỏ qua PEP.

## P3 · Mô hình dữ liệu (DDL sketch)

Bảng mới (SQLite, đồng nhất kiểu với schema v5.6):

```sql
-- Dự án: PM sở hữu; data_class trần của dự án; gắn corpus/lane.
CREATE TABLE projects (
  project_id TEXT PRIMARY KEY, name TEXT, owner_pm TEXT,
  data_class TEXT, permission_group TEXT, corpus_id TEXT,
  status TEXT DEFAULT 'active', created_at TEXT, updated_at TEXT);

-- Thành viên dự án + vai trò trong dự án (project-scoped RBAC).
CREATE TABLE project_members (
  project_id TEXT, user_id TEXT, project_role TEXT,   -- PM|LEADER|ENGINEER
  PRIMARY KEY(project_id, user_id));

-- Task: có chủ, người giao, trạng thái, ưu tiên, mức phân loại riêng (≤ trần dự án).
CREATE TABLE tasks (
  task_id TEXT PRIMARY KEY, project_id TEXT, title TEXT, description TEXT,
  assignee TEXT, created_by TEXT, status TEXT DEFAULT 'todo',   -- todo|doing|review|done|blocked
  priority TEXT DEFAULT 'P2', data_class TEXT, required_tags_json TEXT,
  spec_doc_ids_json TEXT,                              -- liên kết tới OKF documents
  jira_ref TEXT, gitlab_ref TEXT, due_date TEXT, created_at TEXT, updated_at TEXT);

-- Giao tiếp theo task (context-fenced: comment là DỮ LIỆU, không phải lệnh).
CREATE TABLE task_comments (
  comment_id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, author TEXT,
  body TEXT, created_at TEXT);

-- Cache dữ liệu từ connector (Jira/GitLab) — đã gắn project + quyền.
CREATE TABLE connector_items (
  item_id TEXT PRIMARY KEY, source TEXT,              -- jira|gitlab
  project_id TEXT, kind TEXT,                         -- issue|commit|merge_request
  ref TEXT, title TEXT, author TEXT, state TEXT, ts TEXT, payload_json TEXT);

-- Ảnh chụp tiến độ do task-contract sinh (tất định, versioned).
CREATE TABLE progress_snapshots (
  snapshot_id TEXT PRIMARY KEY, project_id TEXT, generated_by TEXT,
  task_contract_version TEXT, summary_json TEXT, exported_doc_id TEXT, created_at TEXT);
```

Mở rộng bảng `documents` v5.6: thêm `project_id`, `task_id` (đã có `created_by`, `folder_id`) để spec/report gắn vào dự án/task. `authorize()` của resource bổ sung kiểm tra **project membership** (xem P4).

## P4 · Mô hình phân quyền (ma trận)

Quyền hiệu lực = **giao của** RBAC toàn cục (role v5.6) **và** vai trò trong dự án (`project_role`) **và** PEP/clearance trên từng resource. Fail-closed: không là thành viên dự án ⇒ không thấy task/comment/progress của dự án đó.

| Hành động | PM | Leader | Engineer |
| --- | --- | --- | --- |
| Tạo / đóng dự án, gán thành viên | ✅ | ❌ | ❌ |
| Tạo task, giao việc (assignee) | ✅ | ✅ (trong phạm vi) | ❌ |
| Đổi trạng thái task | ✅ | ✅ | ✅ *(chỉ task của mình)* |
| Comment trên task | ✅ | ✅ | ✅ *(task trong dự án mình)* |
| Gắn spec/tài nguyên vào task | ✅ | ✅ | ✅ *(task của mình)* |
| Chạy biên dịch tiến độ + export MD | ✅ | ✅ | ❌ |
| Xem task/comment/progress | ✅ (toàn dự án) | ✅ (toàn dự án) | ✅ *(task liên quan mình)* |

- **Engineer-scope** dùng lại tinh thần ReBAC v5.6 (`assignee == user` ↔ `manages`): kỹ sư thấy/sửa task **được giao cho mình** + comment trong dự án mình thuộc về.
- **data_class của task/spec ≤ trần dự án ≤ clearance người tạo** — đúng `min(clearance, limit)` + highest-wins; tạo nội dung vượt quyền bị từ chối (như workspace upload v5.6).
- Mọi quyết định vẫn qua **`authorize()` (PEP-2)** trên từng resource; danh sách task/dự án **chỉ dựng từ tập cho phép** (chống liệt kê).

## P5 · Quản lý Task & giao việc

- Task có vòng đời `todo → doing → review → done` (+ `blocked`), `priority` P0–P3, `assignee`, `due_date`.
- Leader giao việc trong phạm vi; chuyển trạng thái và reassign ghi **audit**.
- Task liên kết: `spec_doc_ids` (OKF documents), `jira_ref`, `gitlab_ref` (kéo trạng thái từ connector).
- Trang **Bảng task** (kanban đơn giản theo cột trạng thái) + **chi tiết task**.

## P6 · Giao tiếp theo task

- `task_comments` hiển thị theo dòng thời gian trong chi tiết task; người trong dự án trao đổi tại đây.
- **Context-fencing tuyệt đối:** nội dung comment (và item connector) khi đưa vào bất kỳ LLM/biên dịch nào đều là **dữ liệu**, không phải chỉ thị — đồng nhất S3 v5.6 (chống prompt-injection qua comment/issue).
- Comment kế thừa mức phân loại của task; replay/hiển thị lại qua PEP hiện thời.

## P7 · Tài nguyên & đặc tả

- Đặc tả/tài nguyên = **OKF documents v5.6** (đã có corpus/lane/PEP/scanner/quarantine), nay **gắn `project_id`/`task_id`**.
- Upload spec qua **workspace v5.6** (đã có hierarchy + security scan + spell check), chọn dự án/task đích.
- **Concept graph (S7)** dùng lại để trả lời "đổi spec này ảnh hưởng task/spec nào" (impact) — vẫn qua PEP.

## P8 · Connector Git/Jira (stub, pluggable)

- Module `kms_app/connectors/` với `jira.py`, `gitlab.py`; bản v0.1 trả **dữ liệu mock tất định** đã seed, nạp vào `connector_items` gắn `project_id`.
- **Điểm cắm API thật** giữ nguyên giao diện hàm (như `docling_to_markdown()` / StubLLM): khi lên production, cắm REST client gọi qua **uplink đã duyệt** — và phải tuân P11.
- **Bảo mật connector (kế thừa S8 v5.6):**
  - **Read-only**, **scope `min(caller, service-account)`** — chống *confused-deputy* (kỹ sư quyền thấp không mượn quyền service-account).
  - Item connector đi qua **scanner ingest** (secret/NER) ⇒ commit chứa secret/PII bị quarantine y như document.
  - **Egress theo tier:** chỉ ≤C2 được phép gọi uplink; dữ liệu C3 không bao giờ rời enclave (P17 v5.6).

## P9 · Biên dịch tiến độ dự án

- Một **task-contract tất định** `compile_project_progress` (T=0, schema-validated, ghi `task_contract_version`):
  1. `load_inputs` — tasks của dự án (qua PEP) + `connector_items` (Jira issues, GitLab commits/MR) + báo cáo tuần (PROGRESS_REPORT).
  2. `aggregate` — đếm task theo trạng thái, % done, blockers; đối chiếu Jira/GitLab.
  3. `assess` — rủi ro, lệch kế hoạch, hạng mục tuần tới.
  4. `validate` — output theo schema cố định.
- **Output schema:** `Summary · TaskStats · VsJiraGitlab · Risks · NextWeek · Blockers`.
- Chạy 2 lần cùng input ⇒ cùng dạng (tái lập, kiểm toán). Mọi nguồn đọc đều qua PEP của người chạy.

## P10 · Ghi ra MD (OKF export)

- Sau biên dịch, một bước **promote** ghi tiến độ thành **OKF concept `.md`** (dùng lại writer của workspace/`compact_session`):
  - frontmatter `vsi_*` kế thừa **`max_data_class` của dữ liệu đã chạm (hard floor, highest-wins)** + `project_id`.
  - lưu vào corpus đúng ranh giới; ingest → trích dẫn được, versioned trong git.
- Kết quả: "tiến độ dự án tuần N" trở thành **tri thức hạng nhất** — hỏi đáp RAG/đồ thị về nó như mọi concept khác.

## P11 · Bảo mật & tuân thủ (bất biến)

Lớp PM **phục tùng** 4 ranh giới + fail-closed của KMS v5.6:
1. **Phân loại + highest-wins** — task/comment/progress kế thừa mức cao nhất chạm tới; conversation/progress chạm C3 ⇒ C3-only.
2. **Air-gap C3** — dữ liệu C3 (kể cả task/connector item C3) không rời enclave; connector C3 in-lane.
3. **Chặn cứng credential** — scanner trên item connector + spec; secret ⇒ quarantine, không index.
4. **DPIA** — comment/issue nêu đích danh người → NER → DPIA/steward review.
- **PEP kép** trên mọi resource PM; **audit hash-chain** cho mọi thay đổi (create/assign/comment/compile/export) kèm danh tính + `task_contract_version`.
- **Context-fencing** cho comment + connector item.

## P12 · Giao diện (trang mới)

| Trang | Vai trò thấy | Nội dung |
| --- | --- | --- |
| `/projects` | tất cả (lọc theo membership) | danh sách dự án của tôi; PM: tạo dự án + gán thành viên |
| `/project/<id>` | thành viên | dashboard: thống kê task, tiến độ mới nhất, link spec/report |
| `/tasks` | thành viên | bảng kanban theo trạng thái; Leader: tạo/giao việc |
| `/task/<id>` | thành viên/assignee | chi tiết + đổi trạng thái + **comments** + spec liên kết |
| `/progress` | PM/Leader | chạy biên dịch tiến độ + **export MD**; xem snapshot trước |

Tái dùng shell/nav/CSS v5.6; thêm nhóm nav **"Dự án"**.

## P13 · Lộ trình & tiêu chí nghiệm thu

**Giai đoạn build (đã chốt: làm toàn bộ slice, theo thứ tự an toàn):**

| GĐ | Hạng mục | Tiêu chí nghiệm thu (acceptance) |
| --- | --- | --- |
| 1 | Projects + members + RBAC dự án | non-member **không** thấy dự án; chỉ PM tạo/gán; mọi list dựng từ tập authorize() |
| 2 | Tasks + giao việc + comments | engineer chỉ sửa task của mình; comment context-fenced; mọi thay đổi vào audit |
| 3 | Connectors stub + cache | item connector qua scanner (secret⇒quarantine); scope `min(caller,SA)`; ≤C2 mới egress |
| 4 | Biên dịch tiến độ (task-contract) | chạy 2 lần cùng input ⇒ cùng schema; nguồn đọc qua PEP của người chạy |
| 5 | Export OKF `.md` | progress kế thừa `max_data_class` làm sàn cứng; ingest ⇒ trích dẫn được; versioned |
| — | Toàn bộ | 4 ranh giới + fail-closed không bị nới ở bất kỳ trang/task nào; self-test bổ sung PASS |

**Nguyên tắc thứ tự:** quyền/dự án trước (GĐ1) → công việc (GĐ2) → dữ liệu ngoài (GĐ3) → tổng hợp (GĐ4) → tri thức hoá (GĐ5). Mỗi giai đoạn là một lát cắt chạy được, có self-test.

---

## Phụ lục A · Hợp đồng connector (giao diện điểm cắm)

```python
# kms_app/connectors/base.py  (bản v0.1: stub trả mock; production: REST qua uplink ≤C2)
def fetch_issues(project_id, caller_scope) -> list[dict]:   ...   # jira
def fetch_commits(project_id, caller_scope) -> list[dict]:  ...   # gitlab
# caller_scope = min(quyền người gọi, quyền service-account) — chống confused-deputy
```

## Phụ lục B · Schema output biên dịch tiến độ

```json
{ "Summary": "...", "TaskStats": {"todo":N,"doing":N,"review":N,"done":N,"blocked":N,"percent_done":N},
  "VsJiraGitlab": "...", "Risks": ["..."], "NextWeek": ["..."], "Blockers": ["..."] }
```

## Phụ lục C · Ánh xạ vai trò KMS ↔ vai trò dự án

| role v5.6 (toàn cục) | project_role mặc định | Ghi chú |
| --- | --- | --- |
| PM | PM | sở hữu dự án |
| LEADER | LEADER | điều phối task, duyệt báo cáo |
| ENGINEER | ENGINEER | thực thi task được giao |
| ADMIN | (bypass) | thấy tất cả (như v5.6) |

---

_Khi bản thiết kế này được duyệt, sẽ build theo P13 vào `KMS-v5.6_app/kms_backend/` (module `kms_app/pm/` + `kms_app/connectors/` + trang web mới), tái dùng skill `vsi_design_to_app` và giữ nguyên mọi guardrail v5.6._
