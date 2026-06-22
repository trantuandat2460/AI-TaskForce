"""Hợp đồng connector + đồng bộ (S8 v5.6, sửa theo phê bình connector & W4).

Bảo mật connector (bất biến):
  - READ-ONLY: KMS không ghi ngược Jira/GitLab.
  - Scope = min(clearance người gọi, service-account) — chống confused-deputy: item có
    data_class vượt scope bị DROP (kỹ sư C3 vẫn không kéo được C3 nếu SA chỉ C2).
  - Mỗi item mang data_class + permission_group (W4) ⇒ PEP đọc/biên dịch phân quyền y
    như document; KHÔNG có item 'vô phân loại'.
  - Scanner ingest tầng-1: secret/PII trong payload ⇒ quarantine (không index, không vào
    biên dịch tiến độ) — kế thừa S5.
  - Egress-by-tier: chỉ ≤ settings.EGRESS_MAX_CLASS được rời enclave qua uplink (bản stub
    offline; ràng buộc dành cho production REST).

Điểm cắm REST thật: thay thân jira.fetch_issues / gitlab.fetch_commits, GIỮ chữ ký.
"""
import json, datetime
from config import settings
from config.settings import CLASS_RANK
from kms_app.security import audit
from kms_app.ingestion import scanners
from kms_app.pm import authz
from kms_app.pm.connectors import jira, gitlab


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def caller_scope_class(subject):
    """min(clearance người gọi, service-account) theo rank phân loại."""
    sa = settings.CONNECTOR_SA_CLEARANCE
    return subject["clearance"] if CLASS_RANK[subject["clearance"]] <= CLASS_RANK[sa] else sa


def list_items(conn, subject, project_id, include_quarantine=True):
    rows = conn.execute("SELECT * FROM connector_items WHERE project_id=? ORDER BY ts DESC",
                        (project_id,)).fetchall()
    if subject["role"] == "ADMIN":
        return rows
    from kms_app import db
    out = []
    for r in rows:
        if not include_quarantine and r["status"] != "active":
            continue
        if authz.can_read(conn, subject, db.connector_item_to_resource(r)):
            out.append(r)
    return out


def sync_project(conn, subject, project_id):
    """Đồng bộ Jira+GitLab vào cache connector_items (idempotent qua item_id)."""
    d = authz.authorize_action(conn, subject, "fetch_connector", {"project_id": project_id})
    if not d.allow:
        audit.append(conn, on_behalf_of_user=subject["user_id"], agent_id="pm:connector",
                     action="pm:fetch_connector", resource_ref=project_id, authz_reason=d.reason, near_miss=1)
        return {"ok": False, "reason": d.reason}

    proj = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
    proj_ceiling = proj["data_class"] if proj else "C2"
    perm = proj["permission_group"] if proj else "vsi_internal"
    scope = caller_scope_class(subject)

    raw = jira.fetch_issues(project_id, scope) + gitlab.fetch_commits(project_id, scope)
    rep = {"ok": True, "fetched": 0, "dropped_scope": 0, "quarantined": 0, "active": 0, "scope": scope}
    for it in raw:
        rep["fetched"] += 1
        cls = it.get("data_class", "C2")
        # confused-deputy: không kéo item vượt min(caller, SA)
        if CLASS_RANK[cls] > CLASS_RANK[scope]:
            rep["dropped_scope"] += 1
            continue
        # không vượt trần dự án
        if CLASS_RANK[cls] > CLASS_RANK[proj_ceiling]:
            rep["dropped_scope"] += 1
            continue
        sec_hit, reason = scanners.secret_scan(it.get("payload", ""))
        status, qreason = ("quarantined", reason) if sec_hit else ("active", None)
        item_id = f'{it["source"]}:{it["ref"]}'
        conn.execute("""INSERT OR REPLACE INTO connector_items
            (item_id,source,project_id,kind,ref,title,author,state,ts,payload_json,
             data_class,permission_group,owner_project,status,quarantine_reason,fetched_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (item_id, it["source"], project_id, it["kind"], it["ref"], it["title"], it["author"],
             it["state"], it["ts"], json.dumps(it, ensure_ascii=False), cls, perm, project_id,
             status, qreason, _now()))
        rep["quarantined" if status == "quarantined" else "active"] += 1

    audit.append(conn, on_behalf_of_user=subject["user_id"], agent_id="pm:connector",
                 action="pm:fetch_connector", resource_ref=project_id, authz_reason="ALLOW",
                 max_data_class_accessed=scope, infra_tier="connector")
    conn.commit()
    return rep
