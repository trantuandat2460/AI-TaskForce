# Tính năng người dùng — VSI KMS

**Knowledge Management System (KMS) · v5.6 — Danh mục tính năng dành cho người dùng**

_Tài liệu này định nghĩa những gì người dùng **làm được** khi dùng KMS, viết theo góc nhìn người dùng. Mỗi tính năng kèm trạng thái trưởng thành rõ ràng._

> **Quy ước trạng thái**
> - ✅ **LIVE** — đang chạy thật hôm nay, dùng được ngay.
> - 🔨 **ĐANG XÂY** — kiến trúc đích, chưa dùng được; mô tả để biết hướng đi.
> - 🕓 **HOÃN** — sẽ bật khi có nhu cầu thực.
>
> Một nguyên tắc xuyên suốt: **mỗi người chỉ thấy lát cắt tri thức theo quyền của riêng mình.** Hai người hỏi cùng một câu, nếu khác mức được duyệt (clearance), sẽ nhận hai tập kết quả khác nhau — và việc lọc quyền luôn xảy ra **trước** khi mô hình ngôn ngữ được gọi.

---

## Ai dùng được gì (nhìn nhanh)

| Đối tượng | Nhóm tính năng |
| --- | --- |
| **Kỹ sư VSI** | Hỏi đáp có phân quyền, trích dẫn nguồn, hội thoại nhiều lượt, đồ thị tri thức |
| **Trưởng nhóm / Lead** | Mọi tính năng của kỹ sư + điều phối tác vụ (rà soát báo cáo tuần, Jira, GitLab, đề bạt tri thức) |
| **Data Steward** | Phê chuẩn (ratify) tri thức và duyệt nhãn phân loại trước khi tri thức vào hệ |

---

## 1. Kỹ sư VSI — nền hỏi đáp tri thức

### 1.1 Hỏi đáp có phân quyền (permission-scoped Q&A) — ✅ LIVE
Hỏi bằng ngôn ngữ tự nhiên qua giao diện chat; nhận câu trả lời tổng hợp **chỉ từ đúng lát cắt tri thức bạn được phép xem**. Bộ lọc quyền là hàng rào cứng, chạy trước khi gọi LLM.

### 1.2 Trích dẫn nguồn (citations) — ✅ LIVE
Mỗi câu trả lời kèm trích dẫn truy ngược về đúng concept / tài liệu nguồn đã sinh ra nội dung đó.

### 1.3 Hội thoại nhiều lượt + viết lại câu hỏi — ✅ LIVE
Hỏi câu phụ thuộc ngữ cảnh ("còn cái này thì sao?") — hệ tự viết lại thành câu hỏi độc lập trước khi truy xuất, nhờ nhớ ngữ cảnh hội thoại.

### 1.4 Truy vấn đa ngữ — ✅ LIVE
Hỏi bằng tiếng Việt, tiếng Anh, hoặc về code; embedding bge-m3 hỗ trợ cả ba.

### 1.5 Đồ thị tri thức — 🔨 ĐANG XÂY
- **Related concepts** — "Spec này liên quan tới những concept nào?" (truy vấn 1–2 hop).
- **Impact analysis** — "Nếu sửa `datapath/mac`, những spec / test nào bị ảnh hưởng?" (đảo chiều cạnh).
- **Progressive navigation** — đi từ tổng quan xuống chi tiết theo các cạnh trong đồ thị.
- **Provenance phong phú** — truy ngược một claim về đúng concept / nguồn đã sinh ra nó.

> Mọi traversal đồ thị đều đi **qua PEP**: thấy *có* một cạnh không có nghĩa được đọc *nội dung* đích.

---

## 2. Trưởng nhóm / Lead — điều phối tác vụ

Gồm toàn bộ tính năng của kỹ sư, cộng thêm khả năng để hệ thống *làm việc*, không chỉ trả lời.

### 2.1 Rà soát báo cáo tuần (`review_report`) — ✅ LIVE
Tác vụ **tất định**: chạy cùng một cách mỗi lần, đọc cùng một bộ nguồn, áp cùng một quyền, xuất ra **target của tuần kế tiếp**.

### 2.2 Tra cứu Jira (`jira.*`) — ✅ LIVE
Truy cập issue / sprint Jira ngay trong luồng hội thoại.

### 2.3 Tra cứu GitLab (`gitlab.*`) — ✅ LIVE
Truy cập merge request / repo GitLab ngay trong luồng hội thoại.

### 2.4 Đề bạt phiên thành tri thức (`compact_session`) — ✅ LIVE
Chắt lọc một phiên hội thoại đáng giữ thành một **concept tri thức được curated**, có khoá trích dẫn bền vững và nhãn phân loại kế thừa. Concept đề bạt **kế thừa `max_data_class` của hội thoại như một sàn cứng** (phiên từng chạm C3 ⇒ concept C3).

---

## 3. Data Steward — phê chuẩn tri thức

### 3.1 Phê chuẩn tri thức (ratify) — 🔨 ĐANG XÂY
Tri thức tự động làm giàu vào trạng thái `quarantined` (chưa truy hồi được). Data Steward rà soát và **lật trạng thái sang `active`** — một chuyển trạng thái chặn (blocking), không phải lời hứa chính sách.

### 3.2 Duyệt nhãn phân loại — 🔨 ĐANG XÂY
Chỉ con người mới được gán / đổi `data_class`. LLM chỉ được **đề xuất** cấu trúc và candidate flags; gán mức phân loại là quyết định bảo mật của con người.

---

## Ranh giới bảo mật mà mọi tính năng phải phục tùng

Mọi tính năng ở trên đều vận hành *bên trong* các ranh giới này — không tính năng nào được phép nới một ranh giới để đổi lấy tiện ích:

1. **Phân loại C1 / C2 / C3 + highest-wins** — hội thoại chạm tới mức cao nhất bị xử lý theo mức cao nhất đó.
2. **Air-gapped C3 enclave** — core-IP nhạy cảm nhất không bao giờ rời vùng cách ly.
3. **Chặn cứng credential** — nội dung chứa bí mật không index, không tới LLM.
4. **Ranh giới dữ liệu cá nhân (DPIA)** — nội dung mô tả con người vào phạm vi quản trị riêng.

Nền tảng xuyên suốt: **fail-closed** — khi thiếu thông tin hoặc gặp lỗi, hệ mặc định **từ chối**, không mặc định mở.

---

_Chi tiết kỹ thuật của từng tính năng: xem [KMS-v5.6.md](KMS-v5.6.md) — S6 (truy xuất), S7 (đồ thị), S8 (điều phối tác vụ), S3 (bảo mật)._
