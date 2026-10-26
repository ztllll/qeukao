"""Windows Agent and management API business logic; all DB scopes close explicitly."""
from contextlib import closing
import hmac
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import unquote

import app
import qk_config


CLOSED_MESSAGE = "当前暂无可填报场次，请联系考务管理员"


def put_setting(conn, key, value):
    conn.execute("""INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (key, value, app.now_iso()))


def migrate_session_state():
    with closing(app.get_db()) as conn, conn:
        conn.execute("""INSERT OR IGNORE INTO app_settings (key, value, updated_at)
            SELECT 'session_state', CASE WHEN EXISTS(SELECT 1 FROM current_report_drafts)
            THEN 'open' ELSE 'closed' END, ?""", (app.now_iso(),))
        # 旧库升级：有未验收草稿却没有场次的标题/日期设置时，从最早的草稿补回，否则新规则（标题/日期归管理员）有空档
        for key, column in (("current_project_title", "title"), ("current_exam_date", "exam_date")):
            conn.execute(f"""INSERT OR IGNORE INTO app_settings (key, value, updated_at)
                SELECT ?, {column}, ? FROM current_report_drafts WHERE {column} != '' ORDER BY room_number LIMIT 1""", (key, app.now_iso()))


def session_status():
    with closing(app.get_db()) as conn:
        settings = dict(conn.execute("SELECT key, value FROM app_settings WHERE key IN ('session_state', 'current_project_title', 'current_exam_date')").fetchall())
    return {"open": settings.get("session_state") == "open",
            "title": settings.get("current_project_title", ""),
            "examDate": settings.get("current_exam_date", ""),
            "closedMessage": CLOSED_MESSAGE, "serverTime": app.now_iso()}


def session_is_open(conn):
    row = conn.execute("SELECT value FROM app_settings WHERE key='session_state'").fetchone()
    return bool(row and row["value"] == "open")


def require_open_session(conn=None):
    is_open = session_status()["open"] if conn is None else session_is_open(conn)
    if not is_open:
        raise app.AppError(409, "NO_OPEN_SESSION", CLOSED_MESSAGE)


def handles(path):
    return path.startswith("/api/agent/") or path.startswith((
        "/api/admin/dispatch", "/api/admin/live", "/api/admin/clients/", "/api/admin/site", "/api/admin/analytics",
        "/api/admin/settings", "/api/admin/password", "/api/admin/client/"))


# 弹窗文案的「显示行数」上限。一个硬换行至少占一整个渲染行，所以只数换行或只数字数都不能保证放得下：
# 每个硬行按 30 字折行（客户端最窄的屏幕、20px 字号下一行也至少能放 30 个汉字）累加，总共不超过 9 行
# （最紧的 1920x1080@146% 下正文区正好 9 行）。必须与 client/fit.go 的 noticeLineChars/noticeMaxLines、
# static/admin.js 的 MESSAGE_LINE_CHARS/MESSAGE_MAX_LINES 保持一致。
MESSAGE_LINE_CHARS = 30
MESSAGE_MAX_LINES = 9
_LINE_BREAKS = re.compile(r"\r\n|[\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]")


def normalize_message(message):
    """把各种换行字符统一成 \\n：服务端、管理端、客户端对「几行」才会是同一个答案。"""
    return _LINE_BREAKS.sub("\n", message)


# CJK 与全角字符范围；与 client/fit.go cjkRanges、static/admin.js CJK_RANGES 逐项一致
_CJK_RANGES = ((0x1100, 0x11FF), (0x2E80, 0x2FDF), (0x3000, 0x30FF), (0x3100, 0x312F), (0x3400, 0x4DBF), (0x4E00, 0x9FFF),
               (0xAC00, 0xD7AF), (0xF900, 0xFAFF), (0xFE30, 0xFE4F), (0xFF00, 0xFFEF))  # 补充平面汉字故意不在表里：按「未知一律 2」处理


def _weight(ch):
    """一个字符占几个「字符宽」：宽字符约 2em，按 2 计；与 client/fit.go runeWeight、admin.js messageWeight 一致。"""
    o = ord(ch)
    if o < 0x250 or 0x2000 <= o <= 0x206F:
        return 1  # ASCII、拉丁字母、常用标点：约 1em
    for lo, hi in _CJK_RANGES:
        if lo <= o <= hi:
            return 1  # CJK 与全角字符：约 1em
    return 2  # 其它一律按 2 计（emoji、符号、箭头、数学字母、希腊/西里尔…）：未知宁可保守


def display_lines(message):
    return sum(max(1, -(-sum(_weight(c) for c in line) // MESSAGE_LINE_CHARS)) for line in message.split("\n"))


def bad_request(message):
    raise app.AppError(400, "VALIDATION_ERROR", message)


def text(payload, key, limit, default=""):
    value = payload.get(key, default)
    if not isinstance(value, str) or len(value) > limit:
        bad_request("字段 %s 格式不正确或内容过长" % key)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:  # JSON 里的孤立代理项（\ud83d）无法写入数据库，按格式错误拒绝而不是 500
        bad_request("字段 %s 含有非法字符" % key)
    return value.strip()


def fire_dispatch(conn, dispatch_id):
    now = app.now_iso()
    claimed = conn.execute("UPDATE dispatches SET status='fired', fired_at=? WHERE id=? AND status='pending'",
                           (now, dispatch_id)).rowcount
    if not claimed:
        return
    row = conn.execute("SELECT title, exam_date FROM dispatches WHERE id=?", (dispatch_id,)).fetchone()
    put_setting(conn, "session_state", "open")
    if row["title"] and not app.has_pending_drafts(conn):  # 有未验收数据时沿用当前场次的标题，不让后到的下发改掉表头
        put_setting(conn, "current_project_title", row["title"])
        put_setting(conn, "current_exam_date", row["exam_date"] or app.today_str())
    for event, title in (("session_opened", "场次已开放"), ("dispatch_fired", "通知已下发")):
        app.write_operation_log(conn, event, title, title, details={"dispatchId": dispatch_id})


def create_dispatch(payload, actor_ip):
    title = text(payload, "title", 120)
    if not title:
        bad_request("请填写标题（统计表的表头，每次下发都要填）")
    exam_date = text(payload, "examDate", 20) or app.today_str()
    try:
        datetime.strptime(exam_date, "%Y-%m-%d")
    except ValueError:
        bad_request("考试日期格式不正确")
    message = normalize_message(text(payload, "message", 200)) or "请点击确定填写缺考信息"
    if display_lines(message) > MESSAGE_MAX_LINES:  # 200 字可以敲成很多短行，弹窗放不下
        bad_request("弹窗内容太长或换行太多（按每行约 %d 字折算，最多 %d 行；表情、符号、箭头、生僻字等每个按 2 字计）" % (MESSAGE_LINE_CHARS, MESSAGE_MAX_LINES))
    mode = payload.get("mode")
    if mode not in ("now", "scheduled"):
        bad_request("下发模式不正确")
    scheduled = None
    if mode == "scheduled":
        raw = text(payload, "scheduledAt", 19)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?", raw):
            bad_request("定时时间格式不正确")
        try:
            when = datetime.fromisoformat(raw).replace(tzinfo=app.LOCAL_TZ)
        except ValueError:
            bad_request("定时时间格式不正确")
        if when <= datetime.now(app.LOCAL_TZ):
            bad_request("定时时间必须晚于当前服务端时间")
        scheduled = when.isoformat(timespec="seconds")
    with closing(app.get_db()) as conn, conn:
        cursor = conn.execute("""INSERT INTO dispatches
            (title, message, mode, scheduled_at, status, created_at, exam_date) VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
            (title, message, mode, scheduled, app.now_iso(), exam_date))
        dispatch_id = cursor.lastrowid
        app.write_operation_log(conn, "dispatch_created", "通知已创建", "已创建下发通知。",
                                actor_ip=actor_ip, details={"dispatchId": dispatch_id})
        in_force = None
        if mode == "now":
            fire_dispatch(conn, dispatch_id)
            # 在同一个事务里取场次实际用的表头：事后另开连接读，可能读到别的管理员刚下发的那一条
            settings = dict(conn.execute("SELECT key, value FROM app_settings WHERE key IN ('current_project_title', 'current_exam_date')").fetchall())
            in_force = (settings.get("current_project_title", ""), settings.get("current_exam_date", ""))
    item = next(item for item in list_dispatches() if item["id"] == dispatch_id)
    if in_force:  # 告诉管理员场次实际用的表头：有未验收数据时沿用旧场次，本次填的标题/日期不生效
        item = {**item, "sessionTitle": in_force[0], "sessionExamDate": in_force[1],
                "titleKept": in_force != (title, exam_date)}
    return item


def cancel_dispatch(dispatch_id, actor_ip):
    with closing(app.get_db()) as conn, conn:
        if not conn.execute("UPDATE dispatches SET status='cancelled' WHERE id=? AND status='pending'", (dispatch_id,)).rowcount:
            raise app.AppError(409, "DISPATCH_NOT_PENDING", "仅待发送的通知可取消")
        app.write_operation_log(conn, "dispatch_cancelled", "通知已取消", "已取消定时下发。",
                                actor_ip=actor_ip, details={"dispatchId": dispatch_id})
    return {"ok": True}


def online(last_seen):
    try:
        return (datetime.now(app.LOCAL_TZ) - datetime.fromisoformat(last_seen)).total_seconds() <= 40
    except (TypeError, ValueError):
        return False


def dispatch_objects(rows, clients, acks):
    online_count = sum(online(client["last_seen_at"]) for client in clients)
    counts = {}
    for ack in acks:
        bucket = counts.setdefault(ack["dispatch_id"], {})
        bucket[ack["state"]] = bucket.get(ack["state"], 0) + 1
    return [{"id": row["id"], "title": row["title"], "examDate": row["exam_date"] or "", "message": row["message"],
             "mode": row["mode"], "scheduledAt": row["scheduled_at"], "status": row["status"],
             "createdAt": row["created_at"], "firedAt": row["fired_at"],
             "counts": {"online": online_count, **{state: counts.get(row["id"], {}).get(state, 0)
                        for state in ("shown", "confirmed", "opened", "failed")}}} for row in rows]


def list_dispatches():
    with closing(app.get_db()) as conn:
        rows = conn.execute("SELECT * FROM dispatches ORDER BY id DESC LIMIT 50").fetchall()
        clients = conn.execute("SELECT last_seen_at FROM agent_clients").fetchall()
        acks = conn.execute("SELECT dispatch_id, state FROM dispatch_acks WHERE dispatch_id IN (SELECT id FROM dispatches ORDER BY id DESC LIMIT 50)").fetchall()
    return dispatch_objects(rows, clients, acks)


def change_password(payload, actor_ip):
    old = payload.get("oldPassword")
    if not isinstance(old, str) or not qk_config.check_admin_password(old):
        raise app.AppError(401, "UNAUTHORIZED", "旧密码不正确")
    try:
        qk_config.set_admin_password(payload.get("newPassword"))
    except ValueError as exc:
        bad_request(str(exc))
    app.log_operation("password_changed", "管理密码已修改", "管理员修改了管理密码。", actor_ip=actor_ip)
    return {"ok": True}


# ---------------------------------------------------------------- 数据分析（可视化的数据源）
# 「一次考试 = 一个标题」：同一标题的所有教室记录合成一场；日期取该标题记录里最早的考试日期。
# 同一个标题在不同日期各考一次（银行招聘笔试A 10-01 和 10-22）是两场，所以实际按 (标题, 考试日期) 分场。
ANALYTICS_BUCKETS = ((0, 0.5, "<50%"), (0.5, 0.7, "50–70%"), (0.7, 0.8, "70–80%"), (0.8, 0.9, "80–90%"), (0.9, 0.95, "90–95%"), (0.95, 1.0001, "95–100%"))


def analytics_filter(query):
    """与「数据」页的表格/汇总/导出共用 app.range_filter；这里只多一个 room（单间教室历史）。"""
    clauses, params = app.range_filter(query)
    room = ((query.get("room") or [""])[0]).strip()
    if len(room) > 20:
        bad_request("筛选条件过长")
    return ((" WHERE " + " AND ".join(clauses)) if clauses else ""), params, room


def rate_of(expected, actual):
    return round(actual / expected, 4) if expected else 0


def analytics(query):
    where, params, room = analytics_filter(query)
    with closing(app.get_db()) as conn:
        conn.execute("BEGIN")  # 几条聚合必须读同一个快照，否则老师恰好在中间提交时，总览与各教室合计对不上
        # 一场 = (标题, 考试日期)；同一场可能分几次下发验收（批次），人数累加，教室数/批次数去重
        exams = [{"title": r["title"], "examDate": r["exam_date"], "rooms": r["rooms"], "batches": r["batches"], "records": r["records"],
                  "expected": r["e"], "actual": r["a"], "absent": r["e"] - r["a"], "rate": rate_of(r["e"], r["a"])}
                 for r in conn.execute(f"""SELECT title, exam_date, COUNT(DISTINCT room_name) AS rooms, COUNT(*) AS records,
                    COUNT(DISTINCT COALESCE(NULLIF(batch_token, ''), 'created:' || created_at)) AS batches,
                    SUM(expected_count) AS e, SUM(actual_count) AS a
                    FROM absence_reports{where} GROUP BY title, exam_date ORDER BY exam_date, title""", params)]
        rooms = []
        for r in conn.execute(f"""SELECT room_name, MIN(COALESCE(room_number, 9999)) AS n, COUNT(DISTINCT title || char(31) || exam_date) AS times,
                    SUM(expected_count) AS e, SUM(actual_count) AS a FROM absence_reports{where}
                    GROUP BY room_name ORDER BY n, room_name""", params):
            rooms.append({"roomName": r["room_name"], "exams": r["times"], "expected": r["e"], "actual": r["a"],
                          "absent": r["e"] - r["a"], "rate": rate_of(r["e"], r["a"])})
        history = []
        if room:
            history = [{"title": r["title"], "examDate": r["exam_date"], "expected": r["expected_count"], "actual": r["actual_count"],
                        "absent": r["absent_count"], "rate": rate_of(r["expected_count"], r["actual_count"])}
                       for r in conn.execute(f"""SELECT title, exam_date, expected_count, actual_count, absent_count FROM absence_reports
                          {where + (" AND" if where else " WHERE")} room_name = :room ORDER BY exam_date, title""", {**params, "room": room})]
    expected, actual = sum(e["expected"] for e in exams), sum(e["actual"] for e in exams)
    distribution = [{"label": label, "count": sum(1 for r in rooms if r["expected"] and lo <= r["actual"] / r["expected"] < hi)} for lo, hi, label in ANALYTICS_BUCKETS]
    return {"totals": {"exams": len(exams), "reports": sum(e["records"] for e in exams), "expected": expected, "actual": actual,
                       "absent": expected - actual, "rate": rate_of(expected, actual)},
            "exams": exams, "rooms": rooms, "topAbsent": sorted((r for r in rooms if r["absent"] > 0), key=lambda r: (-r["absent"], r["roomName"]))[:10],
            "distribution": distribution, "roomHistory": history}


def site_info():
    """前台和后台都读的站点信息：考场名称/地址、教室名单。公开，不含任何密钥。"""
    site = qk_config.load()["site"]
    return {"orgName": site["orgName"], "orgAddress": site["orgAddress"], "roomNames": qk_config.room_names(),
            "roomNotice": site["roomNotice"]}


def save_site(payload, actor_ip):
    if not isinstance(payload, dict):
        bad_request("请求必须是 JSON 对象")
    patch = {k: payload[k] for k in ("orgName", "orgAddress", "roomCount", "roomNames", "roomNotice") if k in payload}
    if "orgName" in patch and (not isinstance(patch["orgName"], str) or not patch["orgName"].strip()):
        bad_request("请填写单位名称")
    try:
        with app.ROOM_LIST_LOCK:  # 与老师提交互斥：检查和保存之间不能插进一次提交
            current = qk_config.load()["site"]
            # 草稿按教室号存：未验收时换名单，已提交的数据会挂到别的教室名下，管理员也改不了它——必须先验收
            if qk_config.names_of(qk_config.merge_site(current, patch)) != qk_config.names_of(current):
                with closing(app.get_db()) as conn:
                    if app.has_pending_drafts(conn):
                        raise app.AppError(409, "ROOMS_LOCKED", "当前有未验收的数据，教室名单暂时不能修改；请先验收后再改")
            qk_config.save({"site": patch})
    except ValueError as exc:
        bad_request(str(exc))
    app.log_operation("site_changed", "基本信息已修改", "管理员修改了单位名称/教室配置。", actor_ip=actor_ip)
    return site_info()


def route(handler, method, path, query):
    if path.startswith("/api/agent/"):
        handler.write_json(app.success(agent_request(handler, method, path, query)))
        return
    handler.require_admin(allow_default_password=(path == "/api/admin/password" and method == "POST"))
    actor_ip = handler.request_client_ip()
    if path == "/api/admin/dispatch" and method == "POST":
        result = create_dispatch(handler.read_json(), actor_ip)
    elif path == "/api/admin/dispatches" and method == "GET":
        result = {"items": list_dispatches()}
    elif re.fullmatch(r"/api/admin/dispatches/\d+/cancel", path) and method == "POST":
        result = cancel_dispatch(int(path.split("/")[4]), actor_ip)
    elif path == "/api/admin/live" and method == "GET":
        result = live_status()
    elif path.startswith("/api/admin/clients/"):
        result = manage_client(method, path, handler, actor_ip)
    elif path == "/api/admin/analytics" and method == "GET":
        result = analytics(query)
    elif path == "/api/admin/site" and method == "POST":
        result = save_site(handler.read_json(), actor_ip)
    elif path.startswith("/api/admin/settings"):
        result = settings_request(method, path, handler, actor_ip)
    elif path == "/api/admin/client/download" and method == "GET":
        download_client(handler)
        return
    elif path == "/api/admin/password" and method == "POST":
        result = change_password(handler.read_json(), actor_ip)
    else:
        raise app.AppError(404, "NOT_FOUND", "接口地址不存在")
    handler.write_json(app.success(result))


def client_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", value):
        bad_request("客户端标识必须是 8..64 位字母、数字、下划线或连字符")
    return value


def check_blocked(conn, identity):
    row = conn.execute("SELECT blocked FROM agent_clients WHERE client_id=?", (identity,)).fetchone()
    if row and row["blocked"]:
        raise app.AppError(403, "CLIENT_BLOCKED", "客户端已被拉黑")
    return row


def agent_request(handler, method, path, query):
    supplied = handler.headers.get("X-Qk-Key", "")
    if not hmac.compare_digest(supplied.encode("utf-8"), qk_config.enroll_key().encode("utf-8")):
        raise app.AppError(401, "UNAUTHORIZED", "客户端密钥不正确")
    payload = handler.read_json() if method == "POST" else {}
    if not isinstance(payload, dict):
        bad_request("请求必须是 JSON 对象")
    identity = client_id((query.get("clientId") or [None])[0] if method == "GET" else payload.get("clientId"))
    peer_ip = handler.client_address[0]
    if path == "/api/agent/hello" and method == "POST":
        hostname = text(payload, "hostname", 255)
        version = text(payload, "version", 100)
        ips = payload.get("localIps", [])
        if not isinstance(ips, list) or len(ips) > 100 or any(not isinstance(ip, str) or len(ip) > 64 for ip in ips):
            bad_request("localIps 格式不正确")
        with closing(app.get_db()) as conn, conn:
            existing = check_blocked(conn, identity)
            now = app.now_iso()
            conn.execute("""INSERT INTO agent_clients
                (client_id, hostname, ip, version, local_ips, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(client_id) DO UPDATE SET
                hostname=excluded.hostname, ip=excluded.ip, version=excluded.version,
                local_ips=excluded.local_ips, last_seen_at=excluded.last_seen_at""",
                (identity, hostname, peer_ip, version, json.dumps(ips), now, now))
            if existing is None:
                app.write_operation_log(conn, "client_enrolled", "客户端已登记", "新客户端已登记。", actor_ip=peer_ip, details={"clientId": identity})
        room = qk_config.room_from_ip(peer_ip)
        return {"serverTime": app.now_iso(), "serverName": qk_config.load()["serverName"],
                "pollSeconds": 25, "room": {"matched": room is not None,
                "roomName": room["roomName"] if room else "", "roomNumber": room["roomNumber"] if room else None}}
    if path == "/api/agent/poll" and method == "GET":
        try:
            wait = float((query.get("wait") or ["25"])[0])
        except ValueError:
            bad_request("等待秒数格式不正确")
        if wait != wait:  # NaN
            bad_request("等待秒数格式不正确")
        wait = min(max(wait, 0.0), 30.0)
        with closing(app.get_db()) as conn, conn:
            if check_blocked(conn, identity) is None:
                raise app.AppError(404, "CLIENT_NOT_FOUND", "请先登记客户端")
            conn.execute("UPDATE agent_clients SET ip=?, last_seen_at=? WHERE client_id=?", (peer_ip, app.now_iso(), identity))
        return poll_notice(identity, peer_ip, wait)
    if path == "/api/agent/ack" and method == "POST":
        state = payload.get("state")
        dispatch_id = payload.get("dispatchId")
        if state not in ("shown", "confirmed", "opened", "failed") or type(dispatch_id) is not int or dispatch_id <= 0:
            bad_request("通知回执格式不正确")
        detail = text(payload, "detail", 2000)
        with closing(app.get_db()) as conn, conn:
            if check_blocked(conn, identity) is None:
                raise app.AppError(404, "CLIENT_NOT_FOUND", "请先登记客户端")
            if conn.execute("SELECT 1 FROM dispatches WHERE id=?", (dispatch_id,)).fetchone() is None:
                raise app.AppError(404, "NOT_FOUND", "通知不存在")
            # 只允许前进 shown < confirmed < opened；failed 随时可写，也可被后续回执覆盖（失败后重试）
            conn.execute("""INSERT INTO dispatch_acks (dispatch_id, client_id, state, detail, updated_at)
                VALUES (?, ?, ?, ?, ?) ON CONFLICT(dispatch_id, client_id) DO UPDATE SET
                state=excluded.state, detail=excluded.detail, updated_at=excluded.updated_at
                WHERE excluded.state='failed' OR dispatch_acks.state='failed'
                   OR (CASE excluded.state WHEN 'shown' THEN 1 WHEN 'confirmed' THEN 2 ELSE 3 END)
                    > (CASE dispatch_acks.state WHEN 'shown' THEN 1 WHEN 'confirmed' THEN 2 ELSE 3 END)""",
                (dispatch_id, identity, state, detail, app.now_iso()))
        return {"ok": True}
    raise app.AppError(404, "NOT_FOUND", "接口地址不存在")


def poll_notice(identity, peer_ip, wait):
    deadline = time.monotonic() + wait
    while True:
        # Every iteration closes before sleeping: SQLite context managers alone do not close.
        with closing(app.get_db()) as conn:
            conn.execute("BEGIN")
            check_blocked(conn, identity)
            setting = conn.execute("SELECT value FROM app_settings WHERE key='session_state'").fetchone()
            is_open = bool(setting and setting["value"] == "open")
            notice = None
            if is_open:
                latest = conn.execute("SELECT * FROM dispatches WHERE status='fired' ORDER BY fired_at DESC, id DESC LIMIT 1").fetchone()
                room = qk_config.room_from_ip(peer_ip)
                if latest:
                    ack = conn.execute("SELECT state FROM dispatch_acks WHERE dispatch_id=? AND client_id=?", (latest["id"], identity)).fetchone()
                    draft = room and conn.execute("SELECT 1 FROM current_report_drafts WHERE room_number=?", (room["roomNumber"],)).fetchone()
                    if not draft and (ack is None or ack["state"] not in ("confirmed", "opened")):
                        notice = {"dispatchId": latest["id"], "title": latest["title"], "message": latest["message"], "openPath": "/"}
        remaining = deadline - time.monotonic()
        if notice is not None or remaining <= 0:
            return {"serverTime": app.now_iso(), "session": {"open": is_open}, "notice": notice}
        time.sleep(min(0.5, remaining))


def live_status():
    with closing(app.get_db()) as conn:
        conn.execute("BEGIN")
        clients = conn.execute("SELECT * FROM agent_clients ORDER BY client_id").fetchall()
        drafts = conn.execute("SELECT * FROM current_report_drafts").fetchall()
        dispatches = conn.execute("SELECT * FROM dispatches ORDER BY id DESC LIMIT 20").fetchall()
        latest = conn.execute("SELECT id FROM dispatches WHERE status='fired' ORDER BY fired_at DESC, id DESC LIMIT 1").fetchone()
        acks = conn.execute("SELECT * FROM dispatch_acks WHERE dispatch_id IN (SELECT id FROM dispatches ORDER BY id DESC LIMIT 20) OR dispatch_id=?", (latest["id"] if latest else None,)).fetchall()
        settings = dict(conn.execute("SELECT key, value FROM app_settings WHERE key IN ('session_state', 'current_project_title', 'current_exam_date')").fetchall())
    latest_id = latest["id"] if latest else None
    current_acks = {ack["client_id"]: ack for ack in acks if ack["dispatch_id"] == latest_id}
    client_objects = []
    room_clients = {}
    for client in clients:
        room = qk_config.room_from_ip(client["ip"])
        number = room["roomNumber"] if room else None
        room_clients.setdefault(number, []).append(client["client_id"])
        ack = current_acks.get(client["client_id"])
        client_objects.append({"clientId": client["client_id"], "name": client["hostname"], "ip": client["ip"],
            "roomNumber": number, "roomName": room["roomName"] if room else "",
            "online": online(client["last_seen_at"]), "lastSeenAt": client["last_seen_at"],
            "blocked": bool(client["blocked"]), "version": client["version"],
            "notice": {"dispatchId": latest_id, "state": ack["state"] if ack else "none", "at": ack["updated_at"] if ack else None}})
    by_room = {row["room_number"]: app.draft_row_to_report(row) for row in drafts}
    rooms = [{"roomNumber": number, "roomName": name, "submitted": number in by_room,
              "report": ({key: by_room[number][key] for key in ("expectedCount", "actualCount", "absentCount", "attendanceRate", "updatedAt")} if number in by_room else None),
              "clientIds": room_clients.get(number, [])} for number, name in enumerate(qk_config.room_names(), 1)]
    return {"serverTime": app.now_iso(), "session": {"open": settings.get("session_state") == "open",
            "title": settings.get("current_project_title", ""), "examDate": settings.get("current_exam_date", ""), "dispatchId": latest_id},
            "summary": {"clientsTotal": len(clients), "clientsOnline": sum(item["online"] for item in client_objects), "roomsSubmitted": len(drafts), "roomsTotal": len(rooms)},
            "rooms": rooms, "clients": client_objects, "dispatches": dispatch_objects(dispatches, clients, acks)}


def manage_client(method, path, handler, actor_ip):
    match = re.fullmatch(r"/api/admin/clients/([^/]+)(/block)?", path)
    if not match or (method, bool(match[2])) not in (("POST", True), ("DELETE", False)):
        raise app.AppError(404, "NOT_FOUND", "接口地址不存在")
    identity = unquote(match[1])
    payload = handler.read_json() if method == "POST" else {}
    if method == "POST" and not isinstance(payload.get("blocked"), bool):
        bad_request("blocked 必须是布尔值")
    with closing(app.get_db()) as conn, conn:
        if method == "POST":
            blocked = payload["blocked"]
            changed = conn.execute("UPDATE agent_clients SET blocked=? WHERE client_id=?", (int(blocked), identity)).rowcount
            event = "client_blocked" if blocked else "client_unblocked"
        else:
            changed = conn.execute("DELETE FROM agent_clients WHERE client_id=?", (identity,)).rowcount
            conn.execute("DELETE FROM dispatch_acks WHERE client_id=?", (identity,))
            event = "client_deleted"
        if not changed:
            raise app.AppError(404, "NOT_FOUND", "客户端不存在")
        app.write_operation_log(conn, event, "客户端管理", "已更新客户端。", actor_ip=actor_ip, details={"clientId": identity})
    return {"ok": True}


def recent_client_ips(limit=200):
    with closing(app.get_db()) as conn:
        return [row["ip"] for row in conn.execute("SELECT ip FROM agent_clients ORDER BY last_seen_at DESC LIMIT ?", (max(0, int(limit)),)).fetchall()]


def client_summary():
    with closing(app.get_db()) as conn:
        rows = conn.execute("SELECT last_seen_at FROM agent_clients").fetchall()
    return {"total": len(rows), "online": sum(online(row["last_seen_at"]) for row in rows)}


def settings_request(method, path, handler, actor_ip):
    if path == "/api/admin/settings" and method == "GET":
        cfg = qk_config.load()
        with closing(app.get_db()) as conn:
            pending = app.has_pending_drafts(conn)
        return {"serverName": cfg["serverName"], "roomRule": cfg["roomRule"], "site": cfg["site"],
                "roomNames": qk_config.room_names(), "hasUnacceptedData": pending, "accessUrls": qk_config.access_urls(handler.server.server_port)}
    if path == "/api/admin/settings/room-rule/suggest" and method == "GET":
        return {"suggestion": qk_config.suggest_room_rule(recent_client_ips())}
    if path in ("/api/admin/settings/room-rule", "/api/admin/settings/room-rule/preview") and method == "POST":
        payload = handler.read_json()
        try:
            rule = qk_config.validate_room_rule(payload)
        except ValueError as exc:
            bad_request(str(exc))
        if path.endswith("/preview"):
            room = qk_config.room_from_ip(payload.get("ip", ""), rule)
            return {"matched": room is not None, "roomName": room["roomName"] if room else ""}
        qk_config.save({"roomRule": rule})
        app.log_operation("room_rule_changed", "教室识别规则已修改", "管理员修改了教室识别规则。", actor_ip=actor_ip, details=rule)
        return rule
    raise app.AppError(404, "NOT_FOUND", "接口地址不存在")


def client_template_path():
    """客户端模板：环境变量 → 程序目录旁的 client/dist → （打包成单文件 exe 时）包内的 client/dist。"""
    if os.getenv("QEUKAO_CLIENT_TEMPLATE"):
        return Path(os.environ["QEUKAO_CLIENT_TEMPLATE"])
    relative = Path("client") / "dist" / "qeukao-client-template.exe"
    candidates = [qk_config.BASE_DIR / relative]
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        candidates.append(Path(sys._MEIPASS) / relative)
    return next((p for p in candidates if p.is_file()), candidates[0])


def build_client_exe(servers, out_path, name=""):
    template = client_template_path()
    if not template.is_file():
        raise FileNotFoundError("客户端模板不存在，请先构建客户端模板。")
    config = {"v": 1, "servers": list(dict.fromkeys(servers)), "enrollKey": qk_config.enroll_key(), "name": name or qk_config.load()["serverName"]}
    raw = json.dumps(config, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    output = Path(out_path)
    output.write_bytes(template.read_bytes() + raw + struct.pack("<I", len(raw)) + b"QKCFG-V1\n")
    return output


def _is_loopback_host(host):
    """Host 头（已校验过格式）是不是回环地址。按整段比较，所以 127.0.0.1.nip.io 之类的域名不会被误伤。"""
    name = host.lower()
    if name.startswith("["):  # [::1] 或 [::1]:8000
        name = name.split("]")[0] + "]"
    else:
        name = name.split(":")[0]
    nums = qk_config.parse_ipv4(name)
    return name in ("localhost", "[::1]") or (nums is not None and nums[0] == 127)


def download_client(handler):
    servers = ["http://%s:%d" % (ip, handler.server.server_port) for ip in qk_config.lan_ipv4_addresses()]
    host = handler.headers.get("Host") or ""
    if re.fullmatch(r"(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\])(?::\d{1,5})?", host) and not _is_loopback_host(host):
        servers.append("http://" + host)  # 回环地址对教室机无用；畸形 Host 直接丢弃
    with tempfile.TemporaryDirectory(prefix="qk-client-") as folder:
        try:
            result = build_client_exe(servers, Path(folder) / "qeukao-client.exe")
        except FileNotFoundError as exc:
            raise app.AppError(404, "CLIENT_TEMPLATE_MISSING", str(exc))
        raw = result.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", "application/octet-stream")
    handler.send_header("Content-Disposition", 'attachment; filename="qeukao-client.exe"')
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(raw)


_scheduler_lock = threading.Lock()
_scheduler_thread = None


def dispatch_tick():
    now = datetime.now(app.LOCAL_TZ)
    with closing(app.get_db()) as conn, conn:
        rows = conn.execute("SELECT id, scheduled_at FROM dispatches WHERE status='pending' AND mode='scheduled'").fetchall()
        for row in rows:
            try:
                due = datetime.fromisoformat(row["scheduled_at"])
            except (TypeError, ValueError):
                continue  # 坏数据行不阻塞其它通知（例如导入的库里 scheduled_at 非法）
            if due.tzinfo is None:
                due = due.replace(tzinfo=app.LOCAL_TZ)
            if due > now:
                continue
            if now - due > timedelta(minutes=10):
                if conn.execute("UPDATE dispatches SET status='missed' WHERE id=? AND status='pending'", (row["id"],)).rowcount:
                    app.write_operation_log(conn, "dispatch_missed", "定时通知已过期", "通知逾期超过十分钟，未下发。", details={"dispatchId": row["id"]})
            else:
                fire_dispatch(conn, row["id"])


def start_dispatch_scheduler():
    global _scheduler_thread
    def run():
        while True:
            try:
                dispatch_tick()
            except Exception as exc:
                print("[%s] dispatch scheduler failed: %s" % (app.now_iso(), exc))
            time.sleep(1)
    with _scheduler_lock:
        if _scheduler_thread is None or not _scheduler_thread.is_alive():
            _scheduler_thread = threading.Thread(target=run, name="qk-dispatch", daemon=True)
            _scheduler_thread.start()
        return _scheduler_thread
