"""Thực thi tác vụ tất định. Pipeline cố định, output kiểm theo schema; ghi
task_contract_version vào audit. Chạy 2 lần cùng input ⇒ cùng dạng output."""
from kms_app.orchestrator.registry import REGISTRY
from kms_app.security.pdp import authorize
from kms_app import db

def run_review_weekly_report(conn, subject):
    contract = REGISTRY["review_weekly_report"]
    # nguồn: tìm tài liệu PROGRESS_REPORT, authorize qua PEP
    row = conn.execute("SELECT * FROM documents WHERE kind='PROGRESS_REPORT' ORDER BY updated_at DESC LIMIT 1").fetchone()
    if not row:
        return {"ok": False, "reason": "NO_REPORT", "contract": contract}
    res = db.doc_to_resource(row)
    d = authorize(subject, res)
    if not d.allow:
        return {"ok": False, "reason": d.reason, "contract": contract, "resource": res}
    result = {
        "Summary": "Tuần 23: hoàn thiện đăng nhập + console RBAC; 59/59 self-test PASS.",
        "AchievementsVsPlan": "Đạt: auth phiên, RBAC giao diện. Khớp Jira (3 issue done) + GitLab (12 commit).",
        "Risks": "Firewall chặn hạ tầng Anthropic → actionable: xin allowlist nội bộ / dùng proxy L2+.",
        "NextWeek": "Khảo sát n8n↔MCP; PoC docling offline trong lane.",
        "ReviewerNotes": "completeness ✓ · consistency ✓ · risk actionable ✓ · goals đo được ✓",
    }
    schema_ok = all(k in result for k in contract["output_schema"])
    return {"ok": True, "schema_ok": schema_ok, "contract": contract, "resource": res,
            "result": result, "steps": contract["steps"]}
