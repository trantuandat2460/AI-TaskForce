"""Cấu hình tập trung cho KMS backend (v5.6). Mọi đường dẫn / hằng số sống ở đây.

Triển khai thật: chỉnh HOST/PORT, trỏ DATA_DIR sang volume bền vững, bật
COOKIE_SECURE=True sau reverse proxy HTTPS, thay DEMO_AUTH bằng SSO/OIDC,
và đổi LLM_BACKEND sang 'http' (xem kms_app/llm/client.py).

v5.6 thêm: named-corpus isolation + lane routing (S3), OKF vsi_ frontmatter (S4),
phễu truy xuất 5 lớp (S6), concept graph (S7), credential/NER scanner ở ingest.
"""
from pathlib import Path

# ---- Đường dẫn (code tách khỏi dữ liệu) ----
BASE_DIR      = Path(__file__).resolve().parent.parent          # gốc project
DATA_DIR      = BASE_DIR / "data"                               # TẤT CẢ dữ liệu runtime nằm ở đây
DB_PATH       = DATA_DIR / "kms.db"                             # SQLite — mở bằng bất kỳ trình xem nào
DOCUMENTS_DIR = DATA_DIR / "documents"                          # kho markdown nguồn (OKF: bạn nhìn thấy trực tiếp)
UPLOADS_DIR   = DATA_DIR / "uploads"                            # file thô trước khi ingest
EXPORTS_DIR   = DATA_DIR / "exports"                            # nơi xuất audit.csv ...
SECRET_FILE   = DATA_DIR / "secret.key"                         # khoá HMAC cho chuỗi audit (tự sinh, chmod 600)

# ---- Mạng ----
HOST = "127.0.0.1"
PORT = 8077

# ---- Phiên (control-plane §21) ----
SESSION_TTL_SECONDS = 8 * 3600
SESSION_COOKIE      = "kms_session"
COOKIE_SECURE       = False        # True khi chạy sau HTTPS thật

# ---- Auth ----
DEMO_AUTH = True                   # demo: mật khẩu = user_id. Thật: tắt + dùng SSO.
PBKDF2_ROUNDS = 100_000

# ---- Mô hình phân loại ----
CLASS_RANK = {"C1": 1, "C2": 2, "C3": 3}

# ---- Named-corpus isolation + lane (S3 v5.6) -------------------------------
# Mỗi corpus = một index có tên, gắn ĐÚNG một ranh giới phân loại + một lane.
# corpus C3 nằm trong enclave air-gapped; C1/C2 ở lane SECURED.
CORPORA = {
    "corpus_c1": {"lane": "SECURED",     "max_class": "C1"},
    "corpus_c2": {"lane": "SECURED",     "max_class": "C2"},
    "corpus_c3": {"lane": "C3_ENCLAVE",  "max_class": "C3"},
}
# corpus mặc định theo data_class khi OKF không khai vsi_corpus_id.
CLASS_TO_CORPUS = {"C1": "corpus_c1", "C2": "corpus_c2", "C3": "corpus_c3"}
# Ràng buộc topology: truy vấn xuất phát ở một lane chỉ "với tới" được các corpus sau.
# Enclave C3 thấy corpus C3 + bản mirror read-only của C1/C2; lane SECURED KHÔNG thấy C3.
LANE_REACHES = {
    "SECURED":    {"corpus_c1", "corpus_c2"},
    "C3_ENCLAVE": {"corpus_c1", "corpus_c2", "corpus_c3"},
}

# ---- Nhóm quyền hợp lệ (permission_group) — admin chỉ được gán trong tập này ----
PERMISSION_GROUPS = ["vsi_public", "vsi_internal", "vsi_confidential"]

# ---- Trần vai trò (kind nào vai trò được chạm) ----
ROLE_KINDS = {
    "ADMIN": "*",
    "ENGINEER": {"IP","SPEC_OVERVIEW","SPEC_DETAIL","TESTBENCH","FOUNDRY","PROGRESS_REPORT","PLAN","METADATA","PUBLIC","FA","PII"},
    "LEADER":   {"SPEC_OVERVIEW","PROGRESS_REPORT","PLAN","METADATA","PUBLIC","FA","PII"},
    "PM":       {"PROGRESS_REPORT","PLAN","METADATA","PUBLIC"},
    "HR":       {"PUBLIC","METADATA","PII"},
}

# ---- Retention (A17/P35) ----
CONVERSATION_RETAIN_DAYS = 180

# ---- Phễu truy xuất 5 lớp (S6) ----
RETRIEVAL_TOPK   = 5               # số chunk cuối cùng đưa cho LLM
RRF_K            = 60              # hằng số Reciprocal Rank Fusion
RERANK_CANDIDATE_CAP = 40         # trần ứng viên đưa vào rerank (chống nổ chi phí)
GRAPH_EXPAND_HOPS = 1             # graph-expand mở rộng 1 hop từ kết quả top

# ---- Scanner ingest (Tầng-1, độc lập với cờ producer — S5) ----
# Mẫu key/token đã biết để bắt credential kể cả khi producer quên gắn cờ.
SECRET_PATTERNS = [
    r"AKIA[0-9A-Z]{16}",                       # AWS access key id
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    r"gh[pousr]_[A-Za-z0-9]{20,}",             # GitHub token
    r"xox[baprs]-[A-Za-z0-9-]{10,}",           # Slack token
    r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*\S{12,}",
]

# ---- LLM (llm/client.py) ----
LLM_BACKEND   = "stub"             # 'stub' = mô phỏng tất định, offline. 'http' = gọi vLLM/Viettel AI.
LLM_HTTP_URL  = "http://127.0.0.1:8000/v1/chat/completions"
LLM_MODEL     = "Qwen2.5-72B-Instruct-AWQ"
