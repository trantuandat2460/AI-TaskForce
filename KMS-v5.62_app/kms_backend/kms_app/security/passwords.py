"""Băm mật khẩu PBKDF2-HMAC-SHA256 (P §21.2). Không lưu mật khẩu thô."""
import hashlib, hmac, os, base64
from config import settings

def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, settings.PBKDF2_ROUNDS)
    return base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()

def verify_password(pw: str, stored: str) -> bool:
    try:
        s, h = stored.split("$")
        salt = base64.b64decode(s); expected = base64.b64decode(h)
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, settings.PBKDF2_ROUNDS)
        return hmac.compare_digest(dk, expected)   # chống timing
    except Exception:
        return False
