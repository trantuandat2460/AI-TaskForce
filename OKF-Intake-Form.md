---
type: Intake Form Template
title: OKF Knowledge Intake Form — VSI KMS
description: Biểu mẫu nạp tri thức vào KMS, ánh xạ 1:1 sang OKF frontmatter + các điểm ra quyết định bảo mật của con người. Bám S3/S4/S5 của KMS-v5.6.
version: 1.0
timestamp: 2026-06-18T00:00:00Z
---

# OKF Knowledge Intake Form

> Mục đích: chuẩn hoá việc đưa một tài liệu / concept vào KMS sao cho **mỗi đơn vị
> tri thức mang theo nhãn bảo mật của chính nó** trước khi được index. Form chia làm
> 3 vùng theo *ai được quyền điền*: **A — Producer**, **B — LLM auto-enrich (đề xuất)**,
> **C — Data Steward (phê chuẩn, blocking)**. Ranh giới giữa B và C là bất biến bảo mật:
> máy chỉ *đề xuất cấu trúc*, con người *phê chuẩn quyền truy cập*.

---

## Vùng A · Producer điền (định danh & cấu trúc)

| Trường | Bắt buộc | Ví dụ (SOVRA) | Ghi chú |
| --- | --- | --- | --- |
| `type` (okf_type) | ✅ | `RTL Module Spec` | routing / filter / hiển thị |
| `title` | ✅ | `Turbo Encoder — Datapath MAC` | |
| `description` | ⬜ | `Đặc tả khối MAC trong datapath bộ mã Turbo.` | tuỳ chọn — thiếu KHÔNG bị loại (rộng lượng với cấu trúc) |
| `resource` | ⬜ | `git+ssh://vsi-internal/sovra/turbo/datapath/mac` | URI canonical nếu có asset |
| `tags` | ⬜ | `[sovra, turbo, datapath, core-ip]` | |
| `source_file` | ✅ | `RAG/documents/sovra/turbo/datapath/mac.md` | đường dẫn file gốc (filesystem = nguồn-chân-lý) |
| `okf_concept_id` (đề xuất) | ✅ | `sovra/turbo/datapath/mac` | = đường dẫn bỏ `.md`; business key bền vững |
| `owner_project` | ✅ | `SOVRA` | cô lập dự án (PEP-2) |
| `owner_dept` | ✅ | `WS4` | |
| **Candidate flags (tự khai, mặc định false)** | | | máy/người *đề xuất*, không quyết định cuối |
| `candidate_is_credential` | ✅ | `false` | nếu true ⇒ ứng viên hard-block |
| `candidate_is_personnel_report` | ✅ | `false` | nếu true ⇒ ứng viên DPIA |
| `candidate_subject_person` | ⬜ | `null` | tên người nếu là báo cáo nhân sự |
| **Đề xuất phân loại (KHÔNG ràng buộc)** | | | |
| `proposed_data_class` | ⬜ | `C3` | chỉ là *gợi ý* cho Steward — KHÔNG có hiệu lực tới khi Vùng C phê chuẩn |
| `proposed_permission_group` | ⬜ | `sovra_core` | gợi ý; phải tồn tại trong registry mới được duyệt |

> ⚠️ Producer **không** tự kích hoạt phân loại. `proposed_*` chỉ là đầu vào cho review.

---

## Vùng B · LLM auto-enrich đề xuất (tier-(b), advisory)

Tại ingest, một LLM trích xuất cấu trúc và **đề xuất** — toàn bộ vào trạng thái
`status='quarantined'`, KHÔNG truy hồi được, tới khi Vùng C lật trạng thái.

| Trường máy-đề-xuất | Ví dụ | Bản chất |
| --- | --- | --- |
| `suggested_okf_type` | `RTL Module Spec` | gợi ý |
| `suggested_tags` | `[turbo, mac, datapath]` | gợi ý |
| `extracted_entities` | `[Turbo, MAC, datapath]` | NER |
| `candidate_flag_credential` | `false` ⟵ secret scanner (entropy + key formats) | độc lập với cờ tự khai |
| `candidate_flag_personnel` | `false` ⟵ NER PII scan | độc lập với cờ tự khai |

> 🔒 Bất biến: **LLM KHÔNG BAO GIỜ gán `vsi_data_class`.** Gán phân loại là quyết định
> bảo mật của con người (S3/S4).

---

## Vùng C · Data Steward phê chuẩn (RATIFY GATE — blocking)

Chỉ Data Steward được điền vùng này. Hành động cuối: lật `status: quarantined → active`.

| Trường (→ frontmatter `vsi_`) | Bắt buộc | Quy tắc fail-closed |
| --- | --- | --- |
| `vsi_data_class` `{C1\|C2\|C3}` | ✅ | thiếu/sai ⇒ **quarantine + mặc định C3**; KHÔNG bao giờ mặc định "public" |
| `vsi_permission_group` | ✅ | không có trong registry quyền ⇒ **từ chối index** |
| `vsi_owner_project` | ✅ | cô lập dự án (PEP-2) |
| `vsi_owner_dept` | ✅ | |
| `vsi_required_tags` | ⬜ | ABAC tag (PEP-2) |
| `vsi_corpus_id` | ✅ | **phải khớp ranh giới phân loại** — concept C3 trỏ corpus ≤C2 ⇒ **từ chối** (chống hạ cấp qua routing) |
| `vsi_lane` `{C3_ENCLAVE\|SECURED}` | ✅ | C3 ⇒ `C3_ENCLAVE`; ≤C2 ⇒ `SECURED` |
| `vsi_is_credential` | ✅ | `true` ⇒ **CHẶN CỨNG**: không index, không vào LLM; chỉ ghi nhận tồn tại |
| `vsi_is_personnel_report` | ✅ | `true` ⇒ vào phạm vi **DPIA** (retention/RTBF) |
| `vsi_subject_person` | ⬜ | |
| `status` | ✅ | `quarantined → active` (hoặc `rejected`/`deprecated`) |
| `ratified_by` / `ratified_at` | ✅ | đi vào audit hash-chain |

---

## Đầu ra cuối — concept OKF đã ratify (ví dụ SOVRA)

```yaml
---
# —— OKF chuẩn ——
type: RTL Module Spec
title: Turbo Encoder — Datapath MAC
description: Đặc tả khối MAC trong datapath bộ mã Turbo.
resource: git+ssh://vsi-internal/sovra/turbo/datapath/mac
tags: [sovra, turbo, datapath, core-ip]
timestamp: 2026-06-18T09:00:00Z
# —— VSI Security Profile (Steward đã phê chuẩn) ——
vsi_data_class: C3
vsi_permission_group: sovra_core
vsi_owner_project: SOVRA
vsi_owner_dept: WS4
vsi_required_tags: [core-ip]
vsi_is_personnel_report: false
vsi_subject_person: null
vsi_is_credential: false
vsi_corpus_id: corpus_c3_sovra
vsi_lane: C3_ENCLAVE
---

# Schema
...
# Examples
...
# Citations
[1] [SAURIA datapath ref](/refs/sauria-datapath.md)
```
