"""Public Windows HTTP contract checks (standard library, isolated data/ports)."""
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import struct
from datetime import datetime, timedelta
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
import unittest
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
CLOSED = "当前暂无可填报场次，请联系考务管理员"


def xlsx_bytes(sheets):
    """sheets: [(name, rows)]；单元格为 str（inlineStr）或数字。只用标准库造最小 xlsx。"""
    def cell(r, c, v):
        ref = "%s%d" % (chr(65 + c), r)
        return '<c r="%s"><v>%s</v></c>' % (ref, v) if isinstance(v, (int, float)) else '<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, escape(v))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>%s</sheets></workbook>' % "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(n), i, i) for i, (n, _) in enumerate(sheets, 1)))
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>' % "".join('<Relationship Id="rId%d" Target="worksheets/sheet%d.xml"/>' % (i, i) for i in range(1, len(sheets) + 1)))
        for i, (_, rows) in enumerate(sheets, 1):
            body = "".join('<row r="%d">%s</row>' % (r, "".join(cell(r, c, v) for c, v in enumerate(row))) for r, row in enumerate(rows, 1))
            z.writestr("xl/worksheets/sheet%d.xml" % i, '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % body)
    return out.getvalue()


def xlsx_rows(data):
    """读回导出的 sheet1：每行是单元格文本列表（只认 inlineStr 与数值）。"""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    return [["".join(t.text or "" for t in c.iter(ns + "t")) if c.get("t") == "inlineStr" else c.find(ns + "v").text for c in row] for row in root.iter(ns + "row")]


class AgentsHTTPTest(unittest.TestCase):
    def setUp(self):
        self.data = Path(subprocess.check_output(["mktemp", "-d"], text=True).strip())
        self.addCleanup(shutil.rmtree, self.data)
        (self.data / "config.json").write_text(json.dumps({"backup": {"enabled": False, "dir": str(self.data / "backups")}}), encoding="utf-8")
        self.cookie = ""
        self.process = None
        self.addCleanup(self.stop)

    def start(self, admin_password="112233"):
        for port in range(18320, 18999):
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", port))
                    break
                except OSError:
                    continue
        else:
            self.fail("no isolated test port available")
        self.url = "http://127.0.0.1:%s" % port
        env = dict(os.environ, QEUKAO_DATA_DIR=str(self.data), QEUKAO_HOST="127.0.0.1", QEUKAO_PORT=str(port), QEUKAO_CLIENT_TEMPLATE=str(self.data / "client-template.exe"))
        env.pop("QEUKAO_DB", None)
        env.pop("QEUKAO_ADMIN_PASSWORD", None)
        if admin_password:  # 默认用环境变量指定密码，不触发「首次必须改密码」；那条路径有专门的测试
            env["QEUKAO_ADMIN_PASSWORD"] = admin_password
        env.pop("QEUKAO_SESSION_SECRET", None)
        code = "import app; app.init_all(); app.init_all(); app.build_server(app.HOST, app.PORT).serve_forever()"
        self.process = subprocess.Popen([sys.executable, "-u", "-c", code], cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.fail(self.process.stdout.read().decode())
            try:
                if self.call("GET", "/api/health")[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(0.05)
        self.fail("test server did not start")

    def stop(self):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.communicate()

    def call(self, method, path, body=None, headers=None):
        request_headers = {"Cookie": self.cookie, **(headers or {})}
        raw = body if isinstance(body, bytes) else None if body is None else json.dumps(body).encode()
        if raw is not None:
            request_headers["Content-Type"] = "application/octet-stream" if isinstance(body, bytes) else "application/json"
        request = urllib.request.Request(self.url + path, raw, request_headers, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            cookie = response.headers.get("Set-Cookie")
            if cookie:
                self.cookie = cookie.split(";", 1)[0]
            result = json.load(response) if "application/json" in response.headers.get("Content-Type", "") else response.read()
            return response.status, result

    def upload(self, path, data, name="出考率.xlsx"):
        return self.call("POST", path, data, {"X-File-Name": urllib.parse.quote(name)})

    def login(self, password="112233"):
        self.assertEqual(self.call("POST", "/api/admin/login", {"password": password})[0], 200)

    def test_new_database_is_closed_before_password_or_report_validation(self):
        self.start()
        status, payload = self.call("GET", "/api/session")
        self.assertEqual(status, 200)
        self.assertFalse(payload["data"]["open"])
        self.assertEqual(payload["data"]["closedMessage"], CLOSED)
        for path in ("/api/current-reports/check-room", "/api/current-reports"):
            status, payload = self.call("POST", path, {"password": "wrong"})
            self.assertEqual(status, 409)
            self.assertEqual(payload["error"], {"code": "NO_OPEN_SESSION", "message": CLOSED})

    def test_dispatch_submission_acceptance_and_historical_password(self):
        self.start()
        self.login()
        status, payload = self.call("POST", "/api/admin/dispatch", {"mode": "now", "title": "上午考试"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["status"], "fired")
        self.assertTrue(self.call("GET", "/api/session")[1]["data"]["open"])
        report = {"roomName": "一教室", "expectedCount": 45, "actualCount": 43}
        self.assertEqual(self.call("POST", "/api/current-reports/check-room", report)[0], 200)
        self.assertEqual(self.call("POST", "/api/current-reports", report)[0], 200)
        self.assertEqual(self.call("POST", "/api/admin/accept", {})[0], 201)
        self.assertEqual(self.call("GET", "/api/current-reports")[1]["data"]["items"], [])
        self.assertEqual(self.call("POST", "/api/current-reports", {**report, "previousRoomName": "一教室"})[0], 409)
        self.assertEqual(self.call("POST", "/api/current-reports/check-room", report)[0], 409)
        self.assertEqual(self.call("POST", "/api/admin/password", {"oldPassword": "wrong", "newPassword": "new-pass"})[0], 401)
        self.assertEqual(self.call("POST", "/api/admin/password", {"oldPassword": "112233", "newPassword": "x"})[0], 400)
        self.assertEqual(self.call("POST", "/api/admin/password", {"oldPassword": "112233", "newPassword": "new-pass"})[0], 200)
        self.assertEqual(self.call("POST", "/api/admin/login", {"password": "112233"})[0], 401)
        self.login("new-pass")
        record = self.call("GET", "/api/admin/reports")[1]["data"]["items"][0]
        path = "/api/admin/reports/%s" % record["id"]
        self.cookie = ""
        self.assertEqual(self.call("DELETE", path)[0], 401, "没登录后台不能删除")
        self.login("new-pass")
        self.assertEqual(self.call("DELETE", path)[0], 200)

    # ---- 重构：管理员统一在后台设置，前台只填报----
    def open_session(self, title="期中考试"):
        self.login()
        status, payload = self.call("POST", "/api/admin/dispatch", {"mode": "now", "title": title})
        self.assertEqual(status, 200, payload)

    def test_dispatch_requires_a_title_and_defaults_the_exam_date_to_today(self):
        self.start()
        self.login()
        for bad in ({}, {"title": ""}, {"title": "   "}):
            status, payload = self.call("POST", "/api/admin/dispatch", {"mode": "now", **bad})
            self.assertEqual(status, 400, payload)
            self.assertIn("标题", payload["error"]["message"])
        self.assertFalse(self.call("GET", "/api/session")[1]["data"]["open"], "标题缺失时不能开放场次")
        status, payload = self.call("POST", "/api/admin/dispatch", {"mode": "now", "title": "第三次月考"})
        self.assertEqual(status, 200, payload)
        session = self.call("GET", "/api/session")[1]["data"]
        self.assertEqual(session["title"], "第三次月考")
        self.assertEqual(session["examDate"], datetime.now().strftime("%Y-%m-%d"))
        self.assertEqual(self.call("POST", "/api/admin/dispatch", {"mode": "now", "title": "x", "examDate": "2026-13-40"})[0], 400)

    def test_title_and_exam_date_come_from_the_dispatch_not_from_the_fill_page(self):
        self.start()
        self.login()
        self.call("POST", "/api/admin/dispatch", {"mode": "now", "title": "秋季期末", "examDate": "2026-12-30"})
        report = {"roomName": "一教室", "expectedCount": 45, "actualCount": 43, "title": "老师乱填的标题", "examDate": "1999-01-01"}
        self.assertEqual(self.call("POST", "/api/current-reports", report)[0], 200)
        item = self.call("GET", "/api/current-reports")[1]["data"]["items"][0]
        self.assertEqual((item["title"], item["examDate"]), ("秋季期末", "2026-12-30"))

    def test_front_page_cannot_change_anything_after_submit(self):
        self.start()
        self.open_session()
        report = {"roomName": "二教室", "expectedCount": 40, "actualCount": 39}
        self.assertEqual(self.call("POST", "/api/current-reports", report)[0], 200)
        self.cookie = ""  # 老师没有后台登录态
        for method, path, body in (
            ("POST", "/api/current-reports", {**report, "actualCount": 30, "previousRoomName": "二教室", "password": "112233"}),
            ("POST", "/api/current-reports", {**report, "actualCount": 30}),
            ("POST", "/api/current-project", {"title": "改标题", "password": "112233"}),
            ("POST", "/api/reports/accept", {"password": "112233"}),
            ("POST", "/api/reports/verify-password", {"password": "112233"}),
        ):
            status, payload = self.call(method, path, body)
            self.assertIn(status, (401, 404, 409), (path, payload))
        self.assertEqual(self.call("GET", "/api/current-reports")[1]["data"]["items"][0]["actualCount"], 39)

    def test_admin_changes_data_and_accepts_without_retyping_the_password(self):
        self.start()
        self.open_session()
        self.assertEqual(self.call("POST", "/api/current-reports", {"roomName": "三教室", "expectedCount": 30, "actualCount": 29})[0], 200)
        self.assertEqual(self.call("POST", "/api/admin/accept", {})[0], 201)
        self.assertEqual(self.call("GET", "/api/current-reports")[1]["data"]["items"], [])
        self.assertEqual(self.call("GET", "/api/session")[1]["data"]["open"], False)
        record = self.call("GET", "/api/admin/reports")[1]["data"]["items"][0]
        path = "/api/admin/reports/%s" % record["id"]
        status, _ = self.call("PUT", path, {"title": "改后的标题", "examDate": "2026-10-01", "items": [{"id": record["id"], "expectedCount": 30, "actualCount": 28}]})
        self.assertEqual(status, 200)
        self.assertEqual(self.call("DELETE", path)[0], 200)
        self.cookie = ""
        self.assertEqual(self.call("POST", "/api/admin/accept", {})[0], 401, "没登录后台不能验收")
        self.assertEqual(self.call("DELETE", path)[0], 401)

    def test_admin_edits_a_submitted_room_from_the_backend(self):
        self.start()
        self.open_session()
        self.call("POST", "/api/current-reports", {"roomName": "四教室", "expectedCount": 50, "actualCount": 48})
        status, payload = self.call("PUT", "/api/admin/current-reports/" + urllib.parse.quote("四教室"), {"expectedCount": 50, "actualCount": 47})
        self.assertEqual(status, 200, payload)
        self.assertEqual(self.call("GET", "/api/current-reports")[1]["data"]["items"][0]["actualCount"], 47)
        self.cookie = ""
        self.assertEqual(self.call("PUT", "/api/admin/current-reports/" + urllib.parse.quote("四教室"), {"expectedCount": 50, "actualCount": 1})[0], 401)

    def test_site_settings_drive_names_room_count_and_public_site_info(self):
        self.start()
        self.login()
        site = self.call("GET", "/api/site")[1]["data"]
        self.assertEqual((site["orgName"], len(site["roomNames"])), ("", 30))
        self.assertEqual(self.call("POST", "/api/admin/site", {"orgName": "  "})[0], 400)  # 保存时单位名称不能空
        status, payload = self.call("POST", "/api/admin/site", {"orgName": "示范考点", "orgAddress": "某市某路1号", "roomCount": 3, "roomNames": ["甲教室", "乙教室", "丙教室"]})
        self.assertEqual(status, 200, payload)
        site = self.call("GET", "/api/site")[1]["data"]
        self.assertEqual((site["orgName"], site["orgAddress"], site["roomNames"]), ("示范考点", "某市某路1号", ["甲教室", "乙教室", "丙教室"]))
        self.call("POST", "/api/admin/dispatch", {"mode": "now", "title": "t"})
        self.assertEqual(self.call("POST", "/api/current-reports", {"roomName": "乙教室", "expectedCount": 10, "actualCount": 9})[0], 200)
        self.assertEqual(self.call("POST", "/api/current-reports", {"roomName": "一教室", "expectedCount": 10, "actualCount": 9})[0], 400)
        self.assertEqual(len(self.call("GET", "/api/admin/live")[1]["data"]["rooms"]), 3)
        for bad in ({"roomCount": 0}, {"roomCount": 501}, {"roomCount": 2, "roomNames": ["只有一个"]}, {"orgName": ""}, {"roomNames": ["甲", "甲", "丙"], "roomCount": 3}):
            self.assertEqual(self.call("POST", "/api/admin/site", bad)[0], 400, bad)
        self.cookie = ""
        self.assertEqual(self.call("POST", "/api/admin/site", {"orgName": "黑客"})[0], 401)

    def test_room_list_cannot_change_while_there_is_unaccepted_data(self):
        # 草稿按 room_number 存：名单一变，已提交的数据会挂到别的教室名下，管理员也改不了它。有未验收数据时必须先验收。
        self.start()
        self.open_session()
        self.assertEqual(self.call("POST", "/api/current-reports", {"roomName": "一教室", "expectedCount": 10, "actualCount": 9})[0], 200)
        for change in ({"roomCount": 2, "roomNames": ["甲教室", "乙教室"]}, {"roomCount": 40}, {"roomNames": ["甲教室"] + ["%d号" % i for i in range(29)]}):
            status, payload = self.call("POST", "/api/admin/site", change)
            self.assertEqual(status, 409, (change, payload))
            self.assertIn("验收", payload["error"]["message"])
        self.assertEqual(self.call("GET", "/api/site")[1]["data"]["roomNames"][0], "一教室")
        # 名称和地址与教室名单无关，随时可以改
        self.assertEqual(self.call("POST", "/api/admin/site", {"orgName": "新名称", "orgAddress": "新地址"})[0], 200)
        # 原样提交同一份名单也不算变动（后台表单整体提交时不应被误拦）
        same = self.call("GET", "/api/site")[1]["data"]["roomNames"]
        self.assertEqual(self.call("POST", "/api/admin/site", {"roomCount": 30, "roomNames": same})[0], 200)
        # 验收之后就可以改了
        self.assertEqual(self.call("POST", "/api/admin/accept", {})[0], 201)
        self.assertEqual(self.call("POST", "/api/admin/site", {"roomCount": 2, "roomNames": ["甲教室", "乙教室"]})[0], 200)

    def test_live_board_totals_follow_the_configured_room_count(self):
        self.start()
        self.login()
        self.assertEqual(self.call("POST", "/api/admin/site", {"roomCount": 2, "roomNames": ["甲教室", "乙教室"]})[0], 200)
        live = self.call("GET", "/api/admin/live")[1]["data"]
        self.assertEqual((len(live["rooms"]), live["summary"]["roomsTotal"]), (2, 2))
        self.assertEqual(self.call("POST", "/api/admin/site", {"roomCount": 45})[0], 200)
        self.assertEqual(self.call("GET", "/api/admin/live")[1]["data"]["summary"]["roomsTotal"], 45)

    def test_dispatch_reply_says_which_title_and_date_the_session_really_uses(self):
        self.start()
        self.login()
        first = self.call("POST", "/api/admin/dispatch", {"mode": "now", "title": "场次A", "examDate": "2026-10-26"})[1]["data"]
        self.assertEqual((first["sessionTitle"], first["sessionExamDate"], first["titleKept"]), ("场次A", "2026-10-26", False))
        self.call("POST", "/api/current-reports", {"roomName": "一教室", "expectedCount": 5, "actualCount": 5})
        second = self.call("POST", "/api/admin/dispatch", {"mode": "now", "title": "场次B", "examDate": "2030-01-01"})[1]["data"]
        # 已有未验收数据：沿用当前场次的表头，并明确告诉管理员（而不是静默丢掉他刚填的标题）
        self.assertEqual((second["sessionTitle"], second["sessionExamDate"], second["titleKept"]), ("场次A", "2026-10-26", True))
        self.assertEqual(self.call("GET", "/api/session")[1]["data"]["title"], "场次A")

    def test_old_database_without_session_title_or_date_cannot_be_overridden_by_a_teacher(self):
        # 旧库升级：有未验收的旧草稿，但没有 current_exam_date（也可能没有 current_project_title）设置
        self.start()
        self.open_session("旧场次")
        self.call("POST", "/api/current-reports", {"roomName": "一教室", "expectedCount": 10, "actualCount": 9})
        self.stop()
        db = sqlite3.connect(str(self.data / "qeukao.sqlite3"))
        db.execute("DELETE FROM app_settings WHERE key IN ('current_exam_date', 'current_project_title')")
        db.commit()
        db.close()
        self.start()
        session = self.call("GET", "/api/session")[1]["data"]
        self.assertEqual((session["title"], session["examDate"]), ("旧场次", datetime.now().strftime("%Y-%m-%d")), "启动迁移要从草稿补回场次标题/日期")
        self.cookie = ""
        report = {"roomName": "二教室", "expectedCount": 8, "actualCount": 8}
        status, _ = self.call("POST", "/api/current-reports", {"report": {**report, "title": "老师写的", "examDate": "1999-01-01"}})
        self.assertEqual(status, 200)
        items = {i["roomName"]: i for i in self.call("GET", "/api/current-reports")[1]["data"]["items"]}
        self.assertEqual((items["二教室"]["title"], items["二教室"]["examDate"]), ("旧场次", datetime.now().strftime("%Y-%m-%d")))

    def test_session_without_any_title_still_ignores_what_the_teacher_typed(self):
        # 兜底：即使场次设置真的缺失（极端损坏），也不能回退成老师填的值
        self.start()
        self.open_session("会被抹掉")
        self.stop()
        db = sqlite3.connect(str(self.data / "qeukao.sqlite3"))
        db.execute("DELETE FROM app_settings WHERE key IN ('current_exam_date', 'current_project_title')")
        db.commit()
        db.close()
        self.start()
        self.cookie = ""
        self.assertEqual(self.call("POST", "/api/current-reports", {"roomName": "一教室", "expectedCount": 5, "actualCount": 5, "title": "老师写的", "examDate": "1999-01-01"})[0], 200)
        item = self.call("GET", "/api/current-reports")[1]["data"]["items"][0]
        self.assertNotEqual(item["title"], "老师写的")
        self.assertNotEqual(item["examDate"], "1999-01-01")

    # ---- 数据分析：「一次考试 = 一个标题」，筛选 = 标题模糊匹配 + 日期范围 ----
    def seed_exams(self):
        """造 4 场考试：银行A(10-01)、银行B(10-08)、期末(10-15)、银行A 再考一次(10-22)，每场几间教室。"""
        self.start()
        self.login()
        plan = [("银行招聘笔试A", "2026-10-01", [("一教室", 30, 28), ("二教室", 30, 24), ("三教室", 30, 30)]),
                ("银行招聘笔试B", "2026-10-08", [("一教室", 30, 27), ("二教室", 30, 30)]),
                ("期末考试", "2026-10-15", [("一教室", 40, 40), ("三教室", 40, 36)]),
                ("银行招聘笔试A", "2026-10-22", [("二教室", 30, 15)])]
        for title, day, rooms in plan:
            self.assertEqual(self.call("POST", "/api/admin/dispatch", {"mode": "now", "title": title, "examDate": day})[0], 200)
            for name, expected, actual in rooms:
                self.assertEqual(self.call("POST", "/api/current-reports", {"roomName": name, "expectedCount": expected, "actualCount": actual})[0], 200)
            self.assertEqual(self.call("POST", "/api/admin/accept", {})[0], 201)

    def analytics(self, **query):
        from urllib.parse import urlencode
        status, payload = self.call("GET", "/api/admin/analytics" + ("?" + urlencode(query) if query else ""))
        self.assertEqual(status, 200, payload)
        return payload["data"]

    def test_analytics_requires_login_and_validates_the_filter(self):
        self.start()
        self.assertEqual(self.call("GET", "/api/admin/analytics")[0], 401)
        self.login()
        for bad in ("?from=2026-13-01", "?to=abc", "?from=2026-10-10&to=2026-10-01", "?title=" + urllib.parse.quote("字" * 200)):
            self.assertEqual(self.call("GET", "/api/admin/analytics" + bad)[0], 400, bad)

    def test_analytics_without_a_filter_covers_everything(self):
        self.seed_exams()
        data = self.analytics()
        self.assertEqual(data["totals"], {"exams": 4, "reports": 8, "expected": 260, "actual": 230, "absent": 30, "rate": round(230 / 260, 4)})
        # 每场考试一个点，按日期排序：这就是趋势折线图
        self.assertEqual([(e["title"], e["examDate"], e["expected"], e["actual"]) for e in data["exams"]],
                         [("银行招聘笔试A", "2026-10-01", 90, 82), ("银行招聘笔试B", "2026-10-08", 60, 57),
                          ("期末考试", "2026-10-15", 80, 76), ("银行招聘笔试A", "2026-10-22", 30, 15)])
        self.assertEqual(data["exams"][0]["rate"], round(82 / 90, 4))

    def test_analytics_title_filter_is_a_fuzzy_contains_match(self):
        self.seed_exams()
        data = self.analytics(title="银行")
        self.assertEqual(sorted({e["title"] for e in data["exams"]}), ["银行招聘笔试A", "银行招聘笔试B"])
        self.assertEqual(data["totals"]["exams"], 3)
        self.assertEqual(self.analytics(title="招聘笔试A")["totals"]["exams"], 2)
        self.assertEqual(self.analytics(title="不存在")["totals"], {"exams": 0, "reports": 0, "expected": 0, "actual": 0, "absent": 0, "rate": 0})
        # LIKE 通配符是普通字符，不是通配：搜 % 或 _ 不应匹配所有
        self.assertEqual(self.analytics(title="%")["totals"]["exams"], 0)
        self.assertEqual(self.analytics(title="银_")["totals"]["exams"], 0)

    def test_analytics_date_range_is_inclusive_and_combines_with_the_title(self):
        self.seed_exams()
        self.assertEqual([e["examDate"] for e in self.analytics(**{"from": "2026-10-08", "to": "2026-10-15"})["exams"]], ["2026-10-08", "2026-10-15"])
        self.assertEqual(self.analytics(**{"from": "2026-10-16"})["totals"]["exams"], 1)
        self.assertEqual(self.analytics(to="2026-10-01")["totals"]["exams"], 1)
        both = self.analytics(title="银行", **{"from": "2026-10-05", "to": "2026-10-31"})
        self.assertEqual([(e["title"], e["examDate"]) for e in both["exams"]], [("银行招聘笔试B", "2026-10-08"), ("银行招聘笔试A", "2026-10-22")])

    def test_analytics_per_room_top_absent_and_distribution_follow_the_filter(self):
        self.seed_exams()
        data = self.analytics(title="银行")
        rooms = {r["roomName"]: r for r in data["rooms"]}
        # 一教室：A(30/28)+B(30/27) ；二教室：A(30/24)+B(30/30)+A2(30/15)；三教室：A(30/30)
        self.assertEqual((rooms["一教室"]["expected"], rooms["一教室"]["actual"], rooms["一教室"]["absent"]), (60, 55, 5))
        self.assertEqual((rooms["二教室"]["expected"], rooms["二教室"]["actual"], rooms["二教室"]["absent"]), (90, 69, 21))
        self.assertNotIn("四教室", rooms)
        self.assertEqual([r["roomName"] for r in data["topAbsent"]][:2], ["二教室", "一教室"])
        self.assertEqual(sum(b["count"] for b in data["distribution"]), len(rooms), "分布直方图的教室数 = 房间条形图的教室数")
        self.assertEqual(sum(b["count"] for b in self.analytics()["distribution"]), 3)

    def test_analytics_one_exam_and_one_room_history(self):
        self.seed_exams()
        one = self.analytics(title="期末考试")
        self.assertEqual([r["roomName"] for r in one["rooms"]], ["一教室", "三教室"])
        hist = self.analytics(room="二教室")["roomHistory"]
        self.assertEqual([(h["examDate"], h["title"], h["expected"], h["actual"]) for h in hist],
                         [("2026-10-01", "银行招聘笔试A", 30, 24), ("2026-10-08", "银行招聘笔试B", 30, 30), ("2026-10-22", "银行招聘笔试A", 30, 15)])
        self.assertEqual(self.analytics()["roomHistory"], [], "不选教室时不返回单间历史")

    def test_analytics_empty_database_is_all_zero_not_an_error(self):
        self.start()
        self.login()
        data = self.analytics()
        self.assertEqual((data["totals"]["exams"], data["exams"], data["rooms"], data["topAbsent"]), (0, [], [], []))

    def test_table_summary_and_export_share_the_analytics_filter(self):
        # 合并页：表格、汇总、导出、图表四处必须同一口径（标题模糊 + 日期范围），否则同一页上数字对不上
        self.seed_exams()
        q = "?title=" + urllib.parse.quote("银行") + "&from=2026-10-05&to=2026-10-31"
        listing = self.call("GET", "/api/admin/reports" + q)[1]["data"]
        self.assertEqual(sorted((i["title"], i["examDate"]) for i in listing["items"]), [("银行招聘笔试A", "2026-10-22"), ("银行招聘笔试B", "2026-10-08")])
        self.assertEqual(listing["total"], 2)
        summary = self.call("GET", "/api/admin/reports/summary" + q)[1]["data"]
        analytics = self.analytics(title="银行", **{"from": "2026-10-05", "to": "2026-10-31"})["totals"]
        self.assertEqual((summary["reportCount"], summary["totalExpectedCount"], summary["totalActualCount"]),
                         (analytics["exams"], analytics["expected"], analytics["actual"]))
        status, exported = self.call("GET", "/api/admin/reports/export" + q)
        self.assertEqual(status, 200)
        rows = xlsx_rows(exported)
        self.assertEqual(rows[0], ["标题", "考试日期", "教室", "应到", "实到", "缺考", "出考率"])
        self.assertEqual([r[:5] for r in rows[1:]], [["银行招聘笔试A", "2026-10-22", "二教室", "30", "15"],
                                                      ["银行招聘笔试B", "2026-10-08", "一教室", "30", "27"],
                                                      ["银行招聘笔试B", "2026-10-08", "二教室", "30", "30"]], "日期降序 → 标题 → 教室编号，且只含筛选内的数据")
        self.assertEqual(rows[1][5:], ["15", "0.5"])
        for bad in ("?from=2026-13-01", "?to=abc", "?from=2026-10-10&to=2026-10-01"):
            self.assertEqual(self.call("GET", "/api/admin/reports" + bad)[0], 400, bad)
        self.assertEqual(self.call("GET", "/api/admin/reports?title=%25")[1]["data"]["total"], 0, "% 是普通字符")

    def test_filter_dates_must_be_zero_padded_and_title_may_be_as_long_as_a_dispatch_title(self):
        # 文本比较 2026-01-15 >= 2026-1-1 会得到错误结果，所以不补零的日期必须 400，而不是悄悄筛空
        self.seed_exams()
        for bad in ("from=2026-1-1", "to=2026-10-5", "from=20261001", "from=2026-10-01T00:00"):
            self.assertEqual(self.call("GET", "/api/admin/analytics?" + bad)[0], 400, bad)
            self.assertEqual(self.call("GET", "/api/admin/reports?" + bad)[0], 400, bad)
        # 下发时标题最长 120 字，把它完整粘进筛选框不应被拒
        long_title = "考" * 120
        self.assertEqual(self.analytics(title=long_title)["totals"]["exams"], 0)
        self.assertEqual(self.call("GET", "/api/admin/analytics?title=" + urllib.parse.quote("考" * 121))[0], 400)

    def test_histogram_buckets_use_the_unrounded_rate(self):
        # 49999/100000 = 49.999% 属于 <50%；先 round 到 0.5 再分桶会误入 50–70%
        self.start()
        self.open_session()
        self.assertEqual(self.call("POST", "/api/current-reports", {"roomName": "一教室", "expectedCount": 100000, "actualCount": 49999})[0], 200)
        self.assertEqual(self.call("POST", "/api/admin/accept", {})[0], 201)
        buckets = {b["label"]: b["count"] for b in self.analytics()["distribution"]}
        self.assertEqual((buckets["<50%"], buckets["50–70%"]), (1, 0))

    def test_same_title_and_date_in_several_batches_is_one_exam_with_distinct_rooms(self):
        # 「一次考试就是标题」：同标题同日期的多次下发（上午场/下午场）合成一场；人数累加，教室数与考试次数去重
        self.start()
        self.login()
        for actual in (9, 8):
            self.assertEqual(self.call("POST", "/api/admin/dispatch", {"mode": "now", "title": "加试", "examDate": "2026-10-30"})[0], 200)
            self.assertEqual(self.call("POST", "/api/current-reports", {"roomName": "一教室", "expectedCount": 10, "actualCount": actual})[0], 200)
            self.assertEqual(self.call("POST", "/api/admin/accept", {})[0], 201)
        data = self.analytics(title="加试")
        exam = data["exams"][0]
        self.assertEqual((data["totals"]["exams"], exam["rooms"], exam["batches"], exam["expected"], exam["actual"]), (1, 1, 2, 20, 17))
        self.assertEqual([(r["roomName"], r["exams"], r["expected"], r["actual"]) for r in data["rooms"]], [("一教室", 1, 20, 17)])

    def test_like_wildcards_and_backslash_in_a_real_title_are_found_literally(self):
        # 只断言「搜 % 查不到」杀不死 ESCAPE 被去掉的变异；必须种入真的含 % _ 反斜杠的标题并能搜到
        self.start()
        self.login()
        for title, day in (("100%达标考试", "2026-11-01"), ("A_B 模拟", "2026-11-02"), ("路径C:\\\\卷", "2026-11-03"), ("AxB 对照", "2026-11-04")):
            self.assertEqual(self.call("POST", "/api/admin/dispatch", {"mode": "now", "title": title, "examDate": day})[0], 200)
            self.assertEqual(self.call("POST", "/api/current-reports", {"roomName": "一教室", "expectedCount": 5, "actualCount": 5})[0], 200)
            self.assertEqual(self.call("POST", "/api/admin/accept", {})[0], 201)
        self.assertEqual([e["title"] for e in self.analytics(title="100%")["exams"]], ["100%达标考试"])
        self.assertEqual([e["title"] for e in self.analytics(title="A_B")["exams"]], ["A_B 模拟"], "_ 不能匹配任意一个字符（AxB）")
        self.assertEqual([e["title"] for e in self.analytics(title="C:\\\\")["exams"]], ["路径C:\\\\卷"])
        self.assertEqual(self.analytics(title="%")["totals"]["exams"], 1, "% 只匹配真正含 % 的标题")

    def test_rooms_with_zero_expected_are_left_out_of_the_distribution_but_not_the_room_list(self):
        self.start()
        self.open_session()
        self.assertEqual(self.call("POST", "/api/current-reports", {"roomName": "一教室", "expectedCount": 0, "actualCount": 0})[0], 200)
        self.assertEqual(self.call("POST", "/api/current-reports", {"roomName": "二教室", "expectedCount": 10, "actualCount": 10})[0], 200)
        self.assertEqual(self.call("POST", "/api/admin/accept", {})[0], 201)
        data = self.analytics()
        self.assertEqual([r["roomName"] for r in data["rooms"]], ["一教室", "二教室"])
        self.assertEqual(sum(b["count"] for b in data["distribution"]), 1, "应到 0 的教室没有出考率，不进直方图的 <50% 档")
        self.assertEqual(data["distribution"][0]["count"], 0)

    def test_live_board_reports_the_exam_date_of_the_running_session(self):
        self.start()
        self.login()
        self.call("POST", "/api/admin/dispatch", {"mode": "now", "title": "进行中", "examDate": "2026-12-30"})
        session = self.call("GET", "/api/admin/live")[1]["data"]["session"]
        self.assertEqual((session["title"], session["examDate"]), ("进行中", "2026-12-30"))

    def test_default_password_only_allows_changing_it(self):
        # 开源后人人都知道默认密码：用它登录后，除了“看登录状态”和“改密码”，后台接口一律 403
        self.start(admin_password=None)
        status, payload = self.call("POST", "/api/admin/login", {"password": "112233"})
        self.assertEqual((status, payload["data"]["mustChangePassword"]), (200, True))
        self.assertEqual(self.call("GET", "/api/admin/me")[1]["data"]["mustChangePassword"], True)
        for method, path, body in (("GET", "/api/admin/settings", None), ("POST", "/api/admin/dispatch", {"mode": "now", "title": "x"}),
                                   ("GET", "/api/admin/reports", None), ("POST", "/api/admin/accept", {})):
            self.assertEqual(self.call(method, path, body)[0], 403, path)
        # 新密码还是公开的默认密码 = 没改：必须拒绝，后台仍然锁着
        self.assertEqual(self.call("POST", "/api/admin/password", {"oldPassword": "112233", "newPassword": "112233"})[0], 400)
        self.assertEqual(self.call("GET", "/api/admin/settings")[0], 403)
        self.assertEqual(self.call("POST", "/api/admin/password", {"oldPassword": "112233", "newPassword": "s3cret!"})[0], 200)
        self.assertEqual(self.call("GET", "/api/admin/settings")[0], 200)
        self.assertEqual(self.call("GET", "/api/admin/me")[1]["data"]["mustChangePassword"], False)
        self.assertEqual(self.call("POST", "/api/admin/login", {"password": "112233"})[0], 401)

    def test_admin_settings_expose_the_raw_site_config_and_the_resolved_names(self):
        self.start()
        self.login()
        data = self.call("GET", "/api/admin/settings")[1]["data"]
        self.assertEqual((data["site"]["orgName"], data["site"]["roomCount"], data["site"]["roomNames"]), ("", 30, []))
        self.assertEqual(len(data["roomNames"]), 30)
        self.assertFalse(data["hasUnacceptedData"])
        self.call("POST", "/api/admin/dispatch", {"mode": "now", "title": "t"})
        self.call("POST", "/api/current-reports", {"roomName": "一教室", "expectedCount": 5, "actualCount": 5})
        self.assertTrue(self.call("GET", "/api/admin/settings")[1]["data"]["hasUnacceptedData"], "有未验收数据时前端要提前把教室名单置灰")

    def test_default_room_names_are_generated_for_any_count(self):
        self.start()
        self.login()
        self.assertEqual(self.call("POST", "/api/admin/site", {"roomCount": 45})[0], 200)
        names = self.call("GET", "/api/site")[1]["data"]["roomNames"]
        self.assertEqual((len(names), names[0], names[10], names[29], names[30], names[44]), (45, "一教室", "十一教室", "三十教室", "三十一教室", "四十五教室"))

    def test_agent_auth_poll_ack_and_room_submission(self):
        self.start()
        hello = {"clientId": "test-client-001", "hostname": "考场电脑", "version": "1.0", "localIps": ["10.10.7.23"]}
        self.assertEqual(self.call("POST", "/api/agent/hello", hello)[0], 401)
        self.assertEqual(self.call("POST", "/api/agent/hello", hello, {"X-Qk-Key": "wrong"})[0], 401)
        key = json.loads((self.data / "config.json").read_text())["enrollKey"]
        headers = {"X-Qk-Key": key, "X-Forwarded-For": "10.10.7.23"}
        status, result = self.call("POST", "/api/agent/hello", hello, headers)
        self.assertEqual(status, 200)
        self.assertFalse(result["data"]["room"]["matched"])
        poll = "/api/agent/poll?clientId=test-client-001&wait=1"
        before = time.monotonic()
        self.assertIsNone(self.call("GET", poll, headers=headers)[1]["data"]["notice"])
        self.assertGreaterEqual(time.monotonic() - before, 0.9)
        self.login()
        dispatch = self.call("POST", "/api/admin/dispatch", {"title": "测试标题", "mode": "now"})[1]["data"]
        before = time.monotonic()
        self.assertEqual(self.call("GET", poll, headers=headers)[1]["data"]["notice"]["dispatchId"], dispatch["id"])
        self.assertLess(time.monotonic() - before, 0.9)
        self.assertEqual(self.call("POST", "/api/agent/ack", {"clientId": hello["clientId"], "dispatchId": dispatch["id"], "state": "confirmed"}, headers)[0], 200)
        self.assertIsNone(self.call("GET", poll.replace("wait=1", "wait=0"), headers=headers)[1]["data"]["notice"])
        self.assertEqual(self.call("POST", "/api/admin/settings/room-rule", {"octet": 4, "prefix": "127.0.0."})[0], 200)
        self.assertEqual(self.call("POST", "/api/current-reports", {"roomName": "一教室", "expectedCount": 10, "actualCount": 9})[0], 200)
        self.call("POST", "/api/admin/dispatch", {"mode": "now", "title": "不能覆盖项目名"})
        self.assertIsNone(self.call("GET", poll.replace("wait=1", "wait=0"), headers=headers)[1]["data"]["notice"])
        live = self.call("GET", "/api/admin/live")[1]["data"]
        self.assertEqual(len(live["rooms"]), 30)
        self.assertEqual(live["summary"]["roomsSubmitted"], 1)
        self.assertEqual(live["clients"][0]["roomNumber"], 1)
        self.assertEqual(self.call("POST", "/api/admin/clients/test-client-001/block", {"blocked": True})[0], 200)
        self.assertEqual(self.call("GET", poll, headers=headers)[0], 403)
        self.assertEqual(self.call("POST", "/api/agent/hello", hello, headers)[0], 403)

    def test_schedule_rejects_past_fires_due_and_marks_stale_missed(self):
        self.start()
        self.login()
        self.assertEqual(self.call("POST", "/api/admin/dispatch", {"title": "测试标题", "mode": "scheduled", "scheduledAt": "2000-01-01T00:00"})[0], 400)
        self.assertEqual(self.call("POST", "/api/admin/dispatch", {"title": "测试标题", "mode": "scheduled", "scheduledAt": "2099-01-01T00:00:00+08:00"})[0], 400)
        server_time = self.call("GET", "/api/session")[1]["data"]["serverTime"]
        due = (datetime.fromisoformat(server_time) + timedelta(seconds=2)).replace(tzinfo=None).isoformat(timespec="seconds")
        status, payload = self.call("POST", "/api/admin/dispatch", {"title": "测试标题", "mode": "scheduled", "scheduledAt": due})
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["status"], "pending")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.call("GET", "/api/session")[1]["data"]["open"]:
                break
            time.sleep(0.1)
        self.assertTrue(self.call("GET", "/api/session")[1]["data"]["open"])
        self.assertEqual(self.call("GET", "/api/admin/dispatches")[1]["data"]["items"][0]["status"], "fired")
        self.stop()
        self.process = None
        with sqlite3.connect(str(self.data / "qeukao.sqlite3")) as conn:
            conn.execute("UPDATE app_settings SET value='closed' WHERE key='session_state'")
            conn.execute("INSERT INTO dispatches(title,message,mode,scheduled_at,status,created_at) VALUES ('old','old','scheduled','2000-01-01T00:00:00','pending','2000-01-01T00:00:00')")
        self.start()
        self.assertFalse(self.call("GET", "/api/session")[1]["data"]["open"])
        self.assertEqual(self.call("GET", "/api/admin/dispatches")[1]["data"]["items"][0]["status"], "missed")

    def test_old_database_with_draft_migrates_open(self):
        with sqlite3.connect(str(self.data / "qeukao.sqlite3")) as conn:
            conn.execute("""CREATE TABLE current_report_drafts (room_number INTEGER PRIMARY KEY,
                room_name TEXT NOT NULL, title TEXT NOT NULL, exam_date TEXT NOT NULL,
                expected_count INTEGER NOT NULL, actual_count INTEGER NOT NULL, absent_count INTEGER NOT NULL,
                attendance_rate REAL NOT NULL, client_ip TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            conn.execute("INSERT INTO current_report_drafts VALUES (7,'七教室','旧考试','2026-10-25',10,9,1,0.9,'10.10.7.23','2026-10-25T10:00:00+08:00','2026-10-25T10:00:00+08:00')")
        self.start()
        self.assertTrue(self.call("GET", "/api/session")[1]["data"]["open"])
        self.assertEqual(len(self.call("GET", "/api/current-reports")[1]["data"]["items"]), 1)

    def test_admin_routes_reject_unauthenticated_and_invalid_json_shape(self):
        self.start()
        routes = [("GET", "/api/admin/me"), ("GET", "/api/admin/reports"),
                  ("GET", "/api/admin/reports/summary"), ("GET", "/api/admin/reports/export"),
                  ("POST", "/api/admin/import/excel-preview"), ("POST", "/api/admin/import/excel"),
                  ("GET", "/api/admin/logs"), ("GET", "/api/admin/logs/summary"),
                  ("GET", "/api/admin/reports/1"), ("PUT", "/api/admin/reports/1"),
                  ("DELETE", "/api/admin/reports/1"), ("POST", "/api/admin/dispatch"),
                  ("GET", "/api/admin/dispatches"), ("POST", "/api/admin/dispatches/1/cancel"),
                  ("GET", "/api/admin/live"), ("POST", "/api/admin/clients/example-id/block"),
                  ("DELETE", "/api/admin/clients/example-id"), ("GET", "/api/admin/settings"),
                  ("POST", "/api/admin/settings/room-rule"), ("POST", "/api/admin/settings/room-rule/preview"),
                  ("GET", "/api/admin/settings/room-rule/suggest"), ("POST", "/api/admin/password"),
                  ("GET", "/api/admin/client/download")]
        for method, path in routes:
            with self.subTest(path=path):
                self.assertEqual(self.call(method, path)[0], 401)
        self.login()
        self.assertEqual(self.call("POST", "/api/admin/dispatch", ["not", "object"])[0], 400)

    def test_forwarded_ip_only_trusts_loopback(self):
        code = """import app
h = {"X-Forwarded-For": "10.10.9.5"}
assert app.resolve_client_ip(h, "10.10.7.23") == "10.10.7.23"
for peer in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
    assert app.resolve_client_ip(h, peer) == "10.10.9.5"
"""
        result = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=dict(os.environ, QEUKAO_DATA_DIR=str(self.data)), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_settings_preview_cancel_download_and_history_compatibility(self):
        self.start()
        self.login()
        status, error = self.call("GET", "/api/admin/client/download")
        self.assertEqual(status, 404)
        self.assertEqual(error["error"]["code"], "CLIENT_TEMPLATE_MISSING")
        (self.data / "client-template.exe").write_bytes(b"MZ-test-template")
        status, binary = self.call("GET", "/api/admin/client/download")
        self.assertEqual(status, 200)
        self.assertTrue(binary.startswith(b"MZ-test-template"))
        self.assertTrue(binary.endswith(b"QKCFG-V1\n"))
        size = struct.unpack("<I", binary[-13:-9])[0]
        config = json.loads(binary[-13-size:-13])
        self.assertEqual(config["v"], 1)
        self.assertTrue(config["servers"], "至少要有一个服务端地址")
        self.assertFalse([s for s in config["servers"] if "127.0.0.1" in s or "localhost" in s], config["servers"])  # 回环地址对教室机无用
        self.assertEqual(config["enrollKey"], json.loads((self.data / "config.json").read_text())["enrollKey"])
        before = self.call("GET", "/api/admin/settings")[1]["data"]["roomRule"]
        preview = self.call("POST", "/api/admin/settings/room-rule/preview", {"octet": 4, "prefix": "192.168.5.", "ip": "192.168.5.7"})
        self.assertEqual(preview[1]["data"], {"matched": True, "roomName": "七教室"})
        self.assertEqual(self.call("GET", "/api/admin/settings")[1]["data"]["roomRule"], before)
        future = "2099-01-01T00:00"
        pending = self.call("POST", "/api/admin/dispatch", {"title": "测试标题", "mode": "scheduled", "scheduledAt": future})[1]["data"]
        self.assertEqual(self.call("POST", "/api/admin/dispatches/%s/cancel" % pending["id"], {})[0], 200)
        self.assertEqual(self.call("POST", "/api/admin/dispatches/%s/cancel" % pending["id"], {})[0], 409)
        self.call("POST", "/api/admin/dispatch", {"mode": "now", "title": "原场次"})
        self.call("POST", "/api/current-reports", {"roomName": "二教室", "expectedCount": 10, "actualCount": 8})
        self.call("POST", "/api/admin/dispatch", {"mode": "now", "title": "不可覆盖"})
        self.assertEqual(self.call("GET", "/api/session")[1]["data"]["title"], "原场次")
        self.call("POST", "/api/admin/accept", {})
        group = self.call("GET", "/api/admin/reports")[1]["data"]["items"][0]
        path = "/api/admin/reports/%s" % group["id"]
        item = self.call("GET", path)[1]["data"]["items"][0]
        status, _ = self.call("PUT", path, {"password": "112233", "title": "历史修改", "examDate": "2026-10-25", "items": [{"id": item["id"], "expectedCount": 10, "actualCount": 9}]})
        self.assertEqual(status, 200)
        self.assertEqual(self.call("GET", "/api/admin/reports/summary")[1]["data"]["totalAbsentCount"], 1)
        self.assertEqual([r[0] for r in xlsx_rows(self.call("GET", "/api/admin/reports/export")[1])[1:]], ["历史修改"])
        logs = self.call("GET", "/api/admin/logs?pageSize=100")[1]["data"]["items"]
        events = {item["eventType"] for item in logs}
        self.assertTrue({"session_opened", "session_closed", "dispatch_created", "dispatch_fired", "dispatch_cancelled"}.issubset(events))

    TABLE_XLSX = [("2026-10-25", [["2026-10-25 导入考试"], ["教室", "应到", "实到"], ["七教室", 20, 18]])]

    def test_excel_upload_preview_and_import_remain_available_when_closed(self):
        self.start()
        self.login()
        data = xlsx_bytes(self.TABLE_XLSX)
        self.assertEqual(self.call("GET", "/api/admin/import/excel-preview")[0], 404, "旧的服务器桌面预览路由已删除")
        status, preview = self.upload("/api/admin/import/excel-preview", data)
        self.assertEqual(status, 200)
        self.assertEqual((preview["data"]["validRowCount"], preview["data"]["fileName"]), (1, "出考率.xlsx"))
        self.assertNotIn("filePath", preview["data"], "不再返回服务器路径")
        self.assertEqual(self.call("GET", "/api/admin/reports/summary")[1]["data"]["reportCount"], 0, "预览不写库")
        status, result = self.upload("/api/admin/import/excel", data)
        self.assertEqual(status, 200)
        self.assertEqual(result["data"]["importedRows"], 1)
        self.assertTrue(Path(result["data"]["backupPath"]).is_relative_to(self.data))
        self.assertFalse(self.call("GET", "/api/session")[1]["data"]["open"])
        self.assertEqual(self.call("GET", "/api/admin/reports/summary")[1]["data"]["totalAbsentCount"], 2)
        # 同一个文件再导入：整张表跳过，记录数不变
        status, again = self.upload("/api/admin/import/excel", data)
        self.assertEqual((status, again["data"]["importedRows"], len(again["data"]["skippedTables"])), (200, 0, 1))
        self.assertEqual(self.call("GET", "/api/admin/reports/summary")[1]["data"]["totalAbsentCount"], 2)

    def test_excel_upload_rejects_non_xlsx_and_oversize(self):
        self.start()
        self.login()
        good = xlsx_bytes(self.TABLE_XLSX)
        for path in ("/api/admin/import/excel-preview", "/api/admin/import/excel"):
            for data, name in ((b"not a zip at all", "a.xlsx"), (good, "a.csv"), (b"", "a.xlsx"), (b"x" * (20 * 1024 * 1024 + 1), "a.xlsx")):
                status, payload = self.upload(path, data, name)
                self.assertEqual(status, 400, (path, name, len(data)))
                self.assertFalse(payload["success"])
        self.assertEqual(self.call("GET", "/api/admin/reports/summary")[1]["data"]["reportCount"], 0)

    def test_excel_flat_rows_group_by_title_and_date_and_discard_bad_rows(self):
        head = ["标题", "考试日期", "教室", "应到", "实到", "缺考", "出考率"]
        serial = (datetime(2026, 10, 1) - datetime(1899, 12, 30)).days  # Excel 日期序列号
        rows = [head,
                ["期中", "2026-10-25", "一教室", 30, 28, 2, 0.9333],
                ["期中", serial, "二教室", 30, 30, 0, 1],
                ["期中", "2026-10-25", "二教室", 30, 25, 5, 0.83],
                ["期中", "不是日期", "三教室", 30, 30, 0, 1],
                ["期中", "2026-10-25", "三教室", 30, 31, 0, 1],
                ["", "2026-10-25", "三教室", 30, 30, 0, 1],
                ["期中", "2026-10-25", "三教室", 12.5, 10, 0, 1]]
        self.start()
        self.login()
        result = self.upload("/api/admin/import/excel-preview", xlsx_bytes([("出考率数据", rows)]))[1]["data"]
        tables = {(t["title"], t["examDate"]): [i["roomName"] for i in t["items"]] for t in result["tables"]}
        self.assertEqual(tables, {("期中", "2026-10-25"): ["一教室", "二教室"], ("期中", "2026-10-01"): ["二教室"]})
        self.assertEqual(sorted(d["reason"] for d in result["discardedItems"]),
                         sorted(["考试日期无法识别，放弃导入", "实到人数大于应到人数，放弃导入", "缺少标题，放弃导入", "缺少应到或实到人数，放弃导入"]))

    def test_exported_xlsx_imports_into_a_fresh_server_unchanged(self):
        def exams():
            data = self.call("GET", "/api/admin/reports?pageSize=100")[1]["data"]["items"]
            return {(g["title"], g["examDate"], i["roomName"], i["expectedCount"], i["actualCount"])
                    for g in data for i in self.call("GET", "/api/admin/reports/%s" % g["id"])[1]["data"]["items"]}
        self.seed_exams()
        before = exams()
        status, exported = self.call("GET", "/api/admin/reports/export")
        self.assertEqual((status, len(before)), (200, 8))
        self.stop()
        self.data = Path(subprocess.check_output(["mktemp", "-d"], text=True).strip())  # 另一个全新数据目录
        self.addCleanup(shutil.rmtree, self.data)
        (self.data / "config.json").write_text(json.dumps({"backup": {"enabled": False, "dir": str(self.data / "backups")}}), encoding="utf-8")
        self.cookie = ""
        self.start()
        self.login()
        self.assertEqual(exams(), set())
        status, result = self.upload("/api/admin/import/excel", exported, "出考率数据-2026-10-29.xlsx")
        self.assertEqual((status, result["data"]["importedRows"], result["data"]["discardedRows"]), (200, 8, 0), result)
        self.assertEqual(exams(), before)

    def test_export_headers_are_an_xlsx_download_with_chinese_filename(self):
        self.start()
        self.login()
        urlopen = urllib.request.Request(self.url + "/api/admin/reports/export", headers={"Cookie": self.cookie})
        with urllib.request.urlopen(urlopen) as response:
            body = response.read()
            disposition = response.headers["Content-Disposition"]
            self.assertEqual(response.headers["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn("filename*=UTF-8''" + urllib.parse.quote("出考率数据-"), disposition)
        self.assertIn('filename="qeukao-reports-', disposition)
        self.assertEqual(xlsx_rows(body), [["标题", "考试日期", "教室", "应到", "实到", "缺考", "出考率"]])

    def test_submission_rechecks_session_after_waiting_for_writer(self):
        self.start()
        self.login()
        self.call("POST", "/api/admin/dispatch", {"title": "测试标题", "mode": "now"})
        with sqlite3.connect(str(self.data / "qeukao.sqlite3")) as conn:
            conn.execute("BEGIN IMMEDIATE")
            with ThreadPoolExecutor(max_workers=1) as pool:
                request = pool.submit(self.call, "POST", "/api/current-reports", {"roomName": "七教室", "expectedCount": 10, "actualCount": 9})
                time.sleep(0.15)
                conn.execute("UPDATE app_settings SET value='closed' WHERE key='session_state'")
                conn.commit()
                status, result = request.result(timeout=5)
        self.assertEqual(status, 409)
        self.assertEqual(result["error"]["code"], "NO_OPEN_SESSION")
        self.assertEqual(self.call("GET", "/api/current-reports")[1]["data"]["items"], [])

    # ---- review df1b12a: red -> green ----
    def _agent(self, cid="review-client-001"):
        self.start()
        self.login()
        key = json.loads((self.data / "config.json").read_text())["enrollKey"]
        headers = {"X-Qk-Key": key}
        hello = {"clientId": cid, "hostname": "考场电脑", "version": "1.0", "localIps": []}
        self.assertEqual(self.call("POST", "/api/agent/hello", hello, headers)[0], 200)
        self.poll_path = "/api/agent/poll?clientId=%s&wait=0" % cid
        return cid, headers

    def _notice(self, headers):
        return self.call("GET", self.poll_path, headers=headers)[1]["data"]["notice"]

    def test_scheduled_notice_still_pops_up_after_a_later_immediate_one_was_handled(self):
        cid, headers = self._agent()
        server_time = self.call("GET", "/api/session")[1]["data"]["serverTime"]
        due = (datetime.fromisoformat(server_time) + timedelta(seconds=2)).replace(tzinfo=None).isoformat(timespec="seconds")
        early = self.call("POST", "/api/admin/dispatch", {"title": "测试标题", "mode": "scheduled", "scheduledAt": due, "message": "定时"})[1]["data"]
        later = self.call("POST", "/api/admin/dispatch", {"title": "测试标题", "mode": "now", "message": "立即"})[1]["data"]
        self.assertLess(early["id"], later["id"])
        self.assertEqual(self._notice(headers)["dispatchId"], later["id"])
        self.call("POST", "/api/agent/ack", {"clientId": cid, "dispatchId": later["id"], "state": "opened"}, headers)
        self.assertIsNone(self._notice(headers))
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            items = self.call("GET", "/api/admin/dispatches")[1]["data"]["items"]
            if next(i for i in items if i["id"] == early["id"])["status"] == "fired":
                break
            time.sleep(0.2)
        self.assertEqual(self._notice(headers)["dispatchId"], early["id"], "定时通知触发后教室必须收到弹窗")
        self.assertEqual(self.call("GET", "/api/admin/live")[1]["data"]["session"]["dispatchId"], early["id"])

    def test_ack_never_goes_backwards(self):
        cid, headers = self._agent()
        notice = self.call("POST", "/api/admin/dispatch", {"title": "测试标题", "mode": "now"})[1]["data"]
        for state in ("shown", "confirmed", "opened", "shown", "confirmed"):
            self.call("POST", "/api/agent/ack", {"clientId": cid, "dispatchId": notice["id"], "state": state}, headers)
        self.assertIsNone(self._notice(headers), "迟到的 shown/confirmed 不能把 opened 覆盖掉")
        live_state = self.call("GET", "/api/admin/live")[1]["data"]["clients"][0]["notice"]["state"]
        self.assertEqual(live_state, "opened", "库里存的回执状态必须仍是 opened")
        self.call("POST", "/api/agent/ack", {"clientId": cid, "dispatchId": notice["id"], "state": "failed", "detail": "x"}, headers)
        self.assertEqual(self._notice(headers)["dispatchId"], notice["id"], "failed 之后允许重新弹窗")

    def test_blank_message_falls_back_to_the_default(self):
        self.start()
        self.login()
        created = self.call("POST", "/api/admin/dispatch", {"title": "测试标题", "mode": "now", "message": "   "})[1]["data"]
        self.assertEqual(created["message"], "请点击确定填写缺考信息")

    def test_accept_with_nothing_pending_closes_an_open_session_only(self):
        self.start()
        self.login()
        self.assertEqual(self.call("POST", "/api/admin/accept", {})[0], 400)  # 已关闭：照旧报错
        self.call("POST", "/api/admin/dispatch", {"title": "测试标题", "mode": "now"})
        self.assertTrue(self.call("GET", "/api/session")[1]["data"]["open"])
        saved_cookie, self.cookie = self.cookie, ""
        self.assertEqual(self.call("POST", "/api/admin/accept", {})[0], 401)
        self.cookie = saved_cookie
        self.assertTrue(self.call("GET", "/api/session")[1]["data"]["open"])
        self.assertEqual(self.call("POST", "/api/admin/accept", {})[0], 201)
        self.assertFalse(self.call("GET", "/api/session")[1]["data"]["open"])
        events = {i["eventType"] for i in self.call("GET", "/api/admin/logs?pageSize=100")[1]["data"]["items"]}
        self.assertIn("session_closed", events)

    def test_client_id_is_restricted_to_manageable_characters(self):
        self.start()
        key = json.loads((self.data / "config.json").read_text())["enrollKey"]
        for bad in ("has/slash-1", "空格 id 12345", "a b c d e f g"):
            hello = {"clientId": bad, "hostname": "h", "version": "1", "localIps": []}
            self.assertEqual(self.call("POST", "/api/agent/hello", hello, {"X-Qk-Key": key})[0], 400, bad)

    def test_download_ignores_a_malformed_host_header(self):
        self.start()
        self.login()
        (self.data / "client-template.exe").write_bytes(b"MZ-test-template")
        status, binary = self.call("GET", "/api/admin/client/download", headers={"Host": 'evil.com:80/x","k":"z'})
        self.assertEqual(status, 200)
        size = struct.unpack("<I", binary[-13:-9])[0]
        servers = json.loads(binary[-13 - size:-13])["servers"]
        self.assertFalse([s for s in servers if "evil" in s], servers)

    def test_listen_backlog_survives_a_boot_storm(self):
        code = "import app\nassert app._Server.request_queue_size >= 64, app._Server.request_queue_size"  # 只看类属性，不真的 bind 端口
        result = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=dict(os.environ, QEUKAO_DATA_DIR=str(self.data)), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_one_corrupt_scheduled_row_does_not_stop_the_scheduler(self):
        self.start()
        self.login()
        now = datetime.now().astimezone().replace(microsecond=0)
        due = (now - timedelta(seconds=2)).isoformat(timespec="seconds")
        with sqlite3.connect(str(self.data / "qeukao.sqlite3")) as conn:
            conn.execute("INSERT INTO dispatches(title,message,mode,scheduled_at,status,created_at) VALUES ('','bad','scheduled','garbage','pending','x')")
            conn.execute("INSERT INTO dispatches(title,message,mode,scheduled_at,status,created_at) VALUES ('','good','scheduled',?,'pending','x')", (due,))
        deadline = time.monotonic() + 6
        status = {}
        while time.monotonic() < deadline:
            items = self.call("GET", "/api/admin/dispatches")[1]["data"]["items"]
            status = {i["message"]: i["status"] for i in items}
            if status.get("good") == "fired":
                break
            time.sleep(0.2)
        self.assertEqual(status.get("good"), "fired", status)
        self.assertNotEqual(status.get("bad"), "fired")

    def test_login_while_the_config_is_locked_says_so(self):
        self.start()
        (self.data / "config.json").write_text("{ broken", encoding="utf-8")
        status, result = self.call("POST", "/api/admin/login", {"password": "112233"})
        self.assertEqual(status, 401)
        self.assertIn("锁定", result["error"]["message"])

    def test_only_exact_loopback_hosts_are_dropped_from_the_bound_servers(self):
        self.start()
        self.login()
        (self.data / "client-template.exe").write_bytes(b"MZ-test-template")
        for host, expected in (("127.0.0.1.nip.io:8000", True), ("localhost:8000", False), ("127.0.0.1:8000", False), ("lan-pc.school:8000", True)):
            status, binary = self.call("GET", "/api/admin/client/download", headers={"Host": host})
            self.assertEqual(status, 200)
            size = struct.unpack("<I", binary[-13:-9])[0]
            servers = json.loads(binary[-13 - size:-13])["servers"]
            self.assertEqual(("http://" + host) in servers, expected, (host, servers))


    def test_display_lines_matches_the_client_vectors(self):
        # 与 client/fit_test.go 的 displayLineVectors 同一张表：服务端、客户端、管理端必须给出同一个行数
        # 在子进程里跑并指向临时数据目录：直接在测试进程里 import qk_agents 会按默认路径在仓库里创建 data/config.json
        code = (
            "import json, qk_agents\n"
            "vectors = [('', 1), ('请点击确定填写缺考信息', 1), ('字' * 30, 1), ('字' * 31, 2), ('字' * 200, 7), ('a\\nb\\nc', 3), ('a\\n\\nb', 3),\n"
            "           ('字' * 186 + '\\n字' * 7, 14), ('字' * 30 + '\\n' + '字' * 31, 3),\n"
            "           ('😀' * 15, 1), ('😀' * 16, 2), ('😀' * 21, 2), ('☀' * 16, 2),\n"
            "           ('é' * 30, 1), ('“' * 30, 1), ('Ж' * 16, 2), ('𝐖' * 16, 2), ('→' * 16, 2),\n"
            "           ('\\U00020000' * 16, 2), ('\\U0002FFFF' * 16, 2)]\n"
            "print(json.dumps([[qk_agents.display_lines(t), n] for t, n in vectors]))\n"
        )
        env = dict(os.environ, QEUKAO_DATA_DIR=str(self.data))
        env.pop("QEUKAO_DB", None)
        out = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        for got, want in json.loads(out.stdout.strip().splitlines()[-1]):
            self.assertEqual(got, want)

    def test_admin_js_counts_lines_like_the_server(self):
        # 管理端 static/admin.js 的 messageWeight/messageDisplayLines 与服务端 display_lines 是三份独立实现之一；
        # 之前没有任何自动检查，改了 JS 的 CJK 表也不会红。这里把同一批向量 + 全码点权重喂给 node 里的真实 JS 源码。
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("node 不可用")
        src = (ROOT / "static" / "admin.js").read_text(encoding="utf-8")
        start = src.index("const MESSAGE_LINE_CHARS")
        end = src.index("function updateDispatchForm")
        js = src[start:end] + (
            "\nconst vectors = [['', 1], ['请点击确定填写缺考信息', 1], ['字'.repeat(30), 1], ['字'.repeat(31), 2], ['字'.repeat(200), 7], ['a\\nb\\nc', 3], ['a\\n\\nb', 3],"
            "\n['字'.repeat(186) + '\\n字'.repeat(7), 14], ['字'.repeat(30) + '\\n' + '字'.repeat(31), 3], ['😀'.repeat(15), 1], ['😀'.repeat(16), 2], ['😀'.repeat(21), 2], ['☀'.repeat(16), 2],"
            "\n['é'.repeat(30), 1], ['“'.repeat(30), 1], ['Ж'.repeat(16), 2], ['𝐖'.repeat(16), 2], ['→'.repeat(16), 2], ['\\u{20000}'.repeat(16), 2], ['\\u{2FFFF}'.repeat(16), 2]];"
            "\nconst lines = vectors.map(([t, n]) => [messageDisplayLines(t), n]);"
            "\nlet w = ''; for (let c = 0; c <= 0x30000; c++) { if (c >= 0xD800 && c <= 0xDFFF) continue; w += messageWeight(String.fromCodePoint(c)); }"
            "\nprocess.stdout.write(JSON.stringify({lines, w}));")
        out = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        got = json.loads(out.stdout)
        for have, want in got["lines"]:
            self.assertEqual(have, want)
        py_code = ("import qk_agents\nprint(''.join(str(qk_agents._weight(chr(c))) for c in range(0x30001) if not 0xD800 <= c <= 0xDFFF))")
        env = dict(os.environ, QEUKAO_DATA_DIR=str(self.data))
        env.pop("QEUKAO_DB", None)
        py = subprocess.run([sys.executable, "-c", py_code], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(py.returncode, 0, py.stderr[-500:])
        self.assertEqual(got["w"], py.stdout.strip(), "管理端与服务端对某些码点的权重不一致")

    def test_dispatch_message_limit_is_by_display_lines_not_by_hard_lines_or_chars_alone(self):
        self.start()
        self.login()
        post = lambda m: self.call("POST", "/api/admin/dispatch", {"title": "测试标题", "mode": "now", "message": m})
        self.assertEqual(post("字" * 200)[0], 200)                          # 200 字一行：7 个显示行
        self.assertEqual(post("\n".join(["行"] * 9))[0], 200)               # 9 个短行：9 个显示行（上限）
        self.assertEqual(post("\n".join(["行"] * 10))[0], 400)              # 10 个短行
        combo = post("字" * 186 + "\n字" * 7)                               # 恰好 200 字、8 个硬行：14 个显示行——审查抓到的漏网组合
        self.assertEqual(combo[0], 400)
        self.assertIn("换行太多", combo[1]["error"]["message"])
        # emoji 约 2em 宽：每行 21 个 ×9 行按字数只有 9 个显示行，实际每行折成两行 = 18 行裁尾（审查者在 wine 里实测）
        self.assertEqual(post("\n".join(["😀" * 21] * 9))[0], 400)
        self.assertEqual(post("\n".join(["\U00020000" * 21] * 9))[0], 400)   # 补充平面汉字：审查者实测 9 行×21 个在 720 宽放不下
        self.assertEqual(post("\n".join(["\U0002FFFF" * 21] * 9))[0], 400)
        self.assertEqual(post("\n".join(["😀" * 15] * 9))[0], 200)

    def test_unpaired_surrogate_is_a_400_not_a_500(self):
        # JSON 里可以单独写 \ud83d；它无法编码成 UTF-8，写库时会炸成 500。应当在入口就按格式错误拒绝
        self.start()
        self.login()
        status, result = self.call("POST", "/api/admin/dispatch", {"title": "测试标题", "mode": "now", "message": "甲\ud83d乙"})
        self.assertEqual(status, 400, result)

    def test_exotic_line_separators_are_normalized_to_newlines(self):
        self.start()
        self.login()
        for sep in ("\r", "\r\n", "\x0b", "\x0c", "\x85", "\u2028", "\u2029"):
            status, result = self.call("POST", "/api/admin/dispatch", {"title": "测试标题", "mode": "now", "message": "甲" + sep + "乙"})
            self.assertEqual(status, 200, repr(sep))
            self.assertEqual(result["data"]["message"], "甲\n乙", repr(sep))
            self.assertEqual(self.call("POST", "/api/admin/dispatch", {"title": "测试标题", "mode": "now", "message": "字" + (sep + "字") * 9})[0], 400, repr(sep))
            # 审查抓到的另一个口径漏洞：CR 分隔的 7 个短行 + 186 字（同为 200 字符）
            self.assertEqual(self.call("POST", "/api/admin/dispatch", {"title": "测试标题", "mode": "now", "message": ("字" + sep) * 7 + "字" * 186})[0], 400, repr(sep))


if __name__ == "__main__":
    unittest.main()