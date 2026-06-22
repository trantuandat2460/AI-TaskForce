"""Self-test: PDP 8 bước (đủ 6 lý do DENY + ALLOW), PEP-1, chuỗi audit + verify
phát hiện giả mạo, và re-authorize-on-replay khi hạ clearance.
Chạy: python -m tests.test_pdp   (hoặc python tests/test_pdp.py từ gốc project)
"""
import os, sys, sqlite3, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kms_app.security.pdp import authorize
from kms_app.security import pep, audit
from kms_app import db

PASS = 0; FAIL = 0
def check(name, got, want):
    global PASS, FAIL
    ok = got == want
    PASS += ok; FAIL += (not ok)
    print(f"  {'✓' if ok else '✗'} {name}: {got}" + ("" if ok else f"  (muốn {want})"))

# ---- chủ thể (khớp seed) ----
U = {
 "admin1": {"user_id":"admin1","role":"ADMIN","department":"IT","clearance":"C3","tags":{"core-ip"},"groups":{"vsi_public","vsi_internal","vsi_confidential"},"projects":{"SOVRA","SAURIA"},"manages":{"eng_dv1"},"hr_purpose":True},
 "eng_pd1":{"user_id":"eng_pd1","role":"ENGINEER","department":"PHYSICAL","clearance":"C3","tags":{"core-ip","proj-sovra","disc-pd"},"groups":{"vsi_public","vsi_internal","vsi_confidential"},"projects":{"SOVRA"},"manages":set(),"hr_purpose":False},
 "lead_dv":{"user_id":"lead_dv","role":"LEADER","department":"DV","clearance":"C3","tags":{"lead","proj-sovra","disc-dv"},"groups":{"vsi_public","vsi_internal","vsi_confidential"},"projects":{"SOVRA"},"manages":{"eng_dv1"},"hr_purpose":False},
 "pm1":    {"user_id":"pm1","role":"PM","department":"PMO","clearance":"C2","tags":{"pmo","proj-sovra"},"groups":{"vsi_public","vsi_internal"},"projects":{"SOVRA"},"manages":set(),"hr_purpose":False},
}
def R(**kw):
    base = dict(resource_id="R", data_class="C2", kind="METADATA", owner_project=None, owner_dept=None,
                required_tags=[], permission_group="vsi_internal", sensitive_level="confidential",
                is_credential=False, is_personnel_report=False, subject_person=None)
    base.update(kw); return base

print("== PDP: 6 lý do DENY + ALLOW ==")
check("pm1 × R-002 (C3 core-ip)", authorize(U["pm1"], R(resource_id="R-002", data_class="C3", kind="SPEC_DETAIL", owner_project="SOVRA", required_tags=["core-ip"], permission_group="vsi_confidential")).reason, "DENY_DCM")
check("eng_pd1 × R-012 (cần disc-dv)", authorize(U["eng_pd1"], R(resource_id="R-012", kind="PROGRESS_REPORT", owner_project="SOVRA", owner_dept="DV", required_tags=["disc-dv"])).reason, "DENY_ABAC")
check("eng_pd1 × R-014 (dự án SAURIA)", authorize(U["eng_pd1"], R(resource_id="R-014", kind="METADATA", owner_project="SAURIA")).reason, "DENY_PROJECT")
check("lead_dv × R-007 (FOUNDRY PHYSICAL)", authorize(U["lead_dv"], R(resource_id="R-007", data_class="C3", kind="FOUNDRY", owner_dept="PHYSICAL")).reason, "DENY_DEPARTMENT")
check("eng_pd1 × R-009 (PII người khác)", authorize(U["eng_pd1"], R(resource_id="R-009", kind="PII", is_personnel_report=True, subject_person="eng_dv1")).reason, "DENY_REBAC_PERSONNEL")
check("pm1 × R-013 (TESTBENCH)", authorize(U["pm1"], R(resource_id="R-013", kind="TESTBENCH", owner_project="SOVRA")).reason, "DENY_ROLE")
check("any × R-010 (credential)", authorize(U["eng_pd1"], R(resource_id="R-010", data_class="C3", kind="METADATA", is_credential=True)).reason, "DENY_CREDENTIAL")
check("eng_pd1 × R-002 (đủ quyền)", authorize(U["eng_pd1"], R(resource_id="R-002", data_class="C3", kind="SPEC_DETAIL", owner_project="SOVRA", required_tags=["core-ip"], permission_group="vsi_confidential")).reason, "ALLOW")
check("lead_dv × R-009 (manages eng_dv1)", authorize(U["lead_dv"], R(resource_id="R-009", kind="PII", is_personnel_report=True, subject_person="eng_dv1")).reason, "ALLOW")
check("admin1 × R-007 (admin bypass dept)", authorize(U["admin1"], R(resource_id="R-007", data_class="C3", kind="FOUNDRY", owner_dept="PHYSICAL")).reason, "ALLOW")

print("== PEP-1: permission_group MatchAny ==")
docs = [R(resource_id="d1", permission_group="vsi_public"), R(resource_id="d2", permission_group="vsi_confidential")]
check("pm1 thấy 1/2 (không có vsi_confidential)", len(pep.pep1_filter_docs(U["pm1"], docs)), 1)
check("eng_pd1 thấy 2/2", len(pep.pep1_filter_docs(U["eng_pd1"], docs)), 2)

print("== max_data_class: highest-wins (P15) ==")
check("max(C2,C3,C1)=C3", pep.max_class([{"data_class":"C2"},{"data_class":"C3"},{"data_class":"C1"}]), "C3")

print("== Audit hash-chain + verify phát hiện giả mạo ==")
conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
conn.executescript(db.SCHEMA)
audit.append(conn, "eng_pd1", "rag_query", "R-002", "ALLOW", max_data_class_accessed="C3")
audit.append(conn, "eng_pd1", "rag_query", "R-001", "ALLOW", max_data_class_accessed="C2")
audit.append(conn, "pm1", "rag_query", "(none)", "DENY_NO_GROUNDED")
check("chuỗi nguyên vẹn", audit.verify(conn)["ok"], True)
conn.execute("UPDATE audit_logs SET authz_reason='DENY_DCM' WHERE log_id=2")  # giả mạo
check("phát hiện giả mạo @log 2", audit.verify(conn)["broken_at"], 1)

print("== Re-authorize-on-replay: hạ clearance ẩn trích dẫn C3 ==")
res_c3 = R(resource_id="R-002", data_class="C3", kind="SPEC_DETAIL", owner_project="SOVRA", required_tags=["core-ip"], permission_group="vsi_confidential")
check("eng_pd1 (C3) đọc được", authorize(U["eng_pd1"], res_c3).allow, True)
demoted = dict(U["eng_pd1"]); demoted["clearance"] = "C1"
check("eng_pd1 (hạ về C1) bị chặn", authorize(demoted, res_c3).reason, "DENY_DCM")

print("== v5.6 · corpus/lane reachability (S3 air-gap) ==")
check("SECURED không với tới corpus_c3", pep.corpus_reachable("corpus_c3", "SECURED", "C3"), False)
check("C3_ENCLAVE với tới corpus_c3", pep.corpus_reachable("corpus_c3", "C3_ENCLAVE", "C3"), True)
check("clearance C2 không reach corpus_c3 dù trong enclave", pep.corpus_reachable("corpus_c3", "C3_ENCLAVE", "C2"), False)
check("SECURED với tới corpus_c2", pep.corpus_reachable("corpus_c2", "SECURED", "C2"), True)
check("corpus None ⇒ fail-closed", pep.corpus_reachable(None, "C3_ENCLAVE", "C3"), False)

print("== v5.6 · scanner ingest (độc lập cờ producer, S5) ==")
from kms_app.ingestion import scanners
check("secret_scan bắt AWS key", scanners.secret_scan("api_key=AKIAIOSFODNN7EXAMPLE9")[0], True)
check("secret_scan bỏ qua prose thường", scanners.secret_scan("Tài liệu kỹ thuật bình thường.")[0], False)
check("ner cần tên riêng (chỉ 'nhân viên' ⇒ không)", scanners.ner_scan("Hướng dẫn cho nhân viên mới.")[0], False)
check("ner bắt hồ sơ + tên riêng", scanners.ner_scan("Đánh giá hiệu suất của Nguyen Van A.")[0], True)

print("== v5.6 · OKF coerce fail-closed (S4) ==")
from kms_app.ingestion import permissions as PM
check("thiếu data_class ⇒ quarantine", PM.coerce({}, "internal")["status"], "quarantined")
check("thiếu data_class ⇒ mặc định C3", PM.coerce({}, "internal")["data_class"], "C3")
check("C3 trỏ corpus ≤C2 ⇒ quarantine (chống hạ cấp)",
      PM.coerce({"vsi_data_class":"C3","vsi_corpus_id":"corpus_c2"}, "confidential")["status"], "quarantined")
check("OKF hợp lệ ⇒ corpus đúng", PM.coerce({"vsi_data_class":"C3"}, "confidential")["corpus_id"], "corpus_c3")

print("== v5.6 · upload theo hierarchy + spell check (workspace) ==")
from kms_app.ingestion import workspace as WS, quality as QA
pm = {"user_id":"pm1","role":"PM","department":"PMO","clearance":"C2","tags":set(),
      "groups":{"vsi_public","vsi_internal"},"projects":{"SOVRA"},"manages":set(),"hr_purpose":False}
fold = {"folder_id":"pm1__x","name":"x","owner_user":"pm1","permission_group":"vsi_internal","owner_project":"SOVRA"}
pf_hi = WS.preflight(pm, {"title":["t"],"body":["noi dung"],"data_class":["C3"]}, fold)
check("C2 user tạo C3 ⇒ hierarchy error", any("clearance" in e for e in pf_hi["hierarchy_errors"]), True)
pf_ok = WS.preflight(pm, {"title":["t"],"body":["noi dung sach"],"data_class":["C2"]}, fold)
check("C2 user tạo C2 ⇒ hợp lệ", pf_ok["ok"], True)
pf_sec = WS.preflight(pm, {"title":["t"],"body":["api_key=AKIAIOSFODNN7EXAMPLE9"],"data_class":["C2"]}, fold)
check("upload chứa secret ⇒ không ok", pf_sec["ok"], False)
check("spell_check bắt lỗi lặp từ", any(i["type"]=="repeated-word" for i in QA.spell_check("This is is wrong")), True)
check("spell_check sạch ⇒ rỗng", QA.spell_check("# Heading\nNoi dung binh thuong."), [])

print(f"\n{'='*40}\nKẾT QUẢ: {PASS} PASS / {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
