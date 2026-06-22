"""PEP kép (A4/P22 · dual-PEP S3 v5.6):
  - corpus_reachable: ACCESS FILTER theo corpus/lane (topology air-gap C3).
  - pep1_filter_docs: lọc thô theo permission_group (MatchAny) + corpus reachable — rẻ.
  - pep2_authorize:   recheck từng resource bằng authorize() — defense-in-depth.
  - max_class:        highest-classification-wins (P15)."""
from config import settings
from config.settings import CLASS_RANK
from kms_app.security.pdp import authorize

def corpus_reachable(corpus_id, from_lane, clearance):
    """Corpus có nằm trong tập 'với tới được' từ lane hiện tại VÀ trong trần clearance không?
    Đây là defense-in-depth cho ranh giới air-gap: truy vấn ngoài enclave KHÔNG thấy corpus C3."""
    if not corpus_id:
        return False                                   # fail-closed: không rõ corpus ⇒ loại
    corpus = settings.CORPORA.get(corpus_id)
    if corpus is None:
        return False
    if corpus_id not in settings.LANE_REACHES.get(from_lane, set()):
        return False                                   # ngoài enclave không reach corpus C3
    return CLASS_RANK[corpus["max_class"]] <= CLASS_RANK[clearance]

def pep1_filter_docs(subject, docs, from_lane=None):
    """PEP-1 = lớp 1 ACCESS FILTER. Lọc permission_group MatchAny; nếu biết lane thì
    đồng thời lọc corpus reachable (corpus C3 vắng mặt khi truy vấn ngoài enclave)."""
    out = []
    for d in docs:
        if d["permission_group"] not in subject["groups"]:
            continue
        if from_lane is not None and not corpus_reachable(d.get("corpus_id"), from_lane, subject["clearance"]):
            continue
        out.append(d)
    return out

def pep2_authorize(subject, resources):
    allowed, denied = [], []
    for r in resources:
        d = authorize(subject, r)
        (allowed if d.allow else denied).append((r, d))
    return allowed, denied

def max_class(resources):
    mdc = "C1"
    for r in resources:
        if CLASS_RANK[r["data_class"]] > CLASS_RANK[mdc]:
            mdc = r["data_class"]
    return mdc
