"""Seed dữ liệu demo: users (PBKDF2) + ghi các file .md mẫu vào data/documents/
(có front-matter để bạn mở ra là thấy phân loại) + ingest + 1 hội thoại mẫu."""
import json, datetime
from config import settings
from kms_app import db
from kms_app.security import passwords
from kms_app.ingestion import store as istore

USERS = [
  ("admin1","ADMIN","IT","C3",["core-ip","proj-sovra","proj-sauria","lead","pmo","disc-pd","disc-dv","hr"],
   ["vsi_public","vsi_internal","vsi_confidential"],["SOVRA","SAURIA"],["eng_pd1","eng_dv1","lead_dv"],1),
  ("eng_pd1","ENGINEER","PHYSICAL","C3",["core-ip","proj-sovra","disc-pd"],
   ["vsi_public","vsi_internal","vsi_confidential"],["SOVRA"],[],0),
  ("lead_dv","LEADER","DV","C3",["lead","proj-sovra","disc-dv"],
   ["vsi_public","vsi_internal","vsi_confidential"],["SOVRA"],["eng_dv1"],0),
  ("pm1","PM","PMO","C2",["pmo","proj-sovra"],["vsi_public","vsi_internal"],["SOVRA"],[],0),
  ("hr1","HR","HR","C2",["hr"],["vsi_public","vsi_internal"],[],[],1),
]

# (relative folder, filename, OKF front-matter dict, body)
# v5.6: thuộc tính bảo mật dùng tiền tố vsi_ (OKF); vsi_corpus_id định tuyến corpus;
# `related` khai cạnh concept graph. Hai doc cuối minh hoạ scanner → quarantine.
DOCS = [
 ("public","onboarding.md",
  dict(doc_id="R-011",vsi_data_class="C1",vsi_corpus_id="corpus_c1",vsi_kind="PUBLIC",vsi_sensitive_level="internal"),
  "# Sổ tay onboarding\n## Quy trình\nHướng dẫn onboarding chung cho nhân viên mới: quy trình, công cụ, văn hoá.\n## Công cụ\nGit, Jira, Confluence, EDA nội bộ."),
 ("internal","sovra_kms_overview.md",
  dict(doc_id="R-001",vsi_data_class="C2",vsi_corpus_id="corpus_c2",vsi_kind="SPEC_OVERVIEW",vsi_owner_project="SOVRA",vsi_sensitive_level="confidential",related="R-002,R-003"),
  "# SOVRA KMS — Thiết kế tổng quan\n## Mục tiêu\nKMS là kho tri thức nội bộ an toàn kết hợp lớp agentic-RAG. Xem [[R-002]].\n## Phạm vi\nPhục vụ truy hồi tài liệu kỹ thuật với kiểm soát truy cập theo tổ chức."),
 ("confidential","sovra_dcm_detail.md",
  dict(doc_id="R-002",vsi_data_class="C3",vsi_corpus_id="corpus_c3",vsi_data_subclass="C3_CORE_IP",vsi_kind="SPEC_DETAIL",vsi_owner_project="SOVRA",vsi_required_tags="core-ip",vsi_sensitive_level="restricted",related="R-004"),
  "# Mô hình phân quyền DCM (chi tiết)\n## Công thức\nMô hình DCM dùng effective = min(clearance, limit); fail-closed.\n## PDP\nPDP authorize() 8 bước: DCM gate → ABAC → cô lập dự án → scope phòng → ReBAC nhân sự → trần vai trò."),
 ("internal","gemmini_overview.md",
  dict(doc_id="R-003",vsi_data_class="C2",vsi_corpus_id="corpus_c2",vsi_kind="SPEC_OVERVIEW",vsi_owner_project="SOVRA",vsi_sensitive_level="confidential",related="R-004"),
  "# Gemmini — Kiến trúc systolic array\n## Thành phần\nGemmini là DNN accelerator: systolic array, scratchpad/accumulator, DMA, giao tiếp RoCC, decoupled access/execute. Chi tiết ISA: [[R-004]]."),
 ("confidential","gemmini_isa_detail.md",
  dict(doc_id="R-004",vsi_data_class="C3",vsi_corpus_id="corpus_c3",vsi_data_subclass="C3_CORE_IP",vsi_kind="SPEC_DETAIL",vsi_owner_project="SOVRA",vsi_required_tags="core-ip",vsi_sensitive_level="restricted"),
  "# Gemmini — RoCC ISA (chi tiết)\n## Tập lệnh\nTập lệnh RoCC của Gemmini: mvin/mvout, matmul, config; mã hoá custom opcode; ràng buộc fence và pipeline."),
 ("confidential","sauria_rtl.md",
  dict(doc_id="R-005",vsi_data_class="C3",vsi_corpus_id="corpus_c3",vsi_data_subclass="C3_CORE_IP",vsi_kind="IP",vsi_owner_project="SAURIA",vsi_owner_dept="PHYSICAL",vsi_required_tags="core-ip",vsi_sensitive_level="restricted",related="R-014"),
  "# SAURIA — RTL datapath\n## Datapath\nDatapath systolic của SAURIA (BSC): PE array, FIFO biên, điều khiển load/compute; tham số hoá kích thước mảng."),
 ("internal","ws4_weekly_w23.md",
  dict(doc_id="R-006",vsi_data_class="C2",vsi_corpus_id="corpus_c2",vsi_kind="PROGRESS_REPORT",vsi_owner_project="SOVRA",vsi_sensitive_level="confidential",related="R-012,R-999"),
  "# Báo cáo tuần WS4 — Week 23\n## Đạt được\nHoàn thiện đăng nhập + điều khiển truy cập theo vai trò cho cổng nội bộ; 59/59 self-test PASS.\n## Rủi ro\nFirewall chặn hạ tầng bên ngoài.\n## Tuần tới\nKhảo sát n8n và tự động hoá luồng."),
 ("confidential","pdk_timing.md",
  dict(doc_id="R-007",vsi_data_class="C3",vsi_corpus_id="corpus_c3",vsi_kind="FOUNDRY",vsi_owner_dept="PHYSICAL",vsi_sensitive_level="restricted"),
  "# PDK — Ràng buộc timing (Foundry)\n## Bảng\nBảng ràng buộc timing PDK foundry: setup/hold, corner, derate; chỉ phòng Physical được truy cập."),
 ("internal","personnel_eng_pd1.md",
  dict(doc_id="R-008",vsi_data_class="C2",vsi_corpus_id="corpus_c2",vsi_data_subclass="PII",vsi_kind="PII",vsi_is_personnel_report="true",vsi_subject_person="eng_pd1",vsi_sensitive_level="confidential"),
  "# Hồ sơ nhân sự — eng_pd1\nĐánh giá hiệu suất, lương, lịch sử dự án của eng_pd1."),
 ("internal","personnel_eng_dv1.md",
  dict(doc_id="R-009",vsi_data_class="C2",vsi_corpus_id="corpus_c2",vsi_data_subclass="PII",vsi_kind="PII",vsi_is_personnel_report="true",vsi_subject_person="eng_dv1",vsi_sensitive_level="confidential"),
  "# Hồ sơ nhân sự — eng_dv1\nĐánh giá hiệu suất, lương, lịch sử dự án của eng_dv1."),
 ("confidential","secrets_store.md",
  dict(doc_id="R-010",vsi_data_class="C3",vsi_corpus_id="corpus_c3",vsi_kind="METADATA",vsi_owner_dept="IT",vsi_is_credential="true",vsi_sensitive_level="restricted"),
  "# Khoá API / Secrets store\n(credential — chặn cứng, không bao giờ đưa vào AI)"),
 ("internal","dv_bug_triage.md",
  dict(doc_id="R-012",vsi_data_class="C2",vsi_corpus_id="corpus_c2",vsi_kind="PROGRESS_REPORT",vsi_owner_project="SOVRA",vsi_owner_dept="DV",vsi_required_tags="disc-dv",vsi_sensitive_level="confidential"),
  "# DV — Bảng triage bug\nTriage bug DV: phân loại, mức ưu tiên, owner; cần tag disc-dv."),
 ("internal","turbo_testbench.md",
  dict(doc_id="R-013",vsi_data_class="C2",vsi_corpus_id="corpus_c2",vsi_kind="TESTBENCH",vsi_owner_project="SOVRA",vsi_sensitive_level="confidential"),
  "# Turbo Encoder — Testbench (tóm tắt)\nTestbench UVM cho Turbo Encoder: coverage plan, plusargs blk_size, kịch bản directed/random."),
 ("internal","sauria_integration.md",
  dict(doc_id="R-014",vsi_data_class="C2",vsi_corpus_id="corpus_c2",vsi_kind="METADATA",vsi_owner_project="SAURIA",vsi_sensitive_level="confidential"),
  "# SAURIA — Ghi chú tích hợp (nội bộ)\nGhi chú tích hợp SAURIA vào luồng VSI: ranh giới IP, mirror nội bộ, Docker tự dựng."),
 # --- Quarantine demo (S5): scanner tầng-1 bắt được dù producer QUÊN gắn cờ ---
 ("internal","ci_runbook_leak.md",
  dict(doc_id="R-015",vsi_data_class="C2",vsi_corpus_id="corpus_c2",vsi_kind="METADATA",vsi_owner_project="SOVRA",vsi_sensitive_level="confidential"),
  "# CI runbook\n## Cấu hình\nĐặt biến môi trường rồi chạy pipeline.\napi_key=AKIAIOSFODNN7EXAMPLE9 (lỡ dán vào tài liệu — producer quên gắn cờ)."),
 ("internal","mentoring_note.md",
  dict(doc_id="R-016",vsi_data_class="C2",vsi_corpus_id="corpus_c2",vsi_kind="METADATA",vsi_owner_project="SOVRA",vsi_sensitive_level="confidential"),
  "# Ghi chú mentoring\nĐánh giá hiệu suất của Nguyen Van A trong quý: cần cải thiện tài liệu (producer quên gắn vsi_is_personnel_report)."),
]

def _fm(meta):
    lines = ["---"] + [f"{k}: {v}" for k, v in meta.items()] + ["---", ""]
    return "\n".join(lines)

def write_documents():
    for folder, name, meta, body in DOCS:
        d = settings.DOCUMENTS_DIR / folder
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(_fm(meta) + body + "\n", encoding="utf-8")

SYSTEM_FOLDERS = [
    ("public",       "Công khai (system)",  "vsi_public"),
    ("internal",     "Nội bộ (system)",     "vsi_internal"),
    ("confidential", "Mật / core-IP (system)", "vsi_confidential"),
]

def seed_folders(conn):
    import datetime
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    for fid, name, grp in SYSTEM_FOLDERS:
        conn.execute("""INSERT OR IGNORE INTO folders(folder_id,name,owner_user,permission_group,owner_project,created_at)
            VALUES(?,?,?,?,?,?)""", (fid, name, "system", grp, None, now))
    conn.commit()

def seed_users(conn):
    for uid, role, dept, cl, tags, groups, projects, manages, hr in USERS:
        conn.execute("""INSERT OR REPLACE INTO users
            (user_id,role,department,clearance,pw_hash,tags_json,groups_json,projects_json,manages_json,hr_purpose)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (uid, role, dept, cl, passwords.hash_password(uid),
             json.dumps(tags), json.dumps(groups), json.dumps(projects), json.dumps(manages), hr))
    conn.commit()

def seed_sample_conversation(conn):
    from kms_app.web import routes
    cid = conn.execute("SELECT conv_id FROM conversations LIMIT 1").fetchone()
    if cid: return
    from kms_app.conversation import store as cstore
    conv = cstore.create(conn, "eng_pd1", title="Hỏi về DCM (mẫu)")
    me = db.row_to_subject(conn.execute("SELECT * FROM users WHERE user_id='eng_pd1'").fetchone())
    routes.run_turn(conn, me, conv, "Mô hình phân quyền DCM của KMS hoạt động thế nào?")

def seed_pm(conn):
    """Dữ liệu demo lớp PM (v5.62): 1 dự án + thành viên + task (đủ trạng thái) +
    comment + sync connector + 1 snapshot tiến độ. Đi qua write-PEP thật (audited)."""
    import datetime
    from kms_app.pm import store as pstore, progress as pprog
    from kms_app.pm.connectors import base as connbase
    if conn.execute("SELECT 1 FROM projects LIMIT 1").fetchone():
        return
    def subj(uid):
        return db.row_to_subject(conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone())
    pm, lead, eng = subj("pm1"), subj("lead_dv"), subj("eng_pd1")

    ok, _, pid, _ = pstore.create_project(conn, pm, "SOVRA KMS", "C2", "vsi_internal")
    if not ok:
        return
    pstore.add_member(conn, pm, pid, "lead_dv", "LEADER")
    pstore.add_member(conn, pm, pid, "eng_pd1", "ENGINEER")

    today = datetime.date.today()
    overdue = (today - datetime.timedelta(days=3)).isoformat()
    soon = (today + datetime.timedelta(days=4)).isoformat()
    specs = [
        ("Thiết kế & hiện thực write-PEP", "eng_pd1", "P1", overdue, "doing"),
        ("Viết self-test phân quyền PM",   "eng_pd1", "P2", soon,    "review"),
        ("Tối ưu PEP-2 per-resource",      "",        "P2", soon,    "todo"),
        ("Chặn lost-update (optimistic lock)", "eng_pd1", "P1", overdue, "blocked"),
    ]
    first_tid = None
    for title, asg, pri, due, st in specs:
        ok, _, tid, _ = pstore.create_task(conn, lead, pid,
            {"title": [title], "assignee": [asg], "data_class": ["C2"],
             "priority": [pri], "due_date": [due], "description": [""]})
        if ok:
            first_tid = first_tid or tid
            if st != "todo":
                t = pstore.get_task(conn, tid)
                pstore.change_status(conn, lead, tid, st, t["version"])
    if first_tid:
        pstore.add_comment(conn, eng, first_tid, "Đang làm theo spec write-PEP; @lead_dv review giúp nhé.")
    connbase.sync_project(conn, pm, pid)
    compiled = pprog.compile_progress(conn, pm, pid)
    if compiled.get("ok"):
        pprog.save_snapshot(conn, pm, pid, compiled)


def run_seed():
    db.init_db()
    write_documents()
    conn = db.connect()
    try:
        seed_users(conn)
        seed_folders(conn)
        istore.ingest_all(conn)
        seed_sample_conversation(conn)
        seed_pm(conn)
    finally:
        conn.close()
    print("  Seed xong: users + documents + chunks + hội thoại mẫu + dự án PM mẫu.")
