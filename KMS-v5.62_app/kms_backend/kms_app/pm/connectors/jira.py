"""Connector Jira (stub tất định). Điểm cắm REST thật giữ NGUYÊN chữ ký hàm — khi
lên production thay thân hàm bằng REST client gọi qua uplink đã duyệt (chỉ ≤C2 egress,
xem connectors/base.py). Mỗi item mang data_class nội tại (W4) để write-PEP/PEP đọc
phân quyền y như mọi resource khác."""

def fetch_issues(project_id, caller_scope=None):
    # caller_scope (nếu có) = trần class hiệu lực; production lọc tại nguồn. Bản stub
    # trả đủ rồi để base.py áp scope min(caller, service-account) — minh hoạ confused-deputy.
    return [
        {"source": "jira", "ref": "SOVRA-101", "kind": "issue", "title": "Rà soát cổng DCM",
         "author": "pm1", "state": "In Progress", "ts": "2026-06-10", "data_class": "C2",
         "payload": "Theo dõi review cổng phân loại DCM cho release."},
        {"source": "jira", "ref": "SOVRA-102", "kind": "issue", "title": "Tối ưu PEP-2 per-resource",
         "author": "lead_dv", "state": "Done", "ts": "2026-06-12", "data_class": "C2",
         "payload": "Giảm chi phí recheck PEP-2 ở phễu truy xuất."},
        {"source": "jira", "ref": "SOVRA-C3", "kind": "issue", "title": "Ghi chú datapath core-IP",
         "author": "eng_pd1", "state": "In Progress", "ts": "2026-06-13", "data_class": "C3",
         "payload": "Chi tiết datapath C3 — chỉ in-lane, không bao giờ egress."},
    ]
