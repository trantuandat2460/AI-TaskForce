"""Hierarchical / structure-aware chunking (A14/P32). Cắt theo heading markdown
(## / ###) → parent = section; child = đoạn văn (giới hạn ký tự). Fallback: cắt
theo size nếu không có heading. Mỗi chunk giữ heading_path + parent_id + level."""
import re, hashlib, json
HEAD = re.compile(r'^(#{1,6})\s+(.*)$')
MAXCHILD = 700

def _kw(text):
    toks = re.findall(r"[a-zA-ZÀ-ỹ0-9_]{3,}", text.lower())
    seen, out = set(), []
    for t in toks:
        if t not in seen:
            seen.add(t); out.append(t)
    return out[:40]

def chunk_markdown(doc_id, body):
    lines = body.splitlines()
    sections, cur = [], {"head": "(intro)", "buf": []}
    for ln in lines:
        m = HEAD.match(ln)
        if m:
            if cur["buf"]: sections.append(cur)
            cur = {"head": m.group(2).strip(), "buf": []}
        else:
            cur["buf"].append(ln)
    if cur["buf"]: sections.append(cur)
    if not sections:  # fallback: no headings → size split
        sections = [{"head": "(body)", "buf": [body[i:i+MAXCHILD]]} for i in range(0, len(body), MAXCHILD)]

    chunks, idx = [], 0
    for s in sections:
        ptext = "\n".join(s["buf"]).strip()
        if not ptext: continue
        parent_id = f"{doc_id}::p{idx}"
        chunks.append({"chunk_id": parent_id, "parent_id": None, "heading_path": s["head"],
                       "chunk_level": "parent", "chunk_index": idx, "text": ptext[:1200], "keywords": _kw(ptext)})
        # children: chia đoạn theo dòng trống
        paras = [p.strip() for p in re.split(r"\n\s*\n", ptext) if p.strip()]
        for j, p in enumerate(paras):
            for k in range(0, len(p), MAXCHILD):
                seg = p[k:k+MAXCHILD]
                cid = hashlib.sha256(f"{parent_id}-{j}-{k}-{seg}".encode()).hexdigest()[:16]
                chunks.append({"chunk_id": f"{doc_id}::c{cid}", "parent_id": parent_id,
                               "heading_path": s["head"], "chunk_level": "child", "chunk_index": idx,
                               "text": seg, "keywords": _kw(seg)})
        idx += 1
    return chunks
