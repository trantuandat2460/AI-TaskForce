"""Phân giải thuộc tính quyền cho mỗi OKF concept (S4 v5.6).

Mỗi file .md mang front-matter YAML; v5.6 dùng tiền tố `vsi_` cho thuộc tính bảo
mật (vsi_data_class, vsi_permission_group, vsi_owner_project, vsi_corpus_id,
vsi_is_credential, vsi_is_personnel_report, vsi_subject_person). Vẫn chấp nhận
khoá trần (data_class…) để tương thích ngược.

QUY TẮC TÁCH ĐÔI (S4): rộng lượng với *cấu trúc tri thức* (kiểu lạ, thiếu trường
tuỳ chọn → dung thứ) nhưng NGHIÊM NGẶT / fail-closed với *thuộc tính bảo mật*:
thiếu/sai data_class → quarantine + mặc định C3; corpus sai ranh giới → từ chối.
"""
from config import settings

FOLDER_GROUP = {"public": "vsi_public", "internal": "vsi_internal", "confidential": "vsi_confidential"}

def parse_front_matter(text):
    meta, body = {}, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end].strip()
            body = text[end+4:].lstrip("\n")
            for line in block.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
    return meta, body

def _get(meta, name, default=None):
    """Đọc khoá vsi_<name> trước, rồi tới khoá trần <name> (back-compat)."""
    if f"vsi_{name}" in meta: return meta[f"vsi_{name}"]
    if name in meta:          return meta[name]
    return default

def coerce(meta, folder):
    """Trả attrs đã chuẩn hoá + corpus_id/lane + status/quarantine_reason (fail-closed)."""
    def lst(s): return [x.strip() for x in s.split(",") if x.strip()] if s else []
    def bol(s): return str(s).lower() in ("1","true","yes","y")

    raw_class = _get(meta, "data_class")
    status, qreason = "active", None

    # --- fail-closed với nhãn phân loại (S3/S4) ---
    if raw_class not in settings.CLASS_RANK:
        # thiếu hoặc sai → cách ly + mặc định mức CAO NHẤT (không bao giờ default-open)
        data_class = "C3"
        status, qreason = "quarantined", f"data_class không hợp lệ ('{raw_class}') → mặc định C3, chờ Data Steward"
    else:
        data_class = raw_class

    # --- corpus + lane: lấy từ vsi_corpus_id hoặc suy theo class; phải khớp ranh giới ---
    corpus_id = _get(meta, "corpus_id") or settings.CLASS_TO_CORPUS.get(data_class)
    corpus = settings.CORPORA.get(corpus_id)
    if corpus is None:
        status, qreason = "quarantined", f"corpus_id không tồn tại ('{corpus_id}')"
        corpus_id = settings.CLASS_TO_CORPUS.get(data_class); corpus = settings.CORPORA[corpus_id]
    elif settings.CLASS_RANK[data_class] > settings.CLASS_RANK[corpus["max_class"]]:
        # chống hạ cấp qua định tuyến: concept C3 trỏ vào corpus ≤C2 → từ chối
        status, qreason = "quarantined", f"concept {data_class} không được vào {corpus_id} (trần {corpus['max_class']})"
        corpus_id = settings.CLASS_TO_CORPUS[data_class]; corpus = settings.CORPORA[corpus_id]
    lane = corpus["lane"]

    return {
        "data_class":      data_class,
        "data_subclass":   _get(meta, "data_subclass"),
        "kind":            _get(meta, "kind", "METADATA"),
        "owner_project":   _get(meta, "owner_project") or None,
        "owner_dept":      _get(meta, "owner_dept") or None,
        "required_tags":   lst(_get(meta, "required_tags")),
        "permission_group":_get(meta, "permission_group") or FOLDER_GROUP.get(folder, "vsi_internal"),
        "sensitive_level": _get(meta, "sensitive_level", "confidential"),
        "corpus_id":       corpus_id,
        "lane":            lane,
        "status":          status,
        "quarantine_reason": qreason,
        "created_by":      _get(meta, "created_by") or None,
        "folder_id":       _get(meta, "folder_id") or None,
        "is_credential":   bol(_get(meta, "is_credential")),
        "is_personnel_report": bol(_get(meta, "is_personnel_report")),
        "subject_person":  _get(meta, "subject_person") or None,
        "related":         lst(_get(meta, "related")),   # concept graph: cạnh khai trong frontmatter
    }
