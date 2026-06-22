"""CRUD lớp PM — MỌI mutation đi qua write-PEP (pm.authz.authorize_action) rồi ghi
audit hash-chain (kể cả near-miss khi bị từ chối). Optimistic-lock cho task (W7).

Hợp đồng: mỗi hàm mutation trả (ok: bool, msg: str, *extra). Hàm liệt kê dùng
can_read() (tái dùng authorize() đọc của v5.6) ⇒ danh sách chỉ gồm thứ được phép
(chống liệt kê) và task/comment C3 bị ẩn khỏi thành viên ≤C2.
"""
import re, json, datetime, secrets
from config import settings
from config.settings import CLASS_RANK, CLASS_TO_CORPUS
from kms_app import db
from kms_app.security import audit
from kms_app.ingestion import scanners
from kms_app.pm import authz, notify


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def _slug(s):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (s or "").strip().lower()).strip("-")
    return s or "x"

def _audit(conn, subject, action, ref, decision, max_class=None):
    audit.append(conn, on_behalf_of_user=subject["user_id"], agent_id="pm:write-pep",
                 action=f"pm:{action}", resource_ref=ref or "-", authz_reason=decision.reason,
                 max_data_class_accessed=max_class, near_miss=0 if decision.allow else 1)


# ===================== PROJECTS =====================
def get_project(conn, pid):
    return conn.execute("SELECT * FROM projects WHERE project_id=?", (pid,)).fetchone()

def project_class(conn, pid):
    r = get_project(conn, pid)
    return r["data_class"] if r else None

def list_projects(conn, subject):
    """Dự án người dùng được thấy: là thành viên (mọi vai trò) — admin: tất cả.
    Dựng từ tập can_read ⇒ chống liệt kê dự án ngoài phạm vi."""
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    out = []
    for r in rows:
        if subject["role"] == "ADMIN" or (authz.is_member(conn, subject["user_id"], r["project_id"])
                                          and authz.can_read(conn, subject, db.project_to_resource(r))):
            out.append(r)
    return out

def create_project(conn, subject, name, data_class, permission_group):
    name = (name or "").strip()
    d = authz.authorize_action(conn, subject, "create_project",
                               {"requested_data_class": data_class})
    if not d.allow:
        _audit(conn, subject, "create_project", name, d)
        return False, f"từ chối: {d.reason}", None, d
    if not name:
        return False, "thiếu tên dự án", None, d
    if data_class not in CLASS_RANK:
        return False, f"data_class không hợp lệ: {data_class}", None, d
    if permission_group not in settings.PERMISSION_GROUPS:
        return False, f"permission_group không hợp lệ: {permission_group}", None, d
    pid = "PRJ-" + _slug(name)[:18].upper().replace("-", "_")
    if get_project(conn, pid):
        pid = pid + "-" + secrets.token_hex(2)
    now = _now()
    conn.execute("""INSERT INTO projects
        (project_id,name,owner_pm,data_class,permission_group,corpus_id,status,created_by,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (pid, name, subject["user_id"], data_class, permission_group,
         CLASS_TO_CORPUS.get(data_class), "active", subject["user_id"], now, now))
    # PM tạo dự án trở thành thành viên PM (bootstrap — W14: ai tạo PM đầu tiên).
    conn.execute("""INSERT OR REPLACE INTO project_members(project_id,user_id,project_role,added_by,added_at)
        VALUES(?,?,?,?,?)""", (pid, subject["user_id"], "PM", subject["user_id"], now))
    _audit(conn, subject, "create_project", pid, d, data_class)
    conn.commit()
    return True, f"đã tạo dự án {pid} ({data_class})", pid, d

def add_member(conn, subject, pid, user_id, project_role):
    d = authz.authorize_action(conn, subject, "add_member", {"project_id": pid})
    if not d.allow:
        _audit(conn, subject, "add_member", f"{pid}/{user_id}", d)
        return False, f"từ chối: {d.reason}", d
    user_id = (user_id or "").strip()
    if project_role not in settings.PROJECT_ROLES:
        return False, f"project_role không hợp lệ: {project_role}", d
    if not conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone():
        return False, f"không có user '{user_id}'", d
    conn.execute("""INSERT OR REPLACE INTO project_members(project_id,user_id,project_role,added_by,added_at)
        VALUES(?,?,?,?,?)""", (pid, user_id, project_role, subject["user_id"], _now()))
    _audit(conn, subject, "add_member", f"{pid}/{user_id}:{project_role}", d)
    notify.push(conn, user_id, "membership", f"Bạn được thêm vào dự án {pid} với vai trò {project_role}.", pid)
    conn.commit()
    return True, f"đã thêm {user_id} ({project_role}) vào {pid}", d

def close_project(conn, subject, pid):
    d = authz.authorize_action(conn, subject, "close_project", {"project_id": pid})
    if not d.allow:
        _audit(conn, subject, "close_project", pid, d)
        return False, f"từ chối: {d.reason}", d
    n_open = conn.execute("SELECT COUNT(*) FROM tasks WHERE project_id=? AND status NOT IN('done')",
                          (pid,)).fetchone()[0]
    if n_open:
        return False, f"còn {n_open} task chưa done — hoàn tất hoặc dời hết trước khi đóng (an toàn).", d
    conn.execute("UPDATE projects SET status='closed', updated_at=? WHERE project_id=?", (_now(), pid))
    _audit(conn, subject, "close_project", pid, d)
    conn.commit()
    return True, f"đã đóng dự án {pid}", d


# ===================== TASKS =====================
def get_task(conn, tid):
    return conn.execute("SELECT * FROM tasks WHERE task_id=?", (tid,)).fetchone()

def list_tasks(conn, subject, pid):
    """Mọi thành viên thấy MỌI task của dự án mình (W11: read = project-scoped);
    task C3 vẫn bị ẩn khỏi thành viên ≤C2 qua can_read."""
    rows = conn.execute("SELECT * FROM tasks WHERE project_id=? ORDER BY created_at", (pid,)).fetchall()
    if subject["role"] == "ADMIN":
        return rows
    if not authz.is_member(conn, subject["user_id"], pid):
        return []
    return [r for r in rows if authz.can_read(conn, subject, db.task_to_resource(r))]

def my_tasks(conn, user_id):
    return conn.execute("SELECT * FROM tasks WHERE assignee=? AND status NOT IN('done') ORDER BY due_date",
                        (user_id,)).fetchall()

def create_task(conn, subject, pid, fields):
    data_class = fields.get("data_class", ["C2"])[0]
    assignee = (fields.get("assignee", [""])[0] or "").strip() or None
    d = authz.authorize_action(conn, subject, "create_task",
                               {"project_id": pid, "project_class": project_class(conn, pid),
                                "requested_data_class": data_class})
    if not d.allow:
        _audit(conn, subject, "create_task", pid, d)
        return False, f"từ chối: {d.reason}", None, d
    title = (fields.get("title", [""])[0] or "").strip()
    if not title:
        return False, "thiếu tiêu đề task", None, d
    if assignee and not authz.is_member(conn, assignee, pid):
        return False, f"assignee '{assignee}' không thuộc dự án (W11)", None, d
    proj = get_project(conn, pid)
    tid = "T-" + secrets.token_hex(3)
    now = _now()
    conn.execute("""INSERT INTO tasks
        (task_id,project_id,title,description,assignee,created_by,status,priority,data_class,
         permission_group,required_tags_json,spec_doc_ids_json,jira_ref,gitlab_ref,due_date,
         approved_by,version,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (tid, pid, title, fields.get("description", [""])[0], assignee, subject["user_id"],
         "todo", fields.get("priority", ["P2"])[0], data_class, proj["permission_group"],
         json.dumps([t.strip() for t in (fields.get("required_tags", [""])[0] or "").split(",") if t.strip()]),
         json.dumps([]), None, None, fields.get("due_date", [""])[0] or None, None, 1, now, now))
    _audit(conn, subject, "create_task", tid, d, data_class)
    if assignee:
        notify.push(conn, assignee, "assigned", f"Bạn được giao task {tid}: {title}", pid, tid)
    conn.commit()
    return True, f"đã tạo task {tid}", tid, d

def assign_task(conn, subject, tid, assignee, expected_version):
    t = get_task(conn, tid)
    if not t:
        return False, "không có task", None
    assignee = (assignee or "").strip() or None
    d = authz.authorize_action(conn, subject, "assign_task",
                               {"project_id": t["project_id"], "task": dict(t), "assignee": assignee})
    if not d.allow:
        _audit(conn, subject, "assign_task", tid, d)
        return False, f"từ chối: {d.reason}", d
    if not _cas(conn, tid, expected_version, {"assignee": assignee}):
        return False, "XUNG ĐỘT phiên bản (có người vừa sửa) — tải lại rồi thử lại (W7).", d
    _audit(conn, subject, "assign_task", tid, d)
    notify.push(conn, assignee, "assigned", f"Bạn được giao task {tid}.", t["project_id"], tid)
    conn.commit()
    return True, f"đã giao {tid} cho {assignee}", d

def change_status(conn, subject, tid, new_status, expected_version):
    t = get_task(conn, tid)
    if not t:
        return False, "không có task", None
    if new_status not in settings.TASK_STATUSES:
        return False, f"trạng thái không hợp lệ: {new_status}", None
    d = authz.authorize_action(conn, subject, "change_status",
                               {"project_id": t["project_id"], "task": dict(t), "new_status": new_status})
    if not d.allow:
        _audit(conn, subject, "change_status", tid, d)
        return False, f"từ chối: {d.reason}", d
    fields = {"status": new_status}
    if new_status == "done" and t["status"] == "review":
        fields["approved_by"] = subject["user_id"]   # ai duyệt (separation-of-duty, W11)
    if not _cas(conn, tid, expected_version, fields):
        return False, "XUNG ĐỘT phiên bản (có người vừa sửa) — tải lại rồi thử lại (W7).", d
    _audit(conn, subject, "change_status", f"{tid}:{t['status']}→{new_status}", d)
    # báo cho assignee + creator (trừ người thao tác)
    notify.fan_out(conn, [t["assignee"], t["created_by"]], "status",
                   f"Task {tid}: {t['status']} → {new_status}", t["project_id"], tid, exclude=subject["user_id"])
    conn.commit()
    return True, f"đã chuyển {tid}: {t['status']} → {new_status}", d

def _cas(conn, tid, expected_version, fields):
    """Compare-and-swap optimistic lock (W7): chỉ ghi nếu version khớp; bump version."""
    try:
        ev = int(expected_version)
    except (TypeError, ValueError):
        ev = None
    sets = ", ".join(f"{k}=?" for k in fields)
    params = list(fields.values())
    if ev is None:
        cur = conn.execute(f"UPDATE tasks SET {sets}, version=version+1, updated_at=? WHERE task_id=?",
                           params + [_now(), tid])
    else:
        cur = conn.execute(f"UPDATE tasks SET {sets}, version=version+1, updated_at=? WHERE task_id=? AND version=?",
                           params + [_now(), tid, ev])
    return cur.rowcount == 1


# ===================== COMMENTS =====================
def list_comments(conn, subject, tid):
    t = get_task(conn, tid)
    if not t:
        return []
    if subject["role"] != "ADMIN" and not authz.can_read(conn, subject, db.task_to_resource(t)):
        return []
    return conn.execute("SELECT * FROM task_comments WHERE task_id=? ORDER BY comment_id", (tid,)).fetchall()

def add_comment(conn, subject, tid, body):
    t = get_task(conn, tid)
    if not t:
        return False, "không có task", None
    d = authz.authorize_action(conn, subject, "comment",
                               {"project_id": t["project_id"], "task": dict(t)})
    if not d.allow:
        _audit(conn, subject, "comment", tid, d)
        return False, f"từ chối: {d.reason}", d
    body = (body or "").strip()
    if not body:
        return False, "comment rỗng", d
    looks_personnel, names = scanners.ner_scan(body)   # NER → DPIA (W3)
    mentions = re.findall(r"@([A-Za-z0-9_]+)", body)
    conn.execute("""INSERT INTO task_comments(task_id,project_id,author,body,data_class,mentions_json,redacted,created_at)
        VALUES(?,?,?,?,?,?,0,?)""",
        (tid, t["project_id"], subject["user_id"], body, t["data_class"],
         json.dumps(sorted(set(mentions) | (set(names) if looks_personnel else set()))), _now()))
    _audit(conn, subject, "comment", tid, d, t["data_class"])
    # báo cho assignee + người đã từng comment + @mention (trừ tác giả)
    prior = [r["author"] for r in conn.execute("SELECT DISTINCT author FROM task_comments WHERE task_id=?", (tid,)).fetchall()]
    notify.fan_out(conn, [t["assignee"]] + prior + mentions, "comment",
                   f"Comment mới trên task {tid}", t["project_id"], tid, exclude=subject["user_id"])
    conn.commit()
    note = " (NER nghi PII → DPIA/steward lưu ý)" if looks_personnel else ""
    return True, "đã thêm comment" + note, d

def redact_comment(conn, subject, cid):
    """RTBF/steward (W3): ẩn nội dung cá nhân khỏi comment, giữ vết audit."""
    row = conn.execute("SELECT * FROM task_comments WHERE comment_id=?", (cid,)).fetchone()
    if not row:
        return False, "không có comment", None
    d = authz.authorize_action(conn, subject, "redact_comment", {"project_id": row["project_id"]})
    if not d.allow:
        _audit(conn, subject, "redact_comment", f"c{cid}", d)
        return False, f"từ chối: {d.reason}", d
    conn.execute("UPDATE task_comments SET body='[đã ẩn theo RTBF/DPIA]', redacted=1 WHERE comment_id=?", (cid,))
    _audit(conn, subject, "redact_comment", f"c{cid}", d)
    conn.commit()
    return True, "đã ẩn comment (RTBF)", d
