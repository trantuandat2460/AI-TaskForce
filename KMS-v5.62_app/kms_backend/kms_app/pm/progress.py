"""Biên dịch tiến độ dự án (task-contract `compile_project_progress`) + promote OKF.

Sửa các phê bình:
  - Determinism THẬT (no-LLM): aggregate = phép đếm tất định; risks = rule-derived từ
    dữ liệu (quá hạn / blocked / chờ duyệt). Chạy 2 lần cùng input + cùng ngày ⇒ cùng
    NỘI DUNG (không chỉ cùng schema). Không có bước LLM tự hứng.
  - Per-PEP: mọi nguồn (tasks/connector_items/PROGRESS_REPORT) lọc qua can_read của NGƯỜI
    CHẠY ⇒ tiến độ chỉ phản ánh phần họ được phép thấy.
  - highest-wins (W8): max_data_class = mức cao nhất CHẠM tới; khi promote OKF lấy làm sàn
    cứng. ĐÁNH ĐỔI được nêu rõ + cho phép xuất bản ≤C2 (redact nguồn C3) để chia sẻ rộng,
    thay vì im lặng nhốt cả tiến độ vào C3-only.
"""
import json, datetime
from config import settings
from config.settings import CLASS_RANK, CLASS_TO_CORPUS
from kms_app import db
from kms_app.security import audit
from kms_app.ingestion import store as istore
from kms_app.orchestrator.registry import REGISTRY
from kms_app.pm import authz

SCHEMA_VERSION = "1"
OUTPUT_KEYS = REGISTRY["compile_project_progress"]["output_schema"]


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def _today():
    return datetime.date.today().isoformat()

def _max_class(classes):
    m = "C1"
    for c in classes:
        if c and CLASS_RANK.get(c, 1) > CLASS_RANK[m]:
            m = c
    return m


def compile_progress(conn, subject, project_id, cap_class=None):
    """Trả dict {ok, result(schema), max_data_class, touched, contract}. cap_class (vd 'C2')
    = chỉ nạp nguồn ≤ mức đó (dùng cho bản chia sẻ ≤C2 — W8)."""
    contract = REGISTRY["compile_project_progress"]
    d = authz.authorize_action(conn, subject, "compile_progress", {"project_id": project_id})
    if not d.allow:
        audit.append(conn, on_behalf_of_user=subject["user_id"], agent_id="agent:progress",
                     action="pm:compile_progress", resource_ref=project_id, authz_reason=d.reason, near_miss=1)
        return {"ok": False, "reason": d.reason, "contract": contract}

    def _ok_class(c):
        return cap_class is None or CLASS_RANK.get(c or "C1", 1) <= CLASS_RANK[cap_class]

    # ---- load_inputs (qua PEP người chạy) ----
    tasks = [t for t in conn.execute("SELECT * FROM tasks WHERE project_id=? ORDER BY created_at", (project_id,)).fetchall()
             if (subject["role"] == "ADMIN" or authz.can_read(conn, subject, db.task_to_resource(t)))
             and _ok_class(t["data_class"])]
    items = [it for it in conn.execute("SELECT * FROM connector_items WHERE project_id=? AND status='active'", (project_id,)).fetchall()
             if (subject["role"] == "ADMIN" or authz.can_read(conn, subject, db.connector_item_to_resource(it)))
             and _ok_class(it["data_class"])]
    reports = [r for r in conn.execute(
                  "SELECT * FROM documents WHERE kind='PROGRESS_REPORT' AND owner_project=? AND status='active'",
                  (project_id,)).fetchall()
               if (subject["role"] == "ADMIN" or authz.can_read(conn, subject, db.doc_to_resource(r)))
               and _ok_class(r["data_class"])]

    # ---- aggregate (TẤT ĐỊNH, không LLM) ----
    by = {s: 0 for s in settings.TASK_STATUSES}
    for t in tasks:
        by[t["status"]] = by.get(t["status"], 0) + 1
    total = len(tasks)
    pct = round(100 * by.get("done", 0) / total) if total else 0
    stats = {"todo": by["todo"], "doing": by["doing"], "review": by["review"],
             "done": by["done"], "blocked": by["blocked"], "percent_done": pct}

    n_jira = sum(1 for it in items if it["source"] == "jira")
    n_gl = sum(1 for it in items if it["source"] == "gitlab")
    n_done_jira = sum(1 for it in items if it["source"] == "jira" and (it["state"] or "").lower() == "done")
    vs = f"Jira: {n_jira} issue ({n_done_jira} done) · GitLab: {n_gl} commit/MR · báo cáo tuần: {len(reports)}."

    # ---- assess (risks rule-derived, KHÔNG LLM) ----
    today = _today()
    overdue = [t for t in tasks if t["due_date"] and t["due_date"] < today and t["status"] != "done"]
    blockers = [f'{t["task_id"]} · {t["title"]}' for t in tasks if t["status"] == "blocked"]
    in_review = [t for t in tasks if t["status"] == "review"]
    risks = []
    if overdue: risks.append(f"{len(overdue)} task quá hạn: " + ", ".join(t["task_id"] for t in overdue))
    if blockers: risks.append(f"{len(blockers)} task blocked đang chặn tiến độ")
    if in_review: risks.append(f"{len(in_review)} task chờ duyệt (review→done cần PM/LEADER)")
    if not risks: risks.append("Không có rủi ro định lượng được phát hiện.")
    nextweek = [f'{t["task_id"]} · {t["title"]}'
                for t in sorted([t for t in tasks if t["status"] in ("todo", "doing")],
                                key=lambda r: (r["due_date"] or "9999", r["priority"], r["task_id"]))[:5]]

    result = {
        "Summary": f"Dự án {project_id}: {pct}% done ({by.get('done',0)}/{total} task) · "
                   f"{by['doing']} đang làm · {by['blocked']} blocked · {len(items)} item connector.",
        "TaskStats": stats,
        "VsJiraGitlab": vs,
        "Risks": risks,
        "NextWeek": nextweek or ["(trống)"],
        "Blockers": blockers or ["(không)"],
    }
    schema_ok = all(k in result for k in OUTPUT_KEYS)
    touched = ([db.task_to_resource(t) for t in tasks]
               + [db.connector_item_to_resource(it) for it in items]
               + [db.doc_to_resource(r) for r in reports])
    mdc = _max_class([r["data_class"] for r in touched]) if touched else "C1"

    audit.append(conn, on_behalf_of_user=subject["user_id"], agent_id="agent:progress",
                 action="pm:compile_progress", resource_ref=project_id, authz_reason="ALLOW",
                 max_data_class_accessed=mdc, task_contract_version=str(contract["version"]))
    return {"ok": True, "schema_ok": schema_ok, "result": result, "max_data_class": mdc,
            "n_tasks": total, "n_items": len(items), "contract": contract,
            "elevated_c3": (mdc == "C3" and cap_class is None)}


def save_snapshot(conn, subject, project_id, compiled):
    import secrets
    sid = "SNP-" + secrets.token_hex(3)
    conn.execute("""INSERT INTO progress_snapshots
        (snapshot_id,project_id,generated_by,task_contract_version,schema_version,summary_json,max_data_class,exported_doc_id,created_at)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (sid, project_id, subject["user_id"], str(compiled["contract"]["version"]), SCHEMA_VERSION,
         json.dumps(compiled["result"], ensure_ascii=False), compiled["max_data_class"], None, _now()))
    conn.commit()
    return sid


def export_okf(conn, subject, project_id, compiled, snapshot_id=None):
    """Promote tiến độ thành OKF concept .md (sàn cứng = max_data_class) rồi ingest.
    Trả (ok, msg, doc_id)."""
    d = authz.authorize_action(conn, subject, "export_progress", {"project_id": project_id})
    if not d.allow:
        return False, f"từ chối: {d.reason}", None
    mdc = compiled["max_data_class"]
    corpus = CLASS_TO_CORPUS.get(mdc, "corpus_c2")
    proj = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
    perm = proj["permission_group"] if proj else "vsi_internal"
    doc_id = f"PROG-{project_id}-{_today().replace('-','')}" + ("-C2" if compiled.get("_redacted") else "")
    meta = {
        "doc_id": doc_id, "vsi_data_class": mdc, "vsi_corpus_id": corpus,
        "vsi_kind": "PROGRESS_REPORT", "vsi_owner_project": project_id,
        "vsi_permission_group": perm, "vsi_sensitive_level": "restricted" if mdc == "C3" else "confidential",
        "vsi_created_by": subject["user_id"],
    }
    r = compiled["result"]
    body = (f"# Tiến độ dự án {project_id} — {_today()}"
            + (" (bản chia sẻ ≤C2, đã lược nguồn C3)" if compiled.get("_redacted") else "")
            + f"\n\n## Tóm tắt\n{r['Summary']}\n\n## Thống kê task\n"
            + " · ".join(f"{k}={v}" for k, v in r["TaskStats"].items())
            + f"\n\n## Đối chiếu Jira/GitLab\n{r['VsJiraGitlab']}\n\n## Rủi ro\n"
            + "\n".join(f"- {x}" for x in r["Risks"])
            + "\n\n## Tuần tới\n" + "\n".join(f"- {x}" for x in r["NextWeek"])
            + "\n\n## Blockers\n" + "\n".join(f"- {x}" for x in r["Blockers"]) + "\n")
    fm = "\n".join(["---"] + [f"{k}: {v}" for k, v in meta.items()] + ["---", ""])
    folder = settings.DOCUMENTS_DIR / "progress"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{doc_id}.md").write_text(fm + body, encoding="utf-8")
    istore.ingest_all(conn)
    if snapshot_id:
        conn.execute("UPDATE progress_snapshots SET exported_doc_id=? WHERE snapshot_id=?", (doc_id, snapshot_id))
    audit.append(conn, on_behalf_of_user=subject["user_id"], agent_id="agent:progress",
                 action="pm:export_progress", resource_ref=doc_id, authz_reason="ALLOW",
                 max_data_class_accessed=mdc, task_contract_version=str(compiled["contract"]["version"]))
    conn.commit()
    return True, f"đã promote OKF {doc_id} ({mdc}) — trích dẫn được, versioned", doc_id
