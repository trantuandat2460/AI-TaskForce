"""Conversation Store có chủ quyền (A11/P29). Hội thoại kế thừa max_data_class
(P15); đọc owner-scope; replay tái cấp quyền (xem web/routes)."""
import datetime, json
from config import settings
from config.settings import CLASS_RANK
from kms_app import db

def _now(): return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def create(conn, owner_user, project_id="SOVRA", title=None):
    n = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] + 1
    conv_id = f"C-{n:03d}"
    retain = (datetime.datetime.utcnow() + datetime.timedelta(days=settings.CONVERSATION_RETAIN_DAYS)).strftime("%Y-%m-%d")
    conn.execute("""INSERT INTO conversations(conv_id,owner_user,project_id,title,max_data_class,created_at,updated_at,retain_until)
        VALUES(?,?,?,?,?,?,?,?)""",
        (conv_id, owner_user, project_id, title or f"Hội thoại {_now()[11:]}", "C1", _now(), _now(), retain))
    conn.commit()
    return conv_id

def list_for(conn, user_id, is_admin):
    if is_admin:
        return conn.execute("SELECT * FROM conversations ORDER BY conv_id DESC").fetchall()
    return conn.execute("SELECT * FROM conversations WHERE owner_user=? ORDER BY conv_id DESC", (user_id,)).fetchall()

def get(conn, conv_id):
    return conn.execute("SELECT * FROM conversations WHERE conv_id=?", (conv_id,)).fetchone()

def messages(conn, conv_id):
    return conn.execute("SELECT * FROM messages WHERE conv_id=? ORDER BY turn_index ASC", (conv_id,)).fetchall()

def citations(conn, msg_id):
    return conn.execute("SELECT * FROM message_citations WHERE msg_id=?", (msg_id,)).fetchall()

def add_message(conn, conv_id, role, content, rewritten=None, refused=0, cites=None):
    n = conn.execute("SELECT COUNT(*) FROM messages WHERE conv_id=?", (conv_id,)).fetchone()[0]
    msg_id = f"{conv_id}-m{n}"
    conn.execute("""INSERT INTO messages(msg_id,conv_id,turn_index,role,content,rewritten,refused,created_at)
        VALUES(?,?,?,?,?,?,?,?)""", (msg_id, conv_id, n, role, content, rewritten, int(refused), _now()))
    for c in (cites or []):
        conn.execute("""INSERT INTO message_citations(msg_id,doc_id,chunk_id,sensitive_level,data_class)
            VALUES(?,?,?,?,?)""", (msg_id, c["doc_id"], c["chunk_id"], c["sensitive_level"], c["data_class"]))
    conn.execute("UPDATE conversations SET updated_at=? WHERE conv_id=?", (_now(), conv_id))
    conn.commit()
    return msg_id

def bump_class(conn, conv_id, mdc):
    row = get(conn, conv_id)
    cur = row["max_data_class"]
    new = mdc if CLASS_RANK[mdc] > CLASS_RANK[cur] else cur
    if new != cur:
        conn.execute("UPDATE conversations SET max_data_class=? WHERE conv_id=?", (new, conv_id)); conn.commit()
    return new
