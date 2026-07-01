# DTR Subsystem — Defect Traceability cho KMS

Mô tả lớp truy vết lỗi trên nền Jira + GitHub, ghép trực tiếp vào KMS đang xây dựng. DTR là lớp hợp nhất và truy vết: Jira là canonical về vấn đề và trạng thái, GitHub bổ sung cách fix được thực hiện, KMS gắn hai thứ đó lại và đưa vào kho tri thức để tra cứu.

- Phạm vi: v1 · Jira-trusted
- Nguồn: Jira · GitHub
- Sync: poll 1h / thủ công
- Mọi dữ liệu bug đi qua PEP · DCM

---

## 1. Mục tiêu & phạm vi

DTR biến một vấn đề rời rạc trên Jira thành một bản ghi có truy vết đầy đủ — phát hiện ở đâu, sửa bằng commit/PR nào, đang ở bước nào trong vòng đời — rồi kết tinh thành tri thức tra cứu được khi đã đóng.

### Trong phạm vi (v1)

- Hợp nhất Jira + GitHub quanh một canonical record cho mỗi lỗi, khóa nối là Jira issue key.
- Suy ra trạng thái thật (`lifecycle_state`) từ Jira status + GitHub PR state, thay vì tin riêng status của Jira.
- Phát hiện bất nhất Jira↔GitHub mà không cần tín hiệu từ tool mô phỏng: code đã merge nhưng ticket chưa đóng; ticket đóng nhưng không có fix.
- Kết tinh tri thức: khi lỗi đóng, sinh một knowledge artifact đưa vào semantic index để trả lời "trước xử lý vấn đề này thế nào".

### Ngoài phạm vi (v1) — có chủ đích

- Không ingest tín hiệu từ vManager / PrimeTime / Calibre. Đạt tin Jira, nên nguồn sự thật về "vấn đề" là Jira, không phải log tool.
- Hệ quả phải chấp nhận: KMS không tự phát hiện "vấn đề tồn tại nhưng chưa ai tạo ticket". Rủi ro còn lại là human error trong kỷ luật Jira, không phải lỗ hổng kiến trúc.

> **Nguyên tắc phân vai.** Jira = nhiệm vụ và trạng thái vấn đề (canonical). GitHub = source code và release (fix). KMS = gắn hai thứ, suy ra vòng đời, đưa vào kho tri thức. DTR không thay thế Jira; nó ngồi trên Jira.

> **Cửa mở rộng đã chừa.** Trường `interaction_type` và chữ ký `reconcile(jira_status, pr_state, verification=None)` để sẵn cho việc thêm tín hiệu verification (vManager) cho riêng mảng DV về sau — thêm một input, không đập schema.

---

## 2. Vị trí trong KMS

DTR là một ingestion source mới. Nó không mở đường riêng vào index — mọi dữ liệu bug đi qua đúng PEP/DCM như corpus tài liệu, vì dữ liệu bug là C2/C3.

Subsystem gồm hai phần *mới* (Sync Worker + DTR Store) và tái dùng bốn thành phần *đã có* của KMS core (DCM, Audit chain, PEP, Semantic index).

```
   Jira API              GitHub API
       │                     │
       ▼                     ▼
   ┌───────────────────────────────────┐   MỚI
   │  DTR Sync Worker                   │   poll 1h / thủ công
   │  · parse join key · reconcile()    │
   └──────────────┬────────────────────┘
                  │ upsert (entity + event)
                  ▼
   ┌───────────────────────────────────┐   MỚI        ┌─── KMS core (đã có) ───┐
   │  DTR Store  (mutable, id ổn định)  │──classify──▶ │  DCM → lane C1..C3      │
   │  + Event chain (append-only)       │──append────▶ │  Audit hash-chain       │
   └──────────────┬────────────────────┘              └─────────────────────────┘
     facet query  │   khi RESOLVED → kết tinh
     (structured) │              │
                  │              ▼
                  │   ┌────────────────────┐   PEP    ┌─────────────────────────┐
                  │   │ Knowledge artifact │──gate──▶ │  Semantic index (lane)   │
                  │   │ (OKF)              │          │  embed · rerank · graph  │
                  │   └────────────────────┘          └─────────────────────────┘
                  ▼
          Structured / facet query surface
```

### Interface với core

Subsystem chỉ chạm KMS qua bốn interface có sẵn — đây là toàn bộ điểm ghép nối. Không gọi thẳng vào index, không tự ghi audit.

| Interface (đã có) | DTR gọi để làm gì | Hướng |
|---|---|---|
| `DCM.classify()` | Tính lane từ `interaction_type` + `affected_block` + `project`, mỗi lần sync | DTR → core |
| `AuditChain.append()` | Ghi mỗi lần `lifecycle_state` đổi thành một event tamper-evident | DTR → core |
| `PEP.ingest()` | Đưa knowledge artifact đã kết tinh vào index, kèm nhãn lane | DTR → core |
| `SemanticIndex` / `FacetIndex` | Đăng ký DTR entity cho structured query; artifact cho semantic query | DTR → core |

---

## 3. Mô hình dữ liệu

DTR là mutable entity với identity ổn định, không phải blob content-addressed. Mỗi giờ status/PR đổi; nếu content-address theo hash thì mỗi sync sinh một bản mới, phình index và phá dedup. DTR update in-place theo `id = DTR-{issue-key}`.

### DTR entity (snapshot hiện tại)

```json
{
  "id":               "DTR-DV-123",
  "source":           "DV-123",
  "project":          "ABC-SoC",
  "affected_block":   "axi_slave",
  "interaction_type": "functional",
  "source_ref":       "tb_axi_cdc, seed 42",

  "jira_status":      "In Review",
  "fix_pr":           ["GH#456 (open)"],
  "fix_commits":      ["a1b2c3"],

  "lane":             "C2",
  "lifecycle_state":  "FIX_IN_REVIEW",
  "last_synced_at":   "2026-06-30T09:00"
}
```

Ghi chú các trường: `id` ổn định theo issue key. `source` là Jira issue key (canonical). `jira_status` đọc từ Jira, không suy ra. `fix_pr` là array vì một ticket có thể có nhiều PR. `fix_commits` derive từ GitHub, không nhập tay. `lane` do DCM tính, re-run mỗi sync. `lifecycle_state` là derived, không lưu thẳng `jira_status`. `last_synced_at` để biết dữ liệu tươi tới đâu.

> **Bất biến · derived state.** `lifecycle_state` luôn là kết quả của `reconcile()`, không bao giờ được ghi trực tiếp từ `jira_status`. Giữ nó derived để sau này thêm input `verification` chỉ là mở rộng hàm, không phải migrate dữ liệu.

### Event chain (append-only)

Mỗi lần state đổi là một event append vào audit chain sẵn có — không ghi đè. Snapshot ở trên chỉ là view của chain. Vừa cho timeline để kể "bug đi qua những bước nào", vừa tamper-evident miễn phí.

```json
{ "dtr": "DTR-DV-123", "at": "2026-06-30T10:00",
  "from": "FIX_IN_REVIEW", "to": "MERGED_PENDING_CLOSE",
  "trigger": "sync", "evidence": { "pr": "GH#456", "pr_state": "merged" },
  "prev_hash": "…", "hash": "…" }
```

### Bảng suy ra `lifecycle_state` (v1)

Chỉ hai nguồn, vì Đạt tin Jira. Hai hàng ⚠ là consistency check Jira↔GitHub — giá trị DTR giữ được mà không cần tool mô phỏng.

| Jira status | GitHub PR | → lifecycle_state | Ghi chú |
|---|---|---|---|
| Open | chưa có PR | `NEW` | chưa ai đụng |
| In Progress | chưa có PR | `IN_PROGRESS` | đang làm |
| In Review | PR mở | `FIX_IN_REVIEW` | fix đang review |
| In Review / In Progress | **PR merged** | `MERGED_PENDING_CLOSE` | ⚠ code đã vào, quên đóng ticket |
| Resolved / Closed | PR merged | `RESOLVED` | khớp — đủ điều kiện kết tinh |
| Resolved / Closed | **không có PR merged** | `RESOLVED_NO_FIX` | ⚠ đóng mà không có fix |
| Reopened | bất kỳ | `REOPENED` | vấn đề quay lại |

Logic thuần đã có bản tham chiếu Python (`dtr_reconcile.py`) — `reconcile()` tách hẳn khỏi lớp sync để unit-test không cần mạng.

---

## 4. Chu kỳ đồng bộ

Sáu bước mỗi lần sync. Trigger: định kỳ 1h, hoặc thủ công (van xả cho ca cần độ tươi cao — ví dụ ngay sau khi merge một fix gấp).

| # | Bước | Nội dung | Gate |
|---|---|---|---|
| 1 | Poll | delta Jira + GitHub theo issue key | |
| 2 | Reconcile | `reconcile()` → `lifecycle_state` | hàm thuần, không I/O |
| 3 | Upsert | update entity in-place | id ổn định, không content-address |
| 4 | Append event | nếu state đổi → audit chain | |
| 5 | Classify | DCM re-run → lane | lane tăng cấp → purge bản cũ |
| 6 | Route | anomaly → alert · RESOLVED → kết tinh | |

> **Reclassification — không phải edge case.** Vì DTR là entity sống, nội dung có thể đổi lane giữa các lần sync (functional C2 → phát hiện chạm PDK/foundry → C3). Bước 5 phải re-run DCM mỗi lần; khi lane tăng cấp, mọi bản đã index/cache ở lane thấp phải bị purge, không chỉ thêm bản mới. Đây là "reclassification gap" — với dữ liệu sống nó là đường chạy bình thường, phải xử ngay từ đầu.

Độ trễ: chu kỳ 1h nghĩa là DTR có thể lệch thực tế tối đa ~1 tiếng. Chấp nhận được cho phần lớn truy vấn tra cứu; `last_synced_at` hiển thị ra để kỹ sư biết dữ liệu tươi tới đâu, và trigger thủ công là van xả cho ca gấp.

---

## 5. Vận hành vs tri thức

DTR sống hai vòng đời tách biệt. Nhập nhằng hai vòng này là chỗ "theo dõi tiến trình" và "kho tri thức" giẫm chân nhau.

| | Vòng vận hành | Vòng tri thức |
|---|---|---|
| Khi nào | NEW … REOPENED (chưa terminal) | Khi đạt RESOLVED |
| Là gì | Dữ liệu vận hành, còn đang đổi | Knowledge artifact (OKF), bất biến |
| Ở đâu | DTR Store (mutable) | Semantic index (qua PEP) |
| Truy vấn | Facet / structured filter | Semantic: embed · rerank · graph |
| Ví dụ | "bug C2 đang FIX_IN_REVIEW ở axi_slave" | "trước xử lý CDC ở axi_slave thế nào" |

### Kết tinh (crystallization)

Chỉ khi DTR đạt `RESOLVED`, subsystem sinh một OKF artifact (vấn đề gì · lộ ra ở test nào · sửa bằng commit/PR nào · vì sao) và đưa bản đó qua `PEP.ingest()` vào semantic index. DTR đang chạy không embed vào corpus — nó chưa phải tri thức và còn đang đổi.

> **Hai query surface, không dồn một.** Truy vấn có cấu trúc đi vào tầng FACET NARROW của funnel trên metadata DTR — không phải semantic search. Truy vấn tri thức mới đi vào semantic retrieval trên artifact đã kết tinh. Đây là cách DTR phục vụ cả hai mục tiêu ban đầu của KMS mà không trộn lẫn.

> **Anomaly là alert, không phải tri thức.** `MERGED_PENDING_CLOSE` và `RESOLVED_NO_FIX` không vào corpus semantic. Route ra một view/thông báo riêng cho assignee và lead của block. Cờ `is_anomaly` trong `reconcile()` chính là hook để lọc danh sách này mỗi lần sync.

---

## 6. Bất biến & quyết định cần chốt

### Bất biến tích hợp

1. **Không backdoor.** Mọi dữ liệu bug vào index đi qua PEP/DCM. Pipeline sync không được ghi thẳng vào semantic/facet index.
2. **Mutable, không content-addressed.** DTR update in-place theo id ổn định. Không đưa DTR vào cơ chế dedup theo hash của corpus.
3. **State luôn derived.** `lifecycle_state` = `reconcile(...)`, không lưu thẳng `jira_status`.
4. **Reclassification purge.** Lane tăng cấp giữa hai lần sync → purge bản ở lane thấp, không chỉ thêm bản mới.
5. **Chỉ RESOLVED mới kết tinh.** Không embed DTR đang chạy vào semantic corpus.

### Quyết định còn mở

| Quyết định | Lựa chọn | Trạng thái |
|---|---|---|
| DTR Store ngồi ở đâu | Store mutable riêng cạnh các lane content-addressed, hay một lane đặc biệt "operational" | CẦN CHỐT |
| Ai duyệt artifact kết tinh | Tự động vào index, hay qua curated gate (người duyệt) trước khi vào semantic corpus | CẦN CHỐT |
| Enforce join key | commit-msg hook (client) + CI check (server) reject PR thiếu key | KHUYẾN NGHỊ |

---

## Phụ lục · Contract & quy ước

### Quy ước nối Jira ↔ GitHub

Join key duy nhất là Jira issue key `{PROJECT}-{NUMBER}`. KMS parse theo thứ tự ưu tiên: dòng `Resolves:` trong PR body → PR title → commit message, rồi dedupe.

```
Branch :  bugfix/DV-123-cdc-handshake
Commit :  DV-123: add 2-FF synchronizer on req path
PR     :  title  → [DV-123] Fix CDC on axi_slave req path
          body   → Resolves: DV-123           // KMS đọc dòng này trước
Nhiều  :  Resolves: DV-123, DV-124            // 1 PR → nhiều DTR
          (mỗi PR ghi cùng key)               // nhiều PR → 1 DTR (fix_pr là array)
```

### Jira schema tối thiểu (issue type Defect)

| Field | Kiểu | Vai trò |
|---|---|---|
| `Project / IP` | select | Chip nào — để DCM định lane |
| `Affected Block` | text/select | Neo context vào RTL hierarchy |
| `Interaction Type` | select | Chọn lifecycle + ảnh hưởng lane (v1: functional) |
| `Source Reference` | text | Vấn đề lộ ra ở đâu (test, seed…) |

`Fix Commits` / `Fix PR` / `lane` không phải field Jira — KMS derive, không để kỹ sư nhập tay.

### Thành phần & tham chiếu

| Thành phần | Trạng thái | Tham chiếu |
|---|---|---|
| Hàm reconcile() thuần | CÓ | `dtr_reconcile.py` |
| DCM · Audit chain · PEP · Semantic index | CORE KMS | tái dùng, không sửa |
| DTR Sync Worker · DTR Store | MỚI | subsystem này |

---

*DTR Subsystem · Mô tả tích hợp KMS v1 (Jira-trusted) · VSI WS4 · bản làm việc, cần chốt các mục ở §6*
