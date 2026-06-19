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
