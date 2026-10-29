from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

import qk_config
import qk_dbtools


def make_db(path: Path, rows, with_table=True):
    conn = sqlite3.connect(str(path))
    if with_table:
        conn.execute("CREATE TABLE absence_reports (id INTEGER PRIMARY KEY, note TEXT)")
        conn.executemany("INSERT INTO absence_reports (note) VALUES (?)", [(r,) for r in rows])
    else:
        conn.execute("CREATE TABLE other (x)")
    conn.commit()
    conn.close()


def notes(path: Path):
    conn = sqlite3.connect(str(path))
    try:
        return [r[0] for r in conn.execute("SELECT note FROM absence_reports ORDER BY id")]
    finally:
        conn.close()


class DbTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="qk-db-"))
        self._saved = {k: os.environ.get(k) for k in ("QEUKAO_DATA_DIR", "QEUKAO_DB")}
        os.environ.pop("QEUKAO_DB", None)
        os.environ["QEUKAO_DATA_DIR"] = str(self.tmp / "data")
        qk_config._reload_paths_for_tests()
        (self.tmp / "data").mkdir()
        self.bdir = self.tmp / "backups"
        qk_config.save({"backup": {"dir": str(self.bdir)}})
        make_db(qk_config.DB_PATH, ["live-1", "live-2"])
        qk_dbtools.set_post_import_hook(None)

    def tearDown(self):
        qk_dbtools.set_post_import_hook(None)
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        qk_config._reload_paths_for_tests()
        shutil.rmtree(self.tmp, ignore_errors=True)


class BackupExportTests(DbTestCase):
    def test_backup_name_and_content(self):
        p = qk_dbtools.backup_database(tag="t1")
        self.assertEqual(p.parent, self.bdir)
        self.assertRegex(p.name, r"^qeukao-db-\d{8}-\d{6}-t1\.sqlite3$")
        self.assertEqual(notes(p), ["live-1", "live-2"])

    def test_two_backups_in_same_second_do_not_overwrite(self):
        a = qk_dbtools.backup_database()
        b = qk_dbtools.backup_database()
        self.assertNotEqual(a, b)
        self.assertEqual(len(qk_dbtools.list_backups()), 2)

    def test_export_creates_parent_and_valid_copy(self):
        out = qk_dbtools.export_database(self.tmp / "sub" / "x.sqlite3")
        self.assertEqual(notes(out), ["live-1", "live-2"])

    def test_missing_live_db_is_user_error_not_empty_file(self):
        qk_config.DB_PATH.unlink()
        with self.assertRaises(qk_dbtools.DbToolError):
            qk_dbtools.backup_database()
        self.assertFalse(qk_config.DB_PATH.exists())


class ImportTests(DbTestCase):
    def test_import_ok(self):
        src = self.tmp / "src.sqlite3"
        make_db(src, ["new-1", "new-2", "new-3"])
        calls = []
        qk_dbtools.set_post_import_hook(lambda: calls.append(notes(qk_config.DB_PATH)))
        res = qk_dbtools.import_database(src)
        self.assertEqual(res["reportCount"], 3)
        self.assertEqual(notes(qk_config.DB_PATH), ["new-1", "new-2", "new-3"])
        self.assertEqual(calls, [["new-1", "new-2", "new-3"]])  # hook runs after data is in
        self.assertIn("before-import", res["backupPath"])
        self.assertEqual(notes(Path(res["backupPath"])), ["live-1", "live-2"])
        self.assertEqual(notes(src), ["new-1", "new-2", "new-3"])  # user file untouched

    def test_import_into_wal_db_with_open_connection(self):
        conn = sqlite3.connect(str(qk_config.DB_PATH))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("INSERT INTO absence_reports (note) VALUES ('wal-row')")
        conn.commit()
        src = self.tmp / "src.sqlite3"
        make_db(src, ["new-1"])
        try:
            qk_dbtools.import_database(src)
            self.assertEqual([r[0] for r in conn.execute("SELECT note FROM absence_reports")],
                             ["new-1"])
        finally:
            conn.close()

    def _assert_rejected(self, src):
        before = notes(qk_config.DB_PATH)
        qk_dbtools.set_post_import_hook(lambda: self.fail("hook must not run"))
        with self.assertRaises(qk_dbtools.DbToolError):
            qk_dbtools.import_database(src)
        self.assertEqual(notes(qk_config.DB_PATH), before)
        self.assertEqual(list(self.bdir.glob("*before-import*")) if self.bdir.exists() else [], [])

    def test_rejects_non_sqlite(self):
        src = self.tmp / "junk.sqlite3"
        src.write_bytes(b"this is not a database" * 100)
        self._assert_rejected(src)

    def test_rejects_missing_file(self):
        self._assert_rejected(self.tmp / "nope.sqlite3")

    def test_rejects_missing_table(self):
        src = self.tmp / "notable.sqlite3"
        make_db(src, [], with_table=False)
        self._assert_rejected(src)

    def test_rejects_failed_integrity_check(self):
        src = self.tmp / "bad.sqlite3"
        conn = sqlite3.connect(str(src))
        conn.execute("CREATE TABLE absence_reports (id INTEGER PRIMARY KEY, note TEXT)")
        conn.execute("CREATE INDEX ix ON absence_reports(note)")
        conn.executemany("INSERT INTO absence_reports (note) VALUES (?)",
                         [("row-%d" % i * 5,) for i in range(3000)])
        conn.commit()
        conn.close()
        data = bytearray(src.read_bytes())
        ps = 4096
        for off in range(ps * 3, ps * 5):
            data[off] = 0xFF
        src.write_bytes(bytes(data))
        probe = sqlite3.connect(str(src))
        try:
            try:
                ok = probe.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            except sqlite3.DatabaseError:
                ok = False
        finally:
            probe.close()
        self.assertFalse(ok, "test fixture failed to corrupt the db")
        self._assert_rejected(src)


class RetentionAndSchedulerTests(DbTestCase):
    def test_count_rotation_preserves_safety_snapshots_and_current_backup(self):
        self.bdir.mkdir()
        auto = []
        for n in range(5):
            p = self.bdir / ("qeukao-db-20261029-00000%d-auto.sqlite3" % n)
            p.write_bytes(b"x")
            os.utime(p, (1000 + n, 1000 + n))
            auto.append(p)
        safety = [self.bdir / ("qeukao-db-20261029-000000-" + tag + ".sqlite3")
                  for tag in ("before-import", "before-excel-import-2")]
        other = self.bdir / "other.sqlite3"
        for p in safety + [other]:
            p.write_bytes(b"safe")
        qk_config.save({"backup": {"keepCount": 3, "retentionDays": 0}})
        self.assertEqual(qk_dbtools.cleanup_old_backups(), 2)
        self.assertEqual([p.exists() for p in auto], [False, False, True, True, True])
        self.assertTrue(all(p.exists() for p in safety + [other]))
        # A clock rollback must not let either limit remove this operation's backup.
        self.assertEqual(qk_dbtools.cleanup_old_backups(retention_days=1, keep_count=1,
                                                       protect_path=auto[2]), 2)
        self.assertTrue(auto[2].exists())
        for p in safety:
            os.utime(p, (1000, 1000))
        qk_dbtools.cleanup_old_backups(retention_days=1, keep_count=0, protect_path=auto[2])
        self.assertTrue(auto[2].exists() and other.exists())
        self.assertFalse(any(p.exists() for p in safety))

    def test_cleanup_never_deletes_live_db_or_accepts_invalid_limits(self):
        self.bdir.mkdir()
        live_name = self.bdir / "qeukao-db-live.sqlite3"
        qk_config.DB_PATH = live_name
        make_db(live_name, ["live"])
        old = qk_dbtools.backup_database(tag="manual")
        os.utime(live_name, (1, 1))
        for kwargs in ({"keep_count": -1}, {"retention_days": -1}, {"keep_count": True}):
            with self.assertRaises(ValueError):
                qk_dbtools.cleanup_old_backups(**kwargs)
            self.assertTrue(live_name.exists() and old.exists())
        qk_dbtools.cleanup_old_backups(retention_days=1, keep_count=1, protect_path=old)
        self.assertEqual(notes(live_name), ["live"])
        self.assertTrue(old.exists())

    def test_cleanup_removes_only_own_parts_older_than_one_day(self):
        from unittest.mock import patch
        self.bdir.mkdir()
        names = (".qeukao-db-stale.sqlite3.part", ".qeukao-db-boundary.sqlite3.part",
                 ".qeukao-db-fresh.sqlite3.part", ".other.sqlite3.part", "qeukao-db-visible.sqlite3")
        paths = [self.bdir / name for name in names]
        for path, stamp in zip(paths, (1, 13600, 13601, 1, 1)):
            path.write_bytes(b"x")
            os.utime(path, (stamp, stamp))
        with patch("qk_dbtools.time.time", return_value=100000):
            self.assertEqual(qk_dbtools.cleanup_old_backups(retention_days=0, keep_count=0), 1)
        self.assertEqual([p.exists() for p in paths], [False, True, True, True, True])

    def test_cleanup_only_old_matching_files(self):
        self.bdir.mkdir()
        old = self.bdir / "qeukao-db-20200101-000000.sqlite3"
        new = self.bdir / "qeukao-db-20990101-000000.sqlite3"
        other = self.bdir / "other-old.sqlite3"
        for f in (old, new, other):
            f.write_bytes(b"x")
        t = time.time() - 100 * 86400
        os.utime(old, (t, t))
        os.utime(other, (t, t))
        self.assertEqual(qk_dbtools.cleanup_old_backups(retention_days=90), 1)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists() and other.exists())

    def test_list_backups_newest_first(self):
        self.bdir.mkdir()
        a = self.bdir / "qeukao-db-a.sqlite3"
        b = self.bdir / "qeukao-db-b.sqlite3"
        a.write_bytes(b"1")
        b.write_bytes(b"22")
        os.utime(a, (1000, 1000))
        os.utime(b, (2000, 2000))
        items = qk_dbtools.list_backups()
        self.assertEqual([i["name"] for i in items], [b.name, a.name])
        self.assertEqual(items[0]["size"], 2)

    def test_backup_due_boundaries(self):
        self.assertTrue(qk_dbtools.backup_due(1000.0, None, 1))
        self.assertFalse(qk_dbtools.backup_due(3599, 0.0, 1))
        self.assertTrue(qk_dbtools.backup_due(3600, 0.0, 1))

    def test_tick_respects_enabled_and_recency(self):
        qk_config.save({"backup": {"enabled": False}})
        self.assertFalse(qk_dbtools._scheduler_tick())
        self.assertEqual(qk_dbtools.list_backups(), [])
        qk_config.save({"backup": {"enabled": True, "everyDays": 1}})
        self.assertTrue(qk_dbtools._scheduler_tick())
        self.assertEqual(len(qk_dbtools.list_backups()), 1)
        self.assertFalse(qk_dbtools._scheduler_tick())  # fresh backup -> not due
        qk_config.save({"backup": {"everyHours": 1, "keepCount": 1}})
        first = Path(qk_dbtools.list_backups()[0]["path"])
        stamp = time.time() - 3601
        os.utime(first, (stamp, stamp))
        self.assertTrue(qk_dbtools._scheduler_tick())
        self.assertEqual(len(qk_dbtools.list_backups()), 1)
        self.assertFalse(first.exists())

    def test_start_scheduler_returns_daemon_thread(self):
        # A real daemon must not outlive the fixture and read later tests' config.
        import subprocess
        import sys
        qk_config.save({"backup": {"enabled": False}})
        subprocess.run([sys.executable, "-c", """
import qk_dbtools
thread = qk_dbtools.start_backup_scheduler()
assert thread.daemon and thread.is_alive()
assert qk_dbtools.start_backup_scheduler() is thread
"""], env=dict(os.environ), check=True, timeout=10)

LOG_DDL = (
    "CREATE TABLE operation_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, "
    "severity TEXT NOT NULL, title TEXT NOT NULL, message TEXT NOT NULL, actor_ip TEXT, room_name TEXT, "
    "report_id INTEGER, batch_token TEXT, details TEXT, created_at TEXT NOT NULL)"
)


def add_log_table(path: Path):
    conn = sqlite3.connect(str(path))
    conn.execute(LOG_DDL)
    conn.commit()
    conn.close()


def log_events(path: Path):
    conn = sqlite3.connect(str(path))
    try:
        return [r[0] for r in conn.execute("SELECT event_type FROM operation_logs ORDER BY id")]
    finally:
        conn.close()


class OperationLogTests(DbTestCase):
    """契约 v1.1：db_backup / db_exported / db_imported 由 qk_dbtools 自己写（GUI 直接调用，不经 app 路由）。"""

    def test_backup_writes_one_db_backup_event(self):
        add_log_table(qk_config.DB_PATH)
        qk_dbtools.backup_database(tag="auto")
        self.assertEqual(log_events(qk_config.DB_PATH), ["db_backup"])

    def test_export_writes_db_exported_event(self):
        add_log_table(qk_config.DB_PATH)
        qk_dbtools.export_database(self.tmp / "out" / "x.sqlite3")
        self.assertEqual(log_events(qk_config.DB_PATH), ["db_exported"])

    def test_import_writes_db_imported_only_after_hook_created_the_table(self):
        src = self.tmp / "src.sqlite3"
        make_db(src, ["new-1"])  # 没有 operation_logs 表，模拟旧库
        qk_dbtools.set_post_import_hook(lambda: add_log_table(qk_config.DB_PATH))  # 模拟 init_db 补表
        qk_dbtools.import_database(src)
        # 导入前的自动备份不记日志（它写进的现库马上会被覆盖）；导入完成记一条
        self.assertEqual(log_events(qk_config.DB_PATH), ["db_imported"])

    def test_log_write_failure_never_fails_the_operation(self):
        conn = sqlite3.connect(str(qk_config.DB_PATH))
        conn.execute("CREATE TABLE operation_logs (event_type TEXT)")  # 缺列：INSERT 必失败
        conn.commit()
        conn.close()
        p = qk_dbtools.backup_database()
        self.assertTrue(p.is_file())
        qk_dbtools.export_database(self.tmp / "e.sqlite3")
        self.assertTrue((self.tmp / "e.sqlite3").is_file())

    def test_no_log_table_is_silently_skipped(self):
        self.assertTrue(qk_dbtools.backup_database().is_file())  # 现库没有 operation_logs


class ImportNoDeadlockTests(DbTestCase):
    def test_import_with_existing_live_db_returns_promptly(self):
        import threading
        src = self.tmp / "src.sqlite3"
        make_db(src, ["n"])
        done = []
        th = threading.Thread(target=lambda: done.append(qk_dbtools.import_database(src)), daemon=True)
        th.start()
        th.join(8)
        self.assertTrue(done, "import_database 卡死（持 _io_lock 时再取同一把锁）")


if __name__ == "__main__":
    unittest.main()
