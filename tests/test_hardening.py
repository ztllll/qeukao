"""审查（a4125e1）发现的加固项：先红后绿。"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
import unittest

import qk_config
import qk_dbtools
from tests.test_dbtools import DbTestCase, make_db, notes


class WindowsPortSharingTests(unittest.TestCase):
    """Windows 的 SO_REUSEADDR 允许第二个进程绑定到「正在监听」的同一端口，双击两次 exe 会悄悄起两个服务。
    allow_reuse_address 是类体里按 os.name 求值的，Linux 上直接测不到 Windows 分支，所以这里读源码、在伪造的 os.name 下求值。
    （在 wine 里连这条回退都分不出来：wine 的 bind 一律拒绝，所以只能靠这个源码级检查守住。）"""

    def _reuse_flag(self, os_name):
        import ast
        from pathlib import Path
        tree = ast.parse((Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "_Server")
        assign = next(n for n in cls.body if isinstance(n, ast.Assign) and any(getattr(x, "id", "") == "allow_reuse_address" for x in n.targets))
        fake_os = type("os", (), {"name": os_name})
        return eval(compile(ast.Expression(assign.value), "app.py", "eval"), {"os": fake_os})

    def test_reuse_address_is_off_on_windows_and_unchanged_elsewhere(self):
        self.assertIs(self._reuse_flag("nt"), False)
        self.assertIs(self._reuse_flag("posix"), True)


class RoomListAtomicityTests(unittest.TestCase):
    """教室名单、老师提交、下发回包的原子性（审查 e9b50cb）。
    每个场景在子进程里跑（临时数据目录），并在关键点插入另一个线程/调用来制造竞态，不靠运气。
    不变量：库里每个草稿的 room_name 都等于「当前名单」里该 room_number 对应的名字。"""

    PRELUDE = r'''
import json, os, sys, threading, time
sys.path.insert(0, os.getcwd())
import app, qk_agents, qk_config
app.init_all()
qk_agents.create_dispatch({"mode": "now", "title": "T"}, "x")
def invariant():
    names = qk_config.room_names()
    with app.get_db() as conn:
        rows = conn.execute("SELECT room_number, room_name FROM current_report_drafts").fetchall()
    return all(0 < r["room_number"] <= len(names) and names[r["room_number"] - 1] == r["room_name"] for r in rows)
def outcome_of(fn):
    try:
        fn()
        return "ok"
    except Exception as exc:
        return str(getattr(exc, "code", type(exc).__name__))
'''

    def run_scenario(self, body):
        import subprocess
        import sys
        import tempfile
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory(prefix="qk-atomic-") as tmp:
            (Path(tmp) / "config.json").write_text(json.dumps({"backup": {"enabled": False, "dir": str(Path(tmp) / "b")}}), encoding="utf-8")
            env = dict(os.environ, QEUKAO_DATA_DIR=tmp)
            for key in ("QEUKAO_DB", "QEUKAO_ADMIN_PASSWORD", "QEUKAO_SESSION_SECRET"):
                env.pop(key, None)
            out = subprocess.run([sys.executable, "-c", self.PRELUDE + body], cwd=str(root), env=env, capture_output=True, text=True, timeout=90)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        return json.loads(out.stdout.strip().splitlines()[-1])

    def test_teacher_submit_arriving_between_the_admin_check_and_save_cannot_break_the_room_list(self):
        got = self.run_scenario(r'''
real_save = qk_config.save
state = {}
def teacher():
    state["teacher"] = outcome_of(lambda: app.upsert_current_report_draft({"roomName": "一教室", "expectedCount": 5, "actualCount": 5}, "1.1.1.1"))
def slow_save(patch):
    state["thread"] = threading.Thread(target=teacher)
    state["thread"].start()
    time.sleep(0.5)  # 老师的提交恰好在管理员「检查之后、保存之前」到达
    return real_save(patch)
qk_config.save = slow_save
state["admin"] = outcome_of(lambda: qk_agents.save_site({"roomCount": 2, "roomNames": ["甲教室", "乙教室"]}, "x"))
state["thread"].join(15)
print(json.dumps({"admin": state["admin"], "teacher": state["teacher"], "invariant": invariant()}))
''')
        self.assertTrue(got["invariant"], got)
        self.assertNotEqual((got["admin"], got["teacher"]), ("ok", "ok"), "名单换了，老师还按旧名单提交成功")

    def test_teacher_validated_against_the_old_list_cannot_commit_after_the_admin_changed_it(self):
        got = self.run_scenario(r'''
real_validate = app.validate_report
state = {}
def admin():
    state["admin"] = outcome_of(lambda: qk_agents.save_site({"roomCount": 1, "roomNames": ["甲教室"]}, "x"))
def validate_then_race(raw):
    data = real_validate(raw)
    if "thread" not in state:  # 老师已经按旧名单验证完，管理员在这时改名单（场次开放、还没有草稿）
        state["thread"] = threading.Thread(target=admin)
        state["thread"].start()
        time.sleep(0.5)
    return data
app.validate_report = validate_then_race
state["teacher"] = outcome_of(lambda: app.upsert_current_report_draft({"roomName": "一教室", "expectedCount": 5, "actualCount": 5}, "1.1.1.1"))
state["thread"].join(15)
print(json.dumps({"admin": state["admin"], "teacher": state["teacher"], "invariant": invariant()}))
''')
        self.assertTrue(got["invariant"], got)

    def test_dispatch_reply_reports_the_title_this_dispatch_really_got_not_a_later_ones(self):
        got = self.run_scenario(r'''
real_list = qk_agents.list_dispatches
def hijack():
    qk_agents.list_dispatches = real_list
    qk_agents.create_dispatch({"mode": "now", "title": "C"}, "x")  # 另一位管理员在回包生成前又下发了一条
    return real_list()
qk_agents.list_dispatches = hijack
reply = qk_agents.create_dispatch({"mode": "now", "title": "B"}, "x")
print(json.dumps({"sessionTitle": reply["sessionTitle"], "titleKept": reply["titleKept"]}))
''')
        self.assertEqual(got, {"sessionTitle": "B", "titleKept": False})

    def test_analytics_answers_from_one_snapshot_even_if_a_report_lands_mid_request(self):
        got = self.run_scenario(r"""
import sqlite3
app.upsert_current_report_draft({"roomName": "一教室", "expectedCount": 10, "actualCount": 9}, "1.1.1.1")
app.accept_reports({}, "x")
real_get_db = app.get_db
state = {"fired": False}
class Conn(sqlite3.Connection):
    def execute(self, sql, *args):
        cur = super().execute(sql, *args)
        if "GROUP BY title, exam_date" in sql and not state["fired"]:
            state["fired"] = True
            app.get_db = real_get_db  # 这一次提交走普通连接，模拟另一位老师/管理员此刻刚好入库
            qk_agents.create_dispatch({"mode": "now", "title": "T2"}, "x")
            app.upsert_current_report_draft({"roomName": "二教室", "expectedCount": 20, "actualCount": 20}, "1.1.1.2")
            app.accept_reports({}, "x")
        return cur
def patched_get_db():
    conn = sqlite3.connect(app.DB_PATH, timeout=5, factory=Conn)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn
app.get_db = patched_get_db
data = qk_agents.analytics({})
app.get_db = real_get_db
print(json.dumps({"fired": state["fired"], "total": data["totals"]["expected"], "rooms": sum(r["expected"] for r in data["rooms"]),
                  "exams": sum(e["expected"] for e in data["exams"]), "topAbsent": sum(r["absent"] for r in data["topAbsent"]),
                  "totalAbsent": data["totals"]["absent"]}))
""")
        self.assertTrue(got["fired"], got)
        self.assertEqual(got["total"], got["rooms"], got)
        self.assertEqual(got["total"], got["exams"], got)
        self.assertEqual(got["topAbsent"], got["totalAbsent"], got)

    def test_whole_database_import_cannot_slip_between_the_room_list_check_and_save(self):
        got = self.run_scenario(r"""
import qk_dbtools
app.upsert_current_report_draft({"roomName": "一教室", "expectedCount": 5, "actualCount": 5}, "1.1.1.1")
snapshot = str(qk_dbtools.backup_database(tag="t"))  # 带着「一教室」草稿的备份
app.accept_reports({}, "x")                          # 现库验收后没有草稿
real_save = qk_config.save
state = {}
def importer():
    state["import"] = outcome_of(lambda: qk_dbtools.import_database(snapshot))
def slow_save(patch):
    state["thread"] = threading.Thread(target=importer)
    state["thread"].start()
    time.sleep(0.8)  # 管理员「检查无草稿」之后、保存之前，另一个人导入了带草稿的库
    return real_save(patch)
qk_config.save = slow_save
state["admin"] = outcome_of(lambda: qk_agents.save_site({"roomCount": 1, "roomNames": ["甲教室"]}, "x"))
state["thread"].join(30)
print(json.dumps({"admin": state["admin"], "import": state["import"], "invariant": invariant()}))
""")
        self.assertTrue(got["invariant"], got)
        self.assertNotEqual((got["admin"], got["import"]), ("ok", "ok"), got)

    def test_importing_a_database_whose_drafts_do_not_fit_the_current_room_list_is_refused(self):
        got = self.run_scenario(r"""
import qk_dbtools
app.upsert_current_report_draft({"roomName": "一教室", "expectedCount": 5, "actualCount": 5}, "1.1.1.1")
snapshot = str(qk_dbtools.backup_database(tag="t"))
app.accept_reports({}, "x")
qk_agents.save_site({"roomCount": 1, "roomNames": ["甲教室"]}, "x")  # 名单已改，备份里的草稿还是旧名单
state = {"import": outcome_of(lambda: qk_dbtools.import_database(snapshot))}
state["invariant"] = invariant()
print(json.dumps(state))
""")
        self.assertTrue(got["invariant"], got)
        self.assertNotEqual(got["import"], "ok", "草稿与当前教室名单对不上的库不应被导入")

    def test_import_refuses_a_backup_whose_draft_table_is_unreadable_before_touching_the_live_database(self):
        got = self.run_scenario(r"""
import sqlite3, qk_dbtools
app.upsert_current_report_draft({"roomName": "一教室", "expectedCount": 5, "actualCount": 5}, "1.1.1.1")
snapshot = str(qk_dbtools.backup_database(tag="t"))
c = sqlite3.connect(snapshot)
c.execute("ALTER TABLE current_report_drafts RENAME COLUMN room_number TO wrong_number")
c.commit(); c.close()
app.accept_reports({}, "x")
before = sqlite3.connect(str(qk_config.DB_PATH)).execute("SELECT sql FROM sqlite_master WHERE name='current_report_drafts'").fetchone()[0]
outcome = outcome_of(lambda: qk_dbtools.import_database(snapshot))
after = sqlite3.connect(str(qk_config.DB_PATH)).execute("SELECT sql FROM sqlite_master WHERE name='current_report_drafts'").fetchone()[0]
print(json.dumps({"outcome": outcome, "liveTableUntouched": before == after}))
""")
        self.assertNotEqual(got["outcome"], "ok", got)
        self.assertTrue(got["liveTableUntouched"], "坏备份必须在覆盖现库之前被拒绝")

    def test_import_still_accepts_an_old_backup_that_has_no_draft_table(self):
        got = self.run_scenario(r"""
import sqlite3, qk_dbtools
snapshot = str(qk_dbtools.backup_database(tag="t"))
c = sqlite3.connect(snapshot)
c.execute("DROP TABLE current_report_drafts")
c.commit(); c.close()
print(json.dumps({"outcome": outcome_of(lambda: qk_dbtools.import_database(snapshot))}))
""")
        self.assertEqual(got["outcome"], "ok", got)


class ImportSnapshotTests(DbTestCase):
    def test_import_keeps_rows_that_only_live_in_the_source_wal(self):
        src = self.tmp / "wal-src.sqlite3"
        s = sqlite3.connect(str(src))
        try:
            s.execute("PRAGMA journal_mode=WAL")
            s.execute("PRAGMA wal_autocheckpoint=0")
            s.execute("CREATE TABLE absence_reports (id INTEGER PRIMARY KEY, note TEXT)")
            s.execute("INSERT INTO absence_reports (note) VALUES ('checkpointed')")
            s.commit()
            s.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            s.execute("INSERT INTO absence_reports (note) VALUES ('only-in-wal')")
            s.commit()
            res = qk_dbtools.import_database(src)
        finally:
            s.close()
        self.assertEqual(res["reportCount"], 2)
        self.assertEqual(notes(qk_config.DB_PATH), ["checkpointed", "only-in-wal"])


class ExportGuardTests(DbTestCase):
    def test_export_to_the_live_database_path_is_refused(self):
        conn = sqlite3.connect(str(qk_config.DB_PATH))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            with self.assertRaises(qk_dbtools.DbToolError):
                qk_dbtools.export_database(qk_config.DB_PATH)
            alias = qk_config.DB_PATH.parent / ".." / qk_config.DB_PATH.parent.name / qk_config.DB_PATH.name
            with self.assertRaises(qk_dbtools.DbToolError):
                qk_dbtools.export_database(alias)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM absence_reports").fetchone()[0], 2)
        finally:
            conn.close()


class HookRunsUnderImportLockTests(DbTestCase):
    def test_second_import_waits_for_the_first_imports_hook(self):
        s1 = self.tmp / "s1.sqlite3"
        make_db(s1, ["one"])
        s2 = self.tmp / "s2.sqlite3"
        make_db(s2, ["two-a", "two-b"])
        entered, release, calls, done = threading.Event(), threading.Event(), [], []

        def hook():
            calls.append(1)
            if len(calls) == 1:
                entered.set()
                release.wait(10)

        qk_dbtools.set_post_import_hook(hook)
        a = threading.Thread(target=lambda: done.append("a" if qk_dbtools.import_database(s1) else ""), daemon=True)
        b = threading.Thread(target=lambda: done.append("b" if qk_dbtools.import_database(s2) else ""), daemon=True)
        a.start()
        self.assertTrue(entered.wait(10))
        b.start()
        b.join(1.0)
        try:
            self.assertEqual(done, [], "第二次导入不应在第一次的 hook 结束前完成")
            self.assertEqual(notes(qk_config.DB_PATH), ["one"])
        finally:
            release.set()
            a.join(10)
            b.join(10)
        self.assertEqual(sorted(done), ["a", "b"])
        self.assertEqual(notes(qk_config.DB_PATH), ["two-a", "two-b"])


class CorruptConfigTests(DbTestCase):
    def test_corrupt_config_after_a_password_change_does_not_reopen_the_default_password(self):
        qk_config.set_admin_password("changed-admin")
        self.assertTrue(qk_config.check_admin_password("changed-admin"))
        qk_config.CONFIG_PATH.write_text("{ not json", encoding="utf-8")
        qk_config._reload_paths_for_tests()
        self.assertFalse(qk_config.check_admin_password("112233"))
        self.assertFalse(qk_config.check_admin_password("changed-admin"))
        self.assertTrue(qk_config.password_locked())
        self.assertTrue(list(qk_config.DATA_DIR.glob("config.json.bad-*")), "坏文件应被隔离保留")
        qk_config.set_admin_password("brand-new")  # 本机 GUI 重设密码是唯一恢复路径
        self.assertTrue(qk_config.check_admin_password("brand-new"))
        self.assertFalse(qk_config.check_admin_password("112233"))
        self.assertFalse(qk_config.password_locked())

    def test_missing_config_is_still_a_first_run_with_the_default_password(self):
        qk_config.CONFIG_PATH.unlink()
        qk_config._reload_paths_for_tests()
        self.assertTrue(qk_config.check_admin_password("112233"))
        self.assertFalse(qk_config.password_locked())

    def test_absurd_hash_rounds_fail_closed_without_raising(self):
        for rounds in ("999999999999999999999", "0", "-5", "99999999"):
            cfg = json.loads(qk_config.CONFIG_PATH.read_text(encoding="utf-8"))
            cfg["passwordHash"] = "pbkdf2$%s$%s$%s" % (rounds, "00" * 16, "00" * 32)
            qk_config.CONFIG_PATH.write_text(json.dumps(cfg), encoding="utf-8")
            qk_config._reload_paths_for_tests()
            self.assertFalse(qk_config.check_admin_password("x"), rounds)


class RoomPreviewMatchesRealMatchingTests(DbTestCase):
    def test_gui_preview_never_disagrees_with_room_from_ip(self):
        import server_gui
        for ip in ("10.10.7.23", "10.10.007.23", "10.10.\u00b2.23", "10.10.7", "10.10.7.999", "10.11.7.23", "10.10.31.1", ""):
            real = qk_config.room_from_ip(ip)
            rule = qk_config.load()["roomRule"]
            shown = server_gui.preview_room(str(rule["octet"]), rule["prefix"], ip)  # 用当前生效的规则预览；不得抛异常
            if real:
                self.assertEqual(shown, "→ 教室编号 %d" % real["roomNumber"], ip)
            else:
                self.assertFalse(shown.startswith("→"), (ip, shown))

class ConfigEncodingTests(DbTestCase):
    def test_config_saved_with_a_utf8_bom_is_not_treated_as_corrupt(self):
        key_before = qk_config.enroll_key()
        raw = qk_config.CONFIG_PATH.read_text(encoding="utf-8")
        qk_config.CONFIG_PATH.write_bytes(b"\xef\xbb\xbf" + raw.encode("utf-8"))  # 记事本另存为 UTF-8(带 BOM)
        qk_config._reload_paths_for_tests()
        self.assertEqual(qk_config.enroll_key(), key_before, "BOM 不能让密钥被轮换(已分发的客户端会全部失效)")
        self.assertFalse(qk_config.password_locked())
        self.assertFalse(list(qk_config.DATA_DIR.glob("config.json.bad-*")))


class ReadOnlySourceTests(DbTestCase):
    def test_import_from_a_read_only_directory_with_wal_but_no_shm(self):
        src = self.tmp / "wal-src.sqlite3"
        s = sqlite3.connect(str(src))
        s.execute("PRAGMA journal_mode=WAL")
        s.execute("PRAGMA wal_autocheckpoint=0")
        s.execute("CREATE TABLE absence_reports (id INTEGER PRIMARY KEY, note TEXT)")
        s.execute("INSERT INTO absence_reports (note) VALUES ('a')")
        s.commit()
        s.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        s.execute("INSERT INTO absence_reports (note) VALUES ('b')")
        s.commit()
        ro = self.tmp / "ro"
        ro.mkdir()
        shutil.copyfile(src, ro / "x.sqlite3")
        shutil.copyfile(str(src) + "-wal", ro / "x.sqlite3-wal")  # 故意不带 -shm（只读介质/拷贝时常见）
        s.close()
        os.chmod(ro, 0o555)
        try:
            res = qk_dbtools.import_database(ro / "x.sqlite3")
        finally:
            os.chmod(ro, 0o755)
        self.assertEqual(res["reportCount"], 2)
        self.assertEqual(sorted(p.name for p in ro.iterdir()), ["x.sqlite3", "x.sqlite3-wal"], "不得在用户目录留下文件")


class HashRoundsBoundTests(DbTestCase):
    def test_huge_rounds_are_refused_instantly_not_computed(self):
        cfg = json.loads(qk_config.CONFIG_PATH.read_text(encoding="utf-8"))
        cfg["passwordHash"] = "pbkdf2$50000000$%s$%s" % ("00" * 16, "00" * 32)
        qk_config.CONFIG_PATH.write_text(json.dumps(cfg), encoding="utf-8")
        qk_config._reload_paths_for_tests()
        started = time.monotonic()
        self.assertFalse(qk_config.check_admin_password("x"))
        self.assertLess(time.monotonic() - started, 3.0, "超大 rounds 必须直接拒绝，不能真去算")


if __name__ == "__main__":
    unittest.main()