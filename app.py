#!/usr/bin/env python3
import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import zipfile
import qk_config
import qk_dbtools
if __name__ == "__main__":
    sys.modules["app"] = sys.modules[__name__]
import qk_agents
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
import xml.etree.ElementTree as ET


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = qk_config.DATA_DIR
DB_PATH = qk_config.DB_PATH
HOST = os.getenv("QEUKAO_HOST", qk_config.load()["host"])
PORT = int(os.getenv("QEUKAO_PORT", str(qk_config.load()["port"])))
COOKIE_NAME = "qeukao_admin"
SESSION_TTL = timedelta(hours=8)
LOCAL_TZ = timezone(timedelta(hours=8))
# 教室名单由管理员在后台「基本信息」配置（qk_config.room_names()）；这里不再写死。
PENDING_ACCEPTANCE_MESSAGE = "数据未验收，不支持重新填报！请联系考务老师确认！"
LOG_RETENTION_DAYS = 30
SESSION_NAME_MAX_LEN = 40
EXCEL_DATE_PLACEHOLDER = "1900-01-01"
EXCEL_IMPORT_FILE = os.getenv("QEUKAO_EXCEL_IMPORT_FILE", "")
_profile = Path(os.getenv("USERPROFILE", str(Path.home())))
_excel_dirs = ([Path(os.environ["QEUKAO_EXCEL_IMPORT_DIR"]).expanduser()]
               if os.getenv("QEUKAO_EXCEL_IMPORT_DIR") else [])
_excel_dirs += [_profile / "Desktop", _profile / "OneDrive" / "Desktop",
                Path.home() / "桌面", Path.home() / "Desktop"]
EXCEL_IMPORT_DIR = next((path for path in _excel_dirs if path.is_dir()), _excel_dirs[-1])


class AppError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def now_iso():
    return datetime.now(LOCAL_TZ).isoformat(timespec="seconds")


def today_str():
    return datetime.now(LOCAL_TZ).date().isoformat()


def get_db():
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def add_column_if_missing(conn, table_name, column_name, definition):
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def init_db():
    with get_db() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS absence_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                exam_date TEXT NOT NULL,
                exam_time TEXT,
                session_name TEXT,
                room_name TEXT NOT NULL,
                room_number INTEGER,
                subject_name TEXT,
                class_name TEXT,
                reporter_name TEXT NOT NULL DEFAULT '现场填报',
                reporter_contact TEXT,
                expected_count INTEGER NOT NULL,
                actual_count INTEGER NOT NULL,
                absent_count INTEGER NOT NULL,
                attendance_rate REAL NOT NULL,
                total_count INTEGER NOT NULL DEFAULT 0,
                total_attendance_rate REAL NOT NULL DEFAULT 0,
                batch_token TEXT,
                absent_students_text TEXT,
                remark TEXT,
                client_ip TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS current_report_drafts (
                room_number INTEGER PRIMARY KEY,
                report_id INTEGER,
                batch_token TEXT,
                room_name TEXT NOT NULL,
                title TEXT NOT NULL,
                exam_date TEXT NOT NULL,
                expected_count INTEGER NOT NULL,
                actual_count INTEGER NOT NULL,
                absent_count INTEGER NOT NULL,
                attendance_rate REAL NOT NULL,
                client_ip TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                actor_ip TEXT,
                room_name TEXT,
                report_id INTEGER,
                batch_token TEXT,
                details TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("""CREATE TABLE IF NOT EXISTS agent_clients (
            client_id TEXT PRIMARY KEY, hostname TEXT, ip TEXT, version TEXT,
            local_ips TEXT, first_seen_at TEXT, last_seen_at TEXT,
            blocked INTEGER DEFAULT 0)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS dispatches (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, message TEXT,
            mode TEXT, scheduled_at TEXT, status TEXT, created_at TEXT, fired_at TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS dispatch_acks (
            dispatch_id INTEGER, client_id TEXT, state TEXT, detail TEXT,
            updated_at TEXT, PRIMARY KEY(dispatch_id, client_id))""")
        add_column_if_missing(conn, "dispatches", "exam_date", "TEXT")
        add_column_if_missing(conn, "current_report_drafts", "report_id", "INTEGER")
        add_column_if_missing(conn, "current_report_drafts", "batch_token", "TEXT")
        add_column_if_missing(conn, "absence_reports", "room_number", "INTEGER")
        add_column_if_missing(conn, "absence_reports", "session_name", "TEXT")
        add_column_if_missing(
            conn,
            "absence_reports",
            "total_count",
            "INTEGER NOT NULL DEFAULT 0",
        )
        add_column_if_missing(
            conn,
            "absence_reports",
            "total_attendance_rate",
            "REAL NOT NULL DEFAULT 0",
        )
        add_column_if_missing(conn, "absence_reports", "batch_token", "TEXT")
        conn.execute(
            """
            UPDATE absence_reports
            SET total_count = expected_count
            WHERE total_count IS NULL OR total_count = 0
            """
        )
        conn.execute(
            """
            UPDATE absence_reports
            SET total_attendance_rate = attendance_rate
            WHERE total_attendance_rate IS NULL OR total_attendance_rate = 0
            """
        )
        rows = conn.execute(
            """
            SELECT id, room_name FROM absence_reports
            WHERE room_number IS NULL
            """
        ).fetchall()
        for row in rows:
            room_number = room_number_from_name(row["room_name"])
            if room_number is not None:
                conn.execute(
                    "UPDATE absence_reports SET room_number = ? WHERE id = ?",
                    (room_number, row["id"]),
                )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_absence_reports_exam_date "
            "ON absence_reports(exam_date)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_absence_reports_created_at "
            "ON absence_reports(created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_absence_reports_room_number "
            "ON absence_reports(room_number)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_absence_reports_batch_token "
            "ON absence_reports(batch_token)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_absence_reports_group_lookup "
            "ON absence_reports(exam_date, title, batch_token, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_operation_logs_created_at "
            "ON operation_logs(created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_operation_logs_event_type "
            "ON operation_logs(event_type)"
        )


def row_to_report(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "examDate": row["exam_date"],
        "examTime": row["exam_time"] or "",
        "manualSessionName": row["session_name"] or "",
        "roomName": row["room_name"],
        "roomNumber": row["room_number"] or room_number_from_name(row["room_name"]),
        "subjectName": row["subject_name"] or "",
        "className": row["class_name"] or "",
        "reporterName": row["reporter_name"],
        "reporterContact": row["reporter_contact"] or "",
        "expectedCount": row["expected_count"],
        "actualCount": row["actual_count"],
        "absentCount": row["absent_count"],
        "attendanceRate": row["attendance_rate"],
        "totalCount": row["total_count"],
        "totalAttendanceRate": row["total_attendance_rate"],
        "batchToken": row["batch_token"] or "",
        "absentStudentsText": row["absent_students_text"] or "",
        "remark": row["remark"] or "",
        "clientIp": row["client_ip"] or "",
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def normalize_text(payload, key, required=False, max_len=500):
    value = payload.get(key, "")
    if value is None:
        value = ""
    value = str(value).strip()
    if required and not value:
        raise AppError(HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "请填写必填项")
    if len(value) > max_len:
        raise AppError(HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "填写内容过长")
    return value


def normalize_date(payload, key):
    value = normalize_text(payload, key, required=True, max_len=20)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise AppError(
            HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "考试日期格式不正确"
        ) from exc
    return value


def normalize_optional_date(payload, key):
    value = normalize_text(payload, key, max_len=20)
    if not value:
        return today_str()
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise AppError(
            HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "日期格式不正确"
        ) from exc
    return value


def normalize_session_name(payload, key="sessionName"):
    value = normalize_text(payload, key, max_len=SESSION_NAME_MAX_LEN)
    if not value:
        return ""
    return re.sub(r"\s+", " ", value)


def normalize_count(payload, key, label):
    raw = payload.get(key)
    try:
        count = int(raw)
    except (TypeError, ValueError) as exc:
        raise AppError(
            HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", f"{label}必须是整数"
        ) from exc
    if count < 0:
        raise AppError(
            HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", f"{label}不能小于 0"
        )
    if count > 100000:
        raise AppError(
            HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", f"{label}数值过大"
        )
    return count


def room_number_from_name(room_name):
    names = qk_config.room_names()
    if room_name in names:
        return names.index(room_name) + 1
    digit_match = re.search(r"(\d+)", room_name)
    if digit_match:
        room_number = int(digit_match.group(1))
        if 1 <= room_number <= len(names):
            return room_number
    return None


def normalize_forwarded_ip(value):
    if not value:
        return ""
    first_value = str(value).split(",", 1)[0].strip()
    if first_value.lower().startswith("for="):
        first_value = first_value[4:].strip()
    return first_value.strip('"[] ')


def resolve_client_ip(headers, fallback):
    if fallback not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        return fallback or ""
    forwarded = headers.get("X-Forwarded-For")
    real_ip = headers.get("X-Real-IP")
    standard_forwarded = headers.get("Forwarded")
    return (
        normalize_forwarded_ip(forwarded)
        or normalize_forwarded_ip(real_ip)
        or normalize_forwarded_ip(standard_forwarded)
        or fallback
        or ""
    )


def classroom_from_client_ip(client_ip):
    return qk_config.room_from_ip(client_ip)


def client_context(client_ip):
    matched_room = classroom_from_client_ip(client_ip)
    return {
        "clientIp": client_ip,
        "matchedRoomName": matched_room["roomName"] if matched_room else "",
        "matchedRoomNumber": matched_room["roomNumber"] if matched_room else None,
    }


def get_setting(key, default=""):
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    updated_at = now_iso()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, updated_at),
        )
    return {"key": key, "value": value, "updatedAt": updated_at}


def json_details(details):
    if not details:
        return ""
    return json.dumps(details, ensure_ascii=False, sort_keys=True)


def write_operation_log(
    conn,
    event_type,
    title,
    message,
    *,
    severity="info",
    actor_ip="",
    room_name="",
    report_id=None,
    batch_token="",
    details=None,
):
    conn.execute(
        """
        INSERT INTO operation_logs (
            event_type, severity, title, message, actor_ip, room_name,
            report_id, batch_token, details, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_type,
            severity,
            title,
            message,
            actor_ip,
            room_name,
            report_id,
            batch_token,
            json_details(details),
            now_iso(),
        ),
    )


def log_operation(event_type, title, message, **kwargs):
    with get_db() as conn:
        write_operation_log(conn, event_type, title, message, **kwargs)


def write_failure_log(conn, event_type, title, message, **kwargs):
    write_operation_log(conn, event_type, title, message, **kwargs)
    conn.commit()


def row_to_operation_log(row):
    details = {}
    if row["details"]:
        try:
            details = json.loads(row["details"])
        except json.JSONDecodeError:
            details = {"raw": row["details"]}
    return {
        "id": row["id"],
        "eventType": row["event_type"],
        "severity": row["severity"],
        "title": row["title"],
        "message": row["message"],
        "actorIp": row["actor_ip"] or "",
        "roomName": row["room_name"] or "",
        "reportId": row["report_id"],
        "batchToken": row["batch_token"] or "",
        "details": details,
        "createdAt": row["created_at"],
    }


def list_operation_logs(query):
    page, page_size = parse_page(query)
    event_type = (query.get("eventType") or [""])[0].strip()
    date = (query.get("date") or [""])[0].strip()
    keyword = (query.get("keyword") or [""])[0].strip()
    clauses = []
    params = {}
    if event_type:
        clauses.append("event_type = :event_type")
        params["event_type"] = event_type
    if date:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError as exc:
            raise AppError(
                HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "日志日期格式不正确"
            ) from exc
        clauses.append("created_at LIKE :date")
        params["date"] = f"{date}%"
    if keyword:
        clauses.append(
            """
            (
                event_type LIKE :keyword OR severity LIKE :keyword OR
                title LIKE :keyword OR message LIKE :keyword OR
                actor_ip LIKE :keyword OR room_name LIKE :keyword OR
                batch_token LIKE :keyword OR details LIKE :keyword OR
                created_at LIKE :keyword
            )
            """
        )
        params["keyword"] = f"%{keyword}%"
    where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
    offset = (page - 1) * page_size
    with get_db() as conn:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS total FROM operation_logs{where_sql}",
            params,
        ).fetchone()
        rows = conn.execute(
            f"""
            SELECT * FROM operation_logs
            {where_sql}
            ORDER BY id DESC
            LIMIT :limit OFFSET :offset
            """,
            {**params, "limit": page_size, "offset": offset},
        ).fetchall()
    return {
        "items": [row_to_operation_log(row) for row in rows],
        "total": total_row["total"] if total_row else 0,
        "page": page,
        "pageSize": page_size,
    }


def summarize_operation_logs():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT event_type, severity, COUNT(*) AS count
            FROM operation_logs
            GROUP BY event_type, severity
            ORDER BY count DESC, event_type ASC
            """
        ).fetchall()
        latest = conn.execute(
            """
            SELECT * FROM operation_logs
            ORDER BY id DESC
            LIMIT 5
            """
        ).fetchall()
    return {
        "items": [
            {
                "eventType": row["event_type"],
                "severity": row["severity"],
                "count": row["count"],
            }
            for row in rows
        ],
        "latest": [row_to_operation_log(row) for row in latest],
    }


def cleanup_old_operation_logs(days=LOG_RETENTION_DAYS):
    cutoff = (datetime.now(LOCAL_TZ) - timedelta(days=days)).isoformat(
        timespec="seconds"
    )
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM operation_logs WHERE created_at < ?",
            (cutoff,),
        ).fetchone()
        deleted_count = row["total"] if row else 0
        if deleted_count:
            conn.execute("DELETE FROM operation_logs WHERE created_at < ?", (cutoff,))
            write_operation_log(
                conn,
                "logs_cleaned",
                "系统日志自动清理",
                f"已自动清理 {deleted_count} 条超过 {days} 天的系统日志。",
                details={"retentionDays": days, "cutoff": cutoff},
            )
    return deleted_count


def start_log_cleanup_scheduler():
    def run():
        while True:
            time.sleep(24 * 60 * 60)
            try:
                cleanup_old_operation_logs()
            except Exception as exc:
                print(f"[{now_iso()}] log cleanup failed: {exc}")

    thread = threading.Thread(target=run, name="log-cleanup", daemon=True)
    thread.start()


def has_pending_drafts(conn):
    row = conn.execute(
        "SELECT COUNT(*) AS draft_count FROM current_report_drafts"
    ).fetchone()
    return bool(row and row["draft_count"] > 0)


def get_current_project():
    with get_db() as conn:
        title_row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            ("current_project_title",),
        ).fetchone()
        draft_row = conn.execute(
            "SELECT COUNT(*) AS draft_count FROM current_report_drafts"
        ).fetchone()
    draft_count = draft_row["draft_count"] if draft_row else 0
    return {
        "title": title_row["value"] if title_row else "",
        "locked": draft_count > 0,
        "pendingDraftCount": draft_count,
    }


def normalize_room_name(payload):
    room_name = normalize_text(payload, "roomName", required=True, max_len=20)
    names = qk_config.room_names()
    if room_name not in names:
        raise AppError(
            HTTPStatus.BAD_REQUEST,
            "VALIDATION_ERROR",
            "请选择系统配置的教室名称",
        )
    return room_name, names.index(room_name) + 1


def validate_report(payload):
    room_name, room_number = normalize_room_name(payload)
    expected_count = normalize_count(payload, "expectedCount", "应到人数")
    actual_count = normalize_count(payload, "actualCount", "实到人数")
    if actual_count > expected_count:
        raise AppError(
            HTTPStatus.BAD_REQUEST,
            "VALIDATION_ERROR",
            "实到人数不能大于应到人数",
        )

    absent_count = expected_count - actual_count
    if "absentCount" in payload and payload.get("absentCount") not in (None, ""):
        input_absent_count = normalize_count(payload, "absentCount", "缺考人数")
        if input_absent_count != absent_count:
            raise AppError(
                HTTPStatus.BAD_REQUEST,
                "VALIDATION_ERROR",
                "缺考人数必须等于应到人数减实到人数",
            )
    attendance_rate = 0 if expected_count == 0 else actual_count / expected_count
    return {
        "title": normalize_text(
            payload, "title", max_len=120
        ) or f"出考率信息 {today_str()}",
        "exam_date": normalize_optional_date(payload, "examDate"),
        "exam_time": normalize_text(payload, "examTime", max_len=60),
        "session_name": normalize_session_name(payload),
        "room_name": room_name,
        "room_number": room_number,
        "subject_name": normalize_text(payload, "subjectName", max_len=80),
        "class_name": normalize_text(payload, "className", max_len=80),
        "reporter_name": normalize_text(payload, "reporterName", max_len=60)
        or "现场填报",
        "reporter_contact": normalize_text(payload, "reporterContact", max_len=80),
        "expected_count": expected_count,
        "actual_count": actual_count,
        "absent_count": absent_count,
        "attendance_rate": round(attendance_rate, 4),
        "total_count": expected_count,
        "total_attendance_rate": round(attendance_rate, 4),
        "batch_token": "",
        "absent_students_text": normalize_text(
            payload, "absentStudentsText", max_len=5000
        ),
        "remark": normalize_text(payload, "remark", max_len=5000),
    }


def draft_row_to_report(row):
    return {
        "reportId": row["report_id"],
        "batchToken": row["batch_token"] or "",
        "title": row["title"],
        "examDate": row["exam_date"],
        "roomName": row["room_name"],
        "roomNumber": row["room_number"],
        "expectedCount": row["expected_count"],
        "actualCount": row["actual_count"],
        "absentCount": row["absent_count"],
        "attendanceRate": row["attendance_rate"],
        "clientIp": row["client_ip"] or "",
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def list_current_report_drafts():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM current_report_drafts
            ORDER BY room_number ASC
            """
        ).fetchall()
    return {"items": [draft_row_to_report(row) for row in rows]}


def check_current_report_room(payload, client_ip=""):
    qk_agents.require_open_session()
    room_name, room_number = normalize_room_name(payload)
    with get_db() as conn:
        existing = conn.execute(
            "SELECT room_number FROM current_report_drafts WHERE room_number = ?",
            (room_number,),
        ).fetchone()
    if existing is not None:
        log_operation(
            "duplicate_report_blocked",
            "重复填报被拦截",
            f"{room_name} 已有未验收数据，系统拒绝重新填报。",
            severity="warning",
            actor_ip=client_ip,
            room_name=room_name,
            details={"roomNumber": room_number},
        )
        raise AppError(
            HTTPStatus.CONFLICT,
            "PENDING_ACCEPTANCE",
            PENDING_ACCEPTANCE_MESSAGE,
        )
    return {
        "available": True,
        "roomName": room_name,
        "roomNumber": room_number,
    }


def calculate_draft_totals(conn, exclude_room_number=None, include_report=None):
    rows = conn.execute(
        """
        SELECT room_number, expected_count, actual_count, absent_count
        FROM current_report_drafts
        """
    ).fetchall()
    items = [
        {
            "room_number": row["room_number"],
            "expected_count": row["expected_count"],
            "actual_count": row["actual_count"],
            "absent_count": row["absent_count"],
        }
        for row in rows
        if row["room_number"] != exclude_room_number
    ]
    if include_report is not None:
        items.append(include_report)
    total_expected = sum(item["expected_count"] for item in items)
    total_actual = sum(item["actual_count"] for item in items)
    total_absent = sum(item["absent_count"] for item in items)
    total_rate = 0 if total_expected == 0 else total_actual / total_expected
    return total_expected, total_actual, total_absent, round(total_rate, 4)


def update_report_totals_for_batch(conn, batch_token):
    rows = conn.execute(
        """
        SELECT report_id FROM current_report_drafts
        WHERE batch_token = ? AND report_id IS NOT NULL
        """,
        (batch_token,),
    ).fetchall()
    report_ids = [row["report_id"] for row in rows]
    if not report_ids:
        return
    totals = conn.execute(
        f"""
        SELECT
            COALESCE(SUM(expected_count), 0) AS total_expected,
            COALESCE(SUM(actual_count), 0) AS total_actual
        FROM absence_reports
        WHERE id IN ({",".join("?" for _ in report_ids)})
        """,
        report_ids,
    ).fetchone()
    total_expected = totals["total_expected"] or 0
    total_actual = totals["total_actual"] or 0
    total_rate = 0 if total_expected == 0 else total_actual / total_expected
    conn.execute(
        f"""
        UPDATE absence_reports
        SET total_count = ?, total_attendance_rate = ?, updated_at = ?
        WHERE id IN ({",".join("?" for _ in report_ids)})
        """,
        (total_expected, round(total_rate, 4), now_iso(), *report_ids),
    )


def update_report_totals_for_ids(conn, report_ids):
    if not report_ids:
        return 0, 0, 0, 0
    placeholders = ",".join("?" for _ in report_ids)
    totals = conn.execute(
        f"""
        SELECT
            COALESCE(SUM(expected_count), 0) AS total_expected,
            COALESCE(SUM(actual_count), 0) AS total_actual,
            COALESCE(SUM(absent_count), 0) AS total_absent
        FROM absence_reports
        WHERE id IN ({placeholders})
        """,
        report_ids,
    ).fetchone()
    total_expected = totals["total_expected"] or 0
    total_actual = totals["total_actual"] or 0
    total_absent = totals["total_absent"] or 0
    total_rate = 0 if total_expected == 0 else total_actual / total_expected
    total_rate = round(total_rate, 4)
    conn.execute(
        f"""
        UPDATE absence_reports
        SET total_count = ?, total_attendance_rate = ?, updated_at = ?
        WHERE id IN ({placeholders})
        """,
        (total_expected, total_rate, now_iso(), *report_ids),
    )
    return total_expected, total_actual, total_absent, total_rate


def migrate_current_drafts_to_reports():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM current_report_drafts
            WHERE report_id IS NULL
            ORDER BY room_number ASC
            """
        ).fetchall()
        if not rows:
            return
        batch_token = get_setting("current_batch_token", "") or secrets.token_urlsafe(12)
        set_setting("current_batch_token", batch_token)
        total_expected = sum(row["expected_count"] for row in rows)
        total_actual = sum(row["actual_count"] for row in rows)
        total_rate = 0 if total_expected == 0 else total_actual / total_expected
        for row in rows:
            cursor = conn.execute(
                """
                INSERT INTO absence_reports (
                    title, exam_date, session_name, room_name, room_number, reporter_name,
                    expected_count, actual_count, absent_count, attendance_rate,
                    total_count, total_attendance_rate, batch_token,
                    client_ip, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["title"],
                    row["exam_date"],
                    "",
                    row["room_name"],
                    row["room_number"],
                    "现场填报",
                    row["expected_count"],
                    row["actual_count"],
                    row["absent_count"],
                    row["attendance_rate"],
                    total_expected,
                    round(total_rate, 4),
                    batch_token,
                    row["client_ip"],
                    row["created_at"],
                    row["updated_at"],
                ),
            )
            conn.execute(
                """
                UPDATE current_report_drafts
                SET report_id = ?, batch_token = ?
                WHERE room_number = ?
                """,
                (cursor.lastrowid, batch_token, row["room_number"]),
            )


ROOM_LIST_LOCK = qk_config.ROOM_LIST_LOCK  # 说明见 qk_config


def upsert_current_report_draft(payload, client_ip, admin_edit_room=None):
    with ROOM_LIST_LOCK:
        return _upsert_current_report_draft(payload, client_ip, admin_edit_room)


def _upsert_current_report_draft(payload, client_ip, admin_edit_room=None):
    qk_agents.require_open_session()
    raw_report = payload.get("report") if isinstance(payload.get("report"), dict) else payload
    if not isinstance(raw_report, dict):
        raise AppError(
            HTTPStatus.BAD_REQUEST,
            "VALIDATION_ERROR",
            "教室数据格式不正确",
        )

    # 老师只能填报：不接受 previousRoomName/password（旧版前台带来的修改入口一律当作「重复填报」处理）。
    # 管理员改已提交的数据走 admin_edit_current_report（后台登录态）。
    previous_room_name = admin_edit_room or ""
    previous_room_number = room_number_from_name(previous_room_name) if previous_room_name else None
    data = validate_report(raw_report)
    now = now_iso()
    is_editing = previous_room_number is not None

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        qk_agents.require_open_session(conn)
        # 标题和考试日期由管理员下发时设定，老师填什么都不算数
        # 场次设置缺失（极端损坏）时也不回退成老师填的值：用已有草稿的，再不行用默认
        title_row = conn.execute("SELECT value FROM app_settings WHERE key='current_project_title'").fetchone()
        date_row = conn.execute("SELECT value FROM app_settings WHERE key='current_exam_date'").fetchone()
        any_draft = conn.execute("SELECT title, exam_date FROM current_report_drafts ORDER BY room_number LIMIT 1").fetchone()
        data["title"] = (title_row and title_row["value"]) or (any_draft and any_draft["title"]) or f"出考率信息 {today_str()}"
        data["exam_date"] = (date_row and date_row["value"]) or (any_draft and any_draft["exam_date"]) or today_str()
        existing_target = conn.execute(
            "SELECT * FROM current_report_drafts WHERE room_number = ?",
            (data["room_number"],),
        ).fetchone()
        previous_draft = None
        if previous_room_number is not None:
            previous_draft = conn.execute(
                "SELECT * FROM current_report_drafts WHERE room_number = ?",
                (previous_room_number,),
            ).fetchone()

        if previous_room_number is not None:
            if previous_draft is None:
                raise AppError(
                    HTTPStatus.NOT_FOUND,
                    "NOT_FOUND",
                    "要修改的教室数据不存在",
                )
            if existing_target is not None and existing_target["room_number"] != previous_room_number:
                write_failure_log(
                    conn,
                    "duplicate_report_blocked",
                    "重复填报被拦截",
                    f"{data['room_name']} 已有未验收数据，系统拒绝覆盖其他教室数据。",
                    severity="warning",
                    actor_ip=client_ip,
                    room_name=data["room_name"],
                    report_id=existing_target["report_id"],
                    batch_token=existing_target["batch_token"] or "",
                    details={
                        "previousRoomName": previous_room_name,
                        "targetRoomName": data["room_name"],
                    },
                )
                raise AppError(
                    HTTPStatus.CONFLICT,
                    "PENDING_ACCEPTANCE",
                    PENDING_ACCEPTANCE_MESSAGE,
                )
        elif existing_target is not None:
            write_failure_log(
                conn,
                "duplicate_report_blocked",
                "重复填报被拦截",
                f"{data['room_name']} 已有未验收数据，系统拒绝重新填报。",
                severity="warning",
                actor_ip=client_ip,
                room_name=data["room_name"],
                report_id=existing_target["report_id"],
                batch_token=existing_target["batch_token"] or "",
                details={"roomNumber": data["room_number"]},
            )
            raise AppError(
                HTTPStatus.CONFLICT,
                "PENDING_ACCEPTANCE",
                PENDING_ACCEPTANCE_MESSAGE,
            )

        batch_token = (
            previous_draft["batch_token"]
            if previous_draft and previous_draft["batch_token"]
            else get_setting("current_batch_token", "")
        )
        if not batch_token:
            batch_token = secrets.token_urlsafe(12)
            qk_agents.put_setting(conn, "current_batch_token", batch_token)

        total_expected, _total_actual, _total_absent, total_rate = calculate_draft_totals(
            conn,
            exclude_room_number=previous_room_number or data["room_number"],
            include_report=data,
        )
        data["total_count"] = total_expected
        data["total_attendance_rate"] = total_rate
        data["batch_token"] = batch_token

        if previous_draft and previous_draft["report_id"]:
            report_id = previous_draft["report_id"]
            conn.execute(
                """
                UPDATE absence_reports
                SET title = :title,
                    exam_date = :exam_date,
                    exam_time = :exam_time,
                    session_name = :session_name,
                    room_name = :room_name,
                    room_number = :room_number,
                    subject_name = :subject_name,
                    class_name = :class_name,
                    reporter_name = :reporter_name,
                    reporter_contact = :reporter_contact,
                    expected_count = :expected_count,
                    actual_count = :actual_count,
                    absent_count = :absent_count,
                    attendance_rate = :attendance_rate,
                    total_count = :total_count,
                    total_attendance_rate = :total_attendance_rate,
                    batch_token = :batch_token,
                    absent_students_text = :absent_students_text,
                    remark = :remark,
                    client_ip = :client_ip,
                    updated_at = :updated_at
                WHERE id = :report_id
                """,
                {
                    **data,
                    "client_ip": client_ip,
                    "updated_at": now,
                    "report_id": report_id,
                },
            )
        else:
            cursor = conn.execute(
                """
                INSERT INTO absence_reports (
                    title, exam_date, exam_time, session_name, room_name, room_number,
                    subject_name, class_name, reporter_name, reporter_contact,
                    expected_count, actual_count, absent_count, attendance_rate,
                    total_count, total_attendance_rate, batch_token,
                    absent_students_text, remark, client_ip, created_at, updated_at
                ) VALUES (
                    :title, :exam_date, :exam_time, :session_name, :room_name, :room_number,
                    :subject_name, :class_name, :reporter_name, :reporter_contact,
                    :expected_count, :actual_count, :absent_count, :attendance_rate,
                    :total_count, :total_attendance_rate, :batch_token,
                    :absent_students_text, :remark, :client_ip, :created_at,
                    :updated_at
                )
                """,
                {
                    **data,
                    "client_ip": client_ip,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            report_id = cursor.lastrowid

        if previous_room_number is not None and previous_room_number != data["room_number"]:
            conn.execute(
                "DELETE FROM current_report_drafts WHERE room_number = ?",
                (previous_room_number,),
            )

        existing_current = conn.execute(
            "SELECT created_at FROM current_report_drafts WHERE room_number = ?",
            (data["room_number"],),
        ).fetchone()
        created_at = (
            existing_current["created_at"]
            if existing_current
            else (previous_draft["created_at"] if previous_draft else now)
        )
        conn.execute(
            """
            INSERT INTO current_report_drafts (
                room_number, report_id, batch_token, room_name, title, exam_date,
                expected_count, actual_count, absent_count, attendance_rate,
                client_ip, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(room_number) DO UPDATE SET
                report_id = excluded.report_id,
                batch_token = excluded.batch_token,
                room_name = excluded.room_name,
                title = excluded.title,
                exam_date = excluded.exam_date,
                expected_count = excluded.expected_count,
                actual_count = excluded.actual_count,
                absent_count = excluded.absent_count,
                attendance_rate = excluded.attendance_rate,
                client_ip = excluded.client_ip,
                updated_at = excluded.updated_at
            """,
            (
                data["room_number"],
                report_id,
                batch_token,
                data["room_name"],
                data["title"],
                data["exam_date"],
                data["expected_count"],
                data["actual_count"],
                data["absent_count"],
                data["attendance_rate"],
                client_ip,
                created_at,
                now,
            ),
        )
        update_report_totals_for_batch(conn, batch_token)
        write_operation_log(
            conn,
            "report_updated" if is_editing else "report_submitted",
            "教室数据已修改" if is_editing else "教室数据已提交",
            (
                f"{data['room_name']} 数据已修改：应到 {data['expected_count']}，"
                f"实到 {data['actual_count']}，缺考 {data['absent_count']}。"
                if is_editing
                else f"{data['room_name']} 已提交：应到 {data['expected_count']}，"
                f"实到 {data['actual_count']}，缺考 {data['absent_count']}。"
            ),
            actor_ip=client_ip,
            room_name=data["room_name"],
            report_id=report_id,
            batch_token=batch_token,
            details={
                "title": data["title"],
                "examDate": data["exam_date"],
                "expectedCount": data["expected_count"],
                "actualCount": data["actual_count"],
                "absentCount": data["absent_count"],
                "previousRoomName": previous_room_name,
            },
        )

    return list_current_report_drafts()


def accept_reports(payload, client_ip):
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        count_row = conn.execute(
            "SELECT COUNT(*) AS draft_count FROM current_report_drafts"
        ).fetchone()
        draft_count = count_row["draft_count"] if count_row else 0
        if draft_count <= 0 and qk_agents.session_is_open(conn):
            # 场次已开放但没人提交（或唯一一条被删）：验收只关闭场次，否则场次永远关不掉
            qk_agents.put_setting(conn, "session_state", "closed")
            write_operation_log(conn, "session_closed", "场次已关闭", "验收完成，当前场次已关闭（没有未验收数据）。", actor_ip=client_ip)
            write_operation_log(conn, "reports_accepted", "当前数据已验收", "验收完成：本场没有教室提交数据。", actor_ip=client_ip,
                                details={"clearedCount": 0})
            return {"clearedCount": 0, "savedCount": 0, "batchToken": "", "message": "当前场次已关闭，本场没有教室提交数据。"}
        if draft_count <= 0:
            write_failure_log(
                conn,
                "accept_failed",
                "验收失败",
                "当前没有可验收的数据，未执行清空。",
                severity="warning",
                actor_ip=client_ip,
            )
            raise AppError(
                HTTPStatus.BAD_REQUEST,
                "VALIDATION_ERROR",
                "当前没有可验收的数据",
            )
        batch_token = get_setting("current_batch_token", "")
        rows = conn.execute(
            """
            SELECT room_name, expected_count, actual_count, absent_count
            FROM current_report_drafts
            ORDER BY room_number ASC
            """
        ).fetchall()
        total_expected = sum(row["expected_count"] for row in rows)
        total_actual = sum(row["actual_count"] for row in rows)
        total_absent = sum(row["absent_count"] for row in rows)
        conn.execute("DELETE FROM current_report_drafts")
        qk_agents.put_setting(conn, "session_state", "closed")
        write_operation_log(conn, "session_closed", "场次已关闭", "验收完成，当前场次已关闭。", actor_ip=client_ip)
        conn.execute(
            "DELETE FROM app_settings WHERE key = ?",
            ("current_batch_token",),
        )
        write_operation_log(
            conn,
            "reports_accepted",
            "当前数据已验收",
            f"验收完成：本场 {draft_count} 间教室的数据已入库，场次已关闭。",
            actor_ip=client_ip,
            batch_token=batch_token,
            details={
                "clearedCount": draft_count,
                "totalExpected": total_expected,
                "totalActual": total_actual,
                "totalAbsent": total_absent,
                "rooms": [row["room_name"] for row in rows],
            },
        )

    return {
        "clearedCount": draft_count,
        "savedCount": draft_count,
        "batchToken": batch_token,
        "message": f"验收完成：本场 {draft_count} 间教室的数据已入库，场次已关闭。",
    }


def parse_filter_values(query):
    date = (query.get("date") or [""])[0].strip()
    keyword = (query.get("keyword") or [""])[0].strip()

    if date:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError as exc:
            raise AppError(
                HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "筛选日期格式不正确"
            ) from exc

    return date, keyword


def build_filters(query):
    clauses = []
    params = {}
    date, keyword = parse_filter_values(query)

    if date:
        clauses.append("exam_date = :date")
        params["date"] = date

    if keyword:
        clauses.append(
            """
            (
                title LIKE :keyword OR room_name LIKE :keyword OR
                batch_token LIKE :keyword
            )
            """
        )
        params["keyword"] = f"%{keyword}%"

    where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where_sql, params


def build_date_filter(query):
    date, _keyword = parse_filter_values(query)
    if not date:
        return "", {}
    return " WHERE exam_date = :date", {"date": date}


def like_pattern(value):
    """把 % _ \\ 当普通字符：用户搜「银_」不应该匹配「银行」。"""
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def range_filter(query, prefix=""):
    """标题模糊（包含）+ 考试日期范围（含两端）。表格、汇总、导出、数据分析共用这一处，口径才不会各算各的。"""
    def one(key):
        return ((query.get(key) or [""])[0]).strip()
    title, start, end = one("title"), one("from"), one("to")
    if len(title) > 120:  # 与下发时标题的上限一致：能建出来的标题就能原样粘进来搜
        raise AppError(HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "筛选条件过长")
    for value in (start, end):
        if value:
            try:
                # 库里的日期是零填充文本，按文本比较；2026-1-1 这类不补零的写法会悄悄筛空，必须拒绝而不是接受
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError(value)
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError as exc:
                raise AppError(HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "日期格式不正确，应为 YYYY-MM-DD") from exc
    if start and end and start > end:
        raise AppError(HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "开始日期不能晚于结束日期")
    clauses, params = [], {}
    if title:
        clauses.append(f"{prefix}title LIKE :rtitle ESCAPE '\\'")
        params["rtitle"] = like_pattern(title)
    if start:
        clauses.append(f"{prefix}exam_date >= :rstart")
        params["rstart"] = start
    if end:
        clauses.append(f"{prefix}exam_date <= :rend")
        params["rend"] = end
    return clauses, params


def build_report_filter(query, alias=""):
    date, keyword = parse_filter_values(query)
    prefix = f"{alias}." if alias else ""
    clauses, params = range_filter(query, prefix)
    if date:
        clauses.append(f"{prefix}exam_date = :date")
        params["date"] = date
    if keyword:
        clauses.append(
            f"""
            (
                {prefix}title LIKE :keyword OR {prefix}room_name LIKE :keyword OR
                {prefix}batch_token LIKE :keyword OR {prefix}exam_date LIKE :keyword OR
                {prefix}created_at LIKE :keyword
            )
            """
        )
        params["keyword"] = f"%{keyword}%"
    where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where_sql, params


def parse_page(query):
    try:
        page = int((query.get("page") or ["1"])[0])
        page_size = int((query.get("pageSize") or ["20"])[0])
    except ValueError as exc:
        raise AppError(
            HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "分页参数格式不正确"
        ) from exc
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    return page, page_size


def report_group_key(report):
    group_token = report["batchToken"] or f'created:{report["createdAt"]}'
    return (report["examDate"], report["title"], group_token)


def room_sort_value(report):
    room_number = report["roomNumber"]
    return room_number if room_number is not None else 9999


def date_sort_value(date_text):
    try:
        return -datetime.strptime(date_text, "%Y-%m-%d").toordinal()
    except ValueError:
        return 0


def datetime_desc_sort_value(datetime_text):
    try:
        return -datetime.fromisoformat(datetime_text).timestamp()
    except (TypeError, ValueError):
        return 0


def room_summary(items):
    if not items:
        return "-"
    if len(items) == 1:
        return items[0]["roomName"]
    return f'{items[0]["roomName"]}等 {len(items)} 间'


def group_reports(rows, include_items=False):
    groups_by_key = {}
    for row in rows:
        report = row_to_report(row)
        key = report_group_key(report)
        group = groups_by_key.setdefault(
            key,
            {
                "title": report["title"],
                "examDate": report["examDate"],
                "batchToken": report["batchToken"],
                "manualSessionName": report["manualSessionName"],
                "items": [],
            },
        )
        group["items"].append(report)

    groups = []
    for group in groups_by_key.values():
        items = sorted(
            group["items"],
            key=lambda item: (room_sort_value(item), item["roomName"], item["id"]),
        )
        total_expected = sum(item["expectedCount"] for item in items)
        total_actual = sum(item["actualCount"] for item in items)
        total_absent = sum(item["absentCount"] for item in items)
        attendance_rate = 0 if total_expected == 0 else total_actual / total_expected
        first_created = min(item["createdAt"] for item in items)
        latest_created = max(item["createdAt"] for item in items)
        latest_updated = max(item["updatedAt"] for item in items)
        first_item = items[0]
        grouped_report = {
            "id": first_item["id"],
            "title": group["title"],
            "examDate": group["examDate"],
            "examTime": first_item["examTime"],
            "manualSessionName": group["manualSessionName"],
            "roomName": room_summary(items),
            "roomSummary": room_summary(items),
            "roomCount": len(items),
            "firstRoomNumber": room_sort_value(first_item),
            "expectedCount": total_expected,
            "actualCount": total_actual,
            "absentCount": total_absent,
            "attendanceRate": round(attendance_rate, 4),
            "totalCount": total_expected,
            "totalAttendanceRate": round(attendance_rate, 4),
            "batchToken": group["batchToken"],
            "firstCreatedAt": first_created,
            "createdAt": latest_created,
            "updatedAt": latest_updated,
        }
        if include_items:
            grouped_report["items"] = items
        groups.append(grouped_report)

    session_groups = {}
    for group in groups:
        session_groups.setdefault((group["examDate"], group["title"]), []).append(group)
    for session_items in session_groups.values():
        session_items.sort(key=lambda item: (item["firstCreatedAt"], item["id"]))
        for index, group in enumerate(session_items, start=1):
            group["sessionNumber"] = index
            group["sessionName"] = group["manualSessionName"] or f"第{index}场"

    groups.sort(
        key=lambda item: (
            datetime_desc_sort_value(item["createdAt"]),
            item["sessionNumber"],
            date_sort_value(item["examDate"]),
            item["title"],
            -item["id"],
        )
    )
    return groups


def group_matches_keyword(group, keyword):
    if not keyword:
        return True
    keyword = keyword.lower()
    searchable = [
        group["title"],
        group["examDate"],
        group["sessionName"],
        group["batchToken"],
        group["roomSummary"],
    ]
    searchable.extend(item["roomName"] for item in group.get("items", []))
    return any(keyword in str(value or "").lower() for value in searchable)


def report_group_expression(alias=""):
    prefix = f"{alias}." if alias else ""
    return f"""
        {prefix}exam_date || char(31) || {prefix}title || char(31) ||
        COALESCE(NULLIF({prefix}batch_token, ''), 'created:' || {prefix}created_at)
    """


def build_report_group_filter(query):
    return build_report_filter(query, alias="r")


def fetch_report_groups(query, *, include_items=False, limit=None, offset=0):
    where_sql, params = build_report_group_filter(query)
    group_expr = report_group_expression("r")
    paging_sql = ""
    paging_params = dict(params)
    if limit is not None:
        paging_sql = " LIMIT :limit OFFSET :offset"
        paging_params.update({"limit": limit, "offset": offset})
    with get_db() as conn:
        key_rows = conn.execute(
            f"""
            SELECT
                {group_expr} AS group_key,
                MIN(r.id) AS first_id,
                MAX(r.id) AS latest_id,
                MAX(r.exam_date) AS group_exam_date,
                MAX(r.created_at) AS latest_created
            FROM absence_reports r
            {where_sql}
            GROUP BY group_key
            ORDER BY
                group_exam_date DESC,
                latest_created DESC,
                latest_id DESC
            {paging_sql}
            """,
            paging_params,
        ).fetchall()
        group_keys = [row["group_key"] for row in key_rows]
        if not group_keys:
            return []
        row_group_expr = report_group_expression()
        rows = conn.execute(
            f"""
            SELECT *, {row_group_expr} AS group_key
            FROM absence_reports
            WHERE {row_group_expr} IN ({",".join("?" for _ in group_keys)})
            ORDER BY
                created_at DESC,
                COALESCE(room_number, 9999) ASC,
                room_name ASC,
                id ASC
            """,
            group_keys,
        ).fetchall()
    groups = group_reports(rows, include_items=True)
    order = {row["group_key"]: index for index, row in enumerate(key_rows)}
    groups.sort(key=lambda group: order.get(report_group_key_text(group), len(order)))
    apply_session_numbers(groups)
    if not include_items:
        for group in groups:
            group.pop("items", None)
    return groups


def report_group_key_text(report):
    group_token = report["batchToken"] or f'created:{report.get("firstCreatedAt") or report["createdAt"]}'
    return "\x1f".join((report["examDate"], report["title"], group_token))


def apply_session_numbers(groups):
    if not groups:
        return
    pairs = sorted({(group["examDate"], group["title"]) for group in groups})
    session_by_key = {}
    with get_db() as conn:
        for exam_date, title in pairs:
            rows = conn.execute(
                f"""
                SELECT
                    {report_group_expression()} AS group_key,
                    MIN(id) AS first_id,
                    MIN(created_at) AS first_created
                FROM absence_reports
                WHERE exam_date = ? AND title = ?
                GROUP BY group_key
                ORDER BY first_created ASC, first_id ASC
                """,
                (exam_date, title),
            ).fetchall()
            for index, row in enumerate(rows, start=1):
                session_by_key[row["group_key"]] = (index, f"第{index}场")
    for group in groups:
        session = session_by_key.get(report_group_key_text(group))
        if session:
            group["sessionNumber"] = session[0]
            group["sessionName"] = group.get("manualSessionName") or session[1]


def count_report_groups(query):
    where_sql, params = build_report_group_filter(query)
    group_expr = report_group_expression("r")
    with get_db() as conn:
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM (
                SELECT {group_expr} AS group_key
                FROM absence_reports r
                {where_sql}
                GROUP BY group_key
            )
            """,
            params,
        ).fetchone()
    return row["total"] if row else 0


def query_grouped_reports(query, include_items=False):
    return fetch_report_groups(query, include_items=include_items)


def list_reports(query):
    page, page_size = parse_page(query)
    offset = (page - 1) * page_size
    total = count_report_groups(query)
    groups = fetch_report_groups(
        query,
        include_items=False,
        limit=page_size,
        offset=offset,
    )
    return {
        "items": groups,
        "total": total,
        "page": page,
        "pageSize": page_size,
    }


def summarize_reports(query):
    where_sql, params = build_report_group_filter(query)
    matched_group_expr = report_group_expression("r")
    row_group_expr = report_group_expression("a")
    with get_db() as conn:
        row = conn.execute(
            f"""
            WITH matched_groups AS (
                SELECT {matched_group_expr} AS group_key
                FROM absence_reports r
                {where_sql}
                GROUP BY group_key
            ),
            grouped_reports AS (
                SELECT
                    {row_group_expr} AS group_key,
                    SUM(a.expected_count) AS expected_sum,
                    SUM(a.actual_count) AS actual_sum,
                    SUM(a.absent_count) AS absent_sum
                FROM absence_reports a
                WHERE {row_group_expr} IN (SELECT group_key FROM matched_groups)
                GROUP BY group_key
            )
            SELECT
                COUNT(*) AS report_count,
                COALESCE(SUM(expected_sum), 0) AS total_expected,
                COALESCE(SUM(actual_sum), 0) AS total_actual,
                COALESCE(SUM(absent_sum), 0) AS total_absent
            FROM grouped_reports
            """,
            params,
        ).fetchone()
    total_expected = row["total_expected"] if row else 0
    total_actual = row["total_actual"] if row else 0
    total_absent = row["total_absent"] if row else 0
    overall_rate = 0 if total_expected == 0 else total_actual / total_expected
    return {
        "reportCount": row["report_count"] if row else 0,
        "totalExpectedCount": total_expected,
        "totalActualCount": total_actual,
        "totalAbsentCount": total_absent,
        "overallAttendanceRate": round(overall_rate, 4),
    }


def get_report(report_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM absence_reports WHERE id = ?", (report_id,)
        ).fetchone()
        if row is None:
            raise AppError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "上报记录不存在")
        report = row_to_report(row)
        if report["batchToken"]:
            rows = conn.execute(
                """
                SELECT * FROM absence_reports
                WHERE exam_date = ? AND title = ? AND batch_token = ?
                ORDER BY COALESCE(room_number, 9999) ASC, room_name ASC, id ASC
                """,
                (report["examDate"], report["title"], report["batchToken"]),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM absence_reports
                WHERE exam_date = ? AND title = ? AND created_at = ?
                ORDER BY COALESCE(room_number, 9999) ASC, room_name ASC, id ASC
                """,
                (report["examDate"], report["title"], report["createdAt"]),
            ).fetchall()
    grouped = group_reports(rows, include_items=True)
    if not grouped:
        raise AppError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "上报记录不存在")
    all_groups = query_grouped_reports(
        {"date": [report["examDate"]], "keyword": [report["title"]]},
    )
    session_by_key = {
        report_group_key(group): (group["sessionNumber"], group["sessionName"])
        for group in all_groups
        if group["title"] == report["title"]
    }
    target_key = report_group_key(report)
    for group in grouped:
        for item in group["items"]:
            if report_group_key(item) == target_key:
                if target_key in session_by_key:
                    group["sessionNumber"], group["sessionName"] = session_by_key[
                        target_key
                    ]
                return group
    fallback_key = report_group_key(grouped[0])
    if fallback_key in session_by_key:
        grouped[0]["sessionNumber"], grouped[0]["sessionName"] = session_by_key[
            fallback_key
        ]
    return grouped[0]


def update_report_group(report_id, payload, client_ip=""):
    title = normalize_text(payload, "title", required=True, max_len=120)
    exam_date = normalize_optional_date(payload, "examDate")
    session_name = normalize_session_name(payload)
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise AppError(HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "请填写教室数据")

    updates = {}
    for item in items:
        if not isinstance(item, dict):
            raise AppError(HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "教室数据格式不正确")
        item_id = item.get("id")
        try:
            item_id = int(item_id)
        except (TypeError, ValueError) as exc:
            raise AppError(
                HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "记录 ID 格式不正确"
            ) from exc
        expected_count = normalize_count(item, "expectedCount", "应到人数")
        actual_count = normalize_count(item, "actualCount", "实到人数")
        if actual_count > expected_count:
            raise AppError(
                HTTPStatus.BAD_REQUEST,
                "VALIDATION_ERROR",
                "实到人数不能大于应到人数",
            )
        absent_count = expected_count - actual_count
        attendance_rate = 0 if expected_count == 0 else actual_count / expected_count
        updates[item_id] = {
            "expected_count": expected_count,
            "actual_count": actual_count,
            "absent_count": absent_count,
            "attendance_rate": round(attendance_rate, 4),
        }

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM absence_reports WHERE id = ?", (report_id,)
        ).fetchone()
        if row is None:
            raise AppError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "上报记录不存在")
        if row["batch_token"]:
            rows = conn.execute(
                """
                SELECT * FROM absence_reports
                WHERE exam_date = ? AND title = ? AND batch_token = ?
                ORDER BY COALESCE(room_number, 9999) ASC, room_name ASC, id ASC
                """,
                (row["exam_date"], row["title"], row["batch_token"]),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM absence_reports
                WHERE exam_date = ? AND title = ? AND created_at = ?
                ORDER BY COALESCE(room_number, 9999) ASC, room_name ASC, id ASC
                """,
                (row["exam_date"], row["title"], row["created_at"]),
            ).fetchall()

        report_ids = [item["id"] for item in rows]
        if set(updates) != set(report_ids):
            raise AppError(
                HTTPStatus.BAD_REQUEST,
                "VALIDATION_ERROR",
                "提交的教室记录和当前场次不一致，请刷新后重试",
            )

        previous_summary = {
            "title": row["title"],
            "examDate": row["exam_date"],
            "sessionName": row["session_name"] or "",
            "rooms": [
                {
                    "id": item["id"],
                    "roomName": item["room_name"],
                    "expectedCount": item["expected_count"],
                    "actualCount": item["actual_count"],
                    "absentCount": item["absent_count"],
                }
                for item in rows
            ],
        }
        updated_at = now_iso()
        for item in rows:
            values = updates[item["id"]]
            conn.execute(
                """
                UPDATE absence_reports
                SET title = ?,
                    exam_date = ?,
                    session_name = ?,
                    expected_count = ?,
                    actual_count = ?,
                    absent_count = ?,
                    attendance_rate = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    title,
                    exam_date,
                    session_name,
                    values["expected_count"],
                    values["actual_count"],
                    values["absent_count"],
                    values["attendance_rate"],
                    updated_at,
                    item["id"],
                ),
            )
            conn.execute(
                """
                UPDATE current_report_drafts
                SET title = ?,
                    exam_date = ?,
                    expected_count = ?,
                    actual_count = ?,
                    absent_count = ?,
                    attendance_rate = ?,
                    updated_at = ?
                WHERE report_id = ?
                """,
                (
                    title,
                    exam_date,
                    values["expected_count"],
                    values["actual_count"],
                    values["absent_count"],
                    values["attendance_rate"],
                    updated_at,
                    item["id"],
                ),
            )
        totals = update_report_totals_for_ids(conn, report_ids)
        write_operation_log(
            conn,
            "report_group_updated",
            "后台数据已修改",
            f"已修改“{row['title']}” {row['exam_date']} 的 {len(report_ids)} 条教室记录。",
            actor_ip=client_ip,
            room_name=room_summary([{"roomName": item["room_name"]} for item in rows]),
            report_id=report_id,
            batch_token=row["batch_token"] or "",
            details={
                "previous": previous_summary,
                "next": {
                    "title": title,
                    "examDate": exam_date,
                    "sessionName": session_name,
                    "totalExpected": totals[0],
                    "totalActual": totals[1],
                    "totalAbsent": totals[2],
                    "totalAttendanceRate": totals[3],
                },
            },
        )

    return get_report(report_id)


def delete_report_group(report_id, payload, client_ip=""):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM absence_reports WHERE id = ?", (report_id,)
        ).fetchone()
        if row is None:
            raise AppError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "上报记录不存在")

        if row["batch_token"]:
            rows = conn.execute(
                """
                SELECT id FROM absence_reports
                WHERE exam_date = ? AND title = ? AND batch_token = ?
                ORDER BY id ASC
                """,
                (row["exam_date"], row["title"], row["batch_token"]),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id FROM absence_reports
                WHERE exam_date = ? AND title = ? AND created_at = ?
                ORDER BY id ASC
                """,
                (row["exam_date"], row["title"], row["created_at"]),
            ).fetchall()

        report_ids = [item["id"] for item in rows]
        if not report_ids:
            raise AppError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "上报记录不存在")
        deleted_rooms = conn.execute(
            f"""
            SELECT room_name, expected_count, actual_count, absent_count
            FROM absence_reports
            WHERE id IN ({",".join("?" for _ in report_ids)})
            ORDER BY COALESCE(room_number, 9999) ASC, room_name ASC
            """,
            report_ids,
        ).fetchall()

        placeholders = ",".join("?" for _ in report_ids)
        conn.execute(
            f"DELETE FROM current_report_drafts WHERE report_id IN ({placeholders})",
            report_ids,
        )
        conn.execute(
            f"DELETE FROM absence_reports WHERE id IN ({placeholders})",
            report_ids,
        )

        if row["batch_token"]:
            remaining_drafts = conn.execute(
                """
                SELECT COUNT(*) AS draft_count
                FROM current_report_drafts
                WHERE batch_token = ?
                """,
                (row["batch_token"],),
            ).fetchone()
            if not remaining_drafts or remaining_drafts["draft_count"] == 0:
                current_batch_row = conn.execute(
                    "SELECT value FROM app_settings WHERE key = ?",
                    ("current_batch_token",),
                ).fetchone()
                current_batch = current_batch_row["value"] if current_batch_row else ""
                if current_batch == row["batch_token"]:
                    conn.execute(
                        "DELETE FROM app_settings WHERE key = ?",
                        ("current_batch_token",),
                    )
        write_operation_log(
            conn,
            "reports_deleted",
            "后台记录已删除",
            f"已永久删除“{row['title']}” {row['exam_date']} 的 {len(report_ids)} 条教室记录。",
            severity="warning",
            actor_ip=client_ip,
            room_name=room_summary([{"roomName": item["room_name"]} for item in deleted_rooms]),
            report_id=report_id,
            batch_token=row["batch_token"] or "",
            details={
                "deletedIds": report_ids,
                "title": row["title"],
                "examDate": row["exam_date"],
                "rooms": [item["room_name"] for item in deleted_rooms],
            },
        )

    return {
        "deletedCount": len(report_ids),
        "title": row["title"],
        "examDate": row["exam_date"],
    }


def export_reports_csv(query):
    groups = query_grouped_reports(query, include_items=True)

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(
        [
            "记录ID",
            "标题",
            "日期",
            "场次",
            "考试时间",
            "教室",
            "教室编号",
            "科目",
            "班级",
            "上报人",
            "联系方式",
            "应到",
            "实到",
            "缺考",
            "出考率",
            "总数",
            "总出考率",
            "验收批次",
            "缺考学生",
            "备注",
            "提交时间",
            "更新时间",
            "提交 IP",
        ]
    )
    for group in groups:
        for report in group["items"]:
            writer.writerow(
                [
                    report["id"],
                    report["title"],
                    report["examDate"],
                    group["sessionName"],
                    report["examTime"],
                    report["roomName"],
                    report["roomNumber"] or "",
                    report["subjectName"],
                    report["className"],
                    report["reporterName"],
                    report["reporterContact"],
                    report["expectedCount"],
                    report["actualCount"],
                    report["absentCount"],
                    f'{report["attendanceRate"] * 100:.2f}%',
                    report["totalCount"],
                    f'{report["totalAttendanceRate"] * 100:.2f}%',
                    report["batchToken"],
                    report["absentStudentsText"],
                    report["remark"],
                    report["createdAt"],
                    report["updatedAt"],
                    report["clientIp"],
                ]
            )
    return output.getvalue().encode("utf-8")


def text_value(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_excel_number(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text.replace("%", "")))
    except ValueError:
        return None


def parse_excel_int(value):
    number = parse_excel_number(value)
    return number if number is not None else None


def extract_title_from_excel_text(value):
    text = text_value(value)
    if not text:
        return ""
    match = re.search(r"[（(]([^（）()]+)[）)]", text)
    if match:
        return match.group(1).strip()
    org = qk_config.load()["site"]["orgName"]
    if org:
        text = text.replace(org, "")
    text = re.sub(r"出考情况明细表", "", text)
    return text.strip()


def infer_excel_date(sheet_name, title_text=""):
    for source, source_label in ((title_text, "标题"), (sheet_name, "工作表")):
        explicit = re.search(
            r"(20\d{2})[.\-/年](\d{1,2})[.\-/月](\d{1,2})",
            source or "",
        )
        if explicit:
            year, month, day = map(int, explicit.groups())
            return f"{year:04d}-{month:02d}-{day:02d}", f"{source_label}明确日期"
    for source, source_label in ((title_text, "标题"), (sheet_name, "工作表")):
        month_day = re.search(
            r"(?<!\d)(\d{1,2})[.月](\d{1,2})(?:日)?",
            source or "",
        )
        if month_day:
            month, day = map(int, month_day.groups())
            current_date = datetime.now(LOCAL_TZ).date()
            year = current_date.year
            inferred_date = datetime(year, month, day).date()
            if inferred_date > current_date:
                inferred_date = datetime(year - 1, month, day).date()
                return (
                    inferred_date.isoformat(),
                    f"{source_label}按上一年推断",
                )
            return (
                inferred_date.isoformat(),
                f"{source_label}按当前年份推断",
            )
    return "", "缺少日期"


def infer_excel_session(sheet_name, title_text=""):
    chinese_order = (
        ("第一场", "第1场"),
        ("第二场", "第2场"),
        ("第三场", "第3场"),
        ("第四场", "第4场"),
        ("第五场", "第5场"),
        ("第六场", "第6场"),
        ("第七场", "第7场"),
        ("第八场", "第8场"),
        ("第九场", "第9场"),
        ("第十场", "第10场"),
    )
    for source in (title_text or "", sheet_name or ""):
        for key, value in chinese_order:
            if key in source:
                return value
        numbered = re.search(r"第(\d+)场", source)
        if numbered:
            return f"第{int(numbered.group(1))}场"
        for word in ("上午", "下午", "晚上"):
            if word in source:
                return word
    return ""


def column_index(cell_ref):
    letters = re.match(r"[A-Z]+", cell_ref or "")
    if not letters:
        return 0
    index = 0
    for char in letters.group(0):
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def parse_excel_cell_value(cell, shared_strings):
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        text_parts = [
            node.text or ""
            for node in cell.iter(f"{namespace}t")
        ]
        return "".join(text_parts)
    value_node = cell.find(f"{namespace}v")
    if value_node is None:
        return ""
    raw = value_node.text or ""
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError):
            return raw
    if cell_type == "b":
        return "TRUE" if raw == "1" else "FALSE"
    try:
        number = float(raw)
    except ValueError:
        return raw
    return int(number) if number.is_integer() else number


def read_xlsx_shared_strings(zf):
    path = "xl/sharedStrings.xml"
    if path not in zf.namelist():
        return []
    root = ET.fromstring(zf.read(path))
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    values = []
    for item in root.findall(f"{namespace}si"):
        values.append("".join(node.text or "" for node in item.iter(f"{namespace}t")))
    return values


def read_xlsx_workbook(zf):
    rels_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_namespace = "{http://schemas.openxmlformats.org/package/2006/relationships}"
    rels = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels_root.findall(f"{rel_namespace}Relationship")
    }
    workbook_root = ET.fromstring(zf.read("xl/workbook.xml"))
    main_namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel_attr = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    sheets = []
    for sheet in workbook_root.findall(f".//{main_namespace}sheet"):
        target = rels.get(sheet.attrib.get(rel_attr, ""), "")
        if target and not target.startswith("/"):
            target = f"xl/{target}"
        target = target.lstrip("/")
        sheets.append({"name": sheet.attrib.get("name", ""), "path": target})
    return sheets


def read_xlsx_sheet_rows(zf, sheet_path, shared_strings):
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    root = ET.fromstring(zf.read(sheet_path))
    rows = []
    for row_node in root.findall(f".//{namespace}row"):
        try:
            row_number = int(row_node.attrib.get("r", len(rows) + 1))
        except ValueError:
            row_number = len(rows) + 1
        while len(rows) < row_number - 1:
            rows.append([])
        values_by_col = {}
        for cell in row_node.findall(f"{namespace}c"):
            col = column_index(cell.attrib.get("r", ""))
            values_by_col[col] = parse_excel_cell_value(cell, shared_strings)
        if not values_by_col:
            rows.append([])
            continue
        max_col = max(values_by_col)
        rows.append([values_by_col.get(index, "") for index in range(max_col + 1)])
    return rows


def excel_column_maps(row):
    headers = [text_value(value) for value in row]
    maps = []
    for index, value in enumerate(headers):
        if value != "教室":
            continue
        expected = index + 1
        actual = index + 2
        if (
            expected < len(headers)
            and actual < len(headers)
            and headers[expected] == "应到"
            and headers[actual] == "实到"
        ):
            maps.append(
                {
                    "start": max(0, index - 1),
                    "serial": index - 1 if index > 0 else None,
                    "room": index,
                    "expected": expected,
                    "actual": actual,
                    "absent": index + 3 if index + 3 < len(headers) else None,
                    "rate": index + 4 if index + 4 < len(headers) else None,
                    "end": index + 6,
                }
            )
    return maps


def excel_column_map(row):
    maps = excel_column_maps(row)
    return maps[0] if maps else None


def room_name_from_excel(value):
    text = text_value(value)
    if not text:
        return "", None
    room_number = room_number_from_name(text)
    if room_number is None:
        match = re.search(r"(\d+)", text)
        if match:
            room_number = int(match.group(1))
    if room_number is None:
        return text, None
    names = qk_config.room_names()
    if 1 <= room_number <= len(names):
        return names[room_number - 1], room_number
    return text, room_number


def cleaned_excel_room(room_raw, serial_raw):
    room_name, room_number = room_name_from_excel(room_raw)
    serial_number = parse_excel_int(serial_raw)
    corrected = False
    original_room = text_value(room_raw)
    if (
        room_number is not None
        and room_number > len(qk_config.room_names())
        and serial_number is not None
        and 1 <= serial_number <= len(qk_config.room_names())
    ):
        room_number = serial_number
        room_name = qk_config.room_names()[room_number - 1]
        corrected = True
    return room_name, room_number, corrected, original_room, serial_number


def excel_cell(row, index):
    if index is None or index < 0 or index >= len(row):
        return ""
    return row[index]


def is_excel_total_row_for_columns(row, columns):
    serial_text = text_value(excel_cell(row, columns.get("serial")))
    room_text = text_value(excel_cell(row, columns["room"]))
    return serial_text.startswith("合计") or room_text.startswith("合计")


def is_same_excel_table_header(row, columns):
    for header in excel_column_maps(row):
        if header["start"] == columns["start"]:
            return True
    return False


def row_has_values_for_columns(row, columns):
    end = min(len(row), columns["end"] + 1)
    return any(text_value(value) for value in row[columns["start"] : end])


def find_excel_title_for_columns(rows, header_row_index, columns, sheet_name):
    for row_index in range(header_row_index - 1, max(-1, header_row_index - 8), -1):
        row = rows[row_index]
        start = max(0, columns["start"] - 1)
        end = min(len(row), columns["end"] + 2)
        values = [text_value(value) for value in row[start:end]]
        for value in values:
            if "出考情况明细表" in value:
                return value
    for row_index in range(header_row_index - 1, max(-1, header_row_index - 8), -1):
        row = rows[row_index]
        values = [text_value(value) for value in row if text_value(value)]
        for value in values:
            if "出考情况明细表" in value:
                return value
    return sheet_name


def build_excel_problem(sheet_name, table_index, row_number, issue, room="", expected=None, actual=None):
    return {
        "sheetName": sheet_name,
        "tableIndex": table_index,
        "rowNumber": row_number,
        "room": text_value(room),
        "expected": expected,
        "actual": actual,
        "issue": issue,
    }


def build_excel_discard(sheet_name, table_index, row_number, reason, room="", expected=None, actual=None):
    return {
        "sheetName": sheet_name,
        "tableIndex": table_index,
        "rowNumber": row_number,
        "room": text_value(room),
        "expected": expected,
        "actual": actual,
        "reason": reason,
    }


def build_excel_warning(sheet_name, table_index, message, row_number=None):
    return {
        "sheetName": sheet_name,
        "tableIndex": table_index,
        "rowNumber": row_number,
        "message": message,
    }


def source_totals_for_row(row, columns):
    return {
        "expectedCount": parse_excel_number(excel_cell(row, columns["expected"])),
        "actualCount": parse_excel_number(excel_cell(row, columns["actual"])),
        "absentCount": parse_excel_number(excel_cell(row, columns.get("absent"))),
    }


def compare_excel_source_totals(table):
    source = table.get("sourceTotals") or {}
    total_expected = sum(item["expectedCount"] for item in table["items"])
    total_actual = sum(item["actualCount"] for item in table["items"])
    total_absent = sum(item["absentCount"] for item in table["items"])
    comparisons = (
        ("应到合计", source.get("expectedCount"), total_expected),
        ("实到合计", source.get("actualCount"), total_actual),
        ("缺考合计", source.get("absentCount"), total_absent),
    )
    messages = [
        f"{label}源表为 {source_value}，系统计算为 {computed_value}"
        for label, source_value, computed_value in comparisons
        if source_value is not None and source_value != computed_value
    ]
    return messages


def parse_excel_preview_tables(file_path):
    if not file_path.exists():
        raise AppError(
            HTTPStatus.NOT_FOUND,
            "NOT_FOUND",
            f"未找到 Excel 文件：{file_path}",
        )
    if file_path.suffix.lower() != ".xlsx":
        raise AppError(
            HTTPStatus.BAD_REQUEST,
            "VALIDATION_ERROR",
            "当前预览只支持 .xlsx 文件",
        )
    tables = []
    problems = []
    discarded_items = []
    warnings = []
    with zipfile.ZipFile(file_path) as zf:
        shared_strings = read_xlsx_shared_strings(zf)
        sheets = read_xlsx_workbook(zf)
        for sheet in sheets:
            if not sheet["path"] or sheet["path"] not in zf.namelist():
                continue
            rows = read_xlsx_sheet_rows(zf, sheet["path"], shared_strings)
            table_index = 0
            for row_index, row in enumerate(rows):
                column_maps = excel_column_maps(row)
                if not column_maps:
                    continue
                for columns in column_maps:
                    table_index += 1
                    title_text = find_excel_title_for_columns(
                        rows,
                        row_index,
                        columns,
                        sheet["name"],
                    )
                    title = extract_title_from_excel_text(title_text) or sheet["name"]
                    exam_date, date_source = infer_excel_date(sheet["name"], title_text)
                    session_name = infer_excel_session(sheet["name"], title_text)
                    table = {
                        "sheetName": sheet["name"],
                        "tableIndex": table_index,
                        "title": title,
                        "examDate": exam_date,
                        "needsDateReview": not bool(exam_date),
                        "dateSource": date_source,
                        "sessionName": session_name,
                        "items": [],
                        "problems": [],
                        "warnings": [],
                        "discardedItems": [],
                        "sourceTotals": {},
                    }
                    data_row_index = row_index + 1
                    seen_data = False
                    while data_row_index < len(rows):
                        data_row = rows[data_row_index]
                        if is_same_excel_table_header(data_row, columns):
                            break
                        if is_excel_total_row_for_columns(data_row, columns):
                            table["sourceTotals"] = source_totals_for_row(
                                data_row,
                                columns,
                            )
                            break
                        if not row_has_values_for_columns(data_row, columns):
                            if seen_data:
                                break
                            data_row_index += 1
                            continue
                        serial_raw = excel_cell(data_row, columns.get("serial"))
                        room_raw = excel_cell(data_row, columns["room"])
                        expected = parse_excel_number(
                            excel_cell(data_row, columns["expected"])
                        )
                        actual = parse_excel_number(
                            excel_cell(data_row, columns["actual"])
                        )
                        source_absent = parse_excel_number(
                            excel_cell(data_row, columns.get("absent"))
                        )
                        row_no = data_row_index + 1
                        (
                            room_name,
                            room_number,
                            room_corrected,
                            original_room,
                            serial_number,
                        ) = cleaned_excel_room(room_raw, serial_raw)
                        discard_reason = ""
                        issue = ""
                        if expected is None or actual is None:
                            discard_reason = "缺少应到或实到人数，放弃导入"
                        elif expected < 0 or actual < 0:
                            discard_reason = "人数为负数，放弃导入"
                        elif actual > expected:
                            discard_reason = "实到人数大于应到人数，放弃导入"
                        elif not room_name:
                            issue = "缺少教室"
                        elif room_number is None:
                            issue = "教室无法识别"
                        elif room_number < 1 or room_number > len(qk_config.room_names()):
                            issue = "教室超出当前系统配置的教室范围"
                        if discard_reason:
                            discarded = build_excel_discard(
                                sheet["name"],
                                table_index,
                                row_no,
                                discard_reason,
                                room_raw,
                                expected,
                                actual,
                            )
                            table["discardedItems"].append(discarded)
                            discarded_items.append(discarded)
                        elif issue:
                            problem = build_excel_problem(
                                sheet["name"],
                                table_index,
                                row_no,
                                issue,
                                room_raw,
                                expected,
                                actual,
                            )
                            table["problems"].append(problem)
                            problems.append(problem)
                        else:
                            absent = expected - actual
                            item = {
                                "rowNumber": row_no,
                                "roomName": room_name,
                                "roomNumber": room_number,
                                "expectedCount": expected,
                                "actualCount": actual,
                                "absentCount": absent,
                                "attendanceRate": round(
                                    0 if expected == 0 else actual / expected,
                                    4,
                                ),
                                "originalRoom": original_room,
                                "serialNumber": serial_number,
                                "roomCorrectedFromSerial": room_corrected,
                            }
                            table["items"].append(item)
                            if source_absent is not None and source_absent != absent:
                                warning = build_excel_warning(
                                    sheet["name"],
                                    table_index,
                                    (
                                        f"第 {row_no} 行源表缺考为 {source_absent}，"
                                        f"按应到-实到应为 {absent}；导入将采用系统计算值。"
                                    ),
                                    row_no,
                                )
                                table["warnings"].append(warning)
                                warnings.append(warning)
                            if room_corrected:
                                warning = build_excel_warning(
                                    sheet["name"],
                                    table_index,
                                    (
                                        f"第 {row_no} 行教室列为“{original_room}”，"
                                        f"已按序号 {serial_number} 清洗为“{room_name}”。"
                                    ),
                                    row_no,
                                )
                                table["warnings"].append(warning)
                                warnings.append(warning)
                        seen_data = True
                        data_row_index += 1
                    if not table["examDate"]:
                        table["examDate"] = EXCEL_DATE_PLACEHOLDER
                        table["dateSource"] = "占位日期，导入后需手动修改"
                        warning = build_excel_warning(
                            sheet["name"],
                            table_index,
                            "表格缺少日期，已使用占位日期 1900-01-01，导入后必须手动修改。",
                            row_index + 1,
                        )
                        table["warnings"].append(warning)
                        warnings.append(warning)
                    for message in compare_excel_source_totals(table):
                        warning = build_excel_warning(
                            sheet["name"],
                            table_index,
                            f"源表合计不一致：{message}；导入将采用系统计算值。",
                        )
                        table["warnings"].append(warning)
                        warnings.append(warning)
                    if table["items"] or table["problems"] or table["discardedItems"]:
                        tables.append(table)
    valid_tables = [table for table in tables if table["items"]]
    valid_rows = sum(len(table["items"]) for table in valid_tables)
    valid_import_tables = [
        table
        for table in valid_tables
        if table["examDate"] and not table["problems"]
    ]
    needs_review_tables = [
        table for table in valid_tables if table["warnings"] or table["discardedItems"]
    ]
    return {
        "fileName": file_path.name,
        "filePath": str(file_path),
        "sheetCount": len({table["sheetName"] for table in tables}),
        "tableCount": len(tables),
        "validTableCount": len(valid_tables),
        "readyTableCount": len(valid_import_tables),
        "needsReviewTableCount": len(needs_review_tables),
        "validRowCount": valid_rows,
        "discardedRowCount": len(discarded_items),
        "warningCount": len(warnings),
        "problemCount": len(problems),
        "tables": tables,
        "problems": problems[:200],
        "warnings": warnings[:200],
        "discardedItems": discarded_items[:200],
    }


def find_excel_import_file():
    if EXCEL_IMPORT_FILE:
        return Path(EXCEL_IMPORT_FILE).expanduser()
    candidates = sorted(
        EXCEL_IMPORT_DIR.glob("*出考率*.xlsx"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    candidates = sorted(
        EXCEL_IMPORT_DIR.glob("*.xlsx"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    return EXCEL_IMPORT_DIR / "出考率1.xlsx"


def preview_excel_import(client_ip=""):
    file_path = find_excel_import_file()
    result = parse_excel_preview_tables(file_path)
    log_operation(
        "excel_previewed",
        "Excel 导入预览",
        (
            f"已预览 {result['fileName']}：识别 {result['tableCount']} 张表、"
            f"{result['validRowCount']} 条教室数据，发现 {result['problemCount']} 个问题。"
        ),
        actor_ip=client_ip,
        details={
            "filePath": result["filePath"],
            "tableCount": result["tableCount"],
            "validRowCount": result["validRowCount"],
            "problemCount": result["problemCount"],
        },
    )
    return result


def excel_table_import_token(result, table):
    raw = "\x1f".join(
        (
            result["fileName"],
            table["sheetName"],
            str(table["tableIndex"]),
            table["title"],
            table["examDate"],
        )
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"excel:{digest}"


def backup_database_for_excel_import():
    if not DB_PATH.exists():
        return ""
    return str(qk_dbtools.backup_database(tag="before-excel-import"))


def import_excel_preview(payload, client_ip=""):
    result = preview_excel_import(client_ip)
    importable_tables = [
        table for table in result["tables"] if table["items"] and not table["problems"]
    ]
    if not importable_tables:
        raise AppError(
            HTTPStatus.BAD_REQUEST,
            "VALIDATION_ERROR",
            "没有可导入的有效数据",
        )

    backup_path = backup_database_for_excel_import()
    now = now_iso()
    imported_tables = 0
    imported_rows = 0
    skipped_tables = []
    imported_warnings = []
    with get_db() as conn:
        for table in importable_tables:
            batch_token = excel_table_import_token(result, table)
            existing = conn.execute(
                "SELECT COUNT(*) AS total FROM absence_reports WHERE batch_token = ?",
                (batch_token,),
            ).fetchone()
            if existing and existing["total"]:
                skipped_tables.append(
                    {
                        "sheetName": table["sheetName"],
                        "tableIndex": table["tableIndex"],
                        "title": table["title"],
                        "reason": "该 Excel 表已导入过，已跳过",
                    }
                )
                continue
            total_expected = sum(item["expectedCount"] for item in table["items"])
            total_actual = sum(item["actualCount"] for item in table["items"])
            total_rate = 0 if total_expected == 0 else total_actual / total_expected
            created_at = now
            for item in table["items"]:
                conn.execute(
                    """
                    INSERT INTO absence_reports (
                        title, exam_date, exam_time, session_name, room_name,
                        room_number, reporter_name, expected_count, actual_count,
                        absent_count, attendance_rate, total_count,
                        total_attendance_rate, batch_token, remark, client_ip,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        table["title"],
                        table["examDate"],
                        "",
                        table["sessionName"],
                        item["roomName"],
                        item["roomNumber"],
                        "Excel导入",
                        item["expectedCount"],
                        item["actualCount"],
                        item["absentCount"],
                        item["attendanceRate"],
                        total_expected,
                        round(total_rate, 4),
                        batch_token,
                        (
                            f"Excel导入：{table['sheetName']} 第{table['tableIndex']}张表"
                            + (
                                "；日期为占位日期，需人工修改"
                                if table.get("needsDateReview")
                                else ""
                            )
                        ),
                        client_ip,
                        created_at,
                        now,
                    ),
                )
                imported_rows += 1
            imported_tables += 1
            if table.get("warnings"):
                imported_warnings.extend(table["warnings"])
        write_operation_log(
            conn,
            "excel_imported",
            "Excel 数据已导入",
            (
                f"已从 {result['fileName']} 导入 {imported_tables} 张表、"
                f"{imported_rows} 条教室数据；跳过 {len(skipped_tables)} 张已导入表。"
            ),
            actor_ip=client_ip,
            details={
                "filePath": result["filePath"],
                "backupPath": backup_path,
                "importedTables": imported_tables,
                "importedRows": imported_rows,
                "discardedRows": result["discardedRowCount"],
                "warnings": len(imported_warnings),
                "skippedTables": skipped_tables,
            },
        )
    return {
        "fileName": result["fileName"],
        "backupPath": backup_path,
        "importedTables": imported_tables,
        "importedRows": imported_rows,
        "discardedRows": result["discardedRowCount"],
        "warningCount": len(imported_warnings),
        "skippedTables": skipped_tables,
    }


def make_signature(payload):
    return hmac.new(
        qk_config.session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def encode_session():
    expires = int((datetime.now(timezone.utc) + SESSION_TTL).timestamp())
    nonce = secrets.token_urlsafe(12)
    payload = f"{expires}:{nonce}"
    signature = make_signature(payload)
    token = f"{payload}:{signature}".encode("utf-8")
    return base64.urlsafe_b64encode(token).decode("utf-8")


def is_valid_session(token):
    if not token:
        return False
    try:
        decoded = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        expires, nonce, signature = decoded.split(":", 2)
        payload = f"{expires}:{nonce}"
        expected = make_signature(payload)
        if not hmac.compare_digest(signature, expected):
            return False
        return int(expires) >= int(datetime.now(timezone.utc).timestamp())
    except (ValueError, TypeError):
        return False


def parse_cookies(headers):
    cookie = SimpleCookie()
    raw = headers.get("Cookie")
    if raw:
        cookie.load(raw)
    return cookie


def success(data=None):
    payload = {"success": True}
    if data is not None:
        payload["data"] = data
    return payload


def error_payload(code, message):
    return {"success": False, "error": {"code": code, "message": message}}


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "QeukaoHTTP/1.0"

    def log_message(self, fmt, *args):
        status = str(args[1]) if len(args) > 1 else ""
        if status.startswith(("4", "5")):
            print(f"[{now_iso()}] {self.client_address[0]} {fmt % args}")

    def do_GET(self):
        self.route_request("GET")

    def do_POST(self):
        self.route_request("POST")

    def do_PUT(self):
        self.route_request("PUT")

    def do_DELETE(self):
        self.route_request("DELETE")

    def route_request(self, method):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/session" and method == "GET":
                self.write_json(success(qk_agents.session_status()))
            elif qk_agents.handles(path):
                qk_agents.route(self, method, path, parse_qs(parsed.query))
            elif path == "/":
                self.serve_file(STATIC_DIR / "index.html")
            elif path == "/admin":
                self.serve_file(STATIC_DIR / "admin.html")
            elif path.startswith("/static/"):
                relative_path = unquote(path.removeprefix("/static/"))
                self.serve_static(relative_path)
            elif path == "/api/health" and method == "GET":
                self.write_json(success({"status": "ok", "today": today_str()}))
            elif path == "/api/client-context" and method == "GET":
                self.handle_client_context()
            elif path == "/api/site" and method == "GET":
                self.write_json(success(qk_agents.site_info()))
            elif path == "/api/current-project" and method == "GET":
                self.write_json(success(get_current_project()))
            elif path == "/api/current-reports" and method == "GET":
                self.write_json(success(list_current_report_drafts()))
            elif path == "/api/current-reports/check-room" and method == "POST":
                self.handle_check_current_report_room()
            elif path == "/api/current-reports" and method == "POST":
                self.handle_upsert_current_report()
            elif path == "/api/admin/accept" and method == "POST":
                self.require_admin()
                self.handle_accept_reports()
            elif path.startswith("/api/admin/current-reports/") and method == "PUT":
                self.require_admin()
                self.handle_admin_edit_current_report(unquote(path.removeprefix("/api/admin/current-reports/")))
            elif path == "/api/admin/login" and method == "POST":
                self.handle_admin_login()
            elif path == "/api/admin/logout" and method == "POST":
                self.handle_admin_logout()
            elif path == "/api/admin/me" and method == "GET":
                self.require_admin(allow_default_password=True)
                self.write_json(success({"authenticated": True, "mustChangePassword": qk_config.must_change_password()}))
            elif path == "/api/admin/reports" and method == "GET":
                self.require_admin()
                self.write_json(success(list_reports(parse_qs(parsed.query))))
            elif path == "/api/admin/reports/summary" and method == "GET":
                self.require_admin()
                self.write_json(success(summarize_reports(parse_qs(parsed.query))))
            elif path == "/api/admin/reports/export" and method == "GET":
                self.require_admin()
                self.handle_export_reports(parse_qs(parsed.query))
            elif path == "/api/admin/import/excel-preview" and method == "GET":
                self.require_admin()
                self.write_json(success(preview_excel_import(self.request_client_ip())))
            elif path == "/api/admin/import/excel" and method == "POST":
                self.require_admin()
                self.handle_import_excel()
            elif path == "/api/admin/logs/summary" and method == "GET":
                self.require_admin()
                self.write_json(success(summarize_operation_logs()))
            elif path == "/api/admin/logs" and method == "GET":
                self.require_admin()
                self.write_json(success(list_operation_logs(parse_qs(parsed.query))))
            elif path.startswith("/api/admin/reports/") and method == "PUT":
                self.require_admin()
                report_id = path.removeprefix("/api/admin/reports/")
                if not report_id.isdigit():
                    raise AppError(
                        HTTPStatus.NOT_FOUND, "NOT_FOUND", "接口地址不存在"
                    )
                self.handle_update_report(int(report_id))
            elif path.startswith("/api/admin/reports/") and method == "DELETE":
                self.require_admin()
                report_id = path.removeprefix("/api/admin/reports/")
                if not report_id.isdigit():
                    raise AppError(
                        HTTPStatus.NOT_FOUND, "NOT_FOUND", "接口地址不存在"
                    )
                self.handle_delete_report(int(report_id))
            elif path.startswith("/api/admin/reports/") and method == "GET":
                self.require_admin()
                report_id = path.removeprefix("/api/admin/reports/")
                if not report_id.isdigit():
                    raise AppError(
                        HTTPStatus.NOT_FOUND, "NOT_FOUND", "接口地址不存在"
                    )
                self.write_json(success(get_report(int(report_id))))
            else:
                raise AppError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "接口地址不存在")
        except AppError as exc:
            self.write_json(error_payload(exc.code, exc.message), exc.status)
        except json.JSONDecodeError:
            self.write_json(
                error_payload("VALIDATION_ERROR", "JSON 格式不正确"),
                HTTPStatus.BAD_REQUEST,
            )
        except Exception as exc:
            print(f"[{now_iso()}] unexpected error: {exc}")
            self.write_json(
                error_payload("INTERNAL_ERROR", "服务器内部错误"),
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError as exc:
            raise AppError(HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "请求长度不正确") from exc
        if not 0 <= length <= 1024 * 1024:
            raise AppError(HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "请求过大或长度不正确")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except UnicodeDecodeError as exc:
            raise AppError(HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "JSON 编码不正确") from exc
        if not isinstance(payload, dict):
            raise AppError(HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "请求必须是 JSON 对象")
        return payload

    def request_client_ip(self):
        fallback = self.client_address[0] if self.client_address else ""
        return resolve_client_ip(self.headers, fallback)

    def handle_client_context(self):
        self.write_json(success(client_context(self.request_client_ip())))

    def handle_upsert_current_report(self):
        payload = self.read_json()
        self.write_json(success(upsert_current_report_draft(payload, self.request_client_ip())))

    def handle_check_current_report_room(self):
        payload = self.read_json()
        self.write_json(success(check_current_report_room(payload, self.request_client_ip())))

    def handle_admin_edit_current_report(self, room_name):
        payload = self.read_json()
        report = {**payload, "roomName": room_name}
        self.write_json(success(upsert_current_report_draft(report, self.request_client_ip(), admin_edit_room=room_name)))

    def handle_accept_reports(self):
        payload = self.read_json()
        client_ip = self.request_client_ip()
        self.write_json(
            success(accept_reports(payload, client_ip)),
            HTTPStatus.CREATED,
        )

    def handle_update_report(self, report_id):
        payload = self.read_json()
        self.write_json(success(update_report_group(report_id, payload, self.request_client_ip())))

    def handle_delete_report(self, report_id):
        payload = self.read_json()
        self.write_json(success(delete_report_group(report_id, payload, self.request_client_ip())))

    def handle_export_reports(self, query):
        body = export_reports_csv(query)
        log_operation(
            "reports_exported",
            "后台表格已导出",
            "管理员导出了后台数据表格。",
            actor_ip=self.request_client_ip(),
        )
        filename = f"qeukao-reports-{today_str()}.csv"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header(
            "Content-Disposition", f'attachment; filename="{filename}"'
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def handle_import_excel(self):
        payload = self.read_json()
        self.write_json(success(import_excel_preview(payload, self.request_client_ip())))

    def handle_admin_login(self):
        payload = self.read_json()
        password = str(payload.get("password") or "")
        if not qk_config.check_admin_password(password):
            log_operation(
                "admin_login_failed",
                "管理员登录失败",
                "管理员密码不正确。",
                severity="warning",
                actor_ip=self.request_client_ip(),
            )
            raise AppError(
                HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED",
                "配置文件曾损坏，管理密码已锁定，请在服务端控制面板重设密码"
                if qk_config.password_locked() else "管理员密码不正确",
            )

        token = encode_session()
        log_operation(
            "admin_login",
            "管理员登录成功",
            "管理员后台登录成功。",
            actor_ip=self.request_client_ip(),
        )
        headers = [
            (
                "Set-Cookie",
                (
                    f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; "
                    f"Max-Age={int(SESSION_TTL.total_seconds())}"
                ),
            )
        ]
        self.write_json(success({"authenticated": True, "mustChangePassword": qk_config.must_change_password()}), headers=headers)

    def handle_admin_logout(self):
        log_operation(
            "admin_logout",
            "管理员退出登录",
            "管理员后台已退出登录。",
            actor_ip=self.request_client_ip(),
        )
        headers = [
            (
                "Set-Cookie",
                f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
            )
        ]
        self.write_json(success(), headers=headers)

    def require_admin(self, allow_default_password=False):
        cookies = parse_cookies(self.headers)
        token = cookies.get(COOKIE_NAME)
        if token is None or not is_valid_session(token.value):
            raise AppError(HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "请先登录")
        # 开源后人人都知道默认密码：还没改过就只放行“看登录状态”和“改密码”，后台其它接口一律拒绝
        if not allow_default_password and qk_config.must_change_password():
            raise AppError(HTTPStatus.FORBIDDEN, "MUST_CHANGE_PASSWORD", "首次使用请先修改默认密码")

    def serve_static(self, relative_path):
        safe_path = (STATIC_DIR / relative_path).resolve()
        if not safe_path.is_relative_to(STATIC_DIR.resolve()):
            raise AppError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "文件不存在")
        self.serve_file(safe_path)

    def serve_file(self, path):
        if not path.exists() or not path.is_file():
            raise AppError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "文件不存在")
        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".ico": "image/x-icon",
        }
        content_type = content_types.get(path.suffix, "application/octet-stream")
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def write_json(self, payload, status=HTTPStatus.OK, headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in headers or []:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


_init_lock = threading.Lock()
_background_started = False


def initialize_database():
    init_db()
    qk_agents.migrate_session_state()
    migrate_current_drafts_to_reports()


def init_all():
    global _background_started
    with _init_lock:
        initialize_database()
        qk_dbtools.set_post_import_hook(initialize_database)
        cleanup_old_operation_logs()
        if not _background_started:
            start_log_cleanup_scheduler()
            qk_dbtools.start_backup_scheduler()
            qk_agents.start_dispatch_scheduler()
            _background_started = True


class _Server(ThreadingHTTPServer):
    request_queue_size = 128  # 默认 5：上课前几十台教室电脑同时开机 hello 会有连接被重置
    daemon_threads = True
    # Windows 的 SO_REUSEADDR 语义不同于 Linux：它允许第二个进程绑定到「正在监听」的同一端口（端口被两个服务共用，
    # 请求随机落到其中一个）。管理员双击两次 exe 就会这样，且不会出现「端口被占用」的提示，所以 Windows 上不设它。
    allow_reuse_address = os.name != "nt"


def build_server(host, port):
    return _Server((host, port), RequestHandler)


def main():
    init_all()
    if qk_config.password_locked():
        print("WARNING: 配置文件曾损坏，管理密码已锁定，请在服务端控制面板重设密码")
    elif not qk_config.load().get("passwordHash") and not os.getenv("QEUKAO_ADMIN_PASSWORD"):
        print("WARNING: 仍在使用默认密码 112233：登录后台后必须先修改")
    httpd = build_server(HOST, PORT)
    print(f"Qeukao server running at http://{HOST}:{PORT}")
    print(f"Database: {DB_PATH}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
