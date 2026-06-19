"""Kiểm tra chính tả / chất lượng văn bản trước khi upload (stdlib heuristic).

Đây là một STAND-IN tất định, offline — không phụ thuộc thư viện ngoài. Nó bắt các
lỗi phổ biến: từ lặp liền ("the the"), ký tự lặp bất thường ("loooi"), sai chính tả
phổ biến (từ điển nhỏ), và khoảng trắng trước dấu câu. Chỗ cắm spell-checker thật
(hunspell/LanguageTool offline) đặt ở spell_check() — giữ nguyên giao diện trả về.
"""
import re

# Từ điển lỗi chính tả phổ biến (VI + EN) → gợi ý sửa. Mở rộng tuỳ nhu cầu.
COMMON_MISSPELL = {
    "teh": "the", "recieve": "receive", "seperate": "separate", "occured": "occurred",
    "definately": "definitely", "wich": "which", "thier": "their", "alot": "a lot",
    "kien truc": "kiến trúc", "tai lieu": "tài liệu", "bao mat": "bảo mật",
    "quyen": "quyền", "nguoi dung": "người dùng",
}

_WORD = re.compile(r"[A-Za-zÀ-ỹ]+(?:['-][A-Za-zÀ-ỹ]+)?")
_REPEAT_CHAR = re.compile(r"(.)\1{2,}")          # 3+ ký tự lặp liền: looo, aaaa
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?])")

def spell_check(text):
    """Trả list issue: {type, word, line, suggestion}. Rỗng = không phát hiện lỗi."""
    issues = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("#", "```", "---")):   # bỏ qua heading / code / frontmatter
            continue
        words = _WORD.findall(line)
        low = [w.lower() for w in words]
        # 1) sai chính tả phổ biến
        for w, lw in zip(words, low):
            if lw in COMMON_MISSPELL:
                issues.append({"type": "misspelling", "word": w, "line": lineno,
                               "suggestion": COMMON_MISSPELL[lw]})
        # 2) từ lặp liền nhau
        for i in range(1, len(low)):
            if low[i] == low[i-1] and len(low[i]) > 1:
                issues.append({"type": "repeated-word", "word": words[i], "line": lineno,
                               "suggestion": f"bỏ bớt '{words[i]}'"})
        # 3) ký tự lặp bất thường
        for w in words:
            if _REPEAT_CHAR.search(w):
                issues.append({"type": "repeated-char", "word": w, "line": lineno,
                               "suggestion": _REPEAT_CHAR.sub(r"\1", w)})
        # 4) khoảng trắng trước dấu câu
        if _SPACE_BEFORE_PUNCT.search(line):
            issues.append({"type": "spacing", "word": _SPACE_BEFORE_PUNCT.search(line).group(0).strip(),
                           "line": lineno, "suggestion": "bỏ khoảng trắng trước dấu câu"})
    # khử trùng lặp, giới hạn để UI gọn
    seen, out = set(), []
    for it in issues:
        k = (it["type"], it["word"], it["line"])
        if k in seen: continue
        seen.add(k); out.append(it)
    return out[:30]
