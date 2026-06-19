"""Workspace người dùng (S4/S5): tự tạo thư mục + tải tài liệu theo ĐÚNG hierarchy.

Bất biến (fail-closed, không thương lượng):
  - Người dùng KHÔNG tạo được nội dung vượt clearance của mình (data_class ≤ clearance).
  - permission_group phải ∈ groups của người dùng; owner_project (nếu có) ∈ projects.
  - Trước khi ghi: security scan (secret/NER) + spell/quality check. Secret ⇒ TỪ CHỐI.
    NER nghi PII chưa gắn cờ ⇒ ghi nhưng QUARANTINE chờ Data Steward.
  - LLM/người không bao giờ tự nới nhãn: gán data_class là lựa chọn trong trần clearance.
Filesystem là nguồn-chân-lý: ghi .md (OKF frontmatter) rồi ingest (derive vào SQLite).
"""
import re, json, datetime, secrets
from config import settings
from kms_app import db
from kms_app.ingestion import scanners, quality, store as istore
from kms_app.security.pdp import authorize

def _now(): return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
def slugify(s):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (s or "").strip().lower()).strip("-")
    return s or "folder"

# ---------------- Folders ----------------
def list_folders(conn, subject):
    """Thư mục người dùng được dùng: của chính mình + system folder có group ∈ groups (admin: tất cả)."""
    rows = conn.execute("SELECT * FROM folders ORDER BY owner_user, name").fetchall()
    if subject["role"] == "ADMIN":
        return rows
    return [r for r in rows if r["owner_user"] == subject["user_id"]
            or (r["owner_user"] == "system" and r["permission_group"] in subject["groups"])]

def get_folder(conn, folder_id):
    return conn.execute("SELECT * FROM folders WHERE folder_id=?", (folder_id,)).fetchone()

def create_folder(conn, subject, name, permission_group, owner_project=None):
    name = (name or "").strip()
    if not name:
        return False, "thiếu tên thư mục", None
    if subject["role"] != "ADMIN" and permission_group not in subject["groups"]:
        return False, f"bạn không thuộc nhóm quyền '{permission_group}'", None
    if permission_group not in settings.PERMISSION_GROUPS:
        return False, f"nhóm quyền không hợp lệ: {permission_group}", None
    if owner_project and subject["role"] != "ADMIN" and owner_project not in subject["projects"]:
        return False, f"bạn không thuộc dự án '{owner_project}'", None
    folder_id = f"{subject['user_id']}__{slugify(name)}"
    if get_folder(conn, folder_id):
        return False, "thư mục đã tồn tại", folder_id
    (settings.DOCUMENTS_DIR / folder_id).mkdir(parents=True, exist_ok=True)
    conn.execute("INSERT INTO folders(folder_id,name,owner_user,permission_group,owner_project,created_at) VALUES(?,?,?,?,?,?)",
                 (folder_id, name, subject["user_id"], permission_group, owner_project or None, _now()))
    conn.commit()
    return True, f"đã tạo thư mục '{name}'", folder_id

# ---------------- Upload preflight + commit ----------------
def preflight(subject, fields, folder):
    """Chạy mọi kiểm tra KHÔNG ghi gì. Trả dict: hierarchy_errors, security, spelling, ok."""
    title = (fields.get("title", [""])[0] or "").strip()
    body  = fields.get("body", [""])[0] or ""
    data_class = fields.get("data_class", ["C2"])[0]

    herr = []
    if not title: herr.append("thiếu tiêu đề")
    if not body.strip(): herr.append("nội dung rỗng")
    if folder is None:
        herr.append("thư mục không hợp lệ / ngoài quyền")
    if data_class not in settings.CLASS_RANK:
        herr.append(f"data_class không hợp lệ: {data_class}")
    elif settings.CLASS_RANK[data_class] > settings.CLASS_RANK[subject["clearance"]]:
        herr.append(f"không thể tạo {data_class} vượt clearance {subject['clearance']} của bạn")

    sec_hit, sec_reason = scanners.secret_scan(body)
    looks_personnel, names = scanners.ner_scan(body)
    flagged_personnel = str(fields.get("is_personnel_report", [""])[0]).lower() in ("1", "true", "on", "yes")
    security = {"secret": (sec_hit, sec_reason),
                "personnel": (looks_personnel, names, flagged_personnel)}
    spelling = quality.spell_check(body)

    # secret ⇒ chặn cứng; hierarchy lỗi ⇒ chặn. spelling/PII là cảnh báo.
    ok = (not herr) and (not sec_hit)
    return {"title": title, "body": body, "data_class": data_class,
            "hierarchy_errors": herr, "security": security, "spelling": spelling, "ok": ok}

def commit_upload(conn, subject, fields, folder, ack_spelling=False):
    """Tái chạy preflight (fail-closed) rồi ghi .md + ingest. Trả (ok, msg, doc_id)."""
    pf = preflight(subject, fields, folder)
    if pf["hierarchy_errors"]:
        return False, "Hierarchy: " + "; ".join(pf["hierarchy_errors"]), None
    if pf["security"]["secret"][0]:
        return False, f"Bị chặn: nội dung chứa credential ({pf['security']['secret'][1]}). Hãy loại bỏ bí mật.", None
    if pf["spelling"] and not ack_spelling:
        return False, f"Còn {len(pf['spelling'])} cảnh báo chính tả — sửa hoặc tick 'bỏ qua cảnh báo' để tiếp tục.", None

    looks_personnel, names, flagged = pf["security"]["personnel"]
    doc_id = f"U-{subject['user_id']}-{secrets.token_hex(3)}"
    meta = {
        "doc_id": doc_id,
        "vsi_data_class": pf["data_class"],
        "vsi_permission_group": folder["permission_group"],
        "vsi_kind": fields.get("kind", ["METADATA"])[0] or "METADATA",
        "vsi_sensitive_level": "restricted" if pf["data_class"] == "C3" else "confidential",
        "vsi_created_by": subject["user_id"],
        "vsi_folder_id": folder["folder_id"],
    }
    op = (fields.get("owner_project", [""])[0] or folder["owner_project"] or "").strip()
    if op: meta["vsi_owner_project"] = op
    tags = (fields.get("required_tags", [""])[0] or "").strip()
    if tags: meta["vsi_required_tags"] = tags
    related = (fields.get("related", [""])[0] or "").strip()
    if related: meta["related"] = related
    # CHỈ gắn cờ nhân sự khi NGƯỜI DÙNG khai tường minh. Nếu NER nghi PII mà user
    # KHÔNG khai → KHÔNG tự gắn cờ: để scanner ở ingest quarantine → Data Steward
    # review (đúng S3: không xử lý như tài liệu kỹ thuật, không tự phân loại).
    if flagged:
        meta["vsi_is_personnel_report"] = "true"
        if names: meta["vsi_subject_person"] = names[0]

    fm = "\n".join(["---"] + [f"{k}: {v}" for k, v in meta.items()] + ["---", ""])
    fpath = settings.DOCUMENTS_DIR / folder["folder_id"] / f"{slugify(pf['title'])}-{doc_id}.md"
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text(fm + f"# {pf['title']}\n\n{pf['body']}\n", encoding="utf-8")

    istore.ingest_all(conn)   # idempotent: chỉ file mới được chunk
    row = conn.execute("SELECT status, quarantine_reason FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    if row and row["status"] == "quarantined":
        return True, f"Đã tải lên {doc_id} nhưng QUARANTINE: {row['quarantine_reason']} (chờ Data Steward).", doc_id
    return True, f"Đã tải lên & index: {doc_id} ({pf['data_class']} · {folder['permission_group']}).", doc_id
