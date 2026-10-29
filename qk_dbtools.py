"""数据库备份/导出/导入工具。契约见 docs/windows-contract.md §3。全部走 sqlite3 backup API。"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import qk_config

log = logging.getLogger("qk_dbtools")

_BACKUP_GLOB = "qeukao-db-*.sqlite3"
_CHECK_INTERVAL = 60
_post_import_hook = None
_io_lock = threading.RLock()  # import_database 持锁时会再调 backup_database
_sched_lock = threading.Lock()
_sched_thread: threading.Thread | None = None


class DbToolError(Exception):
    """message 为面向用户的中文。"""


def set_post_import_hook(fn) -> None:
    global _post_import_hook
    _post_import_hook = fn


_LOCAL_TZ = timezone(timedelta(hours=8))  # 与 app.now_iso 一致


def _log_event(event_type: str, title: str, message: str, details: dict | None = None) -> None:
    """向现库 operation_logs 追加一条日志（契约 v1.1）。失败只记 logging，不得影响备份/导入。"""
    try:
        conn = sqlite3.connect(str(qk_config.DB_PATH), timeout=5)
        try:
            has = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='operation_logs'"
            ).fetchone()
            if not has:
                return
            conn.execute(
                "INSERT INTO operation_logs (event_type, severity, title, message, actor_ip, room_name, "
                "report_id, batch_token, details, created_at) VALUES (?, 'info', ?, ?, '', '', NULL, '', ?, ?)",
                (event_type, title, message,
                 json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
                 datetime.now(_LOCAL_TZ).isoformat(timespec="seconds")),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        log.warning("写入操作日志 %s 失败", event_type, exc_info=True)


def _backup_dir(dest_dir=None) -> Path:
    if dest_dir:
        return Path(dest_dir)
    d = qk_config.load()["backup"]["dir"]
    return Path(d) if d else qk_config.BASE_DIR / "backups"


def _copy_db(src: Path, dest: Path, single_file: bool = True) -> None:
    """backup API 把 src 复制成 dest（先写 .part 再 replace，半成品不会出现在备份列表里）。"""
    part = dest.with_name("." + dest.name + ".part")
    try:
        s = sqlite3.connect(str(src), timeout=30)
        try:
            d = sqlite3.connect(str(part))
            try:
                s.backup(d)
                if single_file:
                    d.execute("PRAGMA journal_mode=DELETE")  # 备份文件不带 -wal，便于拷走
            finally:
                d.close()
        finally:
            s.close()
        os.replace(part, dest)
    except sqlite3.Error as e:
        raise DbToolError("数据库复制失败：%s" % e)
    finally:
        if part.exists():
            try:
                part.unlink()
            except OSError:
                pass


def _require_live_db() -> Path:
    p = qk_config.DB_PATH
    if not p.is_file():
        raise DbToolError("数据库文件不存在，无法备份：%s" % p)
    return p


def backup_database(dest_dir=None, tag="") -> Path:
    src = _require_live_db()
    folder = _backup_dir(dest_dir)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise DbToolError("无法创建备份目录 %s：%s" % (folder, e))
    tag = re.sub(r"[^A-Za-z0-9_-]", "", str(tag or ""))
    base = "qeukao-db-" + time.strftime("%Y%m%d-%H%M%S") + ("-" + tag if tag else "")
    with _io_lock:
        dest, n = folder / (base + ".sqlite3"), 1
        while dest.exists():
            n += 1
            dest = folder / ("%s-%d.sqlite3" % (base, n))
        _copy_db(src, dest)
    _log_event("db_backup", "数据库已备份", "数据库已备份到 %s。" % dest.name, {"file": str(dest), "tag": tag})
    return dest


def _same_file(a, b) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:  # 目标还不存在：退回到规范化路径比较
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def export_database(dest_file) -> Path:
    src = _require_live_db()
    dest = Path(dest_file)
    if _same_file(dest, src):
        raise DbToolError("不能导出到当前正在使用的数据库文件，请选择其他位置。")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise DbToolError("无法创建导出目录：%s" % e)
    with _io_lock:
        _copy_db(src, dest)
    _log_event("db_exported", "数据库已导出", "数据库已导出到 %s。" % dest, {"file": str(dest)})
    return dest


def _snapshot_source(src: Path, tmp: Path) -> None:
    """把源库连同 -wal 复制进私有临时目录，再对副本用 backup API 取快照。

    - -wal 里已提交的行会一起带上（只复制主文件会丢它们）；-shm 只是可重建的索引，不复制，SQLite 打开副本时自行恢复。
    - 不在用户目录里打开/创建/加锁任何东西：源在只读介质、缺 -shm、网络盘上都能导入，也不会留下 -shm/-wal。
    - ponytail: 主文件与 -wal 是先后两次复制；源库正被别的进程写入时可能不一致。导入的是静止的备份/导出文件，故不加锁。
    """
    work = tmp.parent / "src-copy"
    try:
        work.mkdir()
        shutil.copyfile(src, work / "src.sqlite3")
        wal = src.with_name(src.name + "-wal")
        if wal.is_file():
            shutil.copyfile(wal, work / "src.sqlite3-wal")
    except OSError as e:
        raise DbToolError("无法读取所选文件：%s" % e)
    try:
        s = sqlite3.connect(str(work / "src.sqlite3"), timeout=10)
        try:
            d = sqlite3.connect(str(tmp))
            try:
                s.backup(d)
            finally:
                d.close()
        finally:
            s.close()
    except sqlite3.Error:
        raise DbToolError("所选文件不是有效的 SQLite 数据库或已损坏，已取消导入，现有数据未改动。")


def _validate_copy(path: Path) -> None:
    try:
        conn = sqlite3.connect(str(path))
        try:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
            if rows != [("ok",)]:
                raise DbToolError("所选文件未通过数据库完整性检查，已取消导入，现有数据未改动。")
            has = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='absence_reports'"
            ).fetchone()
            if not has:
                raise DbToolError("所选文件不是本系统的数据库（缺少 absence_reports 表），已取消导入。")
        finally:
            conn.close()
    except sqlite3.Error:
        raise DbToolError("所选文件不是有效的 SQLite 数据库或已损坏，已取消导入，现有数据未改动。")


def _align_page_size(tmp: Path, live: Path) -> None:
    """backup API 在目标为 WAL 且页大小不同时会失败；先把临时副本的页大小改成现库一致。"""
    if not live.is_file():
        return
    try:
        lc = sqlite3.connect(str(live))
        try:
            target = lc.execute("PRAGMA page_size").fetchone()[0]
        finally:
            lc.close()
        c = sqlite3.connect(str(tmp))
        try:
            if c.execute("PRAGMA page_size").fetchone()[0] != target:
                c.execute("PRAGMA journal_mode=DELETE")
                c.execute("PRAGMA page_size=%d" % int(target))
                c.execute("VACUUM")
        finally:
            c.close()
    except sqlite3.Error as e:
        raise DbToolError("处理导入文件失败：%s" % e)


def _check_drafts_fit_room_list(tmp) -> None:
    """备份里未验收的草稿必须对得上当前教室名单，否则导入后数据会挂到别的教室名下，管理员也改不了。"""
    names = qk_config.room_names()
    try:
        c = sqlite3.connect(str(tmp))
        try:
            # 只有「确实没有这张表」（旧版本的库）才放行；表在却读不了，说明备份损坏，必须在覆盖现库之前拒绝
            if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='current_report_drafts'").fetchone():
                return
            rows = c.execute("SELECT room_number, room_name FROM current_report_drafts").fetchall()
        finally:
            c.close()
    except sqlite3.Error as e:
        raise DbToolError("所选数据库里的未验收数据表无法读取，不能导入：%s" % e)
    for number, name in rows:
        if not (isinstance(number, int) and 0 < number <= len(names) and names[number - 1] == name):
            raise DbToolError("所选数据库里有未验收的「%s」数据，与当前的教室名单对不上，不能导入。"
                              "请先在后台把教室名单改回备份时的样子，或在原系统里先验收后再备份。" % name)


def import_database(src_file) -> dict:
    src = Path(src_file)
    if not src.is_file():
        raise DbToolError("找不到所选的数据库文件。")
    if _same_file(src, qk_config.DB_PATH):
        raise DbToolError("所选文件就是当前正在使用的数据库，无需导入。")
    tmpdir = tempfile.mkdtemp(prefix="qk-import-")
    try:
        tmp = Path(tmpdir) / "src.sqlite3"
        _snapshot_source(src, tmp)  # 在快照上校验，不锁/不改用户文件
        _validate_copy(tmp)
        live = qk_config.DB_PATH
        with qk_config.ROOM_LIST_LOCK, _io_lock:  # 与改名单、老师提交互斥
            _check_drafts_fit_room_list(tmp)
            _align_page_size(tmp, live)
            backup_path = ""
            if live.is_file():
                # 这条 db_backup 日志写进现库，随后被整库覆盖，无害
                backup_path = str(backup_database(tag="before-import"))
            live.parent.mkdir(parents=True, exist_ok=True)
            try:
                s = sqlite3.connect(str(tmp))
                try:
                    d = sqlite3.connect(str(live), timeout=30)
                    try:
                        s.backup(d)  # 单个写事务，失败时现库保持原样；不替换文件，兼容 WAL
                        count = d.execute("SELECT COUNT(*) FROM absence_reports").fetchone()[0]
                    finally:
                        d.close()
                finally:
                    s.close()
            except sqlite3.Error as e:
                raise DbToolError("导入失败（现有数据未被改动）：%s" % e)
            hook = _post_import_hook  # hook 仍在同一把锁内，第二次导入不会插到它前面
            if hook:
                try:
                    hook()
                except Exception as e:  # noqa: BLE001
                    raise DbToolError("数据已导入，但后续初始化失败，请重启服务端：%s" % e)
        _log_event("db_imported", "数据库已导入",
                   "已从 %s 导入数据库，共 %d 条记录；导入前已自动备份。" % (src.name, int(count)),
                   {"source": str(src), "backup": backup_path, "reportCount": int(count)})
        return {"backupPath": backup_path, "reportCount": int(count)}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def list_backups(dest_dir=None) -> list:
    folder = _backup_dir(dest_dir)
    out = []
    try:
        for p in folder.glob(_BACKUP_GLOB):
            try:
                st = p.stat()
            except OSError:
                continue
            if p.is_file():
                out.append({"path": str(p), "name": p.name, "size": st.st_size, "mtime": st.st_mtime})
    except OSError:
        return []
    out.sort(key=lambda i: (i["mtime"], i["name"]), reverse=True)
    return out


def cleanup_old_backups(dest_dir=None, retention_days=None, keep_count=None, protect_path=None) -> int:
    """Age first, then count; import rollback snapshots are only subject to age.

    protect_path reserves a count slot even after a clock rollback. The newest
    backup is protected when this function is called without an operation path.
    """
    cfg = qk_config.load()["backup"]
    days = cfg["retentionDays"] if retention_days is None else retention_days
    count = cfg["keepCount"] if keep_count is None else keep_count
    # Fail closed before unlinking anything, including for hand-edited config.
    for value, maximum in ((days, 3650), (count, 1000)):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
            raise ValueError("备份保留天数或个数超出范围")
    cutoff = time.time() - days * 86400
    removed = 0
    with _io_lock:
        items = list_backups(dest_dir)
        protected = Path(protect_path).resolve() if protect_path else (Path(items[0]["path"]).resolve() if items else None)
        ordinary = []
        expired = []
        for item in items:
            path = Path(item["path"])
            if _same_file(path, qk_config.DB_PATH):
                continue  # Never rotate the live DB even if it has a backup-like name.
            is_protected = path.resolve() == protected
            if days and item["mtime"] < cutoff and not is_protected:
                expired.append(path)
            elif not re.match(r"^qeukao-db-[0-9]{8}-[0-9]{6}-before-(?:excel-import|import)", item["name"]):
                ordinary.append(path)
        # Reserve a place for this backup rather than retaining N plus one.
        ordinary.sort(key=lambda p: p.resolve() != protected)
        victims = expired + (ordinary[count:] if count else [])
        # A killed process cannot run _copy_db's finally block. Never touch a
        # fresh partial: another process may still be copying a large database.
        for part in _backup_dir(dest_dir).glob(".qeukao-db-*.part"):
            try:
                if part.is_file() and part.stat().st_mtime < time.time() - 86400:
                    victims.append(part)
            except OSError:
                continue
        for path in victims:
            try:
                path.unlink()
                removed += 1
            except OSError:
                log.warning("删除旧备份失败：%s", path)
    return removed


def backup_due(now: float, latest_mtime, every_hours: int) -> bool:
    """纯函数：是否到期。latest_mtime 为 None 表示从未备份。"""
    return latest_mtime is None or now - latest_mtime >= every_hours * 3600


def _scheduler_tick() -> bool:
    cfg = qk_config.load()["backup"]
    if not cfg["enabled"]:
        return False
    folder = _backup_dir()
    with _io_lock:
        items = list_backups(folder)
        if not backup_due(time.time(), items[0]["mtime"] if items else None, cfg["everyHours"]):
            return False
        path = backup_database(dest_dir=folder, tag="auto")
        cleanup_old_backups(dest_dir=folder, protect_path=path)
    return True


def _scheduler_loop() -> None:
    while True:
        try:
            _scheduler_tick()
        except Exception:  # noqa: BLE001  线程不能死
            log.exception("自动备份失败")
        time.sleep(_CHECK_INTERVAL)


def start_backup_scheduler() -> threading.Thread:
    global _sched_thread
    with _sched_lock:
        if _sched_thread is None or not _sched_thread.is_alive():
            _sched_thread = threading.Thread(target=_scheduler_loop, name="qk-backup", daemon=True)
            _sched_thread.start()
        return _sched_thread
