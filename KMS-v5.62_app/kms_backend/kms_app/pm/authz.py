"""WRITE-PEP cho lớp PM (v5.62) — thành phần BỔ SUNG MỚI so với nền v5.6.

Vì sao tồn tại (phê bình W1): `authorize()` của v5.6 (security/pdp.py) chỉ phân quyền
ĐỌC — quyết định một chủ thể có được *truy xuất* một resource hay không. Toàn bộ phía
GHI / đổi-trạng-thái của lớp PM (tạo dự án, giao việc, đổi status, comment, đóng dự án,
biên dịch tiến độ) KHÔNG có cơ chế thực thi trong v5.6. File này LÀ cơ chế đó. Nó KHÔNG
được quảng cáo là 'tái dùng nguyên vẹn v5.6' — nó là write-PEP tách bạch, mới.

Mô hình quyền GHI hiệu lực =
    vai trò TRONG dự án (project_members.project_role)
  × bảng tiền-điều-kiện theo từng action (ROLE_GATE + kiểm tra riêng)
  × trần phân loại (data_class ≤ trần dự án ≤ min(clearance, limit)).

Bất biến:
  - Fail-closed: không là thành viên ⇒ deny; không khớp tiền-điều-kiện ⇒ deny.
  - Kỹ sư-scope nhất quán (W11): READ = mọi thành viên thấy mọi task trong dự án mình;
    WRITE hẹp hơn = PM/LEADER, hoặc ENGINEER chỉ trên task ĐƯỢC GIAO cho mình.
  - Separation-of-duty (W11): review→done phải do PM/LEADER duyệt — assignee-engineer
    KHÔNG tự duyệt task của chính mình.
  - ADMIN = break-glass CÓ AUDIT (không phải bypass im lặng): vượt được project_role
    nhưng VẪN bị siết bởi trần phân loại; KHÔNG chạm credential, KHÔNG phá air-gap C3
    (air-gap do PEP đọc + corpus_reachable giữ ở nơi khác). Sửa overclaim 'ADMIN bypass
    như v5.6' (W2): ở đây bypass là tường minh, ghi audit, và có giới hạn.

Trả Decision{allow, reason, effective, steps[]} — cùng hình dạng với PDP đọc để render
được decision-trace.
"""
from config.settings import CLASS_RANK
from kms_app.security.pdp import Decision, authorize

# Tiền-điều-kiện vai trò theo action.
#   "global"  = tập role TOÀN CỤC được phép (action không gắn dự án, vd tạo dự án).
#   "project" = tập project_role được phép.
#   "own"     = True ⇒ ENGINEER cũng được nếu là assignee của task trong ctx.
ROLE_GATE = {
    "create_project":   {"global": {"PM", "ADMIN"}},
    "close_project":    {"project": {"PM"}},
    "add_member":       {"project": {"PM"}},
    "create_task":      {"project": {"PM", "LEADER"}},
    "assign_task":      {"project": {"PM", "LEADER"}},
    "edit_task":        {"project": {"PM", "LEADER"}, "own": True},
    "attach_spec":      {"project": {"PM", "LEADER"}, "own": True},
    "change_status":    {"project": {"PM", "LEADER"}, "own": True},
    "comment":          {"project": {"PM", "LEADER", "ENGINEER"}},
    "compile_progress": {"project": {"PM", "LEADER"}},
    "export_progress":  {"project": {"PM", "LEADER"}},
    "fetch_connector":  {"project": {"PM", "LEADER"}},
    "redact_comment":   {"project": {"PM"}},
}


def project_role(conn, user_id, project_id):
    if not project_id:
        return None
    r = conn.execute("SELECT project_role FROM project_members WHERE project_id=? AND user_id=?",
                     (project_id, user_id)).fetchone()
    return r["project_role"] if r else None


def is_member(conn, user_id, project_id):
    return project_role(conn, user_id, project_id) is not None


def members(conn, project_id):
    return conn.execute("SELECT * FROM project_members WHERE project_id=? ORDER BY project_role, user_id",
                        (project_id,)).fetchall()


def effective_subject(conn, subject):
    """Bản sao subject có projects = (global projects) ∪ (project_members của user) để
    authorize() ĐỌC áp đúng ranh giới membership PM. Các gate phân loại/tag/credential
    của authorize() vẫn nguyên vẹn (chỉ bổ sung membership, không nới lỏng gì khác)."""
    s = dict(subject)
    s["projects"] = set(subject["projects"])
    for r in conn.execute("SELECT project_id FROM project_members WHERE user_id=?",
                          (subject["user_id"],)).fetchall():
        s["projects"].add(r["project_id"])
    return s


def can_read(conn, subject, resource):
    """READ-side: tái dùng authorize() 8 bước của v5.6 trên effective_subject.
    Dùng để lọc danh sách (chống liệt kê) và ẩn task/comment C3 khỏi thành viên ≤C2."""
    return authorize(effective_subject(conn, subject), resource).allow


def authorize_action(conn, subject, action, ctx=None):
    """Write-PEP: chủ thể có được THỰC HIỆN action không? ctx tuỳ action:
       project_id, project_class, task(row), assignee, new_status, requested_data_class."""
    ctx = ctx or {}
    steps = []
    def add(rule, status, detail): steps.append({"rule": rule, "status": status, "detail": detail})
    def deny(reason): return Decision(allow=False, reason=reason, effective=None, steps=steps)

    if subject is None:
        add("DENY_AUTH", "deny", "không có chủ thể")
        return deny("DENY_AUTH")
    gate = ROLE_GATE.get(action)
    if gate is None:
        add("DENY_UNKNOWN_ACTION", "deny", str(action))
        return deny("DENY_UNKNOWN_ACTION")
    add("subject", "pass", f'{subject["user_id"]} · {subject["role"]} · {subject["clearance"]}')
    add("action", "pass", str(action))

    pid = ctx.get("project_id")
    is_admin = subject["role"] == "ADMIN"

    # ---- 1) Cổng vai trò ----
    if "global" in gate:
        if is_admin or subject["role"] in gate["global"]:
            add("role_gate", "pass", f'vai trò toàn cục {subject["role"]} ∈ {sorted(gate["global"])}')
        else:
            add("DENY_ROLE_GLOBAL", "deny", f'cần {sorted(gate["global"])}, có {subject["role"]}')
            return deny("DENY_ROLE_GLOBAL")
    else:
        prole = project_role(conn, subject["user_id"], pid)
        task = ctx.get("task") or {}
        own_ok = bool(gate.get("own")) and task.get("assignee") == subject["user_id"]
        if is_admin:
            add("role_gate", "pass", "ADMIN break-glass (CÓ AUDIT) — vượt project_role, vẫn bị siết phân loại")
        elif prole is None:
            add("DENY_NOT_MEMBER", "deny", f'không là thành viên dự án {pid} (fail-closed)')
            return deny("DENY_NOT_MEMBER")
        elif prole in gate["project"]:
            add("role_gate", "pass", f'project_role {prole} ∈ {sorted(gate["project"])}')
        elif own_ok and prole == "ENGINEER":
            add("role_gate", "pass", "ENGINEER + là assignee của task (kỹ sư-scope)")
        else:
            add("DENY_ROLE_PROJECT", "deny",
                f'project_role {prole} không đủ cho {action}'
                + (" và không phải assignee" if gate.get("own") else ""))
            return deny("DENY_ROLE_PROJECT")

    # ---- 2) Tiền-điều-kiện riêng ----
    if action == "assign_task":
        assignee = ctx.get("assignee")
        if not assignee or not is_member(conn, assignee, pid):
            add("DENY_ASSIGNEE_NOT_MEMBER", "deny", f'assignee "{assignee}" không thuộc dự án (W11)')
            return deny("DENY_ASSIGNEE_NOT_MEMBER")
        add("assignee_member", "pass", f'{assignee} là thành viên dự án')

    if action == "change_status" and ctx.get("new_status") == "done" \
            and (ctx.get("task") or {}).get("status") == "review":
        prole = project_role(conn, subject["user_id"], pid)
        if not is_admin and prole not in ("PM", "LEADER"):
            add("DENY_SOD", "deny", "review→done cần PM/LEADER duyệt (separation-of-duty, W11)")
            return deny("DENY_SOD")
        add("separation_of_duty", "pass", "review→done do PM/LEADER duyệt")

    # ---- 3) Trần phân loại: data_class ≤ trần dự án ≤ min(clearance, limit) ----
    req = ctx.get("requested_data_class")
    if req:
        if req not in CLASS_RANK:
            add("DENY_CLASS_INVALID", "deny", f'data_class không hợp lệ: {req}')
            return deny("DENY_CLASS_INVALID")
        ceil = ctx.get("project_class")
        if ceil and CLASS_RANK[req] > CLASS_RANK[ceil]:
            add("DENY_OVER_PROJECT", "deny", f'{req} > trần dự án {ceil}')
            return deny("DENY_OVER_PROJECT")
        if CLASS_RANK[req] > CLASS_RANK[subject["clearance"]]:
            add("DENY_OVER_CLEARANCE", "deny", f'{req} > clearance {subject["clearance"]}')
            return deny("DENY_OVER_CLEARANCE")
        add("class_ceiling", "pass", f'{req} ≤ trần dự án ≤ clearance {subject["clearance"]}')

    add("ALLOW", "allow", action + (" · break-glass(ADMIN)" if is_admin and "project" in gate else ""))
    return Decision(allow=True, reason="ALLOW", effective=subject["clearance"], steps=steps)
