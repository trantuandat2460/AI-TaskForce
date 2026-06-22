"""Session State Memory (A12/P30). Cập nhật tăng dần: active_topic, thực thể
nổi bật, referent gần nhất, tóm tắt cuốn chiếu. State là dẫn xuất → thừa kế
mức của hội thoại; nạp cho LLM như DỮ LIỆU (context fencing)."""
import json, datetime
from kms_app import db

def _now(): return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
def _topic(title): return (title or "").split("—")[0].strip() or (title or "")

def get(conn, conv_id):
    r = conn.execute("SELECT * FROM conversation_state WHERE conv_id=?", (conv_id,)).fetchone()
    if not r:
        return {"rolling_summary": "", "salient_entities": [], "active_topic": None, "last_referents": []}
    return {"rolling_summary": r["rolling_summary"] or "",
            "salient_entities": json.loads(r["salient_entities_json"] or "[]"),
            "active_topic": r["active_topic"],
            "last_referents": json.loads(r["last_referents_json"] or "[]")}

def update(conn, conv_id, query, used_resources):
    """used_resources: list dict có 'doc_id' và 'title' (đã qua PEP)."""
    st = get(conn, conv_id)
    topics = [_topic(r.get("title")) for r in used_resources if r.get("title")]
    ents = list(dict.fromkeys(st["salient_entities"] + topics))[-8:]
    active = topics[0] if topics else st["active_topic"]
    summary = (st["rolling_summary"] + " • " if st["rolling_summary"] else "") + "hỏi: " + query[:48]
    conn.execute("""INSERT OR REPLACE INTO conversation_state
        (conv_id,rolling_summary,salient_entities_json,active_topic,last_referents_json,updated_at)
        VALUES(?,?,?,?,?,?)""",
        (conv_id, summary, json.dumps(ents, ensure_ascii=False), active,
         json.dumps([r["doc_id"] for r in used_resources]), _now()))
    conn.commit()
