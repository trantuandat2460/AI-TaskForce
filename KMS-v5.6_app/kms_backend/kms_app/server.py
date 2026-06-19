"""HTTP server stdlib (http.server). Middleware phiên (control-plane fail-closed):
chưa đăng nhập ⇒ GET→/login, POST→403. Mỗi request có một principal cô lập."""
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from config import settings
from kms_app import db
from kms_app.security import passwords, sessions
from kms_app.web import render, routes

PUBLIC_PATHS = {"/login", "/favicon.ico"}

class Handler(BaseHTTPRequestHandler):
    server_version = "KMS/5.6"
    def log_message(self, fmt, *args):
        print("[kms]", self.address_string(), fmt % args)

    # ---- helpers ----
    def _conn(self): return db.connect()
    def _principal(self, conn):
        token = None
        if "Cookie" in self.headers:
            c = SimpleCookie(self.headers["Cookie"])
            if settings.SESSION_COOKIE in c:
                token = c[settings.SESSION_COOKIE].value
        uid = sessions.lookup(conn, token)
        if not uid: return None
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        return db.row_to_subject(row) if row else None

    def _send(self, status, body, ctype="text/html; charset=utf-8", extra=None, download=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        for k, v in (extra or []): self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, loc, cookie=None):
        self.send_response(303)
        self.send_header("Location", loc)
        if cookie: self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _render_shell(self, conn, me, path, payload):
        # payload: ('html', body[, conv])
        body = payload[1]
        conv = payload[2] if len(payload) > 2 else None
        ok, n = routes._chain(conn)
        title = render.TITLES.get(path, "KMS")
        conv_cls = conv["max_data_class"] if conv else None
        return render.shell(me, path, title, body, chain_ok=ok, chain_n=n, conv_cls=conv_cls)

    # ---- GET ----
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)
        conn = self._conn()
        try:
            if path == "/login":
                return self._send(200, render.login_page())
            if path == "/favicon.ico":
                return self._send(204, b"")
            me = self._principal(conn)
            if not me:
                return self._redirect("/login")
            if path == "/logout":
                # handled below via cookie clear
                return self._do_logout(conn)
            out = routes.dispatch("GET", path, query, {}, conn, me)
            return self._emit(conn, me, path, out)
        finally:
            conn.close()

    # ---- POST ----
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode() if length else ""
        form = urllib.parse.parse_qs(raw)
        conn = self._conn()
        try:
            if path == "/login":
                return self._do_login(conn, form)
            me = self._principal(conn)
            if not me:
                return self._send(403, "403 — chưa đăng nhập")
            out = routes.dispatch("POST", path, urllib.parse.parse_qs(parsed.query), form, conn, me)
            return self._emit(conn, me, path, out)
        finally:
            conn.close()

    def _emit(self, conn, me, path, out):
        kind = out[0]
        if kind == "redirect":
            return self._redirect(out[1])
        if kind == "raw":
            _, ctype, data, *rest = out
            dl = rest[0] if rest else None
            return self._send(200, data, ctype=ctype, download=dl)
        # html (maybe with conv)
        return self._send(200, self._render_shell(conn, me, path, out))

    def _do_login(self, conn, form):
        uid = (form.get("user_id", [""])[0] or "").strip()
        pw = form.get("password", [""])[0]
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        ok = bool(row) and (passwords.verify_password(pw, row["pw_hash"]) if not settings.DEMO_AUTH else (pw == uid and passwords.verify_password(pw, row["pw_hash"])))
        if not ok:
            return self._send(200, render.login_page("Sai tài khoản hoặc mật khẩu (demo: mật khẩu = tên đăng nhập)."))
        token = sessions.new_session(conn, uid)
        c = SimpleCookie()
        c[settings.SESSION_COOKIE] = token
        c[settings.SESSION_COOKIE]["httponly"] = True
        c[settings.SESSION_COOKIE]["samesite"] = "Strict"
        c[settings.SESSION_COOKIE]["path"] = "/"
        if settings.COOKIE_SECURE: c[settings.SESSION_COOKIE]["secure"] = True
        return self._redirect("/", cookie=c.output(header="").strip())

    def _do_logout(self, conn):
        token = None
        if "Cookie" in self.headers:
            ck = SimpleCookie(self.headers["Cookie"])
            if settings.SESSION_COOKIE in ck: token = ck[settings.SESSION_COOKIE].value
        if token: sessions.end_session(conn, token)
        clear = f"{settings.SESSION_COOKIE}=; Path=/; Max-Age=0"
        return self._redirect("/login", cookie=clear)

def serve():
    httpd = ThreadingHTTPServer((settings.HOST, settings.PORT), Handler)
    print(f"  KMS v5.6 backend  →  http://{settings.HOST}:{settings.PORT}")
    print(f"  Dữ liệu runtime   →  {settings.DATA_DIR}")
    print("  Ctrl+C để dừng.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Đã dừng.")
        httpd.server_close()
