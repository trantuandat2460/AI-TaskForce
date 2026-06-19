"""Phễu truy xuất 5 lớp (S6 v5.6) — metadata-first, embedding chỉ là MỘT lớp.

  [1] ACCESS FILTER  permission_group / corpus / lane  (PEP-1, fail-closed) — rẻ, cứng
  [2] FACET NARROW   thu hẹp theo facet suy từ câu hỏi (kind/project/tags)
  [3] RANK           "dense" (overlap ngữ nghĩa) ║ lexical (khớp token) → trộn RRF
  [4] RERANK         cross-encoder stand-in chấm lại MỘT lần trên tập đã trộn (cap)
  [5] GRAPH EXPAND   theo concept_links thêm ngữ cảnh liên quan (vẫn qua PEP ở routes)

Bản này mô phỏng vector search bằng overlap keyword; PEP-2 + corpus reachability
được áp ở web/routes (ngoài 5 lớp). Trả list chunk-row + trace từng lớp.
"""
import re, json
from config import settings

STOP = {"của","và","các","là","một","có","cho","khi","thế","nào","hoạt","động","được","theo",
        "với","trong","này","đó","thì","sao","như","về","đến","từ","ra","vào","trên","dưới",
        "hãy","tôi","bạn","cái","gì","những","để","làm","còn","hỏi","xem","cách"}

# facet gợi ý: từ khoá trong câu hỏi → bộ lọc kind (text→filter, model rẻ stand-in)
FACET_KIND = {
    "báo cáo": "PROGRESS_REPORT", "weekly": "PROGRESS_REPORT", "tuần": "PROGRESS_REPORT",
    "testbench": "TESTBENCH", "kiểm thử": "TESTBENCH",
    "isa": "SPEC_DETAIL", "rtl": "IP", "datapath": "IP",
}

def _tok(s):
    return {t for t in re.findall(r"[a-zà-ỹ0-9_]{3,}", (s or "").lower()) if t not in STOP}

def _rrf(rankings, k):
    """Reciprocal Rank Fusion: gộp nhiều bảng xếp hạng theo THỨ HẠNG (không theo điểm)."""
    score = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            score[cid] = score.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return score

def retrieve(conn, query, allowed_doc_ids, top_k=None, trace=None):
    """allowed_doc_ids: tập doc đã qua ACCESS FILTER (PEP-1 + corpus reachable) ở routes."""
    top_k = top_k or settings.RETRIEVAL_TOPK
    tr = trace if trace is not None else []
    if not allowed_doc_ids:
        tr.append(("RANK", "skip", "không có doc nào sau ACCESS FILTER"))
        return [], tr
    qtok = _tok(query)
    if not qtok:
        tr.append(("RANK", "skip", "truy vấn rỗng sau lọc stopword"))
        return [], tr

    ph = ",".join("?" * len(allowed_doc_ids))
    rows = conn.execute(f"SELECT * FROM chunks WHERE doc_id IN ({ph})", tuple(allowed_doc_ids)).fetchall()
    docs = {r["doc_id"]: r for r in conn.execute(
        f"SELECT doc_id,title,kind FROM documents WHERE doc_id IN ({ph})", tuple(allowed_doc_ids)).fetchall()}

    # [2] FACET NARROW — suy facet kind từ câu hỏi; chỉ NARROW, độ tin thấp thì bỏ qua (fail-safe).
    ql = query.lower()
    want_kind = next((v for kkey, v in FACET_KIND.items() if kkey in ql), None)
    if want_kind:
        narrowed = [r for r in rows if r["doc_id"] in docs and docs[r["doc_id"]]["kind"] == want_kind]
        if narrowed:           # chỉ áp khi còn ứng viên (không over-constrain)
            rows = narrowed
            tr.append(("FACET NARROW", "pass", f"kind={want_kind} → còn {len(rows)} chunk"))
        else:
            tr.append(("FACET NARROW", "skip", f"facet kind={want_kind} độ tin thấp → bỏ qua (fail-safe)"))
    else:
        tr.append(("FACET NARROW", "skip", "không suy ra facet từ câu hỏi"))

    # [3] RANK — hai bảng xếp hạng song song rồi trộn RRF.
    dense, lexical = [], []
    for r in rows:
        kw = set(json.loads(r["keywords_json"] or "[]")) - STOP
        title_tok = _tok(docs[r["doc_id"]]["title"] if r["doc_id"] in docs else "")
        dense_s = 2*len(qtok & kw) + 2*len(qtok & title_tok) + len(qtok & _tok(r["heading_path"] or ""))
        lex_s = sum(r["text"].lower().count(t) for t in qtok)      # khớp token thô (lexical)
        if dense_s > 0: dense.append((dense_s, r["chunk_id"]))
        if lex_s > 0:   lexical.append((lex_s, r["chunk_id"]))
    dense.sort(key=lambda x: x[0], reverse=True)
    lexical.sort(key=lambda x: x[0], reverse=True)
    fused = _rrf([[c for _, c in dense], [c for _, c in lexical]], settings.RRF_K)
    if not fused:
        tr.append(("RANK", "skip", "không chunk nào khớp (dense ∪ lexical rỗng)"))
        return [], tr
    tr.append(("RANK", "pass", f"dense={len(dense)} ║ lexical={len(lexical)} → RRF trộn {len(fused)}"))

    # [4] RERANK — một lần, trên tập đã cap.
    byid = {r["chunk_id"]: r for r in rows}
    cand = sorted(fused, key=fused.get, reverse=True)[:settings.RERANK_CANDIDATE_CAP]
    def _rerank_score(cid):
        r = byid[cid]
        return fused[cid] + 0.01*sum(r["text"].lower().count(t) for t in qtok)
    cand.sort(key=_rerank_score, reverse=True)
    tr.append(("RERANK", "pass", f"cross-encoder (stand-in) 1 lần trên ≤{settings.RERANK_CANDIDATE_CAP} ứng viên"))

    # gộp theo doc để đủ đa dạng nguồn, lấy top_k
    seen, out = set(), []
    for cid in cand:
        r = byid[cid]
        if r["doc_id"] in seen: continue
        seen.add(r["doc_id"]); out.append(r)
        if len(out) >= top_k: break
    return out, tr
