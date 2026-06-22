"""Pipeline ingest (S5 v5.6): docling(→markdown) → scanner tầng-1 → chunk → upsert
+ dựng concept graph. Idempotent qua 2 fingerprint: content_fp (sha256 bytes) →
re-embed; perm_fp (sha256 thuộc tính) → chỉ cập nhật payload.

Tầng-1 (S5): secret scanner + NER/DPIA chạy ĐỘC LẬP với cờ producer. Trúng ⇒
quarantine (status='quarantined'), KHÔNG index chunk → không bao giờ tới LLM.
(Nguồn ở bản này đã là .md nên 'docling' là no-op; để sẵn chỗ cắm docling thật
cho PDF — chạy offline trong lane.)"""
import hashlib, json, datetime, re
from pathlib import Path
from config import settings
from kms_app import db
from kms_app.ingestion import permissions as P
from kms_app.ingestion import chunking
from kms_app.ingestion import scanners

def _now(): return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def docling_to_markdown(path: Path) -> str:
    """Chỗ cắm docling. Với .md trả nguyên văn. Với .pdf/.docx: gọi docling ở đây.
    QUAN TRỌNG: docling phải chạy offline trong lane (A15/P33)."""
    return path.read_text(encoding="utf-8", errors="ignore")

_WIKILINK = re.compile(r"\[\[([A-Za-z0-9_\-]+)\]\]")   # cạnh đồ thị trong body: [[R-004]]

def _rebuild_links(conn, doc_id, body, attrs):
    """Dựng concept_links từ frontmatter `related:` + wiki-link [[ID]] trong body.
    Cạnh trỏ tới concept chưa tồn tại = dangling (tri thức tương lai) — vẫn ghi nhận."""
    conn.execute("DELETE FROM concept_links WHERE src_doc=?", (doc_id,))
    dsts = list(dict.fromkeys(attrs.get("related", []) + _WIKILINK.findall(body)))
    for dst in dsts:
        if dst == doc_id: continue
        exists = conn.execute("SELECT 1 FROM documents WHERE doc_id=?", (dst,)).fetchone()
        conn.execute("INSERT INTO concept_links(src_doc,dst_doc,link_kind,dangling) VALUES(?,?,?,?)",
                     (doc_id, dst, "related", 0 if exists else 1))

def ingest_all(conn):
    report = {"new": 0, "changed": 0, "perm_changed": 0, "unchanged": 0,
              "chunks": 0, "files": 0, "quarantined": 0, "links": 0}
    base = settings.DOCUMENTS_DIR
    for path in sorted(base.rglob("*.md")):
        report["files"] += 1
        folder = path.parent.name
        raw = path.read_text(encoding="utf-8", errors="ignore")
        meta, _ = P.parse_front_matter(raw)
        attrs = P.coerce(meta, folder)
        md = docling_to_markdown(path)
        _, body = P.parse_front_matter(md)
        doc_id = meta.get("doc_id") or _get_id(meta) or path.stem

        # ---- Scanner tầng-1 (độc lập cờ producer) ----
        sec_hit, sec_reason = scanners.secret_scan(body)
        looks_personnel, names = scanners.ner_scan(body)
        if sec_hit or attrs["is_credential"]:
            attrs["is_credential"] = True
            attrs["status"], attrs["quarantine_reason"] = "quarantined", (sec_reason or "cờ vsi_is_credential")
        elif looks_personnel and not attrs["is_personnel_report"]:
            # trông giống nhân sự nhưng CHƯA gắn cờ → route DPIA/steward (không xử lý như tài liệu kỹ thuật)
            attrs["status"], attrs["quarantine_reason"] = "quarantined", f"NER nghi PII chưa gắn cờ: {', '.join(names) or '—'} → DPIA review"

        title = (re.search(r"^#\s+(.+)$", body, re.M) or [None, path.stem])[1]
        title = title.strip() if isinstance(title, str) else path.stem
        content_fp = hashlib.sha256(raw.encode()).hexdigest()[:16]
        perm_fp = hashlib.sha256(json.dumps({k: attrs[k] for k in
                  ("data_class","kind","owner_project","owner_dept","required_tags","permission_group",
                   "sensitive_level","corpus_id","lane","status","is_credential","is_personnel_report","subject_person")},
                  sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]

        row = conn.execute("SELECT content_fp, perm_fp FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        rel = str(path.relative_to(settings.BASE_DIR))
        if row is None:                       status = "new"
        elif row["content_fp"] != content_fp: status = "changed"
        elif row["perm_fp"] != perm_fp:       status = "perm_changed"
        else:
            report["unchanged"] += 1
            continue

        conn.execute("""INSERT OR REPLACE INTO documents
            (doc_id,business_key,source_file,title,file_kind,data_class,data_subclass,kind,owner_project,owner_dept,
             required_tags_json,permission_group,sensitive_level,corpus_id,lane,status,quarantine_reason,
             created_by,folder_id,is_credential,is_personnel_report,subject_person,content_fp,perm_fp,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (doc_id, doc_id, rel, title, "markdown", attrs["data_class"], attrs["data_subclass"], attrs["kind"],
             attrs["owner_project"], attrs["owner_dept"], json.dumps(attrs["required_tags"]),
             attrs["permission_group"], attrs["sensitive_level"], attrs["corpus_id"], attrs["lane"],
             attrs["status"], attrs["quarantine_reason"], attrs["created_by"], attrs["folder_id"],
             int(attrs["is_credential"]),
             int(attrs["is_personnel_report"]), attrs["subject_person"], content_fp, perm_fp, _now(), _now()))

        # Concept graph: dựng cạnh kể cả khi quarantine (cạnh là metadata, không phải nội dung).
        _rebuild_links(conn, doc_id, body, attrs)

        if attrs["status"] != "active":
            # quarantine ⇒ KHÔNG index chunk (không bao giờ vào retrieval/LLM)
            conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
            report["quarantined"] += 1
        elif status in ("new", "changed"):    # re-embed chunks (chỉ concept active)
            conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
            for ch in chunking.chunk_markdown(doc_id, body):
                conn.execute("""INSERT INTO chunks(chunk_id,doc_id,corpus_id,parent_id,heading_path,chunk_level,chunk_index,text,keywords_json)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (ch["chunk_id"], doc_id, attrs["corpus_id"], ch["parent_id"], ch["heading_path"],
                     ch["chunk_level"], ch["chunk_index"], ch["text"], json.dumps(ch["keywords"], ensure_ascii=False)))
                report["chunks"] += 1
        report[status] += 1
        conn.commit()
    # Post-pass: dangling = đích chưa tồn tại trong document set (độc lập thứ tự nạp file).
    conn.execute("UPDATE concept_links SET dangling=0 WHERE dst_doc IN (SELECT doc_id FROM documents)")
    conn.execute("UPDATE concept_links SET dangling=1 WHERE dst_doc NOT IN (SELECT doc_id FROM documents)")
    report["links"] = conn.execute("SELECT COUNT(*) FROM concept_links").fetchone()[0]
    conn.commit()
    return report

def _get_id(meta):
    return meta.get("vsi_doc_id") or meta.get("doc_id")
