"""Audit bất biến hash-chain + HMAC (P24). current = SHA256(payload+prev);
hmac = HMAC-SHA256(secret, payload). verify() phát hiện sửa đổi."""
import hashlib, hmac, os, datetime, csv
from config import settings
from kms_app import db

def _secret() -> bytes:
    if not settings.SECRET_FILE.exists():
        settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        settings.SECRET_FILE.write_bytes(os.urandom(32))
        try: os.chmod(settings.SECRET_FILE, 0o600)
        except Exception: pass
    return settings.SECRET_FILE.read_bytes()

def _now(): return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def _payload(ts, e):
    return "|".join([ts, e["on_behalf_of_user"], e.get("agent_id") or "-", e["action"],
                     e.get("resource_ref") or "-", e["authz_reason"],
                     e.get("max_data_class_accessed") or "-", e["previous_log_hash"]])

def append(conn, on_behalf_of_user, action, resource_ref, authz_reason,
           agent_id=None, max_data_class_accessed=None, task_contract_version=None,
           lane=None, infra_tier=None, near_miss=0,
           model_id=None, model_version=None):
    row = conn.execute("SELECT current_log_hash FROM audit_logs ORDER BY log_id DESC LIMIT 1").fetchone()
    prev = row["current_log_hash"] if row else "GENESIS"
    ts = _now()
    e = {"on_behalf_of_user": on_behalf_of_user, "agent_id": agent_id, "action": action,
         "resource_ref": resource_ref, "authz_reason": authz_reason,
         "max_data_class_accessed": max_data_class_accessed, "previous_log_hash": prev}
    payload = _payload(ts, e)
    cur = hashlib.sha256(payload.encode()).hexdigest()
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    conn.execute("""INSERT INTO audit_logs
        (ts,on_behalf_of_user,agent_id,action,resource_ref,authz_reason,model_id,model_version,
         task_contract_version,lane,infra_tier,max_data_class_accessed,near_miss,
         previous_log_hash,current_log_hash,hmac_signature)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (ts, on_behalf_of_user, agent_id, action, resource_ref, authz_reason, model_id, model_version,
         task_contract_version, lane, infra_tier, max_data_class_accessed, near_miss, prev, cur, sig))
    conn.commit()
    return cur

def verify(conn):
    prev = "GENESIS"
    rows = conn.execute("SELECT * FROM audit_logs ORDER BY log_id ASC").fetchall()
    for i, r in enumerate(rows):
        e = {"on_behalf_of_user": r["on_behalf_of_user"], "agent_id": r["agent_id"], "action": r["action"],
             "resource_ref": r["resource_ref"], "authz_reason": r["authz_reason"],
             "max_data_class_accessed": r["max_data_class_accessed"], "previous_log_hash": prev}
        cur = hashlib.sha256(_payload(r["ts"], e).encode()).hexdigest()
        if cur != r["current_log_hash"]:
            return {"ok": False, "broken_at": i, "total": len(rows)}
        prev = r["current_log_hash"]
    return {"ok": True, "broken_at": -1, "total": len(rows)}

def export_csv(conn):
    settings.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = settings.EXPORTS_DIR / "audit.csv"
    rows = conn.execute("SELECT * FROM audit_logs ORDER BY log_id ASC").fetchall()
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        if rows:
            w.writerow(rows[0].keys())
            for r in rows: w.writerow(list(r))
    return path
