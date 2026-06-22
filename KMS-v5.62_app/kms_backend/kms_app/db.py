"""Tầng SQLite: kết nối + khởi tạo schema. Đây là 'cơ sở dữ liệu giao dịch'
thay cho JSON local (A10/P28). File nằm ở data/kms.db — mở được bằng mọi
trình xem SQLite để nhìn thấy dữ liệu khi nhập."""
import sqlite3, json
from config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY, role TEXT, department TEXT, clearance TEXT,
  pw_hash TEXT, tags_json TEXT, groups_json TEXT, projects_json TEXT,
  manages_json TEXT, hr_purpose INTEGER DEFAULT 0
);

-- Tầng Source/Ledger: mỗi tài liệu = một 'resource' (OKF concept) có thuộc tính quyền.
-- v5.6: thêm corpus_id + lane (named-corpus isolation, S3) và status (quarantine, S4).
CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY, business_key TEXT, source_file TEXT, title TEXT, file_kind TEXT,
  data_class TEXT, data_subclass TEXT, kind TEXT,
  owner_project TEXT, owner_dept TEXT, required_tags_json TEXT,
  permission_group TEXT, sensitive_level TEXT,
  corpus_id TEXT, lane TEXT, status TEXT DEFAULT 'active', quarantine_reason TEXT,
  created_by TEXT, folder_id TEXT,
  is_credential INTEGER DEFAULT 0, is_personnel_report INTEGER DEFAULT 0, subject_person TEXT,
  content_fp TEXT, perm_fp TEXT, created_at TEXT, updated_at TEXT
);

-- Thư mục do người dùng tạo để tự quản lý tài nguyên (workspace). owner='system'
-- cho ba thư mục mặc định. permission_group là ranh giới quyền của thư mục.
CREATE TABLE IF NOT EXISTS folders (
  folder_id TEXT PRIMARY KEY, name TEXT, owner_user TEXT,
  permission_group TEXT, owner_project TEXT, created_at TEXT
);

-- 'Vector store' stand-in: chunk theo cấu trúc (parent/child), gắn corpus theo doc.
CREATE TABLE IF NOT EXISTS chunks (
  chunk_id TEXT PRIMARY KEY, doc_id TEXT, corpus_id TEXT, parent_id TEXT, heading_path TEXT,
  chunk_level TEXT, chunk_index INTEGER, text TEXT, keywords_json TEXT,
  FOREIGN KEY(doc_id) REFERENCES documents(doc_id)
);

-- Concept graph (S7): bảng adjacency phẳng — mỗi cạnh = concept nguồn → đích.
-- related = đi xuôi; impact = đảo chiều. Mọi traversal vẫn đi QUA PEP.
CREATE TABLE IF NOT EXISTS concept_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT, src_doc TEXT, dst_doc TEXT,
  link_kind TEXT DEFAULT 'related', dangling INTEGER DEFAULT 0
);

-- Hội thoại có chủ quyền (A11/P29)
CREATE TABLE IF NOT EXISTS conversations (
  conv_id TEXT PRIMARY KEY, owner_user TEXT, project_id TEXT, title TEXT,
  max_data_class TEXT DEFAULT 'C1', status TEXT DEFAULT 'open',
  created_at TEXT, updated_at TEXT, retain_until TEXT
);
CREATE TABLE IF NOT EXISTS messages (
  msg_id TEXT PRIMARY KEY, conv_id TEXT, turn_index INTEGER, role TEXT,
  content TEXT, rewritten TEXT, refused INTEGER DEFAULT 0, created_at TEXT,
  FOREIGN KEY(conv_id) REFERENCES conversations(conv_id)
);
CREATE TABLE IF NOT EXISTS message_citations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, msg_id TEXT, doc_id TEXT, chunk_id TEXT,
  sensitive_level TEXT, data_class TEXT
);
-- Session state (A12/P30)
CREATE TABLE IF NOT EXISTS conversation_state (
  conv_id TEXT PRIMARY KEY, rolling_summary TEXT, salient_entities_json TEXT,
  active_topic TEXT, last_referents_json TEXT, updated_at TEXT
);

-- Audit hash-chain + HMAC (P24)
CREATE TABLE IF NOT EXISTS audit_logs (
  log_id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, on_behalf_of_user TEXT,
  agent_id TEXT, action TEXT, resource_ref TEXT, authz_reason TEXT,
  model_id TEXT, model_version TEXT, task_contract_version TEXT,
  lane TEXT, infra_tier TEXT, max_data_class_accessed TEXT, near_miss INTEGER DEFAULT 0,
  previous_log_hash TEXT, current_log_hash TEXT, hmac_signature TEXT
);

-- Manifest ingest (idempotency) — lưu fingerprint đã thấy
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, user_id TEXT, created_at TEXT, expires_at TEXT
);

-- ============================ LỚP PM (v5.62) ============================
-- Quản lý dự án đặt TRÊN nền v5.6. Mọi tài nguyên PM là 'resource' có thuộc
-- tính phân loại + đi qua PEP đọc (authorize) VÀ write-PEP (pm.authz) khi GHI.

-- Dự án: PM sở hữu; data_class = TRẦN của dự án; gắn permission_group + corpus.
CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY, name TEXT, owner_pm TEXT,
  data_class TEXT DEFAULT 'C2', permission_group TEXT DEFAULT 'vsi_internal',
  corpus_id TEXT, status TEXT DEFAULT 'active',
  created_by TEXT, created_at TEXT, updated_at TEXT
);

-- Thành viên + vai trò TRONG dự án (project-scoped RBAC). added_by/at cho audit.
CREATE TABLE IF NOT EXISTS project_members (
  project_id TEXT, user_id TEXT, project_role TEXT,   -- PM|LEADER|ENGINEER
  added_by TEXT, added_at TEXT,
  PRIMARY KEY(project_id, user_id),
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

-- Task: data_class ≤ trần dự án; version = optimistic-lock chống lost-update (W7);
-- approved_by = ai duyệt review→done (separation-of-duty, W11).
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY, project_id TEXT, title TEXT, description TEXT,
  assignee TEXT, created_by TEXT, status TEXT DEFAULT 'todo',  -- todo|doing|review|done|blocked
  priority TEXT DEFAULT 'P2', data_class TEXT DEFAULT 'C2',
  permission_group TEXT, required_tags_json TEXT, spec_doc_ids_json TEXT,
  jira_ref TEXT, gitlab_ref TEXT, due_date TEXT, approved_by TEXT,
  version INTEGER DEFAULT 1, created_at TEXT, updated_at TEXT,
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

-- Comment: data_class KẾ THỪA task (W4); mentions_json → NER/DPIA (W3);
-- redacted = cờ RTBF (steward ẩn nội dung cá nhân, W3).
CREATE TABLE IF NOT EXISTS task_comments (
  comment_id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, project_id TEXT,
  author TEXT, body TEXT, data_class TEXT, mentions_json TEXT,
  redacted INTEGER DEFAULT 0, created_at TEXT,
  FOREIGN KEY(task_id) REFERENCES tasks(task_id)
);

-- Cache item connector (Jira/GitLab): CÓ cột phân loại để PEP đọc được (W4);
-- status='quarantined' khi scanner bắt secret/PII (kế thừa S5).
CREATE TABLE IF NOT EXISTS connector_items (
  item_id TEXT PRIMARY KEY, source TEXT,             -- jira|gitlab
  project_id TEXT, kind TEXT,                         -- issue|commit|merge_request
  ref TEXT, title TEXT, author TEXT, state TEXT, ts TEXT, payload_json TEXT,
  data_class TEXT DEFAULT 'C2', permission_group TEXT DEFAULT 'vsi_internal',
  owner_project TEXT, status TEXT DEFAULT 'active', quarantine_reason TEXT,
  fetched_at TEXT
);

-- Ảnh chụp tiến độ do task-contract tất định sinh (versioned). summary_json theo
-- schema cố định; max_data_class = sàn cứng highest-wins khi promote ra OKF.
CREATE TABLE IF NOT EXISTS progress_snapshots (
  snapshot_id TEXT PRIMARY KEY, project_id TEXT, generated_by TEXT,
  task_contract_version TEXT, schema_version TEXT, summary_json TEXT,
  max_data_class TEXT, exported_doc_id TEXT, created_at TEXT
);

-- Thông báo trong-ứng-dụng (W9): inbox per-user, KHÔNG email. seen=đã đọc.
CREATE TABLE IF NOT EXISTS notifications (
  notif_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, project_id TEXT,
  task_id TEXT, kind TEXT, body TEXT, seen INTEGER DEFAULT 0, created_at TEXT
);
"""

def connect():
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()

def is_empty():
    conn = connect()
    try:
        n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return n == 0
    finally:
        conn.close()

# ---- tiện ích chuyển Row<->dict cho PDP ----
def doc_to_resource(row):
    return {
        "resource_id": row["doc_id"], "title": (row["title"] or row["source_file"]),
        "data_class": row["data_class"], "data_subclass": row["data_subclass"], "kind": row["kind"],
        "owner_project": row["owner_project"], "owner_dept": row["owner_dept"],
        "required_tags": json.loads(row["required_tags_json"] or "[]"),
        "permission_group": row["permission_group"], "sensitive_level": row["sensitive_level"],
        "corpus_id": (row["corpus_id"] if "corpus_id" in row.keys() else None),
        "lane": (row["lane"] if "lane" in row.keys() else None),
        "status": (row["status"] if "status" in row.keys() else "active"),
        "is_credential": bool(row["is_credential"]), "is_personnel_report": bool(row["is_personnel_report"]),
        "subject_person": row["subject_person"],
    }

def row_to_subject(row):
    return {
        "user_id": row["user_id"], "role": row["role"], "department": row["department"],
        "clearance": row["clearance"], "tags": set(json.loads(row["tags_json"] or "[]")),
        "groups": set(json.loads(row["groups_json"] or "[]")),
        "projects": set(json.loads(row["projects_json"] or "[]")),
        "manages": set(json.loads(row["manages_json"] or "[]")),
        "hr_purpose": bool(row["hr_purpose"]),
    }

# ---- PM (v5.62): mỗi tài nguyên PM → 'resource' để authorize() ĐỌC tái dùng nguyên 8 bước.
#     owner_project = project_id ⇒ bước cô lập dự án của authorize() áp ranh giới membership.
def _pm_resource(rid, data_class, owner_project, permission_group, kind, title="",
                 required_tags=None, status="active"):
    # kind = "METADATA" cho authorize() ĐỌC: tài nguyên PM được phân quyền qua project_role
    # (write-PEP) + phân loại + membership, KHÔNG qua trần kind-doc của v5.6 (ROLE_KINDS).
    return {
        "resource_id": rid, "title": title, "data_class": data_class or "C2",
        "data_subclass": None, "kind": "METADATA", "pm_kind": kind, "owner_project": owner_project, "owner_dept": None,
        "required_tags": required_tags or [], "permission_group": permission_group or "vsi_internal",
        "sensitive_level": "restricted" if data_class == "C3" else "confidential",
        "corpus_id": None, "lane": None, "status": status,
        "is_credential": False, "is_personnel_report": False, "subject_person": None,
    }

def project_to_resource(row):
    return _pm_resource(row["project_id"], row["data_class"], row["project_id"],
                        row["permission_group"], "PROJECT", row["name"] or row["project_id"])

def task_to_resource(row):
    return _pm_resource(row["task_id"], row["data_class"], row["project_id"],
                        row["permission_group"], "TASK", row["title"] or row["task_id"],
                        required_tags=json.loads(row["required_tags_json"] or "[]"))

def comment_to_resource(row):
    return _pm_resource(f'c{row["comment_id"]}', row["data_class"], row["project_id"],
                        None, "TASK", "comment")

def connector_item_to_resource(row):
    return _pm_resource(row["item_id"], row["data_class"], row["owner_project"] or row["project_id"],
                        row["permission_group"], "CONNECTOR_ITEM", row["title"] or row["item_id"],
                        status=(row["status"] if "status" in row.keys() else "active"))
