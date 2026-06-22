"""Task Registry (A16/P34). Năng lực = hợp đồng khai báo: intent/inputs/sources
(+quyền)/steps/criteria/output_schema/version. LLM chỉ làm intent→chọn task."""
REGISTRY = {
    "review_weekly_report": {
        "task": "review_weekly_report", "version": 1,
        "intent": ["review báo cáo tuần", "rà soát weekly report", "đánh giá báo cáo tuần"],
        "inputs": ["report_this_week", "prior_week_report?", "team_id"],
        "sources": ["rag:weekly_report (via PEP)", "rag:review_standard (via PEP)",
                    "mcp:jira.issues {team,read}", "mcp:gitlab.activity {team,read}"],
        "steps": ["load_inputs", "llm_extract (T=0.0)", "cross_check vs jira/gitlab", "llm_assess (T=0.2)"],
        "criteria": ["completeness", "consistency với Jira/GitLab", "risk_flagged + actionable", "goals_measurable"],
        "output_schema": ["Summary", "AchievementsVsPlan", "Risks", "NextWeek", "ReviewerNotes"],
    },
    # v5.62: biên dịch tiến độ dự án — TẤT ĐỊNH THẬT (không LLM): aggregate là phép đếm,
    # risks là rule-derived. 'Tất định' ở đây là về NỘI DUNG, không chỉ schema (sửa phê
    # bình đánh-tráo-khái-niệm-determinism). Mọi nguồn đọc qua PEP của người chạy.
    "compile_project_progress": {
        "task": "compile_project_progress", "version": 1,
        "intent": ["biên dịch tiến độ", "tổng hợp tiến độ dự án", "project progress"],
        "inputs": ["project_id", "tasks (via PEP)", "connector_items (via PEP)", "progress_reports (via PEP)"],
        "sources": ["db:tasks (read-PEP)", "db:connector_items (read-PEP)", "rag:PROGRESS_REPORT (read-PEP)"],
        "steps": ["load_inputs (qua PEP người chạy)", "aggregate (đếm/đối chiếu — KHÔNG LLM)",
                  "assess (risks rule-derived — KHÔNG LLM)", "validate (schema cố định)"],
        "criteria": ["determinism nội dung (no-LLM)", "per-PEP sources", "schema-valid",
                     "highest-wins làm sàn cứng khi promote OKF"],
        "output_schema": ["Summary", "TaskStats", "VsJiraGitlab", "Risks", "NextWeek", "Blockers"],
    },
}

def classify_intent(text):
    t = text.lower()
    for name, c in REGISTRY.items():
        if any(k in t for k in c["intent"]) or ("báo cáo" in t and "tuần" in t):
            return name
    return None
