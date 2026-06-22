"""Concept graph (S7 v5.6): truy vấn adjacency 1–2 hop trên bảng concept_links.

  - related(): đi xuôi cạnh — "concept này liên quan tới những concept nào?"
  - impact():  ĐẢO CHIỀU cạnh — "đổi concept này thì những concept nào bị ảnh hưởng?"

BẤT BIẾN BẢO MẬT: mọi traversal đi QUA PEP. Cạnh tới concept người dùng KHÔNG
được đọc bị DROP HOÀN TOÀN — không trả cạnh, không trả dst-id, không trả số đếm
"N hàng xóm ẩn" (okf_concept_id là metadata nhạy cảm ở mức của đích). Đồ thị
KHÔNG phải cửa hậu: thấy có cạnh ≠ được đọc nội dung đích.
"""
from kms_app import db
from kms_app.security.pdp import authorize
from kms_app.security import pep

def _authz_doc(conn, subject, doc_id, my_lane):
    """Trả document-row nếu subject được phép (PEP-2 + corpus reachable), ngược lại None."""
    row = conn.execute("SELECT * FROM documents WHERE doc_id=? AND status='active'", (doc_id,)).fetchone()
    if not row: return None
    res = db.doc_to_resource(row)
    if not pep.corpus_reachable(res.get("corpus_id"), my_lane, subject["clearance"]):
        return None
    return row if authorize(subject, res).allow else None

def _neighbors(conn, doc_id, reverse):
    if reverse:
        return conn.execute("SELECT src_doc AS nb, link_kind, dangling FROM concept_links WHERE dst_doc=?", (doc_id,)).fetchall()
    return conn.execute("SELECT dst_doc AS nb, link_kind, dangling FROM concept_links WHERE src_doc=?", (doc_id,)).fetchall()

def _walk(conn, subject, start, reverse, hops, my_lane):
    """BFS tới `hops`, chỉ giữ các đích qua được PEP. Cạnh cross-lane/không-quyền bị drop sạch."""
    seen, frontier, out = {start}, [start], []
    for depth in range(hops):
        nxt = []
        for node in frontier:
            for e in _neighbors(conn, node, reverse):
                nb = e["nb"]
                if nb in seen: continue
                seen.add(nb)
                if e["dangling"]:
                    continue   # cạnh gãy (tri thức tương lai) — không phải kết quả đọc được
                row = _authz_doc(conn, subject, nb, my_lane)
                if row is None:
                    continue   # DROP HOÀN TOÀN: không lộ tồn tại/tên/đếm
                out.append({"doc_id": nb, "title": row["title"], "data_class": row["data_class"],
                            "corpus_id": row["corpus_id"], "kind": row["kind"], "hop": depth + 1})
                nxt.append(nb)
        frontier = nxt
    return out

def related(conn, subject, doc_id, hops=2, my_lane="SECURED"):
    return _walk(conn, subject, doc_id, reverse=False, hops=hops, my_lane=my_lane)

def impact(conn, subject, doc_id, hops=2, my_lane="SECURED"):
    return _walk(conn, subject, doc_id, reverse=True, hops=hops, my_lane=my_lane)
