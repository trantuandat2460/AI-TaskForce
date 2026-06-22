"""Self-test lớp PM (v5.62) — kiểm chứng các fix theo đánh giá phản biện:
  W1  write-PEP: tạo dự án/task/giao việc/đổi trạng thái có cổng vai trò + fail-closed.
  W11 kỹ sư-scope nhất quán + separation-of-duty (review→done) + assignee phải là member.
  W7  optimistic-lock: 2 cập nhật cùng version ⇒ 1 thành công, 1 bị từ chối (không mất dữ liệu).
  W4  connector item mang data_class; confused-deputy (scope min(caller,SA)); secret⇒quarantine.
  isolation đọc: non-member thấy [] ; task C3 ẩn khỏi thành viên ≤C2.
  determinism: biên dịch tiến độ 2 lần cùng input ⇒ cùng NỘI DUNG.
Chạy: python -m tests.test_pm
"""
import os, sys, sqlite3, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kms_app import db
from kms_app.pm import authz, store, progress as pmprog
from kms_app.pm.connectors import base as connbase

PASS = 0; FAIL = 0
def check(name, got, want):
    global PASS, FAIL
    ok = got == want
    PASS += ok; FAIL += (not ok)
    print(f"  {'✓' if ok else '✗'} {name}: {got}" + ("" if ok else f"  (muốn {want})"))
def check_true(name, cond): check(name, bool(cond), True)


def S(uid, role, cl, **kw):
    base = dict(user_id=uid, role=role, department="X", clearance=cl, tags=set(),
                groups={"vsi_public", "vsi_internal"}, projects=set(), manages=set(), hr_purpose=False)
    base.update(kw); return base

conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
conn.executescript(db.SCHEMA)
for uid in ["pm1", "lead_dv", "eng_pd1", "eng_dv1", "out1"]:
    conn.execute("""INSERT INTO users(user_id,role,department,clearance,pw_hash,tags_json,groups_json,projects_json,manages_json,hr_purpose)
        VALUES(?,?,?,?,?,?,?,?,?,?)""", (uid, "ENGINEER", "X", "C2", "x", "[]",
        '["vsi_internal"]', "[]", "[]", 0))
conn.execute("""INSERT INTO projects(project_id,name,owner_pm,data_class,permission_group,status,created_by,created_at,updated_at)
    VALUES('PRJ1','SOVRA','pm1','C2','vsi_internal','active','pm1','t','t')""")
for uid, pr in [("pm1", "PM"), ("lead_dv", "LEADER"), ("eng_pd1", "ENGINEER")]:
    conn.execute("INSERT INTO project_members(project_id,user_id,project_role,added_by,added_at) VALUES('PRJ1',?,?,?,?)",
                 (uid, pr, "pm1", "t"))
conn.commit()

pm = S("pm1", "PM", "C2"); lead = S("lead_dv", "LEADER", "C3")
eng = S("eng_pd1", "ENGINEER", "C3"); out = S("out1", "ENGINEER", "C2")

A = lambda subj, action, **ctx: authz.authorize_action(conn, subj, action, ctx)

print("== W1 · write-PEP: cổng vai trò + fail-closed ==")
check("PM tạo dự án", A(pm, "create_project").reason, "ALLOW")
check("ENGINEER KHÔNG tạo dự án", A(eng, "create_project").reason, "DENY_ROLE_GLOBAL")
check("LEADER tạo task (trong dự án)", A(lead, "create_task", project_id="PRJ1", project_class="C2", requested_data_class="C2").reason, "ALLOW")
check("non-member KHÔNG tạo task", A(out, "create_task", project_id="PRJ1").reason, "DENY_NOT_MEMBER")
check("ENGINEER member KHÔNG tạo task", A(eng, "create_task", project_id="PRJ1").reason, "DENY_ROLE_PROJECT")
check("task C3 > trần dự án C2 ⇒ chặn", A(lead, "create_task", project_id="PRJ1", project_class="C2", requested_data_class="C3").reason, "DENY_OVER_PROJECT")

print("== W11 · assignee phải là member · kỹ sư-scope · separation-of-duty ==")
check("giao cho non-member ⇒ chặn", A(lead, "assign_task", project_id="PRJ1", assignee="out1").reason, "DENY_ASSIGNEE_NOT_MEMBER")
check("giao cho member ⇒ ok", A(lead, "assign_task", project_id="PRJ1", assignee="eng_pd1").reason, "ALLOW")
own = {"assignee": "eng_pd1", "status": "doing"}
other = {"assignee": "lead_dv", "status": "doing"}
check("ENGINEER đổi trạng thái task CỦA MÌNH", A(eng, "change_status", project_id="PRJ1", task=own, new_status="review").reason, "ALLOW")
check("ENGINEER KHÔNG đổi task người khác", A(eng, "change_status", project_id="PRJ1", task=other, new_status="doing").reason, "DENY_ROLE_PROJECT")
own_review = {"assignee": "eng_pd1", "status": "review"}
check("ENGINEER KHÔNG tự duyệt review→done (SoD)", A(eng, "change_status", project_id="PRJ1", task=own_review, new_status="done").reason, "DENY_SOD")
check("LEADER duyệt review→done", A(lead, "change_status", project_id="PRJ1", task=own_review, new_status="done").reason, "ALLOW")
check("non-member KHÔNG comment", A(out, "comment", project_id="PRJ1", task=own).reason, "DENY_NOT_MEMBER")
check("ENGINEER member comment được", A(eng, "comment", project_id="PRJ1", task=own).reason, "ALLOW")

print("== W7 · optimistic-lock chống lost-update ==")
ok, _, tid, _ = store.create_task(conn, lead, "PRJ1", {"title": ["T"], "assignee": ["eng_pd1"], "data_class": ["C2"], "priority": ["P2"], "due_date": [""], "description": [""]})
t = store.get_task(conn, tid)
ok1, msg1, _ = store.change_status(conn, lead, tid, "doing", t["version"])
ok2, msg2, _ = store.change_status(conn, lead, tid, "review", t["version"])   # cùng version cũ
check("cập nhật 1 (version đúng) thành công", ok1, True)
check("cập nhật 2 (version cũ) bị từ chối", ok2, False)
check_true("thông điệp là XUNG ĐỘT phiên bản", "XUNG ĐỘT" in (msg2 or ""))

print("== W4 · connector: data_class trên item · confused-deputy · secret⇒quarantine ==")
rep = connbase.sync_project(conn, pm, "PRJ1")
check("sync ok", rep["ok"], True)
check("item Jira C3 bị DROP do scope min(caller,SA=C2)", conn.execute("SELECT COUNT(*) FROM connector_items WHERE ref='SOVRA-C3'").fetchone()[0], 0)
check("commit chứa secret ⇒ quarantine", conn.execute("SELECT status FROM connector_items WHERE ref='e4f5a6b'").fetchone()["status"], "quarantined")
check("mọi item connector đều có data_class", conn.execute("SELECT COUNT(*) FROM connector_items WHERE data_class IS NULL").fetchone()[0], 0)
check("scope hiệu lực = C2", rep["scope"], "C2")

print("== isolation đọc: non-member [] · C3 ẩn khỏi ≤C2 ==")
check("non-member thấy 0 task", len(store.list_tasks(conn, out, "PRJ1")), 0)
res_c3 = db._pm_resource("x", "C3", "PRJ1", "vsi_internal", "TASK")
res_c2 = db._pm_resource("y", "C2", "PRJ1", "vsi_internal", "TASK")
check("PM (C2) KHÔNG đọc được task C3", authz.can_read(conn, pm, res_c3), False)
check("ENGINEER (C3) đọc được task C2 trong dự án", authz.can_read(conn, eng, res_c2), True)
check("out1 (non-member) KHÔNG đọc task dù C2", authz.can_read(conn, out, res_c2), False)

print("== determinism: biên dịch tiến độ 2 lần ⇒ cùng nội dung ==")
c1 = pmprog.compile_progress(conn, pm, "PRJ1")
c2 = pmprog.compile_progress(conn, pm, "PRJ1")
check("compile ok", c1["ok"] and c2["ok"], True)
check("schema PASS", c1["schema_ok"], True)
check("2 lần cùng input ⇒ cùng NỘI DUNG", json.dumps(c1["result"], sort_keys=True, ensure_ascii=False),
      json.dumps(c2["result"], sort_keys=True, ensure_ascii=False))

print(f"\n{'='*44}\nKẾT QUẢ PM: {PASS} PASS / {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
