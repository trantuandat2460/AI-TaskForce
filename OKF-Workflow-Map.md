---
type: Workflow Map
title: OKF Intake → Active Workflow Map — VSI KMS
description: Bản đồ vòng đời một concept từ lúc nạp tới lúc truy hồi được, với các gate fail-closed và swimlane theo actor. Bám pipeline 6 tầng (S5) + ratify gate tier-(b) (S4) của KMS-v5.6.
version: 1.0
timestamp: 2026-06-18T00:00:00Z
---

# OKF Intake → Active · Workflow Map

> Đọc trong 20 giây: một tài liệu đi qua **6 gate fail-closed**. Bất kỳ gate nào
> không chắc chắn ⇒ **quarantine (mặc định C3)**, không bao giờ default-open. Chỉ
> **Data Steward** mới đẩy được sang `active`. Chỉ concept `active` mới truy hồi được.

---

## Sơ đồ swimlane (state machine)

```
 PRODUCER          INGEST/SCANNER          LLM ENRICH         DATA STEWARD        INDEX/STORE
 ────────          ──────────────          ──────────         ────────────        ───────────
[Nộp form] ──┐
 (Vùng A)    │
             ▼
        ┌─────────────────┐  G1 INGEST GATE (Tầng 1)
        │ Secret scanner  │  entropy + key/token formats
        │ NER PII scan    │  ── credential? ──► [HARD-BLOCK] không index, không LLM ✖
        └────────┬────────┘  ── personnel?  ──► [DPIA ROUTE] steward review (nhánh riêng)
                 │ pass
                 ▼
        ┌─────────────────┐  G2 STRUCTURE GATE (Tầng 2)
        │ convert→md      │  Docling (PDF/DOCX/PPTX) hoặc OKF trực tiếp
        │ hierarchical    │  cắt chunk theo heading
        │ chunk           │
        │ LLM auto-enrich │  đề xuất type/tags/entities/candidate flags
        └────────┬────────┘  🔒 KHÔNG gán data_class
                 │
                 ▼
        ┌─────────────────┐  G3 SECURITY-VALIDATION GATE (fail-closed)
        │ data_class hợp lệ? ──── thiếu/sai ──► QUARANTINE (mặc định C3) ⟶ Steward
        │ permission_group ∈ registry? ── không ──► REJECT INDEX ✖
        │ corpus khớp class? ──── lệch ──► REJECT (chống hạ cấp routing) ✖
        └────────┬────────┘
                 │ tất cả pass  →  status = 'quarantined'  (chưa truy hồi được)
                 ▼
                          ┌──────────────────────────┐  G4 RATIFY GATE (blocking, người)
                          │ Steward review:          │
                          │  • set vsi_data_class     │  ⟵ chỉ con người
                          │  • xác nhận perm_group    │
                          │  • xác nhận corpus/lane   │
                          │  • xác nhận flags         │
                          └───────┬─────────┬────────┘
                       quarantined│ → active│ hoặc → rejected / deprecated ✖
                                  ▼         
                          ┌─────────────────┐  G5 INDEX GATE
                          │ embed (bge-m3)  │  upsert vào corpus lane-scoped
                          │ upsert Qdrant   │  (C3 ⟶ corpus_c3_*, trong enclave)
                          │ ghi registry PG │  bảng concepts, status=active
                          │ audit hash-chain│  ratified_by / ratified_at
                          └────────┬────────┘
                                   ▼
                          ┌─────────────────┐  G6 ACTIVE
                          │ status = active │  ✅ truy hồi được qua funnel (S6)
                          │ permission-scoped│  PEP-1 (corpus+perm_group) → PEP-2 (per-resource)
                          └─────────────────┘
```

---

## Bảng trạng thái

| State | Ai đẩy | Điều kiện vào | Truy hồi được? |
| --- | --- | --- | --- |
| `submitted` | Producer | nộp form (Vùng A) | ❌ |
| `scanning` | hệ thống (G1) | qua secret/PII scan | ❌ |
| `enriching` | LLM (G2) | convert + chunk + đề xuất | ❌ |
| `quarantined` | hệ thống (G3) | qua validation HOẶC thiếu nhãn (mặc định C3) | ❌ |
| `active` | **Data Steward** (G4→G5) | steward ratify + index thành công | ✅ |
| `rejected` | Data Steward / G1 / G3 | credential hard-block · perm_group sai · corpus lệch | ❌ |
| `dpia_review` | hệ thống (G1) | phát hiện nhân sự (cờ hoặc NER) | ❌ (kỷ luật DPIA/RTBF) |
| `deprecated` | Data Steward | thay thế / hết hiệu lực | ❌ |

---

## Bất biến fail-closed (không gate nào được nới)

1. **Thiếu/sai `data_class` ⇒ quarantine + mặc định C3** — không bao giờ default-public.
2. **`is_credential=true` ⇒ hard-block** ngay G1 — không index, không vào LLM, chỉ ghi `doc_id`+cờ.
3. **`permission_group` không trong registry ⇒ từ chối index.**
4. **`corpus_id` lệch ranh giới phân loại ⇒ từ chối** (concept C3 không được trỏ corpus ≤C2).
5. **LLM chỉ đề xuất; chỉ Data Steward gán `data_class`** — ranh giới G2↔G4 là bất biến.
6. **Chỉ `status=active` mới truy hồi được**; mọi state khác vô hình với funnel S6.

---

## Đường tier-(c) rút gọn (tài liệu thô, đuôi dài)

Khối lượng lớn PDF/DOCX/PPTX không qua curate tay đi đường rút gọn:
`convert→md → chunk → embed → đóng dấu quyền theo path-glob`.
Ràng buộc fail-closed: **không path-glob nào khớp ⇒ deny/quarantine**, không bao giờ
gán mặc định rộng. Funnel truy hồi cho tier-(c) thu gọn còn `ACCESS FILTER + dense rank
(+ lexical tuỳ chọn)` vì thiếu okf_type/owner_project/tags/concept-link.
