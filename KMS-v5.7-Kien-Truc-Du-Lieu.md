# KMS v5.7 — Kiến trúc Dữ liệu & Lưu trữ
### RAG · Bộ nhớ chủ động của AI · Chunking · Dữ liệu thô đầu vào — tổ chức để *nhất quán logic* và *nâng cấp LLM không phụ thuộc mô hình*

**Trạng thái:** thiết kế (mở rộng ứng dụng đang chạy trong `KMS-v5.7_app/kms_backend`) · **Ngày:** 2026‑06‑24
**Đi kèm:** [KMS-v5.7-Composite-Design.md](KMS-v5.7-Composite-Design.md) (tính năng) — tài liệu *này* đặc tả **lớp dữ liệu mà bản composite đã hoãn lại** (§1.5 "real vector embeddings", §8). Nó **không** làm yếu bất kỳ bất biến an ninh nào của v5.6/v5.62.

**Nguồn gốc / bám thực tế.** Mọi bảng/hằng số được nhắc tới là *đang tồn tại* đều lấy từ mã nguồn thật:
`KMS-v5.7_app/kms_backend/kms_app/db.py` (schema), `ingestion/chunking.py`, `ingestion/store.py`,
`retrieval/search.py`, `conversation/state.py`, `config/settings.py`. Mọi bảng mới đều **bổ sung** (không phá vỡ)
và mang cùng các cột `data_class` / `permission_group` / `corpus_id` / `lane` để PEP hiện hữu lọc chúng như mọi tài nguyên khác.

---

## 0. Luận điểm trong một câu

> **Dữ liệu thô là BẤT BIẾN và là nguồn‑chân‑lý duy nhất. Mọi thứ khác — văn bản đã bóc tách, chunk, embedding,
> cạnh đồ thị, bộ nhớ — đều là *sản phẩm dẫn xuất* mà (a) tái sinh được từ dữ liệu thô và (b) được đóng dấu bằng
> đúng *phiên bản recipe/mô hình* đã tạo ra nó.** Do đó nâng cấp lên LLM/embedder mới là một thao tác *tái‑sinh
> nền + lật con trỏ tức thời (atomic)*, KHÔNG bao giờ là sửa tại chỗ, KHÔNG đổi schema, và KHÔNG bao giờ lệch
> chiều (dimension)/định dạng một cách âm thầm.

Nếu chỉ nhớ một điều: **không hàng dẫn xuất nào được lưu mà thiếu id của mô hình/recipe đã tạo ra nó, kèm dấu vân
tay (fingerprint) của dữ liệu thô mà nó sinh ra từ đó.** Đúng một quy tắc đó làm cho kho dữ liệu vừa *nhất quán
logic* (luôn phát hiện được dữ liệu lỗi thời) vừa *an toàn khi nâng cấp* (luôn dựng lại và rollback được).

---

## 1. Mục tiêu & ngoài phạm vi

**Mục tiêu**
1. **Lưu trữ logic, không lệch.** Một chunk luôn biết nó cắt ra từ nội dung tài liệu nào; một embedding luôn biết
   số chiều, độ đo khoảng cách, và mô hình đã tạo ra nó; một mục bộ nhớ luôn biết phạm vi (scope) và bộ tóm tắt
   của mình. KHÔNG thể biểu diễn được "vector mồ côi không rõ số chiều".
2. **Độc lập & nâng cấp được LLM/embedder.** Đổi `Qwen2.5‑72B` → mô hình tương lai, hoặc `bge‑m3` → embedder mới
   *khác số chiều*, phải là thao tác có kiểm soát, đảo ngược được, không gián đoạn dịch vụ và không mất dữ liệu.
3. **Giữ nguyên mọi bất biến an ninh.** Enclave C3 air‑gap, cô lập named‑corpus, reachability theo lane, read‑PEP
   8 bước, write‑PEP, chuỗi audit hash‑chain — không đổi. Sản phẩm dẫn xuất kế thừa phân loại.
4. **Hai backend, một mã.** Chạy trên **SQLite** local (vector là mảng JSON, cosine vét cạn) và
   **Postgres/Supabase + `pgvector`** ở production — qua đúng adapter `db.connect()` hiện có.

**Ngoài phạm vi (tài liệu này)**
- Đặc tả lại kiểm soát truy cập (giữ nguyên — xem thiết kế v5.62/v5.6).
- Một engine ANN tự chế — ta dùng `pgvector` (prod) / vét cạn (local), không tự viết index.
- Huấn luyện/fine‑tune mô hình. Ta chỉ *tiêu thụ* endpoint embedding + sinh văn bản sau một giao diện ổn định.

---

## 2. Mô hình dữ liệu phân tầng (L0 → L7)

Dữ liệu chảy **xuống** (nạp → dẫn xuất) và được đọc **lên** (truy xuất → trả lời). Mỗi tầng có **tính khả biến**
và **khả năng tái sinh** xác định. Quy tắc vàng: **một tầng có thể bị xoá và dựng lại hoàn toàn từ (các) tầng phía trên.**

```
        ĐƯỜNG GHI (dẫn xuất)                         ĐƯỜNG ĐỌC (phục vụ)
 ┌──────────────────────────────────┐     ┌─────────────────────────────────────┐
 L0  DỮ LIỆU THÔ      bất biến   ────┼──┐  │  L5  TRUY XUẤT RAG  (phễu hybrid)    │ ◄── câu hỏi
     raw_objects, document_files     │  │  │      vector(active set) ⊕ lexical    │
 L1  VĂN BẢN CHUẨN HOÁ  tái sinh ◄───┘  │  │      → PEP/corpus/lane → top-k       │
     extractions  (extractor vN)       │  │  └─────────────────────────────────────┘
 L2  CHUNKS            tái sinh         │  │  L6  BỘ NHỚ CHỦ ĐỘNG  (3 tầng)        │ ◄── hội thoại
     chunks  (chunk_recipe vN)         │  │      working · episodic · semantic    │
 L3  EMBEDDINGS        tái sinh         │  │  L7  XUẤT XỨ / LINEAGE / AUDIT        │
     chunk_embeddings (embed_model vN) │  │      mọi hàng dẫn xuất → (raw fp,      │
 L4  VECTOR INDEX + CON TRỎ ACTIVE-SET │  │       id mô hình/recipe đã sinh)      │
     embedding_sets (1 active/corpus)  │  └─────────────────────────────────────┘
 └──────────────────────────────────┘
```

| Tầng | Bảng | Khả biến | Tái sinh từ | Đóng dấu bằng |
|---|---|---|---|---|
| **L0 Dữ liệu thô** | `raw_objects` *(mới)*, `document_files`, `document_versions` | **bất biến** (append‑only) | — (nguồn‑chân‑lý) | `sha256` nội dung, xuất xứ, `data_class`/`corpus`/`lane` |
| **L1 Văn bản chuẩn hoá** | `extractions` *(mới)* | tái sinh | L0 | `extractor_id` (recipe) |
| **L2 Chunks** | `chunks` *(hiện có, +cột)* | tái sinh | L1 | `chunk_recipe_id`, `content_fp` nguồn |
| **L3 Embeddings** | `chunk_embeddings` *(mới)*, `memory_embeddings` *(mới)* | tái sinh | L2 / L6 | `embed_model_id`, `dim`, `metric` |
| **L4 Index / active set** | `embedding_sets` *(mới)*, `vector_models` *(registry mới)* | con trỏ khả biến | dựng lại | `status` (building/active/…) |
| **L5 RAG runtime** | *(không lưu — đọc L3/L4)* | — | — | chỉ trace |
| **L6 Bộ nhớ chủ động** | `conversation_state` *(hiện có)*, `messages`, `memory_items` *(mới)* | phân tầng | lượt L0 | `memory_model_id`, scope, TTL |
| **L7 Xuất xứ/audit** | `lineage` *(mới)*, `audit_logs` *(hiện có)* | append‑only | — | `model_id`+`model_version` |

> **Vì sao tách bảng riêng thay vì thêm cột vào `chunks`?** Một cột `chunks.embedding` duy nhất ràng buộc cứng kho
> dữ liệu vào *một* embedder của *một* số chiều — đúng cái bẫy lệch. Embedding sống trong `chunk_embeddings` khoá
> `(chunk_id, embed_model_id)` nên **N phiên bản mô hình cùng tồn tại**, và nâng cấp là thêm một bộ hàng mới, KHÔNG
> phải `ALTER COLUMN`.

---

## 3. L0 — Dữ liệu thô (nguồn‑chân‑lý bất biến)

Mọi thứ phía dưới chỉ tái lập được **khi và chỉ khi** dữ liệu thô được giữ nguyên byte, định địa chỉ theo nội dung.

### 3.1 "Thô" là gì
Sản phẩm gốc do producer nộp: file OKF `.md`, PDF/DOCX tải lên, payload connector (Jira/GitLab JSON), báo cáo
tiến độ promote. Hiện markdown nguồn‑chân‑lý nằm ở **`document_files`** (`rel_path → content`) và ảnh chụp index
bất biến ở **`document_versions`**. v5.7 tổng quát hoá thành kho **`raw_objects`** định địa chỉ theo nội dung để
nhị phân ngoài‑markdown (PDF) trở thành công dân hạng nhất.

### 3.2 `raw_objects` (mới) — định địa chỉ theo nội dung, append‑only
```sql
CREATE TABLE IF NOT EXISTS raw_objects (
  raw_id        TEXT PRIMARY KEY,     -- = 'sha256:' || hex(content)   (content-addressed ⇒ dedup + bất biến)
  doc_id        TEXT,                 -- tài liệu sở hữu (hàng head trong `documents`)
  version_no    INTEGER,              -- index/version mà raw này thuộc về
  mime          TEXT,                 -- text/markdown · application/pdf · application/json …
  byte_len      INTEGER,
  storage_kind  TEXT,                 -- 'inline' (nội dung ở `content`) | 'external' (URL object store)
  content       TEXT,                 -- byte inline (base64 cho nhị phân) khi storage_kind='inline'
  external_uri  TEXT,                 -- vd khoá Supabase Storage khi storage_kind='external'
  source_system TEXT,                 -- 'okf' | 'upload' | 'jira' | 'gitlab' | 'pm_progress'
  -- phân loại đi cùng raw để các tầng dẫn xuất kế thừa tất định:
  data_class TEXT, permission_group TEXT, corpus_id TEXT, lane TEXT,
  ingested_by TEXT, ingested_at TEXT,
  FOREIGN KEY(doc_id) REFERENCES documents(doc_id)
);
```
**Bất biến.** `raw_id` là SHA‑256 của byte → nội dung trùng chỉ lưu một lần (dedup) và không thể sửa âm thầm
(đổi = `raw_id` mới = version mới). Raw **không bao giờ** bị xoá khi nâng cấp LLM; chỉ xoá theo **chính sách lưu
trữ/RTBF** (xem §9.4, §14.4).

> **Chống lệch:** "đã re‑chunk nhưng mất bản gốc nên không tái lập/audit được." Bất khả — raw bất biến, định địa
> chỉ theo nội dung; `content_fp` trên mọi hàng dẫn xuất trỏ ngược về một `raw_id` cụ thể.

---

## 4. L1 — Văn bản chuẩn hoá / bóc tách

Nhị phân (PDF/DOCX) và markdown đều được chuẩn hoá về **văn bản + cấu trúc chuẩn** trước khi chunk. Hiện
`ingestion/store.py:docling_to_markdown()` là no‑op với `.md`; v5.7 đặt tên cho bước này và **gắn phiên bản**.

```sql
CREATE TABLE IF NOT EXISTS extractions (
  extraction_id TEXT PRIMARY KEY,
  raw_id       TEXT,            -- nguồn L0
  extractor_id TEXT,            -- id registry, vd 'docling@2.4' | 'md-passthrough@1'
  text         TEXT,            -- markdown/plaintext đã chuẩn hoá
  meta_json    TEXT,            -- bản đồ trang, heading, bảng bóc ra, độ tin OCR …
  content_fp   TEXT,            -- sha256(text)[:16]  (cấp cho kiểm tra lỗi thời của chunk)
  created_at   TEXT,
  FOREIGN KEY(raw_id) REFERENCES raw_objects(raw_id)
);
```
Bộ bóc tách là một **recipe** (xem registry §11). Đổi phiên bản docling = `extractor_id` mới → re‑extract →
re‑chunk → re‑embed, tất cả dẫn xuất được, không có gì bị phá huỷ.

---

## 5. L2 — Chunking (gắn phiên bản recipe)

### 5.1 Hiện có
`ingestion/chunking.py:chunk_markdown()` **bám cấu trúc**: cắt theo heading markdown → `parent` = section,
`child` = đoạn văn (≤ `MAXCHILD=700` ký tự), mỗi chunk giữ `heading_path`, `parent_id`, `chunk_level`,
`chunk_index`, `text`, `keywords`. Lưu ở **`chunks`** (chưa có embedding).

### 5.2 Vấn đề & cách khắc phục
Ranh giới chunk là một *recipe* (luật heading, kích thước tối đa, overlap). Nếu recipe đổi, mọi embedding dựng
trên ranh giới cũ trở nên lỗi thời. Vậy chunk phải ghi lại **recipe nào** đã tạo ra nó và **từ văn bản nào**.

**Thêm hai cột vào `chunks`** (bổ sung, nullable → backfill):
```sql
ALTER TABLE chunks ADD COLUMN chunk_recipe_id TEXT;   -- vd 'struct-md@1' (heading+700+đoạn)
ALTER TABLE chunks ADD COLUMN source_content_fp TEXT; -- = extractions.content_fp đã cắt ra
```
Một chunk **lỗi thời** ⟺ `source_content_fp != extraction.content_fp hiện hành` **hoặc** `chunk_recipe_id !=
recipe active`. Re‑chunk ghi `chunk_id` mới dưới `chunk_recipe_id` mới; chunk cũ (và embedding của chúng) được
thu hồi *sau khi* active set mới đã sống (§7).

> **Chống lệch:** "embedding trỏ vào văn bản chunk không còn tồn tại / đã cắt lại." `chunk_id` ổn định cho một
> `(extraction, recipe)` nhất định; đổi một trong hai sinh id mới, nên embedding không bao giờ treo lơ lửng.

---

## 6. L3 — Embeddings (trái tim của tính độc‑lập‑mô‑hình)

Đây là nơi "nâng cấp được khi LLM/embedder mới ra đời" được *hiện thực hoá*.

### 6.1 Registry mô hình — `vector_models` (mới)
```sql
CREATE TABLE IF NOT EXISTS vector_models (
  embed_model_id TEXT PRIMARY KEY,  -- 'bge-m3@1.5' · 'text-embedding-3-large@1' · 'qwen3-embed@1'
  provider     TEXT,                -- 'viettel-ai' | 'openai' | 'local-vllm' | 'stub'
  dim          INTEGER,             -- 1024 · 3072 …  (TƯỜNG MINH — không bao giờ suy đoán)
  metric       TEXT DEFAULT 'cosine',-- cosine | ip | l2
  normalize    INTEGER DEFAULT 1,   -- lưu vector đã chuẩn hoá L2 (để cosine == dot)
  max_tokens   INTEGER,             -- ngân sách cắt cho embedder
  status       TEXT DEFAULT 'registered', -- registered→building→active→deprecated→retired
  notes        TEXT, created_at TEXT
);
```

### 6.2 Vector — `chunk_embeddings` (mới), đa‑phiên‑bản theo thiết kế
```sql
CREATE TABLE IF NOT EXISTS chunk_embeddings (
  chunk_id       TEXT,
  embed_model_id TEXT,              -- mô hình nào tạo ra vector NÀY
  corpus_id      TEXT,              -- denormalize để ANN theo corpus nhanh + cô lập
  data_class     TEXT,              -- denormalize để PEP tiền‑lọc trước khi quét vector
  dim            INTEGER,           -- lưu lại như lá chắn; PHẢI bằng vector_models.dim
  vector         BLOB,              -- Postgres: vector(dim) (pgvector); SQLite: TEXT JSON float[]
  source_content_fp TEXT,           -- fp văn bản chunk tại lúc embed (kiểm tra lỗi thời)
  created_at     TEXT,
  PRIMARY KEY (chunk_id, embed_model_id),     -- ⇐ N phiên bản mô hình mỗi chunk CÙNG TỒN TẠI
  FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id)
);
```
**Hai mô hình sống cạnh nhau là trạng thái BÌNH THƯỜNG, không phải ngoại lệ.** Trong lúc nâng cấp bạn có vector
active cũ *và* vector building mới cùng lúc; bên đọc vẫn dùng cũ cho tới khi cutover.

### 6.3 Lưu trữ vật lý — hai backend (giống app hiện nay)
- **Postgres/Supabase:** kiểu cột `vector` từ extension **`pgvector`**; index ANN cho mỗi active set
  (HNSW): `CREATE INDEX … USING hnsw (vector vector_cosine_ops)`. Lọc `corpus_id`/`data_class` TRƯỚC (partial
  index hoặc `WHERE`) để quét nằm trong lane.
- **SQLite (local/dev):** `vector` là `TEXT` chứa mảng JSON float; truy xuất làm **cosine vét cạn trong Python**
  trên tập ứng viên (đã qua PEP nên nhỏ). Y như cách `retrieval/search.py` đã tính keyword bằng Python. Hook
  `db.schema_sql()` (đang đổi `AUTOINCREMENT→BIGSERIAL`) là nơi tự nhiên để ánh xạ `vector(dim)` ↔ `TEXT`.

### 6.4 Vector đến từ đâu
Embedder là **endpoint ngoài** sau `llm/client.py` (nay `LLM_BACKEND ∈ {stub, http}`). v5.7 thêm hàm anh em
`embed(texts, model_id) -> list[vector]` với **cùng công tắc stub/http**: **stub** offline trả pseudo‑embedding
băm tất định (giữ app chạy được air‑gap và test tái lập); **http** gọi endpoint embedding Viettel‑AI/vLLM thật.
**Kho dữ liệu KHÔNG quan tâm là cái nào** — nó chỉ ghi `embed_model_id`.

> **Chống lệch:** "đổi embedder và giờ truy vấn 1024 chiều đập vào vector 3072 chiều." Mọi vector mang `dim` +
> `embed_model_id`; truy vấn được embed bằng mô hình của **active set**; so sánh khác chiều là bất khả về cấu
> trúc vì truy xuất chỉ đọc đúng một `embed_model_id` mỗi lần.

---

## 7. L4 — Vector index & **con trỏ active‑set** (cutover tức thời)

Chốt chặn cho nâng cấp không gián đoạn: một **con trỏ theo từng corpus** chỉ ra bộ
`(embed_model_id, chunk_recipe_id)` đang phục vụ đọc.

```sql
CREATE TABLE IF NOT EXISTS embedding_sets (
  set_id         TEXT PRIMARY KEY,  -- 'corpus_c2/bge-m3@1.5/struct-md@1'
  corpus_id      TEXT,
  embed_model_id TEXT,
  chunk_recipe_id TEXT,
  status         TEXT DEFAULT 'building', -- building → active → deprecated → retired
  built_count    INTEGER DEFAULT 0,       -- số chunk đã embed (tiến độ)
  total_count    INTEGER,                 -- số chunk kỳ vọng (kiểm tra đầy đủ)
  activated_at   TEXT, created_at TEXT
);
-- BẤT BIẾN: tối đa MỘT hàng status='active' mỗi corpus_id (ép bằng unique partial index / chốt ứng dụng).
```

**Giao thức cutover (không gián đoạn, đảo ngược được):**
1. **Đăng ký** mô hình/recipe mới vào registry (`status='registered'`).
2. **Dựng** hàng `embedding_sets` mới `status='building'`; embed toàn bộ chunk của corpus ở nền; tăng
   `built_count`. Bên đọc không hề bị đụng (vẫn ở set `active`).
3. **Kiểm chứng** độ đầy đủ (`built_count == total_count`) và chất lượng (tập truy vấn eval cố định phải đạt ≥ set
   cũ; xem §12.3).
4. **Lật** trong một transaction: `active` cũ → `deprecated`, `building` mới → `active`. **Đây là khoảnh khắc DUY
   NHẤT mọi thứ thay đổi với bên đọc**, và nó là một lần đổi trạng thái một hàng.
5. **Thu hồi** set deprecated sau cửa sổ ân hạn (rollback = lật ngược; chỉ xoá vector khi đã chắc chắn).

> **Chống lệch:** "nửa corpus ở mô hình mới, nửa ở cũ, kết quả vô nghĩa." Bên đọc giải về *một* set `active` mỗi
> corpus và chỉ đọc vector của set đó — set đang dựng dở không bao giờ đọc được.

---

## 8. L5 — RAG runtime (phễu hybrid trên active set)

v5.7 GIỮ NGUYÊN **phễu 5 lớp** của `retrieval/search.py` và nâng cấp đúng **một** lớp — hạng "dense" — từ
keyword‑overlap thành **độ tương đồng vector thật trên active embedding set**. Mọi thứ còn lại (access filter
PEP‑trước, facet narrow, trộn RRF, rerank một lần, graph expand) không đổi, nên các tính chất an ninh giữ nguyên.

```
[1] ACCESS FILTER   permission_group / corpus / lane  (PEP-1, fail-closed)      ── không đổi, ĐẦU TIÊN
[2] FACET NARROW    kind/project/tags suy từ câu hỏi                            ── không đổi
[3] RANK (hybrid)   dense = ANN cosine trên active set  ║  lexical = khớp token  ── DENSE nay là vector thật
                    → trộn RRF (settings.RRF_K)                                   ── trộn không đổi
[4] RERANK          cross-encoder (stub→http) một lần trên ứng viên đã cap        ── mô hình cắm được
[5] GRAPH EXPAND    concept_links (theo verb), vẫn qua PEP                        ── không đổi
```

**Đường truy vấn:** embed câu hỏi bằng `embed_model_id` của **active set** → ANN **giới hạn trong các `doc_id`
được PEP cho phép và các corpus reachable** (Access Filter chạy *trước* khi quét vector, nên câu hỏi của user C2
không bao giờ chạm vào vector `corpus_c3`) → trộn RRF với hạng lexical → rerank → top‑k. **Trace** truy xuất ghi
`set_id` và `embed_model_id` đã dùng, nên mọi câu trả lời đều tái lập và audit được.

**Vì sao access‑filter‑trước‑vector quan trọng:** nó giữ **air‑gap**. Vector enclave C3 nằm trong `corpus_c3`;
`LANE_REACHES` cấm truy vấn lane `SECURED` chạm tới chúng, nên chúng bị loại khỏi tập ứng viên ANN hoàn toàn — kho
embedding kế thừa đúng topology reachability của kho tài liệu.

---

## 9. L6 — Bộ nhớ chủ động của AI (3 tầng, gắn phiên bản mô hình)

Hiện "bộ nhớ" = `conversation_state` (tóm tắt **văn bản** cuốn chiếu + thực thể nổi bật + referent gần nhất) cộng
`messages` và `message_citations` thô. v5.7 chính thức hoá **bộ nhớ ba tầng** để trợ lý có hồi tưởng *working*,
*episodic*, *semantic* — mỗi tầng gắn phiên bản mô hình và bị PEP ràng buộc, mỗi tầng **dẫn xuất** (nên dựng lại
được) từ log message bất biến.

| Tầng | Vòng đời | Lưu ở | Dựng bởi | Truy xuất |
|---|---|---|---|---|
| **Working** (session state) | hội thoại hiện tại | `conversation_state` *(hiện có)* | bộ cập nhật tăng dần | nạp nguyên văn làm context |
| **Episodic** (log lượt) | tới khi hết TTL | `messages` + `message_citations` *(hiện có)* | append mỗi lượt | cửa sổ gần + hồi tưởng vector tuỳ chọn |
| **Semantic** (sự kiện dài hạn đã chưng cất) | tới khi bị thay/RTBF | `memory_items` *(mới)* + `memory_embeddings` *(mới)* | mô hình tóm tắt | hồi tưởng vector, scope theo user/project |

### 9.1 `memory_items` (mới) — đã chưng cất, có phân loại, suy giảm
```sql
CREATE TABLE IF NOT EXISTS memory_items (
  mem_id        TEXT PRIMARY KEY,
  scope         TEXT,             -- 'user' | 'project' | 'conversation'
  owner_user    TEXT,             -- bộ nhớ của ai (chủ quyền)
  project_id    TEXT,             -- khi scope='project'
  conv_id       TEXT,             -- xuất xứ: chưng cất từ hội thoại nào
  kind          TEXT,             -- 'fact' | 'preference' | 'decision' | 'entity' | 'summary'
  content       TEXT,             -- phát biểu đã chưng cất
  source_msg_ids_json TEXT,       -- lượt episodic đã chưng cất từ đó (lineage)
  memory_model_id TEXT,           -- bộ tóm tắt nào tạo ra (registry)
  -- phân loại (để PEP lọc bộ nhớ y như tài liệu):
  data_class TEXT, permission_group TEXT, corpus_id TEXT, lane TEXT,
  salience      REAL DEFAULT 1.0, -- suy giảm theo thời gian / tăng khi tái dùng
  retain_until  TEXT,             -- TTL (giống CONVERSATION_RETAIN_DAYS)
  superseded_by TEXT,             -- mem_id thay thế nó (không ghi đè phá huỷ)
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS memory_embeddings (   -- cùng kiểu gắn‑phiên‑bản như chunk_embeddings
  mem_id TEXT, embed_model_id TEXT, dim INTEGER, vector BLOB, created_at TEXT,
  PRIMARY KEY (mem_id, embed_model_id)
);
```

### 9.2 Vòng đời một bộ nhớ semantic
`messages` (episodic, bất biến) → **bộ chưng cất** (một mô hình sinh, gắn phiên bản) trích sự kiện/quyết định →
`memory_items` (kèm `memory_model_id` + lineage `source_msg_ids_json`) → embed vào `memory_embeddings` dưới
**embed model active** → hồi tưởng bằng tương đồng vector ở lượt sau, **lọc qua PEP** (mục bộ nhớ trên clearance
người hỏi, hoặc thuộc group/corpus họ không với tới, bị bỏ — *dù là hàng xóm của "bộ nhớ của họ"*, vì bộ nhớ có
thể trích dẫn sự kiện C3 mà sau này user mất quyền).

### 9.3 Re‑authorize‑on‑replay (kế thừa từ v5.6)
Hồi tưởng bộ nhớ chạy lại `authorize()` tại lúc đọc, nên **đổi clearance ẩn bộ nhớ hồi tố** y như ẩn trích dẫn.
Bộ nhớ không bao giờ thành kênh rò rỉ điều mà kho tài liệu sẽ từ chối.

### 9.4 Suy giảm, thay thế, lưu trữ
- **Suy giảm salience**: `salience` giảm theo tuổi, tăng khi tái dùng → hồi tưởng ưu tiên sự kiện mới, hữu ích
  lặp lại; mục salience thấp bị GC.
- **Thay thế, không ghi đè**: một sự kiện được sửa tạo hàng `memory_items` mới và set `superseded_by` lên hàng
  cũ → đầy đủ lịch sử, đảo ngược được.
- **Lưu trữ/RTBF**: `retain_until` (mặc định `CONVERSATION_RETAIN_DAYS=180`) và steward redaction áp dụng đúng
  như hội thoại hiện nay.

> **Chống lệch:** "embedding bộ nhớ sống lâu hơn embedder dựng ra nó." `memory_embeddings` khoá theo
> `embed_model_id` và dựng lại trong cùng cutover với chunk — bộ nhớ và corpus luôn truy xuất qua một embedder
> *nhất quán* mỗi active set.

---

## 10. L7 — Xuất xứ, lineage & audit

### 10.1 `lineage` (mới) — đồ thị dẫn xuất, tường minh
```sql
CREATE TABLE IF NOT EXISTS lineage (
  child_kind  TEXT, child_id  TEXT,   -- vd ('chunk_embedding','<chunk>:bge-m3@1.5')
  parent_kind TEXT, parent_id TEXT,   -- vd ('chunk','<chunk_id>')
  producer_id TEXT,                   -- id mô hình/recipe đã dẫn xuất
  produced_at TEXT,
  PRIMARY KEY (child_kind, child_id, parent_kind, parent_id)
);
```
Lineage trả lời, cho bất kỳ artifact nào: *từ raw nào? mô hình nào tạo? có lỗi thời không? phải dựng lại gì nếu
thu hồi mô hình X?* — không phải đoán.

### 10.2 Audit (hiện có) đã mang định danh mô hình
`audit_logs` đã có `model_id`, `model_version`, `task_contract_version`, `lane`, `infra_tier`,
`max_data_class_accessed`. Mọi truy xuất/trả lời ghi `embed_model_id` của **active set** và mô hình sinh → một câu
trả lời tái lập được hoàn toàn (raw nào, chunk nào, embedder nào, LLM nào) và chống‑giả‑mạo (hash‑chain + HMAC,
không đổi).

---

## 11. Registry Mô hình & Recipe — một cơ chế, bốn nhà sản xuất

Cả bốn "thứ có thể đổi khi LLM mới ra đời" đều là **hàng registry với vòng đời trạng thái**, và mọi artifact dẫn
xuất tham chiếu một cái. Sự đồng nhất này giữ kho dữ liệu không trôi vào lệch.

| Nhà sản xuất | Registry | Đóng dấu | Đổi nó kích hoạt |
|---|---|---|---|
| **Bộ bóc tách** (PDF→text) | `extractor_id` | `extractions` | re‑extract → re‑chunk → re‑embed |
| **Recipe chunk** | `chunk_recipe_id` | `chunks` | re‑chunk → re‑embed |
| **Embedder** | `vector_models` | `chunk_embeddings`, `memory_embeddings` | re‑embed → active set mới |
| **LLM sinh / tóm tắt** | `generation_models` *(xem dưới)* | `memory_items`, câu trả lời, `audit_logs` | re‑distill bộ nhớ (tuỳ chọn); câu trả lời chỉ chuyển tiếp |

```sql
CREATE TABLE IF NOT EXISTS generation_models (    -- LLM trả lời/tóm tắt (nay: Qwen2.5-72B)
  gen_model_id TEXT PRIMARY KEY,  -- 'qwen2.5-72b@awq' · 'gpt-x@1' · 'qwen3-...@1'
  provider TEXT, context_tokens INTEGER, status TEXT DEFAULT 'registered',
  task_contract_version TEXT, notes TEXT, created_at TEXT
);
```
**Vòng đời trạng thái (mọi registry):** `registered → building → active → deprecated → retired`. **Tối đa một
`active` mỗi vai trò+corpus.** Đổi mô hình sinh là rẻ nhất (câu trả lời vô trạng thái — chỉ trỏ lưu lượng mới sang
`gen_model_id` mới); đổi embedder phức tạp nhất (re‑embed + cutover); đổi extractor/recipe lan xa nhất. Hướng lan
luôn **xuống** các tầng, không bao giờ ngang.

---

## 12. Sổ tay nâng cấp — "một LLM/embedder mới ra đời"

### 12.1 Mô hình **sinh** mới (vd Qwen2.5‑72B → Qwen‑next / GPT‑X)
1. `INSERT INTO generation_models (… status='active')`; đặt `LLM_MODEL`/endpoint (hoặc override theo request).
2. Câu trả lời mới dùng ngay; **không re‑embedding, không migration**. Câu trả lời cũ giữ `model_id` đã ghi
   (tái lập). Tuỳ chọn: re‑distill bộ nhớ semantic bằng mô hình mới cho `memory_items` chất lượng hơn (thuần bổ
   sung; supersession giữ bản cũ).

### 12.2 **Embedder** mới **cùng số chiều**
Vẫn coi là `embed_model_id` mới (KHÔNG ghi đè vector): dựng `embedding_sets` mới, embed, kiểm chứng, lật, thu hồi.
Cùng số chiều *không* phải giấy phép tái dùng hàng — vector khác nhau về ngữ nghĩa.

### 12.3 **Embedder** mới **khác số chiều** (cái đáng sợ — biến thành nhàm chán)
Đúng giao thức như §12.2. Vì vector nằm trong `chunk_embeddings` khoá theo `embed_model_id` với `dim` tường minh,
một mô hình 3072 chiều chỉ ghi hàng mới cạnh hàng 1024 chiều; index ANN cho set mới tạo ở chiều mới; con trỏ active
lật tức thời. **Không `ALTER COLUMN`, không đụng độ số chiều.**
*Cổng kiểm chứng trước khi lật:* chạy tập eval cố định (≥ N cặp truy vấn→tài‑liệu‑liên‑quan đã gán nhãn mỗi
corpus); yêu cầu recall@k và MRR ≥ set đương nhiệm (trong dung sai) — nếu không thì giữ set cũ active và điều tra.

### 12.4 **Recipe chunk** hoặc **bộ bóc tách** mới
Đăng ký → re‑extract/re‑chunk thành id mới → re‑embed (set mới) → kiểm chứng → lật → thu hồi. Lan tự động vì mỗi
tầng ghi cha và nhà sản xuất của mình.

### 12.5 Đặc thù theo corpus & enclave
Nâng cấp **theo từng corpus** (có thể migrate `corpus_c1`/`corpus_c2` trong khi `corpus_c3` chờ). **Enclave C3**
re‑embed **bên trong lane** bằng embedder cư trú trong enclave; vector C3 mới không bao giờ băng qua `SECURED`.
Luật egress (`EGRESS_MAX_CLASS`) áp cả cho artifact mô hình.

### 12.6 Rollback
Vì set cũ chỉ `deprecated` (không xoá) trong cửa sổ ân hạn, rollback là một lần lật trạng thái về `active`. Chỉ
xoá vector đã retired sau khi set mới chứng minh được mình ở production.

---

## 13. Bất biến chống‑lệch (được ép, liệt kê đủ)

Đây là các luật mà reviewer/CI kiểm. Mỗi luật chặn một hỏng hóc cụ thể.

1. **Raw bất biến & định địa chỉ nội dung.** `raw_id = sha256(bytes)`. *(Chặn dẫn xuất không tái lập.)*
2. **Không hàng dẫn xuất nào thiếu (fp nguồn + id nhà sản xuất).** Chunk mang `source_content_fp`+`chunk_recipe_id`;
   embedding mang `embed_model_id`+`dim`; bộ nhớ mang `memory_model_id`. *(Chặn dữ liệu mồ côi/mơ hồ.)*
3. **Số chiều tường minh & có lá chắn.** `chunk_embeddings.dim == vector_models.dim` của mô hình đó; insert lệch
   bị từ chối. *(Chặn đụng độ số chiều.)*
4. **Đúng một `active` embedding set mỗi corpus.** Bên đọc giải về một set. *(Chặn kết quả trộn mô hình.)*
5. **Embed một lần — so một lần — cùng mô hình.** Truy vấn embed bằng đúng mô hình của active set. *(Chặn cosine
   vô nghĩa giữa các mô hình.)*
6. **Phân loại lan xuống không đổi.** `data_class`/`permission_group`/`corpus_id`/`lane` chép raw → extraction →
   chunk → embedding → bộ nhớ. PEP lọc tất cả. *(Chặn rò rỉ dữ liệu dẫn xuất.)*
7. **Access filter trước vector scan.** PEP/corpus/lane giới hạn ứng viên *trước* ANN. *(Giữ air‑gap.)*
8. **Lỗi thời tính được, không giả định.** Một hàng dẫn xuất lỗi thời ⟺ fp/nhà‑sản‑xuất đã đóng dấu ≠ active hiện
   hành. Một "quét lỗi thời" ở nền liệt kê những gì cần dựng lại. *(Chặn trôi âm thầm.)*
9. **Thay thế, không ghi đè.** Sự kiện/version mới thêm hàng + con trỏ ngược. *(Giữ lịch sử + rollback.)*
10. **Nâng cấp là lật con trỏ, không migration.** Không bao giờ `ALTER COLUMN` trên vector. *(Chặn gián đoạn/mất.)*

---

## 14. Lưu trữ vật lý, ước lượng & vòng đời

### 14.1 Ánh xạ backend (qua `db.schema_sql()` / adapter)
| Vấn đề | Postgres / Supabase (prod) | SQLite (local/dev) |
|---|---|---|
| Cột vector | `pgvector` `vector(dim)` | `TEXT` JSON `float[]` |
| ANN | index HNSW mỗi active set | cosine vét cạn trong Python trên ứng viên đã PEP |
| Raw nhị phân | Supabase Storage (`external_uri`) | base64 inline (`content`) |
| Auto id | `BIGSERIAL` (rewrite hiện có) | `AUTOINCREMENT` |

### 14.2 Tham số index (Postgres)
HNSW `m≈16`, `ef_construction≈64`, `ef_search` tinh chỉnh theo mục tiêu độ trễ; một index cho mỗi set **active**
(dựng nó trên set building *trước* khi lật để cutover tức thì). Phân hoạch/`WHERE corpus_id=…` giữ quét cục bộ lane.

### 14.3 Ước lượng (cỡ độ lớn)
Một vector 1024 chiều float32 ≈ 4 KB; 100k chunk ≈ 0.4 GB mỗi embedding set. Giữ một set deprecated trong cửa sổ
ân hạn ⇒ ngân sách ~2× dung lượng active tạm thời. Embedding bộ nhớ nhỏ hơn nhiều (mục đã chưng cất ≪ chunk).

### 14.4 Lưu trữ & dọn rác
- Set embedding đã retired: xoá vector sau ân hạn (giữ hàng `embedding_sets` cho audit).
- Chunk/embedding lỗi thời: gỡ bởi quét lỗi thời khi một active set mới đã phủ tài liệu của chúng.
- Bộ nhớ: TTL (`retain_until`) + GC salience + RTBF redaction.
- Raw: chỉ xoá theo chính sách lưu trữ/RTBF — **không bao giờ** bởi nâng cấp.

### 14.5 Mã hoá & enclave
Mã hoá tại nghỉ cho raw/vector `corpus_c3`; embedder và index ANN C3 cư trú trong enclave; không vector hay mục bộ
nhớ C3 nào băng qua ranh giới lane (reachability + `EGRESS_MAX_CLASS`).

---

## 15. Di trú từ v5.7‑hiện‑tại (bổ sung, không phá vỡ)

Không có gì hiện hữu bị xoá hay đổi tên. Tập thay đổi:

**Bảng mới:** `raw_objects`, `extractions`, `vector_models`, `chunk_embeddings`, `embedding_sets`,
`generation_models`, `memory_items`, `memory_embeddings`, `lineage`.
**Cột thêm (nullable, backfill):** `chunks.chunk_recipe_id`, `chunks.source_content_fp`.
**Không đổi:** `documents`, `document_files`, `document_versions`, `chunks` (text/keywords giữ — rank lexical vẫn
dùng), `concept_links`, `conversation_state`, `messages`, `message_citations`, mọi bảng security/PM/collab, chuỗi
audit.

**Backfill (một lần, idempotent — mở rộng `scripts/migrate_seed.py`):**
1. Mỗi hàng `document_files`/`document_versions` → ghi một hàng `raw_objects` (`raw_id = sha256(content)`).
2. Đóng dấu `chunks` hiện có với `chunk_recipe_id='struct-md@1'` và `source_content_fp` từ tài liệu của chúng.
3. Đăng ký `vector_models` (`stub-embed@1`, `dim=256` cho offline) + embedder thật; dựng `embedding_sets` đầu
   tiên mỗi corpus (`status='active'`); embed toàn bộ chunk.
4. Đăng ký `generation_models` từ `LLM_MODEL` hiện hành.
5. Seed `memory_items` rỗng; bộ nhớ working/episodic đã có sẵn.

Cả **SQLite và Postgres** sinh từ một chuỗi `SCHEMA` qua rewrite `db.schema_sql()` hiện có (thêm ánh xạ
`vector(dim) ↔ TEXT` cạnh luật `AUTOINCREMENT→BIGSERIAL`).

---

## 16. Tham chiếu bảng mới (tổng hợp)

| Bảng | Tầng | Mục đích | Khoá phiên bản |
|---|---|---|---|
| `raw_objects` | L0 | nguồn bất biến định địa chỉ nội dung | `raw_id = sha256` |
| `extractions` | L1 | văn bản chuẩn hoá | `extractor_id` |
| `chunks` (+2 cột) | L2 | chunk cấu trúc | `chunk_recipe_id` + `source_content_fp` |
| `vector_models` | L3 reg | registry embedder (dim/metric) | `embed_model_id` |
| `chunk_embeddings` | L3 | vector, đa mô hình | PK `(chunk_id, embed_model_id)` |
| `embedding_sets` | L4 | con trỏ active‑set mỗi corpus | `status` (một `active`/corpus) |
| `generation_models` | L7 reg | LLM trả lời/tóm tắt | `gen_model_id` |
| `memory_items` | L6 | bộ nhớ semantic dài hạn | `memory_model_id` + supersession |
| `memory_embeddings` | L6 | vector bộ nhớ, đa mô hình | PK `(mem_id, embed_model_id)` |
| `lineage` | L7 | đồ thị dẫn xuất (raw→…→artifact) | `producer_id` |

---

## 17. Ví dụ xuyên suốt (đầu‑cuối + một lần nâng cấp)

**Nạp → trả lời.** `eng_pd1` tải lên `dcm_spec.pdf` (C3) → `raw_objects`(raw_id=sha256, corpus_c3, lane
C3_ENCLAVE) → `extractions`(docling@2.4) → `chunks`(struct‑md@1, kèm `source_content_fp`) →
`chunk_embeddings`(bge‑m3@1.5, dim 1024) vào `embedding_sets` **active** của `corpus_c3` → một user C3 đặt câu
hỏi: Access Filter chỉ giữ corpus reachable cho C3, truy vấn embed bằng bge‑m3@1.5, ANN trên vector `corpus_c3`,
RRF với lexical, rerank, top‑5 → trả lời; `audit_logs` ghi bge‑m3@1.5 + qwen2.5‑72b + các chunk id. Một quyết định
được chưng cất vào `memory_items` (C3) và được hồi tưởng lượt sau — nhưng một user C2 vừa bị hạ quyền bị từ chối
nó bởi re‑authorize‑on‑replay.

**Nâng cấp embedder.** `bge‑next@1` (dim 3072) ra mắt → đăng ký vào `vector_models` → dựng
`embedding_sets`(corpus_c2/bge‑next@1/struct‑md@1, building) ở nền → cổng eval đạt → lật (`bge‑m3@1.5 →
deprecated`, `bge‑next@1 → active`) trong một transaction → `corpus_c2` nay trả lời trên vector 3072 chiều với
**không gián đoạn**, hàng 1024 chiều vẫn còn để rollback tức thì, `corpus_c3` không đụng tới cho đến lần migrate
enclave của nó. **Không cột nào bị altered, không lệch, audit đầy đủ.**

---

## 18. Hoãn lại có chủ đích (phạm vi trung thực)

- **Reranker cross‑encoder như mô hình thật** (bước [4] của phễu) — giữ giao diện stub; cắm reranker hosted theo
  cùng cách embedder khi có.
- **Truy xuất đa‑vector / late‑interaction (kiểu ColBERT)** — schema cho phép (nhiều vector mỗi chunk qua
  `part_no`), nhưng dense một‑vector là mục tiêu v5.7.
- **Tự tìm recipe / tinh chỉnh kích thước chunk** — recipe đăng ký thủ công lúc này.
- **Embedding đồ thị** cho `concept_links` — đồ thị giữ ký hiệu/theo‑verb (đã mạnh); embedding nút là set bổ sung
  về sau.

---

## 19. Truy vết — yêu cầu → bảo đảm

| Yêu cầu của người dùng | Được thoả mãn ở đâu |
|---|---|
| "dữ liệu RAG được tổ chức thế nào" | L0–L5: raw → extract → chunk → embed → active set → phễu hybrid (§3–§8) |
| "bộ nhớ chủ động của AI" | L6: 3 tầng working/episodic/semantic, gắn phiên bản mô hình, PEP ràng buộc (§9) |
| "chunking" | L2: registry recipe + `chunks` đóng dấu `chunk_recipe_id`+`source_content_fp` (§5) |
| "dữ liệu thô đầu vào" | L0: `raw_objects` bất biến định địa chỉ nội dung; không bị xoá bởi nâng cấp (§3) |
| "logic, không lệch" | §13 bất biến + §10 lineage + `dim`/fp/nhà‑sản‑xuất tường minh trên mọi hàng dẫn xuất |
| "cập nhật khi LLM mới ra đời" | §11 registry + §7 cutover active‑set + §12 sổ tay nâng cấp (lật con trỏ, không migration) |

---

*Tài liệu thiết kế — kiến trúc dữ liệu & lưu trữ KMS v5.7. Bổ trợ cho bản composite ở mức tính năng; hiện thực
lớp embedding/RAG/bộ nhớ mà bản đó hoãn lại. Xây để khớp schema thật của `KMS-v5.7_app` và backend kép
SQLite/Postgres. 2026‑06‑24.*
