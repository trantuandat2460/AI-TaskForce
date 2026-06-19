"""Định tuyến + handler trang (control-plane RBAC §21) và PIPELINE mỗi lượt chat.
Trả ('html',body) | ('redirect',loc) | ('raw',ctype,bytes)."""
import json, urllib.parse
from config import settings
from config.settings import CLASS_RANK
from kms_app import db
from kms_app.security import pdp, pep, audit, accounts
from kms_app.security.pdp import authorize
from kms_app.conversation import store as cstore, state as cstate, rewrite as crewrite
from kms_app.retrieval import search
from kms_app.ingestion import workspace as ws
from kms_app.graph import concept as cgraph
from kms_app.llm import client as llm
from kms_app.orchestrator import registry as oreg, tasks as otasks
from kms_app.web import render
from kms_app.web.render import esc, CL, trace_html

def _lane_of(subject):
    """Lane truy vấn xuất phát: kỹ sư C3 làm việc TRONG enclave (reach corpus C3);
    người ≤C2 ở lane SECURED (corpus C3 không với tới được — air-gap, S3)."""
    return "C3_ENCLAVE" if subject["clearance"] == "C3" else "SECURED"

_TAMPER_ORIG = {}   # demo: lưu giá trị gốc khi 'giả mạo' audit để có thể khôi phục

# ---------------- PIPELINE MỖI LƯỢT (proxy bộ não) ----------------
def run_turn(conn, me, conv_id, text):
    trace = []
    st = cstate.get(conn, conv_id)
    trace.append({"rule": "① load_state", "status": "pass", "detail": "active_topic = " + (st["active_topic"] or "∅")})

    rw = crewrite.rewrite(text, st)
    trace.append({"rule": "② query_rewrite",
                  "status": "allow" if rw["changed"] else "skip",
                  "detail": (f'“{rw["original"]}” → “{rw["rewritten"]}”' if rw["changed"] else rw["reason"])})
    q = rw["rewritten"]

    my_lane = _lane_of(me)
    # Chỉ concept ACTIVE mới vào tập ứng viên (quarantine không bao giờ tới LLM).
    all_docs = [db.doc_to_resource(r) for r in
                conn.execute("SELECT * FROM documents WHERE status='active'").fetchall()]
    # ===== Lớp 1 · ACCESS FILTER (PEP-1: permission_group + corpus/lane reachable) =====
    p1 = pep.pep1_filter_docs(me, all_docs, from_lane=my_lane)
    trace.append({"rule": "①L ACCESS FILTER", "status": "pass",
                  "detail": f"PEP-1 (group MatchAny + corpus reachable @{my_lane}) → {len(p1)}/{len(all_docs)} doc"})

    # ===== Lớp 2–4 · FACET NARROW → RANK(RRF) → RERANK =====
    allowed_ids = [d["resource_id"] for d in p1]
    chunks, ftrace = search.retrieve(conn, q, allowed_ids, top_k=settings.RETRIEVAL_TOPK)
    sym = {"FACET NARROW": "②L", "RANK": "③L", "RERANK": "④L"}
    for layer, status, detail in ftrace:
        trace.append({"rule": f"{sym.get(layer,'')} {layer}", "status": status, "detail": detail})

    docmap = {d["resource_id"]: d for d in all_docs}
    allowed_chunks, seen = [], set()
    for ch in chunks:
        res = docmap.get(ch["doc_id"])
        if not res: continue
        d = authorize(me, res)
        if d.allow:
            if ch["doc_id"] not in seen:
                seen.add(ch["doc_id"])
                allowed_chunks.append({"doc_id": ch["doc_id"], "chunk_id": ch["chunk_id"], "text": ch["text"],
                                       "title": res["title"], "data_class": res["data_class"],
                                       "sensitive_level": res["sensitive_level"]})

    # ===== Lớp 5 · GRAPH EXPAND (theo concept_links, VẪN qua PEP) =====
    expanded = 0
    for base_id in list(seen):
        for nb in cgraph.related(conn, me, base_id, hops=settings.GRAPH_EXPAND_HOPS, my_lane=my_lane):
            if nb["doc_id"] in seen or expanded >= 2:
                continue
            crow = conn.execute("SELECT * FROM chunks WHERE doc_id=? ORDER BY chunk_index LIMIT 1", (nb["doc_id"],)).fetchone()
            if not crow:
                continue
            seen.add(nb["doc_id"]); expanded += 1
            res = docmap.get(nb["doc_id"]) or {}
            allowed_chunks.append({"doc_id": nb["doc_id"], "chunk_id": crow["chunk_id"], "text": crow["text"],
                                   "title": nb["title"], "data_class": nb["data_class"],
                                   "sensitive_level": res.get("sensitive_level", "confidential")})
    trace.append({"rule": "⑤L GRAPH EXPAND", "status": "pass" if expanded else "skip",
                  "detail": f"+{expanded} concept liên quan qua PEP" if expanded else "không mở rộng (hoặc đích ngoài quyền → drop sạch)"})

    # ===== PEP-2 recheck per-resource đã chạy ở trên; tổng kết =====
    trace.append({"rule": "PEP-2 recheck", "status": "allow" if allowed_chunks else "deny",
                  "detail": f"giữ {len(allowed_chunks)} chunk được cấp phép (per-resource)"})

    mdc = pep.max_class([{"data_class": c["data_class"]} for c in allowed_chunks]) if allowed_chunks else "C1"
    trace.append({"rule": "⑥ max_data_class", "status": "allow" if allowed_chunks else "deny",
                  "detail": "highest-wins = " + mdc})

    intent = oreg.classify_intent(text)
    trace.append({"rule": "⑦ orchestrator", "status": "pass",
                  "detail": f"intent = {intent or 'QA'}" + ("" if allowed_chunks else " (fail-closed, P5)")})

    lane = "C3_AIRGAP" if mdc == "C3" else "C1C2_INTERNAL"
    answer, refused = llm.synthesize(q, allowed_chunks, lane=lane)

    cites = [{"doc_id": c["doc_id"], "chunk_id": c["chunk_id"],
              "sensitive_level": c["sensitive_level"], "data_class": c["data_class"]} for c in allowed_chunks]
    cstore.add_message(conn, conv_id, "user", text, rewritten=(rw["rewritten"] if rw["changed"] else None))
    cstore.add_message(conn, conv_id, "bot", answer, refused=int(refused), cites=cites)
    cstore.bump_class(conn, conv_id, mdc)
    cstate.update(conn, conv_id, text, allowed_chunks)
    audit.append(conn, on_behalf_of_user=me["user_id"], action="rag_query",
                 resource_ref=",".join(c["doc_id"] for c in allowed_chunks) or "(none)",
                 authz_reason="ALLOW" if allowed_chunks else "DENY_NO_GROUNDED",
                 max_data_class_accessed=mdc, lane=lane, model_id="stub-llm")
    trace.append({"rule": "⑧ persist+audit", "status": "pass",
                  "detail": "message+citations · update state · hash-chain"})
    return trace

# ---------------- helpers ----------------
def _chain(conn):
    v = audit.verify(conn)
    return v["ok"], v["total"]

def _conv_messages_html(conn, me, conv_id):
    out = []
    for m in cstore.messages(conn, conv_id):
        if m["role"] == "user":
            rw = f'<div class="meta" style="margin-top:6px">↳ rewrite: {esc(m["rewritten"])}</div>' if m["rewritten"] else ""
            out.append(f'<div class="msg user"><div class="meta">{esc(m["created_at"])}</div>{esc(m["content"])}{rw}</div>')
        else:
            cites = ""
            for c in cstore.citations(conn, m["msg_id"]):
                row = conn.execute("SELECT * FROM documents WHERE doc_id=?", (c["doc_id"],)).fetchone()
                d = authorize(me, db.doc_to_resource(row)) if row else pdp.Decision(allow=False, reason="DENY")
                title = (row["source_file"].split("/")[-1] if row else c["doc_id"])
                if d.allow:
                    cites += f'<div class="cite">{CL(c["data_class"])}<span>{esc(title)}</span><span class="src">{esc(c["doc_id"])}</span></div>'
                else:
                    cites += f'<div class="cite">{CL(c["data_class"])}<span class="redacted">[đã ẩn theo quyền hiện tại — {esc(d.reason)}]</span><span class="src">{esc(c["doc_id"])}</span></div>'
            refused = ' · <span style="color:var(--deny)">fail-closed</span>' if m["refused"] else ""
            cite_block = f'<div class="cites">{cites}</div>' if cites else ""
            out.append(f'<div class="msg bot"><div class="meta">trợ lý · {esc(m["created_at"])}{refused}</div>{esc(m["content"])}{cite_block}</div>')
    return "".join(out) or '<div class="muted small">Chưa có tin nhắn.</div>'

# ---------------- PAGE HANDLERS ----------------
def page_overview(conn, me):
    is_admin = me["role"] == "ADMIN"
    nres = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    nchunk = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    nconv = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    nlog = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
    body = f"""<div class="page-head"><div class="eyebrow">Backend thật · stdlib · v5.6</div>
<h2>Tổng quan</h2><p>Backend chạy local, dữ liệu bền vững trong <span class="mono">data/</span> (SQLite + thư mục documents OKF). v5.6: named-corpus + lane (S3), phễu truy xuất 5 lớp + RRF (S6), concept graph (S7), scanner credential/NER ở ingest. Mở <span class="mono">data/kms.db</span> bằng trình xem SQLite, hoặc vào <a href="/data">Dữ liệu (xem bảng)</a> để thấy mọi bản ghi khi nhập.</p></div>
<div class="card"><div class="bd"><div class="statgrid">
<div class="stat"><div class="n">{nres}</div><div class="l">documents</div></div>
<div class="stat"><div class="n">{nchunk}</div><div class="l">chunks</div></div>
<div class="stat"><div class="n">{nconv}</div><div class="l">conversations</div></div>
<div class="stat"><div class="n">{nlog}</div><div class="l">audit logs</div></div>
</div></div></div>
<div class="grid g2"><div class="card"><div class="hd"><h3>Bạn đang là</h3></div><div class="bd">
<div class="kv"><span class="k">Principal</span><span class="v">{esc(me['user_id'])}</span></div>
<div class="kv"><span class="k">Vai trò / Phòng</span><span class="v">{esc(me['role'])} · {esc(me['department'])}</span></div>
<div class="kv"><span class="k">Clearance</span><span class="v">{CL(me['clearance'])}</span></div>
<div class="kv"><span class="k">Tags (ABAC)</span><span class="v">{''.join(f'<span class=tag>{esc(t)}</span>' for t in sorted(me['tags'])) or '—'}</span></div>
<div class="kv"><span class="k">Groups</span><span class="v">{''.join(f'<span class=tag>{esc(t)}</span>' for t in sorted(me['groups']))}</span></div>
<div class="kv"><span class="k">Dự án</span><span class="v">{', '.join(sorted(me['projects'])) or '—'}</span></div>
</div></div>
<div class="card"><div class="hd"><h3>Kịch bản nên thử</h3></div><div class="bd">
<ol style="margin:0;padding-left:18px;line-height:1.9" class="small">
<li>Vào <a href="/chat">Trợ lý</a> (eng_pd1) hỏi <i>“Mô hình phân quyền DCM hoạt động thế nào?”</i> → badge Hội thoại leo lên C3.</li>
<li>Hỏi <i>“Kiến trúc systolic array của Gemmini?”</i> rồi <i>“còn ISA của nó thì sao?”</i> → xem query rewrite.</li>
<li>Đăng nhập <span class="mono">pm1</span>, hỏi câu DCM → PEP-1 + PEP-2 chặn → fail-closed.</li>
<li>Vào <a href="/data">Dữ liệu</a> sau khi chat → thấy messages/citations/state mới.</li>
<li>Vào <a href="/audit">Nhật ký</a> → bấm Verify; (admin) Giả mạo một dòng → chuỗi ĐỨT.</li>
</ol></div></div></div>"""
    return body

def page_chat(conn, me, conv_id, trace_steps=None):
    if not conv_id:
        rows = cstore.list_for(conn, me["user_id"], me["role"] == "ADMIN")
        conv_id = rows[0]["conv_id"] if rows else cstore.create(conn, me["user_id"])
    conv = cstore.get(conn, conv_id)
    st = cstate.get(conn, conv_id)
    msgs = _conv_messages_html(conn, me, conv_id)
    state_html = (f'<div class="kv"><span class="k">active_topic</span><span class="v">{esc(st["active_topic"] or "—")}</span></div>'
                  f'<div class="kv"><span class="k">salient_entities</span><span class="v">{"".join(f"<span class=tag>{esc(e)}</span>" for e in st["salient_entities"]) or "—"}</span></div>'
                  f'<div class="kv"><span class="k">last_referents</span><span class="v">{", ".join(st["last_referents"]) or "—"}</span></div>'
                  f'<div class="kv"><span class="k">rolling_summary</span><span class="v" style="white-space:normal;max-width:200px;text-align:right">{esc(st["rolling_summary"] or "—")}</span></div>')
    trace_box = trace_html(trace_steps) if trace_steps else '<div class="muted small">Gửi câu hỏi để xem pipeline 8 bước.</div>'
    body = f"""<div class="page-head"><div class="eyebrow">Pipeline mỗi lượt · bộ não = Proxy</div>
<h2>Trợ lý — RAG có kiểm soát truy cập</h2><p>load_state → query rewrite → PEP-1 → retrieve → PEP-2 recheck → max_data_class → orchestrator → persist+audit. Mọi bản ghi ghi xuống <span class="mono">data/kms.db</span>.</p></div>
<div class="grid gchat"><div class="card"><div class="hd"><h3>Hội thoại <span class="badge">{esc(conv_id)}</span></h3><span class="spacer"></span>{CL(conv['max_data_class'])}
<a class="btn ghost sm" href="/chat?new=1">+ Mới</a></div><div class="bd">
<div class="scroll" id="sc">{msgs}</div>
<form class="chatbox" method="post" action="/chat"><input type="hidden" name="conv_id" value="{esc(conv_id)}">
<input name="text" placeholder="vd: Mô hình phân quyền DCM hoạt động thế nào?" autofocus autocomplete="off">
<button class="btn primary">Gửi</button></form>
<div class="note" style="margin-top:10px">Gợi ý nhanh:
<a href="/chat?conv_id={conv_id}&amp;q=Mô+hình+phân+quyền+DCM+của+KMS+hoạt+động+thế+nào%3F">DCM</a> ·
<a href="/chat?conv_id={conv_id}&amp;q=Kiến+trúc+systolic+array+của+Gemmini%3F">Gemmini</a> ·
<a href="/chat?conv_id={conv_id}&amp;q=còn+ISA+của+nó+thì+sao%3F">“còn nó…”</a> ·
<a href="/chat?conv_id={conv_id}&amp;q=Cho+tôi+xem+báo+cáo+tuần+WS4">Báo cáo tuần</a></div>
</div></div>
<div><div class="card"><div class="hd"><h3>Decision trace</h3></div><div class="bd">{trace_box}</div></div>
<div class="card"><div class="hd"><h3>Session state <span class="badge">A12·P30</span></h3></div><div class="bd">{state_html}</div></div></div></div>
<script>var s=document.getElementById('sc');if(s)s.scrollTop=s.scrollHeight;</script>"""
    return body, conv

def page_conversations(conn, me, open_id=None):
    is_admin = me["role"] == "ADMIN"
    rows = cstore.list_for(conn, me["user_id"], is_admin)
    table = "".join(
        f'<tr><td class="t-id">{r["conv_id"]}</td><td>{esc(r["title"])}</td><td class="t-id">{r["owner_user"]}</td>'
        f'<td>{CL(r["max_data_class"])}</td>'
        f'<td><a class="btn ghost sm" href="/conversations?open={r["conv_id"]}">Mở lại</a></td></tr>'
        for r in rows) or '<tr><td colspan=5 class="muted small" style="padding:16px">Chưa có hội thoại — hãy chat trước.</td></tr>'
    replay = '<div class="muted small">Chọn một hội thoại để xem lại.</div>'
    if open_id:
        conv = cstore.get(conn, open_id)
        if conv and (is_admin or conv["owner_user"] == me["user_id"]):
            replay = (f'<div class="small muted" style="margin-bottom:8px">{open_id} · mức {CL(conv["max_data_class"])} · '
                      f'tái cấp quyền theo clearance hiện tại ({me["clearance"]})</div>'
                      f'<div class="scroll">{_conv_messages_html(conn, me, open_id)}</div>')
        else:
            replay = '<div class="note">403 — không phải hội thoại của bạn (owner-scope).</div>'
    body = f"""<div class="page-head"><div class="eyebrow">A11·P29 · sovereign transcript</div>
<h2>Hội thoại của tôi</h2><p>Mỗi hội thoại kế thừa <span class="mono">max_data_class</span>; khi mở lại, từng trích dẫn được <b>authorize() lại</b> theo quyền hiện tại — hạ quyền ⇒ trích dẫn C3 bị ẩn.</p></div>
<div class="grid g2"><div class="card"><div class="hd"><h3>Danh sách {'(toàn cục)' if is_admin else '(của tôi)'}</h3></div>
<div class="bd" style="padding:0"><table><thead><tr><th>ID</th><th>Tiêu đề</th><th>Chủ</th><th>Mức</th><th></th></tr></thead><tbody>{table}</tbody></table></div></div>
<div class="card"><div class="hd"><h3>Xem lại (replay)</h3></div><div class="bd">{replay}</div></div></div>"""
    return body

def page_pdp(conn, me, form=None):
    is_admin = me["role"] == "ADMIN"
    users = [r["user_id"] for r in conn.execute("SELECT user_id FROM users ORDER BY user_id").fetchall()] if is_admin else [me["user_id"]]
    docs = conn.execute("SELECT doc_id, source_file, data_class FROM documents ORDER BY doc_id").fetchall()
    result = '<div class="muted small">Chạy để xem kết quả.</div>'
    verdict = ""
    if form:
        srow = conn.execute("SELECT * FROM users WHERE user_id=?", (form.get("subject", [me["user_id"]])[0],)).fetchone()
        drow = conn.execute("SELECT * FROM documents WHERE doc_id=?", (form.get("resource", [""])[0],)).fetchone()
        if srow and drow:
            subj = db.row_to_subject(srow); res = db.doc_to_resource(drow)
            if not is_admin and subj["user_id"] != me["user_id"]:
                subj = me  # user thường khoá vào self
            limit = (form.get("limit", [""])[0] or None)
            d = authorize(subj, res, {"requested_limit": limit})
            verdict = f'<span class="verdict {"allow" if d.allow else "deny"}">{d.reason}</span>'
            result = trace_html(d["steps"])
            audit.append(conn, on_behalf_of_user=me["user_id"], action="pdp_check",
                         resource_ref=res["resource_id"], authz_reason=d.reason,
                         max_data_class_accessed=d["effective"] if d.allow else None)
    opt_u = "".join(f'<option value="{u}">{u}</option>' for u in users)
    opt_r = "".join(f'<option value="{r["doc_id"]}">{r["doc_id"]} · {esc(r["source_file"].split("/")[-1])} ({r["data_class"]})</option>' for r in docs)
    body = f"""<div class="page-head"><div class="eyebrow">Data-plane · authorize() 8 bước</div>
<h2>Kiểm tra quyền (PDP)</h2><p>{'Admin mô phỏng mọi chủ thể.' if is_admin else 'Bạn chỉ mô phỏng chính mình (user thường khoá self).'}</p></div>
<div class="grid gchat"><div class="card"><div class="hd"><h3>Yêu cầu</h3></div><div class="bd">
<form method="post" action="/pdp">
<div class="field"><label>Chủ thể</label><select name="subject">{opt_u}</select></div>
<div class="field"><label>Tài nguyên</label><select name="resource">{opt_r}</select></div>
<div class="field"><label>requested_limit (E7)</label><select name="limit"><option value="">= clearance</option><option>C1</option><option>C2</option><option>C3</option></select></div>
<button class="btn primary full">Chạy authorize()</button></form>
<div class="note" style="margin-top:12px">Thử để thấy đủ 6 lý do DENY: pm1×R002(DCM) · eng_pd1×R012(ABAC) · eng_pd1×R014(PROJECT) · lead_dv×R007(DEPARTMENT) · eng_pd1×R009(REBAC) · pm1×R013(ROLE) · any×R010(CREDENTIAL).</div>
</div></div>
<div class="card"><div class="hd"><h3>Decision trace</h3><span class="spacer"></span>{verdict}</div><div class="bd">{result}</div></div></div>"""
    return body

def page_resources(conn, me):
    is_admin = me["role"] == "ADMIN"
    rows = conn.execute("SELECT * FROM documents ORDER BY doc_id").fetchall()
    visible = []
    for r in rows:
        res = db.doc_to_resource(r)
        if is_admin or authorize(me, res).allow:
            visible.append((r, res))
    def _status_badge(r):
        if r["status"] == "quarantined":
            return f'<span class="verdict deny" title="{esc(r["quarantine_reason"] or "")}">quarantine</span>'
        return '<span class="verdict allow">active</span>'
    trs = "".join(
        f'<tr><td class="t-id">{r["doc_id"]}{" 🔒" if r["is_credential"] else ""}</td>'
        f'<td>{esc(r["source_file"].split("/")[-1])}{(" <span class=tag>PII·"+(r["subject_person"] or "?")+"</span>") if r["is_personnel_report"] else ""}</td>'
        f'<td>{esc(r["kind"])}</td><td>{CL(r["data_class"])}</td>'
        f'<td><span class=badge>{esc(r["corpus_id"] or "—")}</span></td>'
        f'<td class="small muted">{esc(r["owner_project"] or "—")}{(" / "+r["owner_dept"]) if r["owner_dept"] else ""}</td>'
        f'<td><span class=badge>{esc(r["permission_group"])}</span></td>'
        f'<td>{_status_badge(r)}</td></tr>'
        for r, _ in visible)
    note = "" if is_admin else '<div class="note" style="margin-top:14px">Danh sách chỉ dựng từ tập authorize() cho phép — không lộ artifact ngoài phạm vi (chống liệt kê).</div>'
    body = f"""<div class="page-head"><div class="eyebrow">Tầng Source/Ledger · A10 · OKF concept</div>
<h2>Tài nguyên {'(tất cả)' if is_admin else '(chỉ những gì bạn được phép)'}</h2>
<p>Mỗi concept gắn một <span class="mono">corpus</span> (ranh giới phân loại + lane). Concept <b>quarantine</b> không index, không tới LLM — chờ Data Steward.</p></div>
<div class="card"><div class="bd" style="padding:0"><table><thead><tr><th>ID</th><th>Tiêu đề</th><th>Loại</th><th>Mức</th><th>corpus</th><th>Dự án/Phòng</th><th>perm_group</th><th>status</th></tr></thead>
<tbody>{trs}</tbody></table></div></div>{note}"""
    return body

def page_graph(conn, me, focus=None):
    """Concept graph (S7): related + impact, mọi traversal qua PEP."""
    is_admin = me["role"] == "ADMIN"
    my_lane = _lane_of(me)
    # chỉ liệt kê concept mà người dùng đọc được (chống liệt kê tên concept ngoài quyền)
    opts = []
    for r in conn.execute("SELECT * FROM documents WHERE status='active' ORDER BY doc_id").fetchall():
        res = db.doc_to_resource(r)
        if is_admin or (pep.corpus_reachable(res.get("corpus_id"), my_lane, me["clearance"]) and authorize(me, res).allow):
            opts.append(r)
    opt_html = "".join(f'<option value="{r["doc_id"]}"{" selected" if r["doc_id"]==focus else ""}>{r["doc_id"]} · {esc(r["title"][:40])}</option>' for r in opts)
    panel = '<div class="muted small">Chọn một concept để xem liên quan / phân tích tác động.</div>'
    if focus:
        rel = cgraph.related(conn, me, focus, hops=2, my_lane=my_lane)
        imp = cgraph.impact(conn, me, focus, hops=2, my_lane=my_lane)
        def _list(items, empty):
            if not items: return f'<div class="muted small">{empty}</div>'
            return "".join(f'<div class="cite">{CL(i["data_class"])}<span>{esc(i["title"][:46])}</span>'
                           f'<span class="src">{esc(i["doc_id"])} · {i["hop"]}-hop · {esc(i["corpus_id"] or "")}</span></div>' for i in items)
        panel = (f'<div class="card"><div class="hd"><h3>Related — “{esc(focus)}” liên quan tới</h3></div>'
                 f'<div class="bd">{_list(rel, "Không có concept liên quan (hoặc đích ngoài quyền → drop sạch).")}</div></div>'
                 f'<div class="card"><div class="hd"><h3>Impact — đổi “{esc(focus)}” ảnh hưởng tới</h3></div>'
                 f'<div class="bd">{_list(imp, "Không concept nào trỏ tới (hoặc ngoài quyền).")}</div></div>')
        audit.append(conn, on_behalf_of_user=me["user_id"], action="graph_query",
                     resource_ref=focus, authz_reason="ALLOW", lane=my_lane)
    body = f"""<div class="page-head"><div class="eyebrow">S7 · concept graph · 1–2 hop qua PEP</div>
<h2>Đồ thị tri thức & phân tích tác động</h2><p>Cạnh tới concept bạn không đọc được bị <b>drop hoàn toàn</b> — không tên, không số đếm. Đồ thị không phải cửa hậu.</p></div>
<div class="grid gchat"><div class="card"><div class="hd"><h3>Chọn concept</h3></div><div class="bd">
<form method="get" action="/graph"><div class="field"><label>Concept (chỉ những gì bạn đọc được)</label>
<select name="focus" onchange="this.form.submit()">{opt_html or '<option>—</option>'}</select></div>
<button class="btn primary full">Truy vấn đồ thị</button></form>
<div class="note" style="margin-top:12px">related = đi xuôi cạnh; impact = đảo chiều (đổi một concept thì vỡ những đâu).</div>
</div></div><div>{panel}</div></div>"""
    return body

def page_data(conn, me):
    if me["role"] != "ADMIN":
        return '<div class="note">403 — trang chỉ dành cho admin.</div>'
    def tbl(sql, cols, label, limit=8):
        rows = conn.execute(sql).fetchall()
        head = "".join(f"<th>{c}</th>" for c in cols)
        body = "".join("<tr>" + "".join(f'<td class="small">{esc(r[c])[:60]}</td>' for c in cols) + "</tr>" for r in rows[:limit])
        more = f'<div class="muted small" style="padding:8px 10px">… tổng {len(rows)} dòng</div>' if len(rows) > limit else ""
        return f'<div class="card"><div class="hd"><h3>{label} <span class="badge">{len(rows)}</span></h3></div><div class="bd" style="padding:0"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{more}</div></div>'
    body = '<div class="page-head"><div class="eyebrow">A10 · bền vững · nhìn thấy dữ liệu khi nhập</div><h2>Dữ liệu (xem bảng)</h2><p>Mọi bản ghi trong <span class="mono">data/kms.db</span>. Chat / chạy PDP / ingest rồi quay lại đây để thấy dữ liệu mới. (Cũng mở được file bằng trình xem SQLite.)</p></div>'
    body += tbl("SELECT * FROM documents ORDER BY doc_id", ["doc_id","data_class","kind","owner_project","permission_group"], "documents")
    body += tbl("SELECT * FROM chunks ORDER BY doc_id", ["chunk_id","doc_id","chunk_level","heading_path"], "chunks")
    body += tbl("SELECT * FROM conversations ORDER BY conv_id DESC", ["conv_id","owner_user","title","max_data_class","retain_until"], "conversations")
    body += tbl("SELECT * FROM messages ORDER BY msg_id DESC", ["msg_id","role","content","rewritten","refused"], "messages")
    body += tbl("SELECT * FROM message_citations ORDER BY id DESC", ["msg_id","doc_id","data_class","sensitive_level"], "message_citations")
    body += tbl("SELECT * FROM conversation_state", ["conv_id","active_topic","salient_entities_json","rolling_summary"], "conversation_state")
    body += tbl("SELECT * FROM audit_logs ORDER BY log_id DESC", ["log_id","on_behalf_of_user","action","authz_reason","max_data_class_accessed"], "audit_logs")
    return body

def page_tasks(conn, me, run=False):
    c = oreg.REGISTRY["review_weekly_report"]
    def rowc(k, arr): return f'<div class="kv"><span class="k">{k}</span><span class="v" style="max-width:62%;white-space:normal;text-align:right">{"".join(f"<span class=chip>{esc(x)}</span>" for x in arr)}</span></div>'
    contract = rowc("intent", c["intent"]) + rowc("inputs", c["inputs"]) + rowc("sources(+quyền)", c["sources"]) + rowc("steps", c["steps"]) + rowc("criteria", c["criteria"]) + rowc("output_schema", c["output_schema"])
    out = '<div class="muted small">Bấm Run để thực thi pipeline tất định trên báo cáo tuần.</div>'
    if run:
        res = otasks.run_review_weekly_report(conn, me)
        if not res["ok"]:
            out = f'<div class="note">Không đủ quyền nguồn: <span class="mono">{esc(res["reason"])}</span>. Tác vụ dừng (fail-closed).</div>'
        else:
            steps = "".join(f'<div class="kv"><span class="k">{i+1}. {esc(s)}</span><span class="v"><span class="verdict allow">ok</span></span></div>' for i, s in enumerate(res["steps"]))
            tbl = "".join(f'<tr><td class="t-id" style="width:150px">{k}</td><td class="small">{esc(res["result"][k])}</td></tr>' for k in c["output_schema"])
            out = (f'<div class="small muted" style="margin-bottom:6px">Pipeline (contract v{c["version"]}, T thấp):</div>{steps}'
                   f'<div class="note" style="margin:10px 0">Output validate theo schema: <span class="verdict {"allow" if res["schema_ok"] else "deny"}">{"PASS" if res["schema_ok"] else "FAIL"}</span> · ghi task_contract_version={c["version"]} vào audit</div>'
                   f'<table><tbody>{tbl}</tbody></table>')
            audit.append(conn, on_behalf_of_user=me["user_id"], agent_id="agent:report_reviewer",
                         action="task:review_weekly_report", resource_ref=res["resource"]["resource_id"],
                         authz_reason="ALLOW", max_data_class_accessed=res["resource"]["data_class"],
                         task_contract_version=str(c["version"]))
    body = f"""<div class="page-head"><div class="eyebrow">A16·P34 · năng lực là hợp đồng</div>
<h2>Orchestrator tất định + Task Registry</h2><p>LLM chỉ làm intent→chọn task; phần còn lại là pipeline khai báo, output kiểm theo schema. Run 2 lần ⇒ cùng dạng (tái lập).</p></div>
<div class="grid g2"><div class="card"><div class="hd"><h3>Task contract · <span class="mono">{c["task"]}</span> <span class="badge">v{c["version"]}</span></h3></div><div class="bd">{contract}</div></div>
<div class="card"><div class="hd"><h3>Chạy tác vụ</h3><span class="spacer"></span><a class="btn primary sm" href="/tasks?run=1">▶ Run</a><a class="btn ghost sm" href="/tasks?run=1">▶ Run lại</a></div><div class="bd">{out}</div></div></div>"""
    return body

def page_ingest(conn, me, did_reingest=False):
    if me["role"] != "ADMIN":
        return '<div class="note">403 — trang chỉ dành cho admin.</div>'
    from config import settings
    files = sorted(str(p.relative_to(settings.BASE_DIR)) for p in settings.DOCUMENTS_DIR.rglob("*.md"))
    flist = "".join(f'<tr><td class="t-id small">{esc(f)}</td></tr>' for f in files)
    report_html = ""
    if did_reingest:
        from kms_app.ingestion import store as istore
        rep = istore.ingest_all(conn)
        report_html = (f'<div class="note" style="margin-bottom:14px">Ingest xong: '
                       f'new={rep["new"]} · changed={rep["changed"]} · perm_changed={rep["perm_changed"]} · unchanged={rep["unchanged"]} · '
                       f'chunks={rep["chunks"]} · <b>quarantined={rep["quarantined"]}</b> · concept_links={rep["links"]}. '
                       f'Vào <a href="/data">Dữ liệu</a> để thấy chunks; <a href="/graph">Đồ thị</a> để xem cạnh.</div>')
    body = f"""<div class="page-head"><div class="eyebrow">A15+A14 · docling + hierarchical chunking</div>
<h2>Nạp tài liệu</h2><p>Đặt file <span class="mono">.md</span> (có front-matter khai báo phân loại) vào <span class="mono">data/documents/&lt;public|internal|confidential&gt;/</span>, rồi bấm Reingest. Pipeline: docling(→md) → chunk theo cấu trúc (parent–child) → upsert; idempotent qua fingerprint.</p></div>
{report_html}
<div class="grid g2"><div class="card"><div class="hd"><h3>Tài liệu trong kho</h3></div><div class="bd" style="padding:0"><table><thead><tr><th>source_file</th></tr></thead><tbody>{flist}</tbody></table></div></div>
<div class="card"><div class="hd"><h3>Chạy ingest</h3></div><div class="bd">
<form method="post" action="/ingest"><button class="btn primary full">⇪ Reingest toàn bộ</button></form>
<div class="note" style="margin-top:12px">Phân loại nguồn giữ nguyên qua docling (no silent downgrade, P16); docling chạy offline trong lane (A15/P33). Đây là chỗ cắm docling thật cho PDF (xem <span class="mono">ingestion/store.py</span>).</div>
</div></div></div>"""
    return body

def page_audit(conn, me, action=None, log_id=None):
    is_admin = me["role"] == "ADMIN"
    if action == "export" and is_admin:
        path = audit.export_csv(conn)
        return ("raw", "text/csv; charset=utf-8", path.read_bytes(), "audit.csv")
    if action == "tamper" and is_admin and log_id:
        row = conn.execute("SELECT authz_reason FROM audit_logs WHERE log_id=?", (log_id,)).fetchone()
        if row:
            if log_id not in _TAMPER_ORIG:
                _TAMPER_ORIG[log_id] = row["authz_reason"]
                conn.execute("UPDATE audit_logs SET authz_reason=? WHERE log_id=?",
                             ("DENY_TAMPERED" if row["authz_reason"] != "DENY_TAMPERED" else "ALLOW", log_id))
            else:
                conn.execute("UPDATE audit_logs SET authz_reason=? WHERE log_id=?", (_TAMPER_ORIG.pop(log_id), log_id))
            conn.commit()
        return ("redirect", "/audit")
    v = audit.verify(conn)
    rows = conn.execute("SELECT * FROM audit_logs ORDER BY log_id ASC").fetchall()
    if not is_admin:
        rows = [r for r in rows if r["on_behalf_of_user"] == me["user_id"]]
    trs = ""
    for i, e in enumerate(conn.execute("SELECT * FROM audit_logs ORDER BY log_id ASC").fetchall()):
        if not is_admin and e["on_behalf_of_user"] != me["user_id"]:
            continue
        broke = (not v["ok"]) and i >= v["broken_at"]
        bg = ' style="background:var(--deny-soft)"' if broke else ""
        rcls = "allow" if e["authz_reason"] == "ALLOW" else ("deny" if e["authz_reason"].startswith("DENY") else "allow")
        tamper_btn = (f'<a class="btn ghost sm" href="/audit?action=tamper&amp;log_id={e["log_id"]}">{"Khôi phục" if e["log_id"] in _TAMPER_ORIG else "Giả mạo"}</a>') if is_admin else ""
        trs += (f'<tr{bg}><td class="t-id">L-{e["log_id"]:04d}</td><td class="small mono">{esc(e["ts"][11:])}</td>'
                f'<td class="t-id">{esc(e["on_behalf_of_user"])}</td><td class="small muted">{esc(e["agent_id"] or "—")}</td>'
                f'<td class="small">{esc(e["action"])}</td><td class="small mono">{esc((e["resource_ref"] or "")[:16])}</td>'
                f'<td><span class="verdict {rcls}">{esc(e["authz_reason"])}</span></td>'
                f'<td>{CL(e["max_data_class_accessed"]) if e["max_data_class_accessed"] else "—"}</td>'
                f'<td class="small mono" title="{esc(e["current_log_hash"])}">{esc(e["current_log_hash"][:10])}…</td>'
                f'<td>{tamper_btn}</td></tr>')
    if not trs:
        trs = '<tr><td colspan=10 class="muted small" style="padding:16px">Chưa có bản ghi — hãy chat / chạy PDP.</td></tr>'
    verdict = f'<span class="verdict {"allow" if v["ok"] else "deny"}">{"INTACT" if v["ok"] else "BROKEN @"+str(v["broken_at"]+1)}</span>'
    exp = '<a class="btn ghost sm" href="/audit?action=export">⬇ Export CSV</a>' if is_admin else ""
    body = f"""<div class="page-head"><div class="eyebrow">P24 · hash-chain + HMAC</div>
<h2>Nhật ký (audit){'' if is_admin else ' — của tôi'}</h2><p><span class="mono">current = SHA-256(payload + previous_hash)</span>; sửa một dòng ⇒ chuỗi đứt từ đó. {('Bấm Verify; Giả mạo để minh hoạ.' if is_admin else '')}</p></div>
<div class="card"><div class="hd"><h3>Chuỗi</h3><span class="spacer"></span>{verdict}<a class="btn ghost sm" href="/audit">↻ Verify</a>{exp}</div>
<div class="bd" style="padding:0"><table><thead><tr><th>#</th><th>ts</th><th>user</th><th>agent</th><th>action</th><th>ref</th><th>lý do</th><th>mức</th><th>hash</th><th></th></tr></thead>
<tbody>{trs}</tbody></table></div></div>"""
    return body

def page_users(conn, me, form=None, action=None, edit=None, flash=None):
    """Quản trị tài khoản (ADMIN-only): tạo / sửa / xoá / gán quyền. Mọi thao tác ghi audit."""
    if me["role"] != "ADMIN":
        return '<div class="note">403 — trang chỉ dành cho admin.</div>'
    # ----- xử lý hành động (POST) -----
    if form is not None:
        act = (form.get("action", [""])[0] or "")
        if act == "create":   ok, msg = accounts.create_user(conn, form)
        elif act == "update": ok, msg = accounts.update_user(conn, form)
        elif act == "delete": ok, msg = accounts.delete_user(conn, form.get("user_id", [""])[0], me["user_id"])
        else:                 ok, msg = False, "hành động không hợp lệ"
        if ok:
            audit.append(conn, on_behalf_of_user=me["user_id"], agent_id="admin:account_mgmt",
                         action=f"admin:{act}_user", resource_ref=form.get("user_id", [""])[0],
                         authz_reason="ALLOW")
        flash = (("ok" if ok else "err"), msg)
    # ----- bảng người dùng -----
    rows = accounts.list_users(conn)
    def _chips(s): return "".join(f'<span class=tag>{esc(x)}</span>' for x in json.loads(s or "[]")) or "—"
    trs = "".join(
        f'<tr><td class="t-id">{esc(r["user_id"])}{" ★" if r["role"]=="ADMIN" else ""}</td>'
        f'<td>{esc(r["role"])}</td><td class="small muted">{esc(r["department"] or "—")}</td>'
        f'<td>{CL(r["clearance"])}</td><td>{_chips(r["groups_json"])}</td>'
        f'<td class="small">{_chips(r["projects_json"])}</td>'
        f'<td class="small">{("HR-purpose" if r["hr_purpose"] else "")}{(" · manages "+",".join(json.loads(r["manages_json"] or "[]"))) if json.loads(r["manages_json"] or "[]") else ""}</td>'
        f'<td><a class="btn ghost sm" href="/users?edit={r["user_id"]}">Sửa</a> '
        f'<a class="btn ghost sm" href="/users?action=delete&amp;user_id={r["user_id"]}" onclick="return confirm(\'Xoá {r["user_id"]}?\')">Xoá</a></td></tr>'
        for r in rows)
    # ----- form tạo/sửa -----
    er = conn.execute("SELECT * FROM users WHERE user_id=?", (edit,)).fetchone() if edit else None
    def _sel(name, opts, cur):
        return f'<select name="{name}">' + "".join(f'<option{" selected" if o==cur else ""}>{o}</option>' for o in opts) + "</select>"
    cur_groups = set(json.loads(er["groups_json"] or "[]")) if er else {"vsi_public", "vsi_internal"}
    gboxes = "".join(
        f'<label style="display:inline-flex;gap:6px;align-items:center;width:auto;margin-right:12px;font-weight:500">'
        f'<input type="checkbox" name="groups" value="{g}" style="width:auto"{" checked" if g in cur_groups else ""}> {g}</label>'
        for g in settings.PERMISSION_GROUPS)
    val = lambda k, d="": esc(er[k]) if er else d
    csv = lambda k: esc(", ".join(json.loads(er[k] or "[]"))) if er else ""
    title = f"Sửa tài khoản · {edit}" if er else "Tạo tài khoản mới"
    flash_html = (f'<div class="note" style="margin-bottom:12px;border-left-color:var(--{"allow" if flash[0]=="ok" else "deny"})">'
                  f'<b>{"✓" if flash[0]=="ok" else "✗"}</b> {esc(flash[1])}</div>') if flash else ""
    form_html = f"""<form method="post" action="/users">
<input type="hidden" name="action" value="{'update' if er else 'create'}">
<div class="field"><label>user_id</label><input name="user_id" value="{val('user_id')}" {'readonly' if er else 'autofocus'}></div>
<div class="field"><label>Mật khẩu {'(để trống = giữ nguyên)' if er else ''}</label><input name="password" type="password" autocomplete="new-password"></div>
<div class="grid g2"><div class="field"><label>Vai trò (role)</label>{_sel('role', list(settings.ROLE_KINDS.keys()), er['role'] if er else 'ENGINEER')}</div>
<div class="field"><label>Clearance</label>{_sel('clearance', list(settings.CLASS_RANK.keys()), er['clearance'] if er else 'C2')}</div></div>
<div class="field"><label>Phòng ban (department)</label><input name="department" value="{val('department')}"></div>
<div class="field"><label>Nhóm quyền (permission_group)</label><div style="padding:4px 0">{gboxes}</div></div>
<div class="field"><label>Tags ABAC (phẩy)</label><input name="tags" value="{csv('tags_json')}" placeholder="core-ip, disc-pd"></div>
<div class="field"><label>Dự án (phẩy)</label><input name="projects" value="{csv('projects_json')}" placeholder="SOVRA, SAURIA"></div>
<div class="field"><label>Quản lý (manages — user_id, phẩy)</label><input name="manages" value="{csv('manages_json')}" placeholder="eng_dv1"></div>
<div class="field"><label style="display:inline-flex;gap:8px;align-items:center;font-weight:500">
<input type="checkbox" name="hr_purpose" value="1" style="width:auto"{" checked" if er and er["hr_purpose"] else ""}> HR-purpose (được xem hồ sơ nhân sự theo mục đích HR)</label></div>
<button class="btn primary full">{'Lưu thay đổi' if er else 'Tạo tài khoản'}</button>
{'<a class="btn ghost full" style="margin-top:8px" href="/users">Huỷ / tạo mới</a>' if er else ''}</form>"""
    body = f"""<div class="page-head"><div class="eyebrow">Control-plane · ADMIN-only · §21</div>
<h2>Quản trị tài khoản</h2><p>Admin tạo / sửa / xoá tài khoản và gán RBAC/ABAC. Fail-closed: nhóm quyền·clearance·vai trò ngoài tập hợp lệ bị từ chối; không xoá được chính mình hay ADMIN cuối cùng. Mọi thao tác vào <a href="/audit">nhật ký</a>.</p></div>
{flash_html}
<div class="grid gchat"><div class="card"><div class="hd"><h3>Người dùng <span class="badge">{len(rows)}</span></h3></div>
<div class="bd" style="padding:0"><table><thead><tr><th>user</th><th>role</th><th>phòng</th><th>clearance</th><th>groups</th><th>dự án</th><th>khác</th><th></th></tr></thead>
<tbody>{trs}</tbody></table></div></div>
<div class="card"><div class="hd"><h3>{esc(title)}</h3></div><div class="bd">{form_html}</div></div></div>"""
    return body

def _checks_html(pf):
    """Render bảng kết quả security + spell preflight."""
    sec = pf["security"]; secret_hit, secret_reason = sec["secret"]
    looks_p, names, flagged = sec["personnel"]
    srows = (f'<div class="trace"><div class="row {"deny" if secret_hit else "allow"}">'
             f'<span class="l2 {"deny" if secret_hit else "allow"}"></span><span class="rule">credential scan</span>'
             f'<span class="det">{esc(secret_reason) if secret_hit else "không phát hiện secret"}</span></div>'
             f'<div class="row {"deny" if (looks_p and not flagged) else "allow"}">'
             f'<span class="l2 {"deny" if (looks_p and not flagged) else "allow"}"></span><span class="rule">NER / DPIA</span>'
             f'<span class="det">{("nghi PII: "+", ".join(names)+(" — sẽ quarantine" if not flagged else " — đã gắn cờ")) if looks_p else "không nghi PII"}</span></div></div>')
    if pf["spelling"]:
        sp = "".join(f'<div class="kv"><span class="k">dòng {i["line"]} · {esc(i["type"])}</span>'
                     f'<span class="v">{esc(i["word"])} → {esc(i["suggestion"])}</span></div>' for i in pf["spelling"])
        sp_box = f'<div class="note" style="margin-top:10px">⚠ {len(pf["spelling"])} cảnh báo chính tả/chất lượng:</div>{sp}'
    else:
        sp_box = '<div class="note" style="margin-top:10px">✓ Không phát hiện lỗi chính tả.</div>'
    he = ('<div class="note" style="border-left-color:var(--deny);margin-top:10px">Hierarchy: ' +
          "; ".join(esc(e) for e in pf["hierarchy_errors"]) + '</div>') if pf["hierarchy_errors"] else ""
    return f'<div class="card"><div class="hd"><h3>Kết quả kiểm tra trước khi tải lên</h3></div><div class="bd">{srows}{sp_box}{he}</div></div>'

def page_workspace(conn, me, form=None):
    """Workspace người dùng: tạo thư mục + tải tài liệu theo hierarchy (mọi user)."""
    flash = None; pf_panel = ""
    if form is not None:
        act = form.get("action", [""])[0]
        if act == "create_folder":
            ok, msg, _ = ws.create_folder(conn, me, form.get("name", [""])[0],
                                          form.get("permission_group", [""])[0],
                                          form.get("owner_project", [""])[0] or None)
            if ok: audit.append(conn, on_behalf_of_user=me["user_id"], action="create_folder",
                                resource_ref=form.get("name", [""])[0], authz_reason="ALLOW")
            flash = ("ok" if ok else "err", msg)
        elif act == "upload":
            fid = form.get("folder_id", [""])[0]
            folder = ws.get_folder(conn, fid)
            allowed = {f["folder_id"] for f in ws.list_folders(conn, me)}
            folder = folder if (folder and folder["folder_id"] in allowed) else None
            ack = str(form.get("ignore_spelling", [""])[0]).lower() in ("1", "on", "true")
            ok, msg, did = ws.commit_upload(conn, me, form, folder, ack_spelling=ack)
            audit.append(conn, on_behalf_of_user=me["user_id"], action="upload_document",
                         resource_ref=did or "(rejected)", authz_reason="ALLOW" if ok else "DENY_UPLOAD")
            flash = ("ok" if ok else "err", msg)
            if not ok and folder is not None:
                pf_panel = _checks_html(ws.preflight(me, form, folder))

    folders = ws.list_folders(conn, me)
    fopts = "".join(f'<option value="{f["folder_id"]}">{esc(f["name"])} · {esc(f["permission_group"])}'
                    f'{" · "+f["owner_project"] if f["owner_project"] else ""}{" (system)" if f["owner_user"]=="system" else ""}</option>'
                    for f in folders)
    frows = "".join(f'<tr><td>{esc(f["name"])}</td><td><span class=badge>{esc(f["permission_group"])}</span></td>'
                    f'<td class="small muted">{esc(f["owner_user"])}</td>'
                    f'<td class="small">{esc(f["owner_project"] or "—")}</td></tr>' for f in folders) \
            or '<tr><td colspan=4 class="muted small" style="padding:14px">Chưa có thư mục — tạo một thư mục để bắt đầu.</td></tr>'
    # data_class chỉ tới trần clearance
    cls_opts = "".join(f'<option>{c}</option>' for c in settings.CLASS_RANK if settings.CLASS_RANK[c] <= settings.CLASS_RANK[me["clearance"]])
    grp_opts = "".join(f'<option>{g}</option>' for g in settings.PERMISSION_GROUPS if me["role"]=="ADMIN" or g in me["groups"])
    proj_opts = '<option value="">(không)</option>' + "".join(f'<option>{esc(p)}</option>' for p in sorted(me["projects"]))
    flash_html = (f'<div class="note" style="margin-bottom:12px;border-left-color:var(--{"allow" if flash[0]=="ok" else "deny"})">'
                  f'<b>{"✓" if flash[0]=="ok" else "✗"}</b> {esc(flash[1])}</div>') if flash else ""
    # recent uploads của tôi
    mine = conn.execute("SELECT doc_id,title,data_class,status FROM documents WHERE created_by=? ORDER BY updated_at DESC LIMIT 8", (me["user_id"],)).fetchall()
    mrows = "".join(f'<tr><td class="t-id">{esc(r["doc_id"])}</td><td>{esc(r["title"])}</td><td>{CL(r["data_class"])}</td>'
                    f'<td>{"<span class=verdict allow>active</span>" if r["status"]=="active" else "<span class=verdict deny>quarantine</span>"}</td></tr>'
                    for r in mine) or '<tr><td colspan=4 class="muted small" style="padding:12px">Chưa tải lên tài liệu nào.</td></tr>'
    body = f"""<div class="page-head"><div class="eyebrow">Workspace · mọi người dùng · S4/S5</div>
<h2>Tải lên & quản lý tài nguyên</h2><p>Tự tạo thư mục và tải tài liệu <b>trong hierarchy của bạn</b>: data_class ≤ clearance ({CL(me["clearance"])}), chỉ nhóm quyền/dự án bạn thuộc về. File được <b>quét bảo mật + kiểm chính tả</b> trước khi index — credential bị chặn, nghi PII bị quarantine.</p></div>
{flash_html}{pf_panel}
<div class="grid g2">
<div class="card"><div class="hd"><h3>Thư mục của tôi <span class="badge">{len(folders)}</span></h3></div>
<div class="bd" style="padding:0"><table><thead><tr><th>Tên</th><th>nhóm quyền</th><th>chủ</th><th>dự án</th></tr></thead><tbody>{frows}</tbody></table></div>
<div class="bd"><form method="post" action="/workspace"><input type="hidden" name="action" value="create_folder">
<div class="field"><label>Tạo thư mục mới — tên</label><input name="name" placeholder="vd: ghi-chú-DV"></div>
<div class="grid g2"><div class="field"><label>nhóm quyền</label><select name="permission_group">{grp_opts}</select></div>
<div class="field"><label>dự án (tuỳ chọn)</label><select name="owner_project">{proj_opts}</select></div></div>
<button class="btn ghost full">+ Tạo thư mục</button></form></div></div>

<div class="card"><div class="hd"><h3>Tải tài liệu lên</h3></div><div class="bd">
<form method="post" action="/workspace"><input type="hidden" name="action" value="upload">
<div class="field"><label>Thư mục đích</label><select name="folder_id">{fopts or '<option value="">(tạo thư mục trước)</option>'}</select></div>
<div class="field"><label>Tiêu đề</label><input name="title" placeholder="Tiêu đề tài liệu"></div>
<div class="grid g2"><div class="field"><label>Phân loại (≤ clearance)</label><select name="data_class">{cls_opts}</select></div>
<div class="field"><label>Loại (kind)</label><input name="kind" value="METADATA"></div></div>
<div class="grid g2"><div class="field"><label>Dự án (tuỳ chọn)</label><select name="owner_project">{proj_opts}</select></div>
<div class="field"><label>required_tags (phẩy)</label><input name="required_tags" placeholder="core-ip"></div></div>
<div class="field"><label>Nội dung (markdown)</label><textarea name="body" rows="7" placeholder="# Mục\nNội dung…"></textarea></div>
<div class="field"><label style="display:inline-flex;gap:8px;align-items:center;font-weight:500"><input type="checkbox" name="ignore_spelling" value="1" style="width:auto"> Bỏ qua cảnh báo chính tả</label></div>
<button class="btn primary full">⇪ Kiểm tra & tải lên</button></form></div></div></div>

<div class="card"><div class="hd"><h3>Tài liệu tôi đã tải lên</h3></div><div class="bd" style="padding:0">
<table><thead><tr><th>doc_id</th><th>tiêu đề</th><th>mức</th><th>trạng thái</th></tr></thead><tbody>{mrows}</tbody></table></div></div>"""
    return body

# ---------------- DISPATCH ----------------
def dispatch(method, path, query, form, conn, me):
    is_admin = me["role"] == "ADMIN"
    if path == "/" :
        return ("html", page_overview(conn, me))
    if path == "/chat":
        if method == "POST":
            conv_id = form.get("conv_id", [None])[0]
            text = (form.get("text", [""])[0] or "").strip()
            if not conv_id:
                conv_id = cstore.create(conn, me["user_id"])
            trace = run_turn(conn, me, conv_id, text) if text else None
            body, conv = page_chat(conn, me, conv_id, trace_steps=trace)
            return ("html", body, conv)
        # GET (maybe ?new or ?q quick-shortcut)
        if query.get("new"):
            cid = cstore.create(conn, me["user_id"])
            return ("redirect", f"/chat?conv_id={cid}")
        conv_id = query.get("conv_id", [None])[0]
        q = query.get("q", [None])[0]
        trace = None
        if q and conv_id:
            trace = run_turn(conn, me, conv_id, q)
        body, conv = page_chat(conn, me, conv_id, trace_steps=trace)
        return ("html", body, conv)
    if path == "/conversations":
        return ("html", page_conversations(conn, me, open_id=query.get("open", [None])[0]))
    if path == "/pdp":
        return ("html", page_pdp(conn, me, form=form if method == "POST" else None))
    if path == "/resources":
        return ("html", page_resources(conn, me))
    if path == "/graph":
        return ("html", page_graph(conn, me, focus=query.get("focus", [None])[0]))
    if path == "/workspace":
        return ("html", page_workspace(conn, me, form=form if method == "POST" else None))
    if path == "/users":
        if method == "POST":
            return ("html", page_users(conn, me, form=form))
        # GET: delete qua link (action=delete) → coi như form; hoặc edit/list
        if query.get("action", [None])[0] == "delete" and is_admin:
            return ("html", page_users(conn, me, form={"action": ["delete"], "user_id": query.get("user_id", [""])}))
        return ("html", page_users(conn, me, edit=query.get("edit", [None])[0]))
    if path == "/tasks":
        return ("html", page_tasks(conn, me, run=bool(query.get("run"))))
    if path == "/data":
        return ("html", page_data(conn, me))
    if path == "/ingest":
        return ("html", page_ingest(conn, me, did_reingest=(method == "POST")))
    if path == "/audit":
        out = page_audit(conn, me, action=query.get("action", [None])[0], log_id=(int(query["log_id"][0]) if query.get("log_id") else None))
        return out if isinstance(out, tuple) and out[0] in ("raw", "redirect") else ("html", out)
    return ("html", '<div class="note">404 — không có trang này.</div>')
