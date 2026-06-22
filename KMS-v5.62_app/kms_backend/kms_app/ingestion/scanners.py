"""Scanner tầng-1 ingest (S3/S5 v5.6) — chạy ĐỘC LẬP với cờ producer.

- secret_scan: entropy + mẫu key/token đã biết → bắt credential kể cả khi producer
  quên gắn vsi_is_credential. Trúng ⇒ quarantine (không index, không vào LLM).
- ner_scan: phát hiện nội dung "trông giống nhân sự / nêu đích danh người" (PII)
  để đặt phạm vi DPIA độc lập với cờ tự khai. Trông giống nhưng chưa gắn cờ ⇒
  route sang steward review (quarantine), không xử lý như tài liệu kỹ thuật.
"""
import re, math
from config import settings

_COMPILED = [re.compile(p) for p in settings.SECRET_PATTERNS]

def _entropy(s):
    if not s: return 0.0
    freq = {}
    for ch in s: freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return -sum((c/n) * math.log2(c/n) for c in freq.values())

def secret_scan(text):
    """Trả (hit: bool, reason: str|None)."""
    for rx in _COMPILED:
        m = rx.search(text)
        if m:
            return True, f"secret-pattern: {rx.pattern[:32]}"
    # heuristic entropy: chuỗi dài liên tục, entropy cao → nghi là khoá
    for tok in re.findall(r"[A-Za-z0-9/\+_\-]{24,}", text):
        if _entropy(tok) >= 4.0:
            return True, f"high-entropy token (H≈{_entropy(tok):.1f})"
    return False, None

# NER tối giản: cần ĐỒNG THỜI một dấu hiệu hồ sơ nhân sự VÀ một tên riêng cụ thể,
# để tránh báo nhầm tài liệu chung chung chỉ nhắc tới "nhân viên".
_PERSONNEL_HINT = re.compile(r"(hồ sơ nhân sự|đánh giá hiệu suất|\blương\b|performance review|personnel)", re.I)
_PROPER_NAME = re.compile(r"\b([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+){1,3})\b")

def ner_scan(text):
    """Trả (looks_personnel: bool, names: list[str]).
    looks_personnel chỉ True khi có dấu hiệu nhân sự VÀ bắt được tên riêng."""
    if not _PERSONNEL_HINT.search(text):
        return False, []
    names = list(dict.fromkeys(_PROPER_NAME.findall(text)))[:5]
    return (bool(names), names)
