"""Connector GitLab (stub tất định). Cùng hợp đồng điểm-cắm như jira.py. Một commit
cố tình chứa khoá AWS để minh hoạ scanner ingest bắt secret trên ITEM CONNECTOR và
quarantine y như document (kế thừa S5 v5.6)."""

def fetch_commits(project_id, caller_scope=None):
    return [
        {"source": "gitlab", "ref": "a1b2c3d", "kind": "commit", "title": "fix: nhánh deny của write-PEP",
         "author": "eng_dv1", "state": "merged", "ts": "2026-06-14", "data_class": "C2",
         "payload": "Sửa nhánh từ chối cho change_status review→done."},
        {"source": "gitlab", "ref": "e4f5a6b", "kind": "merge_request", "title": "feat: seed connector PM",
         "author": "lead_dv", "state": "merged", "ts": "2026-06-15", "data_class": "C2",
         "payload": "Thêm dữ liệu seed. (lỡ dán khoá) api_key=AKIAIOSFODNN7EXAMPLE9"},
    ]
