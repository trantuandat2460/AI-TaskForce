"""Query rewrite / contextualization (A13/P31). Giải tham chiếu tiếng Việt
('cái này', 'nó', 'còn ... thì sao') dùng active_topic của session state.
Giữ nguyên scope (chỉ viết lại ý định); fail-safe: mơ hồ → dùng câu gốc."""
import re
REFERENTIAL = [r"còn (cái này|cái đó|nó|điều này|vấn đề này)", r"(cái này|cái đó|điều đó|vấn đề này)",
               r"\bnó\b", r"tương tự", r"như (vậy|trên)", r"thì sao\??$"]

def rewrite(text, state):
    has_ref = any(re.search(p, text, re.I) for p in REFERENTIAL)
    topic = (state or {}).get("active_topic")
    if has_ref and topic:
        rew = re.sub(r"\bnó\b", topic, text, flags=re.I)
        rew = re.sub(r"(cái này|cái đó|điều này|điều đó|vấn đề này)", topic, rew, flags=re.I)
        if not re.search(re.escape(topic), rew, re.I):
            rew = f"{rew} {topic}"
        changed = rew.strip() != text.strip()
        return {"original": text, "rewritten": rew, "changed": changed,
                "reason": f'giải tham chiếu từ active_topic = "{topic}"'}
    return {"original": text, "rewritten": text, "changed": False,
            "reason": "có tham chiếu nhưng state rỗng → fail-safe (dùng câu gốc)" if has_ref else "không có tham chiếu cần giải"}
