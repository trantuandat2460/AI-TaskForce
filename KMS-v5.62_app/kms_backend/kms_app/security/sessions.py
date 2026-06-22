"""Phiên server-side (control-plane). Token ngẫu nhiên 192-bit, lưu DB, TTL."""
import secrets, datetime
from config import settings
from kms_app import db

def _now(): return datetime.datetime.utcnow()
def _iso(dt): return dt.strftime("%Y-%m-%d %H:%M:%S")

def new_session(conn, user_id: str) -> str:
    token = secrets.token_urlsafe(24)
    exp = _now() + datetime.timedelta(seconds=settings.SESSION_TTL_SECONDS)
    conn.execute("INSERT INTO sessions(token,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                 (token, user_id, _iso(_now()), _iso(exp)))
    conn.commit()
    return token

def lookup(conn, token: str):
    if not token: return None
    row = conn.execute("SELECT * FROM sessions WHERE token=?", (token,)).fetchone()
    if not row: return None
    if _iso(_now()) > row["expires_at"]:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,)); conn.commit()
        return None
    return row["user_id"]

def end_session(conn, token: str):
    conn.execute("DELETE FROM sessions WHERE token=?", (token,)); conn.commit()
