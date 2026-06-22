"""Render HTML server-side. Một stylesheet + khung shell + component dùng lại
(decision-trace, chip phân loại, bảng). Giao diện Viettel, không phụ thuộc CDN."""
import html
from config import settings
VER = settings.APP_VERSION
CL = lambda c: f'<span class="cls {c}">{c}</span>'
def esc(s): return html.escape(str(s if s is not None else ""))

CSS = """
:root{--ink:#0E1525;--ink-3:#1f2c47;--surface:#F6F7F9;--panel:#fff;--panel-2:#FBFCFD;--line:#E4E8EF;--line-2:#D2D9E4;
--text:#16203A;--muted:#67718A;--muted-2:#8A93A6;--brand:#EE0033;--brand-press:#C40029;--brand-soft:#FDEAEE;
--allow:#127A52;--allow-soft:#E4F3EC;--deny:#C0392B;--deny-soft:#FBE9E7;--skip:#9AA3B2;--skip-soft:#EEF1F5;
--c1:#56657F;--c1-soft:#EAEDF2;--c2:#A66A12;--c2-soft:#FAF0DE;--c3:#A92019;--c3-soft:#F8E4E2;
--ui:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,system-ui,Arial,sans-serif;
--mono:"SF Mono","JetBrains Mono",ui-monospace,Menlo,Consolas,monospace;}
*{box-sizing:border-box}body{margin:0;font-family:var(--ui);color:var(--text);background:var(--surface);font-size:14px;line-height:1.5}
a{color:var(--brand);text-decoration:none}button{font-family:inherit;cursor:pointer}.mono{font-family:var(--mono)}
input,select,textarea{font-family:inherit;font-size:14px;padding:9px 11px;border:1px solid var(--line-2);border-radius:7px;background:var(--panel-2);width:100%}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-soft)}
.eyebrow{font-family:var(--mono);text-transform:uppercase;letter-spacing:.12em;font-size:11px;color:var(--muted-2);font-weight:600}
h1,h2,h3{margin:0;letter-spacing:-.01em}
.cls{font-family:var(--mono);font-weight:700;font-size:11px;padding:2px 7px;border-radius:5px;display:inline-flex;align-items:center;gap:5px}
.cls::before{content:"";width:7px;height:7px;border-radius:50%}
.cls.C1{color:var(--c1);background:var(--c1-soft)}.cls.C1::before{background:var(--c1)}
.cls.C2{color:var(--c2);background:var(--c2-soft)}.cls.C2::before{background:var(--c2)}
.cls.C3{color:var(--c3);background:var(--c3-soft)}.cls.C3::before{background:var(--c3)}
.verdict{font-family:var(--mono);font-weight:700;font-size:11px;padding:2px 8px;border-radius:5px}
.verdict.allow{color:var(--allow);background:var(--allow-soft)}.verdict.deny{color:var(--deny);background:var(--deny-soft)}
.btn{border:1px solid transparent;border-radius:7px;padding:9px 14px;font-weight:600;font-size:13px;display:inline-flex;gap:6px;align-items:center}
.btn.primary{background:var(--brand);color:#fff}.btn.primary:hover{background:var(--brand-press)}
.btn.ghost{background:var(--panel);border-color:var(--line-2);color:var(--text)}.btn.ghost:hover{border-color:var(--muted-2)}
.btn.sm{padding:6px 10px;font-size:12px}.btn.full{width:100%;justify-content:center}
.shell{display:grid;grid-template-columns:248px 1fr;grid-template-rows:54px 1fr;min-height:100vh}
.sidebar{grid-row:1/span 2;background:var(--ink);color:#C7D0E0;display:flex;flex-direction:column}
.sb-brand{padding:16px 18px;display:flex;align-items:center;gap:10px;border-bottom:1px solid #20304d}
.sb-brand .dot{width:20px;height:20px;border-radius:6px;background:var(--brand)}.sb-brand b{color:#fff}
.sb-brand .ver{margin-left:auto;font-family:var(--mono);font-size:10px;color:#7E8AA3;border:1px solid #2a3a59;border-radius:5px;padding:1px 6px}
.who{padding:14px 18px;border-bottom:1px solid #20304d}.who .nm{color:#fff;font-weight:600}
.who .rl{font-family:var(--mono);font-size:11px;color:#8E9AB4;margin-top:3px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.nav{padding:10px;flex:1;overflow:auto}
.nav a{display:flex;gap:10px;align-items:center;color:#AEB9CD;padding:9px 12px;border-radius:8px;font-size:13px;font-weight:500}
.nav a:hover{background:#172339;color:#fff}.nav a.active{background:#1d2c48;color:#fff;box-shadow:inset 2px 0 0 var(--brand)}
.nav .sep{font-family:var(--mono);font-size:10px;color:#5d6a85;letter-spacing:.1em;text-transform:uppercase;padding:14px 12px 6px}
.sb-foot{padding:12px 14px;border-top:1px solid #20304d;font-size:11px;color:#6f7c97}
.topbar{display:flex;align-items:center;gap:12px;padding:0 22px;background:var(--panel);border-bottom:1px solid var(--line)}
.topbar .title{font-weight:700}.spacer{flex:1}
.pill{display:inline-flex;align-items:center;gap:7px;font-size:12px;color:var(--muted);background:var(--panel-2);border:1px solid var(--line);padding:5px 10px;border-radius:999px}
.pill .lab{font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted-2)}
.lamp{width:8px;height:8px;border-radius:50%;background:var(--allow)}.lamp.bad{background:var(--deny)}
.main{overflow:auto}.wrap{max-width:1120px;margin:0 auto;padding:24px 22px 60px}
.page-head{margin-bottom:18px}.page-head h2{font-size:21px}.page-head p{color:var(--muted);margin:6px 0 0;max-width:74ch}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;box-shadow:0 1px 2px rgba(16,21,37,.05),0 8px 24px -18px rgba(16,21,37,.18);margin-bottom:16px}
.card .hd{padding:13px 16px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px}.card .hd h3{font-size:14px}
.card .bd{padding:16px}
.grid{display:grid;gap:16px}.g2{grid-template-columns:1fr 1fr}.gchat{grid-template-columns:1fr 340px}
@media(max-width:900px){.g2,.gchat{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted-2);font-weight:600;padding:8px 10px;border-bottom:1px solid var(--line)}
td{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}tr:last-child td{border-bottom:none}
.t-id{font-family:var(--mono);font-size:12px}.small{font-size:12px}.muted{color:var(--muted)}
.tag{font-family:var(--mono);font-size:10px;background:var(--skip-soft);border:1px solid var(--line);padding:1px 6px;border-radius:5px;color:var(--muted);margin:1px 2px 1px 0;display:inline-block}
.badge{font-family:var(--mono);font-size:11px;background:var(--skip-soft);border:1px solid var(--line);border-radius:5px;padding:1px 7px;color:var(--muted)}
.field{margin-bottom:12px}.field label{display:block;font-size:12px;color:var(--muted);margin-bottom:5px;font-weight:600}
.note{font-size:12px;color:var(--muted);background:var(--panel-2);border:1px solid var(--line);border-left:3px solid var(--brand);border-radius:7px;padding:10px 12px}
.trace{font-family:var(--mono);font-size:12px;border:1px solid var(--line);border-radius:7px;overflow:hidden;background:var(--panel-2)}
.trace .row{display:grid;grid-template-columns:16px 150px 1fr;gap:10px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--line)}
.trace .row:last-child{border-bottom:none}
.l2{width:11px;height:11px;border-radius:50%}.l2.pass{background:var(--allow)}.l2.allow{background:var(--allow)}.l2.deny{background:var(--deny)}.l2.skip{background:var(--skip)}
.trace .rule{font-weight:600}.trace .det{color:var(--muted)}.trace .row.deny .rule{color:var(--deny)}.trace .row.allow .rule{color:var(--allow)}
.msg{padding:12px 14px;border-radius:10px;margin-bottom:10px;max-width:90%}
.msg.user{background:var(--ink);color:#EAF0FA;margin-left:auto}.msg.bot{background:var(--panel-2);border:1px solid var(--line)}
.msg .meta{font-family:var(--mono);font-size:10px;opacity:.7;margin-bottom:5px}
.cites{margin-top:9px;border-top:1px dashed var(--line);padding-top:8px}
.cite{font-size:12px;display:flex;gap:8px;align-items:center;padding:3px 0}.cite .src{font-family:var(--mono);font-size:11px;color:var(--muted)}
.redacted{color:var(--deny);font-style:italic}
.kv{display:flex;justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px solid var(--line);font-size:13px}.kv:last-child{border-bottom:none}
.kv .k{color:var(--muted)}.kv .v{font-family:var(--mono);font-size:12px;text-align:right}
.chip{display:inline-block;font-size:11px;background:var(--brand-soft);color:var(--brand);border:1px solid #f6cdd6;border-radius:999px;padding:2px 8px;margin:2px 3px 0 0;font-family:var(--mono)}
.chatbox{display:flex;gap:8px;margin-top:12px}.chatbox input{flex:1}.scroll{max-height:430px;overflow:auto}
.statgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}@media(max-width:700px){.statgrid{grid-template-columns:1fr 1fr}}
.stat{background:var(--panel-2);border:1px solid var(--line);border-radius:8px;padding:12px}
.stat .n{font-size:22px;font-weight:700}.stat .l{font-size:11px;color:var(--muted);font-family:var(--mono);text-transform:uppercase;letter-spacing:.06em}
"""

NAV = [("/", "◎", "Tổng quan", False), ("SEP", "", "Làm việc", False),
       ("/chat", "❯", "Trợ lý (Chat)", False), ("/conversations", "≣", "Hội thoại của tôi", False),
       ("/graph", "⧉", "Đồ thị tri thức", False), ("/workspace", "⬆", "Tải lên & thư mục", False),
       ("/tasks", "⚙", "Tác vụ", False),
       ("SEP", "", "Dự án (PM · v5.62)", False),
       ("/pm/projects", "▣", "Dự án", False), ("/pm/board", "▦", "Bảng công việc", False),
       ("/pm/inbox", "✉", "Hộp thư", False),
       ("SEP", "", "Quản trị / Dữ liệu", False),
       ("/pdp", "⊻", "Kiểm tra quyền (PDP)", False), ("/resources", "▤", "Tài nguyên", False),
       ("/users", "👤", "Quản trị tài khoản", True),
       ("/data", "▦", "Dữ liệu (xem bảng)", True), ("/ingest", "⇪", "Nạp tài liệu", True),
       ("/audit", "⛓", "Nhật ký (audit)", False)]
TITLES = {p: t for p, _, t, _ in NAV if p != "SEP"}
TITLES.update({"/pm/project": "Dự án", "/pm/task": "Chi tiết task",
               "/pm/progress": "Tiến độ", "/pm/connectors": "Connector"})

def trace_html(steps):
    rows = "".join(
        f'<div class="row {s["status"]}"><span class="l2 {s["status"]}"></span>'
        f'<span class="rule">{esc(s["rule"])}</span><span class="det">{esc(s["detail"])}</span></div>'
        for s in steps)
    return f'<div class="trace">{rows}</div>'

def shell(me, active, title, body, chain_ok=True, chain_n=0, conv_cls=None):
    nav = ""
    for p, ic, t, admin in NAV:
        if p == "SEP":
            nav += f'<div class="sep">{t}</div>'; continue
        if admin and me["role"] != "ADMIN": continue
        cls = "active" if p == active else ""
        nav += f'<a class="{cls}" href="{p}"><span>{ic}</span><span>{t}</span></a>'
    convpill = (f'<span class="pill"><span class="lab">Hội thoại</span>{CL(conv_cls)}</span>' if conv_cls else "")
    chainpill = (f'<span class="pill"><span class="lamp {"" if chain_ok else "bad"}"></span>'
                 f'<span class="lab">Chuỗi audit</span>{"OK" if chain_ok else "ĐỨT"} ({chain_n})</span>')
    return f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} · KMS {VER}</title>
<style>{CSS}</style></head><body><div class="shell">
<aside class="sidebar"><div class="sb-brand"><span class="dot"></span><b>VSI · KMS</b><span class="ver">{VER}</span></div>
<div class="who"><div class="nm">{esc(me['user_id'])}</div><div class="rl">{esc(me['role'])} · {esc(me['department'])} {CL(me['clearance'])}</div></div>
<nav class="nav">{nav}</nav>
<div class="sb-foot">stdlib · SQLite · fail-closed · write-PEP<br>data/ chứa toàn bộ dữ liệu runtime</div></aside>
<header class="topbar"><span class="title">{esc(title)}</span><span class="spacer"></span>{convpill}{chainpill}
<a class="btn ghost sm" href="/logout">Đăng xuất</a></header>
<main class="main"><div class="wrap">{body}</div></main></div></body></html>"""

def login_page(err=""):
    accts = "".join(f'<span class="tag" style="cursor:pointer" onclick="document.getElementById(\'u\').value=\'{u}\';document.getElementById(\'p\').value=\'{u}\'">{u}</span>' for u in ["admin1","eng_pd1","lead_dv","pm1","hr1"])
    return f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Đăng nhập · KMS {VER}</title><style>{CSS}
body{{display:flex;align-items:center;justify-content:center;min-height:100vh;background:radial-gradient(1000px 600px at 70% -10%,#1b2942,transparent 60%),var(--ink)}}
.lc{{width:380px;max-width:92vw;background:#fff;border-radius:16px;box-shadow:0 30px 80px -30px rgba(0,0,0,.6);overflow:hidden}}
.lt{{padding:24px 26px;border-bottom:1px solid var(--line)}}.lb{{padding:22px 26px}}</style></head><body>
<form class="lc" method="post" action="/login"><div class="lt"><div style="display:flex;align-items:center;gap:10px">
<span style="width:22px;height:22px;border-radius:6px;background:var(--brand)"></span><b>VSI · KMS</b>
<span style="margin-left:auto;font-family:var(--mono);font-size:11px;color:var(--muted)">{VER}</span></div>
<p style="margin:12px 0 0;color:var(--muted);font-size:13px">Cổng tri thức an toàn — backend thật</p></div>
<div class="lb"><div class="field"><label>Tên đăng nhập</label><input id="u" name="user_id" autocomplete="off"></div>
<div class="field"><label>Mật khẩu</label><input id="p" name="password" type="password" autocomplete="off"></div>
<button class="btn primary full">Đăng nhập</button>
<div style="color:var(--deny);font-size:12px;margin-top:8px;min-height:16px">{esc(err)}</div>
<div class="note" style="margin-top:14px">Demo (mật khẩu = tên đăng nhập): {accts}</div></div></form></body></html>"""
