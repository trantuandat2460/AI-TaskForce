"""LLM client cắm được (pluggable). Mặc định StubLLM = tổng hợp tất định, offline
(không phụ thuộc mạng) — phù hợp test cấu trúc. Đổi settings.LLM_BACKEND='http'
để gọi vLLM (in-lane cho C3) hoặc Viettel AI (uplink cho ≤C2). Định tuyến theo
lane là chỗ thực thi P17 (C3 không bao giờ đi uplink)."""
import json, urllib.request
from config import settings

def synthesize(query, allowed_chunks, lane="C3_AIRGAP"):
    """allowed_chunks: list dict {text, title, data_class}. Trả (text, refused)."""
    if not allowed_chunks:
        return ("Không tìm thấy nguồn **được phép** để trích dẫn cho câu hỏi này. "
                "Theo P5 (không trích dẫn có căn cứ ⇒ không trả lời) và fail-closed, "
                "hệ thống không sinh câu trả lời.", True)
    if settings.LLM_BACKEND == "http":
        return (_http_answer(query, allowed_chunks, lane), False)
    # StubLLM (tất định): nối nội dung nguồn được phép
    body = " ".join(c["text"][:280] for c in allowed_chunks[:3])
    return (f"[trả lời mô phỏng tất định] Dựa trên các nguồn bạn được phép truy cập: {body}", False)

def _http_answer(query, chunks, lane):
    # C3 phải dùng endpoint in-lane; ≤C2 mới được uplink (ràng buộc gọi ở routes).
    context = "\n\n".join(f"[{c['title']}]\n{c['text']}" for c in chunks)
    payload = {"model": settings.LLM_MODEL, "max_tokens": 800,
               "messages": [{"role": "system", "content": "Trả lời chỉ dựa trên ngữ cảnh được cung cấp. Nếu thiếu căn cứ, nói không đủ thông tin."},
                            {"role": "user", "content": f"Ngữ cảnh:\n{context}\n\nCâu hỏi: {query}"}]}
    req = urllib.request.Request(settings.LLM_HTTP_URL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    # OpenAI-compatible
    return data["choices"][0]["message"]["content"]
