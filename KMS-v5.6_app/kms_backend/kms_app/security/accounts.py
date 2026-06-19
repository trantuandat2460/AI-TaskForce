"""Quản trị tài khoản (control-plane, ADMIN-only). Tạo / sửa / xoá / gán quyền
người dùng. Fail-closed: nhóm quyền/clearance/vai trò ngoài tập hợp lệ ⇒ từ chối;
không cho tự xoá mình hay xoá ADMIN cuối cùng (chống tự khoá). Mật khẩu băm PBKDF2.

Hàm trả (ok: bool, msg: str) để route hiển thị; mọi thay đổi do route ghi audit.
"""
import json
from config import settings
from kms_app import db
from kms_app.security import passwords

def _csv(s):
    return [x.strip() for x in (s or "").replace("\n", ",").split(",") if x.strip()]

def list_users(conn):
    return conn.execute("SELECT * FROM users ORDER BY user_id").fetchall()

def get_user(conn, user_id):
    return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

def _validate(role, clearance, groups):
    if role not in settings.ROLE_KINDS:
        return f"vai trò không hợp lệ: {role}"
    if clearance not in settings.CLASS_RANK:
        return f"clearance không hợp lệ: {clearance}"
    bad = [g for g in groups if g not in settings.PERMISSION_GROUPS]
    if bad:
        return "nhóm quyền không hợp lệ: " + ", ".join(bad)
    return None

def create_user(conn, f):
    """f: dict các list-value từ form (urllib.parse.parse_qs)."""
    uid = (f.get("user_id", [""])[0] or "").strip()
    pw  = f.get("password", [""])[0] or ""
    if not uid:
        return False, "thiếu user_id"
    if get_user(conn, uid):
        return False, f"user '{uid}' đã tồn tại"
    if len(pw) < 3:
        return False, "mật khẩu tối thiểu 3 ký tự"
    role = f.get("role", ["ENGINEER"])[0]
    clearance = f.get("clearance", ["C2"])[0]
    groups = f.get("groups", [])                       # checkbox → nhiều giá trị
    err = _validate(role, clearance, groups)
    if err:
        return False, err
    conn.execute("""INSERT INTO users
        (user_id,role,department,clearance,pw_hash,tags_json,groups_json,projects_json,manages_json,hr_purpose)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (uid, role, f.get("department", [""])[0], clearance, passwords.hash_password(pw),
         json.dumps(_csv(f.get("tags", [""])[0])), json.dumps(groups),
         json.dumps(_csv(f.get("projects", [""])[0])), json.dumps(_csv(f.get("manages", [""])[0])),
         1 if f.get("hr_purpose") else 0))
    conn.commit()
    return True, f"đã tạo user '{uid}' ({role}/{clearance})"

def update_user(conn, f):
    uid = (f.get("user_id", [""])[0] or "").strip()
    row = get_user(conn, uid)
    if not row:
        return False, f"không có user '{uid}'"
    role = f.get("role", [row["role"]])[0]
    clearance = f.get("clearance", [row["clearance"]])[0]
    groups = f.get("groups", [])
    err = _validate(role, clearance, groups)
    if err:
        return False, err
    # chống tự khoá: không cho hạ ADMIN cuối cùng xuống vai trò khác
    if row["role"] == "ADMIN" and role != "ADMIN" and _admin_count(conn) <= 1:
        return False, "không thể hạ quyền ADMIN cuối cùng (chống tự khoá)"
    pw = f.get("password", [""])[0] or ""
    conn.execute("""UPDATE users SET role=?,department=?,clearance=?,tags_json=?,groups_json=?,
        projects_json=?,manages_json=?,hr_purpose=? WHERE user_id=?""",
        (role, f.get("department", [row["department"]])[0], clearance,
         json.dumps(_csv(f.get("tags", [""])[0])), json.dumps(groups),
         json.dumps(_csv(f.get("projects", [""])[0])), json.dumps(_csv(f.get("manages", [""])[0])),
         1 if f.get("hr_purpose") else 0, uid))
    if len(pw) >= 3:
        conn.execute("UPDATE users SET pw_hash=? WHERE user_id=?", (passwords.hash_password(pw), uid))
    conn.commit()
    return True, f"đã cập nhật user '{uid}'"

def delete_user(conn, uid, acting_user):
    row = get_user(conn, uid)
    if not row:
        return False, f"không có user '{uid}'"
    if uid == acting_user:
        return False, "không thể xoá chính tài khoản đang đăng nhập"
    if row["role"] == "ADMIN" and _admin_count(conn) <= 1:
        return False, "không thể xoá ADMIN cuối cùng (chống tự khoá)"
    conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))   # thu hồi phiên đang mở
    conn.commit()
    return True, f"đã xoá user '{uid}' và thu hồi phiên"

def _admin_count(conn):
    return conn.execute("SELECT COUNT(*) FROM users WHERE role='ADMIN'").fetchone()[0]
