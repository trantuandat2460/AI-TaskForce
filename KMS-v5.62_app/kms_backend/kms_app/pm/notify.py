"""Thông báo trong-ứng-dụng (W9). Nền v5.6 (chat-only) không có khái niệm
notification per-user; nếu chỉ 'loại email khỏi phạm vi' thì kỹ sư không có cách
nào biết mình được giao việc / có comment mới — công cụ giao-tiếp-theo-task mất
giá trị. Lớp PM thêm inbox tối thiểu KHÔNG dùng email (email vẫn ngoài phạm vi)."""
import datetime


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def push(conn, user_id, kind, body, project_id=None, task_id=None):
    if not user_id:
        return
    conn.execute(
        "INSERT INTO notifications(user_id,project_id,task_id,kind,body,seen,created_at) VALUES(?,?,?,?,?,0,?)",
        (user_id, project_id, task_id, kind, body, _now()))


def fan_out(conn, user_ids, kind, body, project_id=None, task_id=None, exclude=None):
    for u in set(user_ids):
        if u and u != exclude:
            push(conn, u, kind, body, project_id, task_id)


def inbox(conn, user_id, only_unseen=False, limit=50):
    q = ("SELECT * FROM notifications WHERE user_id=?"
         + (" AND seen=0" if only_unseen else "")
         + " ORDER BY notif_id DESC LIMIT ?")
    return conn.execute(q, (user_id, limit)).fetchall()


def unseen_count(conn, user_id):
    return conn.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND seen=0",
                        (user_id,)).fetchone()[0]


def mark_all_seen(conn, user_id):
    conn.execute("UPDATE notifications SET seen=1 WHERE user_id=?", (user_id,))
    conn.commit()
