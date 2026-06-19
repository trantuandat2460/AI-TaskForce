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
    }
}

def classify_intent(text):
    t = text.lower()
    for name, c in REGISTRY.items():
        if any(k in t for k in c["intent"]) or ("báo cáo" in t and "tuần" in t):
            return name
    return None
