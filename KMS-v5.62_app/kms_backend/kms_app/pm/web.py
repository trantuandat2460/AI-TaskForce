"""Trang web lớp PM (v5.62). Tái dùng shell/CSS/nav + helper render của v5.6.
Mọi mutation gọi pm.store / pm.connectors / pm.progress (đi qua write-PEP + audit).
Khi một hành động bị từ chối, hiển thị decision-trace của write-PEP (minh hoạ fail-closed)."""
import json
from config import settings
from kms_app import db
from kms_app.web.render import esc, CL, trace_html
from kms_app.pm import store, authz, notify
from kms_app.pm.connectors import base as connbase
from kms_app.pm import progress as pmprog

STATUS_LABEL = {"todo": "Cần làm", "doing": "Đang làm", "review": "Chờ duyệt", "done": "Xong", "blocked": "Bị chặn"}


def _flash_html(flash):
    if not flash:
        return ""
    kind, msg = flash[0], flash[1]
    trace = trace_html(flash[2]) if len(flash) > 2 and flash[2] else ""
    color = "allow" if kind == "ok" else "deny"
    return (f'<div class="note" style="margin-bottom:12px;border-left-color:var(--{color})">'
            f'<b>{"✓" if kind=="ok" else "✗"}</b> {esc(msg)}</div>{trace}')


def _proj_pill(p):
    return f'<span class="badge">{esc(p["project_id"])}</span> {CL(p["data_class"])}'


# ---------------- /pm/projects ----------------
def page_projects(conn, me, form=None, flash=None):
    if form is not None:
        act = form.get("action", [""])[0]
        if act == "create_project":
            ok, msg, pid, d = store.create_project(conn, me, form.get("name", [""])[0],
                                                   form.get("data_class", ["C2"])[0],
                                                   form.get("permission_group", ["vsi_internal"])[0])
            flash = ("ok" if ok else "err", msg, None if ok else d["steps"])
        elif act == "add_member":
            ok, msg, d = store.add_member(conn, me, form.get("project_id", [""])[0],
                                          form.get("user_id", [""])[0], form.get("project_role", ["ENGINEER"])[0])
            flash = ("ok" if ok else "err", msg, None if ok else d["steps"])
    projs = store.list_projects(conn, me)
    rows = "".join(
        f'<tr><td class="t-id">{esc(p["project_id"])}</td><td>{esc(p["name"])}</td>'
        f'<td class="small muted">{esc(p["owner_pm"])}</td><td>{CL(p["data_class"])}</td>'
        f'<td><span class=badge>{esc(p["permission_group"])}</span></td>'
        f'<td>{"<span class=verdict allow>active</span>" if p["status"]=="active" else "<span class=verdict deny>closed</span>"}</td>'
        f'<td><a class="btn ghost sm" href="/pm/project?id={p["project_id"]}">Mở</a> '
        f'<a class="btn ghost sm" href="/pm/board?project={p["project_id"]}">Bảng</a></td></tr>'
        for p in projs) or '<tr><td colspan=7 class="muted small" style="padding:14px">Chưa có dự án nào bạn là thành viên.</td></tr>'

    can_create = me["role"] in ("PM", "ADMIN")
    create_card = ""
    if can_create:
        gopts = "".join(f'<option>{g}</option>' for g in settings.PERMISSION_GROUPS)
        copts = "".join(f'<option>{c}</option>' for c in settings.CLASS_RANK
                        if settings.CLASS_RANK[c] <= settings.CLASS_RANK[me["clearance"]])
        create_card = f"""<div class="card"><div class="hd"><h3>Tạo dự án (PM)</h3></div><div class="bd">
<form method="post" action="/pm/projects"><input type="hidden" name="action" value="create_project">
<div class="field"><label>Tên dự án</label><input name="name" placeholder="vd: SOVRA KMS"></div>
<div class="grid g2"><div class="field"><label>Trần phân loại (≤ clearance)</label><select name="data_class">{copts}</select></div>
<div class="field"><label>Nhóm quyền</label><select name="permission_group">{gopts}</select></div></div>
<button class="btn primary full">+ Tạo dự án</button></form>
<div class="note" style="margin-top:10px">PM tạo dự án ⇒ tự thành thành viên PM (bootstrap). Mọi thao tác qua write-PEP + audit.</div></div></div>"""
        # add-member form (chọn dự án PM sở hữu)
        owned = [p for p in projs if authz.project_role(conn, me["user_id"], p["project_id"]) == "PM" or me["role"] == "ADMIN"]
        popts = "".join(f'<option value="{p["project_id"]}">{esc(p["project_id"])}</option>' for p in owned)
        uopts = "".join(f'<option>{r["user_id"]}</option>' for r in conn.execute("SELECT user_id FROM users ORDER BY user_id").fetchall())
        ropts = "".join(f'<option>{r}</option>' for r in settings.PROJECT_ROLES)
        if owned:
            create_card += f"""<div class="card"><div class="hd"><h3>Thêm thành viên</h3></div><div class="bd">
<form method="post" action="/pm/projects"><input type="hidden" name="action" value="add_member">
<div class="field"><label>Dự án</label><select name="project_id">{popts}</select></div>
<div class="grid g2"><div class="field"><label>User</label><select name="user_id">{uopts}</select></div>
<div class="field"><label>Vai trò trong dự án</label><select name="project_role">{ropts}</select></div></div>
<button class="btn ghost full">+ Thêm thành viên</button></form></div></div>"""

    body = f"""<div class="page-head"><div class="eyebrow">Lớp PM · v5.62 · write-PEP</div>
<h2>Dự án của tôi</h2><p>Danh sách chỉ gồm dự án bạn là thành viên (chống liệt kê). PM tạo dự án & gán thành viên; mọi quyền GHI đi qua <b>write-PEP</b> (thành phần mới, tách khỏi authorize() đọc của v5.6).</p></div>
{_flash_html(flash)}
<div class="grid gchat"><div class="card"><div class="hd"><h3>Dự án <span class="badge">{len(projs)}</span></h3></div>
<div class="bd" style="padding:0"><table><thead><tr><th>ID</th><th>Tên</th><th>PM</th><th>Trần</th><th>nhóm quyền</th><th>status</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>
<div>{create_card or '<div class="card"><div class="bd muted small">Chỉ PM tạo được dự án.</div></div>'}</div></div>"""
    return body


# ---------------- /pm/project?id= ----------------
def page_project(conn, me, pid):
    p = store.get_project(conn, pid)
    if not p or not (me["role"] == "ADMIN" or authz.is_member(conn, me["user_id"], pid)):
        return '<div class="note">403 — không phải dự án của bạn (fail-closed).</div>'
    tasks = store.list_tasks(conn, me, pid)
    by = {s: 0 for s in settings.TASK_STATUSES}
    for t in tasks:
        by[t["status"]] += 1
    stat = "".join(f'<div class="stat"><div class="n">{by[s]}</div><div class="l">{STATUS_LABEL[s]}</div></div>' for s in settings.TASK_STATUSES)
    mem = authz.members(conn, pid)
    mrows = "".join(f'<div class="kv"><span class="k">{esc(m["user_id"])}</span><span class="v">{esc(m["project_role"])}</span></div>' for m in mem)
    snap = conn.execute("SELECT * FROM progress_snapshots WHERE project_id=? ORDER BY created_at DESC LIMIT 1", (pid,)).fetchone()
    snap_html = '<div class="muted small">Chưa có snapshot — vào Tiến độ để biên dịch.</div>'
    if snap:
        s = json.loads(snap["summary_json"])
        snap_html = (f'<div class="kv"><span class="k">snapshot</span><span class="v">{esc(snap["snapshot_id"])} · {CL(snap["max_data_class"])}</span></div>'
                     f'<div class="kv"><span class="k">% done</span><span class="v">{s["TaskStats"]["percent_done"]}%</span></div>'
                     f'<div class="small muted" style="margin-top:8px">{esc(s["Summary"])}</div>')
    body = f"""<div class="page-head"><div class="eyebrow">Dashboard dự án · {_proj_pill(p)}</div>
<h2>{esc(p["name"])}</h2><p>Trần phân loại {CL(p["data_class"])} · nhóm quyền {esc(p["permission_group"])} · PM {esc(p["owner_pm"])}.</p></div>
<div class="card"><div class="bd"><div class="statgrid">{stat}</div></div></div>
<div class="grid g2">
<div class="card"><div class="hd"><h3>Thành viên <span class="badge">{len(mem)}</span></h3><span class="spacer"></span>
<a class="btn ghost sm" href="/pm/board?project={pid}">Bảng công việc</a></div><div class="bd">{mrows}</div></div>
<div class="card"><div class="hd"><h3>Tiến độ mới nhất</h3><span class="spacer"></span>
<a class="btn ghost sm" href="/pm/progress?project={pid}">Biên dịch</a> <a class="btn ghost sm" href="/pm/connectors?project={pid}">Connector</a></div>
<div class="bd">{snap_html}</div></div></div>"""
    return body


# ---------------- /pm/board?project= ----------------
def page_board(conn, me, pid, form=None, flash=None):
    if not pid:
        projs = store.list_projects(conn, me)
        links = "".join(f'<a class="btn ghost sm" href="/pm/board?project={p["project_id"]}">{esc(p["project_id"])}</a> ' for p in projs)
        return f'<div class="page-head"><h2>Bảng công việc</h2><p>Chọn dự án:</p></div><div class="card"><div class="bd">{links or "Chưa có dự án."}</div></div>'
    p = store.get_project(conn, pid)
    if not p or not (me["role"] == "ADMIN" or authz.is_member(conn, me["user_id"], pid)):
        return '<div class="note">403 — không phải dự án của bạn.</div>'
    if form is not None and form.get("action", [""])[0] == "create_task":
        ok, msg, tid, d = store.create_task(conn, me, pid, form)
        flash = ("ok" if ok else "err", msg, None if ok else d["steps"])
    tasks = store.list_tasks(conn, me, pid)
    cols = ""
    for s in settings.TASK_STATUSES:
        cards = ""
        for t in [t for t in tasks if t["status"] == s]:
            cards += (f'<a href="/pm/task?id={t["task_id"]}" class="cite" style="display:block;border:1px solid var(--line);border-radius:8px;padding:8px;margin-bottom:8px">'
                      f'<div>{CL(t["data_class"])} <span class="badge">{esc(t["priority"])}</span></div>'
                      f'<div style="margin:4px 0;font-weight:600">{esc(t["title"])}</div>'
                      f'<div class="src">{esc(t["task_id"])} · {esc(t["assignee"] or "chưa giao")}</div></a>')
        cols += (f'<div style="flex:1;min-width:150px"><div class="eyebrow" style="margin-bottom:8px">{STATUS_LABEL[s]} ({by_count(tasks,s)})</div>{cards or "<div class=\'muted small\'>—</div>"}</div>')
    # form tạo task (PM/LEADER)
    create = ""
    prole = authz.project_role(conn, me["user_id"], pid)
    if me["role"] == "ADMIN" or prole in ("PM", "LEADER"):
        mem = authz.members(conn, pid)
        aopts = '<option value="">(chưa giao)</option>' + "".join(f'<option>{m["user_id"]}</option>' for m in mem)
        copts = "".join(f'<option>{c}</option>' for c in settings.CLASS_RANK if settings.CLASS_RANK[c] <= settings.CLASS_RANK[p["data_class"]] and settings.CLASS_RANK[c] <= settings.CLASS_RANK[me["clearance"]])
        popts = "".join(f'<option{" selected" if c=="P2" else ""}>{c}</option>' for c in settings.TASK_PRIORITIES)
        create = f"""<div class="card"><div class="hd"><h3>Tạo task (PM/LEADER)</h3></div><div class="bd">
<form method="post" action="/pm/board?project={pid}"><input type="hidden" name="action" value="create_task">
<div class="field"><label>Tiêu đề</label><input name="title"></div>
<div class="field"><label>Mô tả</label><textarea name="description" rows="2"></textarea></div>
<div class="grid g2"><div class="field"><label>Giao cho</label><select name="assignee">{aopts}</select></div>
<div class="field"><label>Ưu tiên</label><select name="priority">{popts}</select></div></div>
<div class="grid g2"><div class="field"><label>Phân loại (≤ trần dự án {p["data_class"]})</label><select name="data_class">{copts}</select></div>
<div class="field"><label>Hạn (YYYY-MM-DD)</label><input name="due_date" placeholder="2026-06-30"></div></div>
<button class="btn primary full">+ Tạo task</button></form></div></div>"""
    body = f"""<div class="page-head"><div class="eyebrow">Kanban · {_proj_pill(p)}</div>
<h2>Bảng công việc — {esc(p["name"])}</h2><p>Mọi thành viên thấy mọi task của dự án (read project-scoped, nhất quán — W11). Sửa task qua write-PEP: PM/LEADER toàn quyền; ENGINEER chỉ task được giao.</p></div>
{_flash_html(flash)}
<div class="grid gchat"><div class="card"><div class="bd"><div style="display:flex;gap:12px;overflow:auto">{cols}</div></div></div>
<div>{create or '<div class="card"><div class="bd muted small">Chỉ PM/LEADER tạo task.</div></div>'}</div></div>"""
    return body


def by_count(tasks, s):
    return sum(1 for t in tasks if t["status"] == s)


# ---------------- /pm/task?id= ----------------
def page_task(conn, me, tid, form=None, flash=None):
    t = store.get_task(conn, tid)
    if not t:
        return '<div class="note">404 — không có task.</div>'
    pid = t["project_id"]
    if not (me["role"] == "ADMIN" or (authz.is_member(conn, me["user_id"], pid)
            and authz.can_read(conn, me, db.task_to_resource(t)))):
        return '<div class="note">403 — task ngoài quyền của bạn (fail-closed).</div>'
    if form is not None:
        act = form.get("action", [""])[0]
        ver = form.get("version", [""])[0]
        if act == "status":
            ok, msg, d = store.change_status(conn, me, tid, form.get("new_status", [""])[0], ver)
            flash = ("ok" if ok else "err", msg, None if ok or d is None else d["steps"])
        elif act == "assign":
            ok, msg, d = store.assign_task(conn, me, tid, form.get("assignee", [""])[0], ver)
            flash = ("ok" if ok else "err", msg, None if ok or d is None else d["steps"])
        elif act == "comment":
            ok, msg, d = store.add_comment(conn, me, tid, form.get("body", [""])[0])
            flash = ("ok" if ok else "err", msg, None if ok or d is None else d["steps"])
        t = store.get_task(conn, tid)   # reload (version đổi)

    comments = store.list_comments(conn, me, tid)
    crows = "".join(
        f'<div class="msg bot"><div class="meta">{esc(c["author"])} · {esc(c["created_at"])}'
        + (' · <span class="badge">PII→DPIA</span>' if (c["mentions_json"] and c["mentions_json"] != "[]") else "")
        + f'</div>{esc(c["body"])}</div>' for c in comments) or '<div class="muted small">Chưa có trao đổi.</div>'

    mem = authz.members(conn, pid)
    aopts = '<option value="">(chưa giao)</option>' + "".join(
        f'<option{" selected" if m["user_id"]==t["assignee"] else ""}>{m["user_id"]}</option>' for m in mem)
    sopts = "".join(f'<option{" selected" if s==t["status"] else ""}>{s}</option>' for s in settings.TASK_STATUSES)
    spec_ids = json.loads(t["spec_doc_ids_json"] or "[]")
    body = f"""<div class="page-head"><div class="eyebrow">Chi tiết task · {_proj_pill(store.get_project(conn,pid))}</div>
<h2>{esc(t["title"])} <span class="badge">{esc(t["task_id"])}</span></h2>
<p>{CL(t["data_class"])} · {esc(t["status"])} · ưu tiên {esc(t["priority"])} · assignee {esc(t["assignee"] or "—")} · v{t["version"]}{(" · duyệt bởi "+t["approved_by"]) if t["approved_by"] else ""}</p></div>
{_flash_html(flash)}
<div class="grid gchat">
<div><div class="card"><div class="hd"><h3>Trao đổi theo task</h3></div><div class="bd">
<div class="scroll">{crows}</div>
<form class="chatbox" method="post" action="/pm/task?id={tid}"><input type="hidden" name="action" value="comment">
<input type="hidden" name="version" value="{t["version"]}">
<input name="body" placeholder="Nhập trao đổi… (@user để nhắc, context-fenced)" autocomplete="off">
<button class="btn primary">Gửi</button></form>
<div class="note" style="margin-top:8px">Comment là DỮ LIỆU (context-fenced) — không phải chỉ thị cho LLM. Kế thừa mức {CL(t["data_class"])} của task.</div>
</div></div></div>
<div>
<div class="card"><div class="hd"><h3>Đổi trạng thái</h3></div><div class="bd">
<form method="post" action="/pm/task?id={tid}"><input type="hidden" name="action" value="status">
<input type="hidden" name="version" value="{t["version"]}">
<div class="field"><label>Trạng thái mới</label><select name="new_status">{sopts}</select></div>
<button class="btn primary full">Cập nhật (optimistic-lock v{t["version"]})</button></form>
<div class="note" style="margin-top:8px">review→done cần PM/LEADER duyệt (separation-of-duty). 2 người sửa cùng lúc ⇒ 1 bị từ chối xung đột (W7).</div></div></div>
<div class="card"><div class="hd"><h3>Giao việc (PM/LEADER)</h3></div><div class="bd">
<form method="post" action="/pm/task?id={tid}"><input type="hidden" name="action" value="assign">
<input type="hidden" name="version" value="{t["version"]}">
<div class="field"><label>Assignee (phải là thành viên)</label><select name="assignee">{aopts}</select></div>
<button class="btn ghost full">Giao</button></form></div></div>
<div class="card"><div class="hd"><h3>Spec liên kết</h3></div><div class="bd">{("".join(f'<span class=tag>{esc(x)}</span>' for x in spec_ids) or '<span class="muted small">—</span>')}
<div class="kv"><span class="k">Jira</span><span class="v">{esc(t["jira_ref"] or "—")}</span></div>
<div class="kv"><span class="k">GitLab</span><span class="v">{esc(t["gitlab_ref"] or "—")}</span></div></div></div>
</div></div>"""
    return body


# ---------------- /pm/progress?project= ----------------
def page_progress(conn, me, pid, query=None, flash=None):
    query = query or {}
    if not pid:
        return '<div class="note">Chọn dự án từ <a href="/pm/projects">Dự án</a>.</div>'
    p = store.get_project(conn, pid)
    if not p or not (me["role"] == "ADMIN" or authz.is_member(conn, me["user_id"], pid)):
        return '<div class="note">403 — không phải dự án của bạn.</div>'
    out = '<div class="muted small">Bấm Biên dịch để chạy task-contract tất định (không LLM).</div>'
    action = query.get("run", [None])[0]
    if action:
        cap = "C2" if action == "shared" else None
        compiled = pmprog.compile_progress(conn, me, pid, cap_class=cap)
        if not compiled["ok"]:
            out = f'<div class="note">Không đủ quyền: <span class="mono">{esc(compiled["reason"])}</span> (fail-closed).</div>'
        else:
            compiled["_redacted"] = (cap == "C2")
            sid = pmprog.save_snapshot(conn, me, pid, compiled)
            r = compiled["result"]
            warn = ""
            if compiled.get("elevated_c3"):
                warn = ('<div class="note" style="border-left-color:var(--deny);margin:10px 0">⚠ Tiến độ chạm dữ liệu '
                        '<b>C3</b> ⇒ snapshot nâng lên C3-only (highest-wins). Thành viên ≤C2 sẽ KHÔNG hỏi-đáp được. '
                        f'Cân nhắc xuất bản <a href="/pm/progress?project={pid}&run=shared">bản chia sẻ ≤C2 (lược nguồn C3)</a> để chia sẻ rộng (W8).</div>')
            kv = "".join(f'<div class="kv"><span class="k">{k}</span><span class="v" style="white-space:normal;max-width:60%;text-align:right">{esc(r["TaskStats"][k] if k=="TaskStats" else "")}</span></div>' for k in [])
            stat = " · ".join(f"{k}={v}" for k, v in r["TaskStats"].items())
            lst = lambda xs: "".join(f'<div class="kv"><span class="k">·</span><span class="v" style="white-space:normal;max-width:80%;text-align:right">{esc(x)}</span></div>' for x in xs)
            out = (f'<div class="note" style="margin-bottom:8px">contract v{compiled["contract"]["version"]} · schema '
                   f'<span class="verdict {"allow" if compiled["schema_ok"] else "deny"}">{"PASS" if compiled["schema_ok"] else "FAIL"}</span> · '
                   f'max_data_class <b>{CL(compiled["max_data_class"])}</b> · snapshot {esc(sid)} · ghi task_contract_version vào audit</div>'
                   f'{warn}'
                   f'<div class="kv"><span class="k">Summary</span><span class="v" style="white-space:normal;max-width:64%;text-align:right">{esc(r["Summary"])}</span></div>'
                   f'<div class="kv"><span class="k">TaskStats</span><span class="v">{esc(stat)}</span></div>'
                   f'<div class="kv"><span class="k">VsJiraGitlab</span><span class="v" style="white-space:normal;max-width:64%;text-align:right">{esc(r["VsJiraGitlab"])}</span></div>'
                   f'<div class="small muted" style="margin-top:8px">Rủi ro</div>{lst(r["Risks"])}'
                   f'<div class="small muted" style="margin-top:8px">Tuần tới</div>{lst(r["NextWeek"])}'
                   f'<div class="small muted" style="margin-top:8px">Blockers</div>{lst(r["Blockers"])}'
                   f'<form method="post" action="/pm/progress?project={pid}" style="margin-top:12px"><input type="hidden" name="action" value="export">'
                   f'<input type="hidden" name="cap" value="{cap or ""}">'
                   f'<button class="btn primary full">⇪ Promote ra OKF .md ({compiled["max_data_class"]}, sàn cứng)</button></form>')
    snaps = conn.execute("SELECT * FROM progress_snapshots WHERE project_id=? ORDER BY created_at DESC LIMIT 8", (pid,)).fetchall()
    srows = "".join(f'<tr><td class="t-id">{esc(s["snapshot_id"])}</td><td>{CL(s["max_data_class"])}</td>'
                    f'<td class="small muted">{esc(s["generated_by"])}</td>'
                    f'<td class="small">{esc(s["exported_doc_id"] or "—")}</td></tr>' for s in snaps) \
            or '<tr><td colspan=4 class="muted small" style="padding:12px">Chưa có snapshot.</td></tr>'
    body = f"""<div class="page-head"><div class="eyebrow">Biên dịch tiến độ · {_proj_pill(p)}</div>
<h2>Tiến độ — {esc(p["name"])}</h2><p>task-contract <b>tất định thật</b> (aggregate=đếm, risks=rule-derived, KHÔNG LLM). Nguồn đọc qua PEP của người chạy. Promote ⇒ OKF concept .md (trích dẫn được, versioned).</p></div>
{_flash_html(flash)}
<div class="grid gchat"><div class="card"><div class="hd"><h3>Kết quả</h3><span class="spacer"></span>
<a class="btn primary sm" href="/pm/progress?project={pid}&run=1">▶ Biên dịch</a></div><div class="bd">{out}</div></div>
<div class="card"><div class="hd"><h3>Snapshot gần đây</h3></div><div class="bd" style="padding:0">
<table><thead><tr><th>id</th><th>mức</th><th>bởi</th><th>OKF</th></tr></thead><tbody>{srows}</tbody></table></div></div></div>"""
    return body


# ---------------- /pm/connectors?project= ----------------
def page_connectors(conn, me, pid, form=None, flash=None):
    if not pid:
        return '<div class="note">Chọn dự án từ <a href="/pm/projects">Dự án</a>.</div>'
    p = store.get_project(conn, pid)
    if not p or not (me["role"] == "ADMIN" or authz.is_member(conn, me["user_id"], pid)):
        return '<div class="note">403 — không phải dự án của bạn.</div>'
    if form is not None and form.get("action", [""])[0] == "sync":
        rep = connbase.sync_project(conn, me, pid)
        if not rep["ok"]:
            flash = ("err", f'từ chối sync: {rep["reason"]}')
        else:
            flash = ("ok", f'Sync xong: fetched={rep["fetched"]} · active={rep["active"]} · '
                          f'quarantined={rep["quarantined"]} · dropped(scope min(caller,SA)={rep["scope"]})={rep["dropped_scope"]}')
    items = connbase.list_items(conn, me, pid)
    rows = "".join(
        f'<tr><td class="t-id">{esc(it["source"])}:{esc(it["ref"])}</td><td>{esc(it["title"])}</td>'
        f'<td class="small muted">{esc(it["author"])}</td><td>{esc(it["state"])}</td><td>{CL(it["data_class"])}</td>'
        f'<td>{"<span class=verdict deny>quarantine</span>" if it["status"]!="active" else "<span class=verdict allow>active</span>"}</td></tr>'
        for it in items) or '<tr><td colspan=6 class="muted small" style="padding:12px">Chưa sync. Bấm Sync để kéo mock Jira/GitLab.</td></tr>'
    body = f"""<div class="page-head"><div class="eyebrow">Connector Jira/GitLab (stub) · {_proj_pill(p)}</div>
<h2>Connector — {esc(p["name"])}</h2><p>Read-only · scope <b>min(caller, service-account {settings.CONNECTOR_SA_CLEARANCE})</b> chống confused-deputy · mỗi item mang data_class (W4) · secret/PII ⇒ quarantine (S5) · chỉ ≤{settings.EGRESS_MAX_CLASS} được egress.</p></div>
{_flash_html(flash)}
<div class="card"><div class="hd"><h3>Item connector <span class="badge">{len(items)}</span></h3><span class="spacer"></span>
<form method="post" action="/pm/connectors?project={pid}"><input type="hidden" name="action" value="sync"><button class="btn primary sm">⟳ Sync</button></form></div>
<div class="bd" style="padding:0"><table><thead><tr><th>ref</th><th>tiêu đề</th><th>tác giả</th><th>state</th><th>mức</th><th>status</th></tr></thead><tbody>{rows}</tbody></table></div></div>"""
    return body


# ---------------- /pm/inbox ----------------
def page_inbox(conn, me, query=None):
    query = query or {}
    if query.get("seen"):
        notify.mark_all_seen(conn, me["user_id"])
    notifs = notify.inbox(conn, me["user_id"])
    nrows = "".join(
        f'<tr{" style=background:var(--panel-2)" if not n["seen"] else ""}><td class="small">{esc(n["created_at"][5:])}</td>'
        f'<td><span class=badge>{esc(n["kind"])}</span></td><td>{esc(n["body"])}</td>'
        f'<td>{("<a class=\"btn ghost sm\" href=\"/pm/task?id=%s\">mở</a>" % n["task_id"]) if n["task_id"] else ""}</td></tr>'
        for n in notifs) or '<tr><td colspan=4 class="muted small" style="padding:12px">Không có thông báo.</td></tr>'
    mine = store.my_tasks(conn, me["user_id"])
    mrows = "".join(f'<tr><td class="t-id"><a href="/pm/task?id={t["task_id"]}">{esc(t["task_id"])}</a></td>'
                    f'<td>{esc(t["title"])}</td><td>{esc(t["status"])}</td><td>{esc(t["due_date"] or "—")}</td></tr>' for t in mine) \
            or '<tr><td colspan=4 class="muted small" style="padding:12px">Không có task được giao.</td></tr>'
    body = f"""<div class="page-head"><div class="eyebrow">Hộp thư trong-ứng-dụng · W9</div>
<h2>Hộp thư & Công việc của tôi</h2><p>Kênh phát hiện thay đổi KHÔNG email (giao việc / comment / đổi trạng thái). Email vẫn ngoài phạm vi.</p></div>
<div class="grid g2">
<div class="card"><div class="hd"><h3>Thông báo</h3><span class="spacer"></span><a class="btn ghost sm" href="/pm/inbox?seen=1">Đánh dấu đã đọc</a></div>
<div class="bd" style="padding:0"><table><thead><tr><th>khi</th><th>loại</th><th>nội dung</th><th></th></tr></thead><tbody>{nrows}</tbody></table></div></div>
<div class="card"><div class="hd"><h3>Công việc của tôi <span class="badge">{len(mine)}</span></h3></div>
<div class="bd" style="padding:0"><table><thead><tr><th>task</th><th>tiêu đề</th><th>trạng thái</th><th>hạn</th></tr></thead><tbody>{mrows}</tbody></table></div></div></div>"""
    return body


# ---------------- DISPATCH ----------------
def dispatch(method, path, query, form, conn, me):
    f = form if method == "POST" else None
    if path == "/pm/projects":
        return ("html", page_projects(conn, me, form=f))
    if path == "/pm/project":
        return ("html", page_project(conn, me, query.get("id", [None])[0]))
    if path == "/pm/board":
        return ("html", page_board(conn, me, query.get("project", [None])[0], form=f))
    if path == "/pm/task":
        return ("html", page_task(conn, me, query.get("id", [None])[0], form=f))
    if path == "/pm/progress":
        if method == "POST" and form.get("action", [""])[0] == "export":
            pid = query.get("project", [None])[0]
            cap = form.get("cap", [""])[0] or None
            compiled = pmprog.compile_progress(conn, me, pid, cap_class=cap)
            if compiled["ok"]:
                compiled["_redacted"] = (cap == "C2")
                ok, msg, doc_id = pmprog.export_okf(conn, me, pid, compiled)
            else:
                ok, msg = False, compiled["reason"]
            return ("html", page_progress(conn, me, pid, query=query, flash=("ok" if ok else "err", msg)))
        return ("html", page_progress(conn, me, query.get("project", [None])[0], query=query))
    if path == "/pm/connectors":
        return ("html", page_connectors(conn, me, query.get("project", [None])[0], form=f))
    if path == "/pm/inbox":
        return ("html", page_inbox(conn, me, query=query))
    return ("html", '<div class="note">404 — không có trang PM này.</div>')
