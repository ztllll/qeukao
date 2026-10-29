from __future__ import annotations

import ast
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import qk_config

PROJECT = Path(__file__).resolve().parent.parent


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qk-cfg-")
        self._saved = {k: os.environ.get(k) for k in (
            "QEUKAO_DATA_DIR", "QEUKAO_DB", "QEUKAO_ADMIN_PASSWORD", "QEUKAO_SESSION_SECRET")}
        for k in self._saved:
            os.environ.pop(k, None)
        os.environ["QEUKAO_DATA_DIR"] = self.tmp
        qk_config._reload_paths_for_tests()

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        qk_config._reload_paths_for_tests()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def raw(self) -> bytes:
        return qk_config.CONFIG_PATH.read_bytes()


class DefaultsAndPasswordTests(ConfigTestCase):
    def test_paths_follow_env_and_defaults_are_created_once(self):
        self.assertEqual(qk_config.DATA_DIR, Path(self.tmp))
        self.assertEqual(qk_config.DB_PATH, Path(self.tmp) / "qeukao.sqlite3")
        cfg = qk_config.load()
        self.assertEqual((cfg["host"], cfg["port"]), ("0.0.0.0", 8000))
        self.assertEqual(cfg["roomRule"], {"octet": 3, "prefix": ""})  # 不预设任何单位的网段
        self.assertEqual(cfg["site"]["orgName"], "")                     # 不预设任何单位名称
        self.assertTrue(qk_config.must_change_password())                # 默认密码必须先改
        self.assertEqual(len(cfg["enrollKey"]), 24)
        self.assertNotIn("passwordHash", cfg)
        again = qk_config.load()
        self.assertEqual(cfg["sessionSecret"], again["sessionSecret"])
        self.assertEqual(cfg["enrollKey"], again["enrollKey"])
        cfg["roomRule"]["octet"] = 1  # snapshot must be a deep copy
        self.assertEqual(qk_config.load()["roomRule"]["octet"], 3)

    def test_password_fallback_chain_then_hash_wins(self):
        self.assertTrue(qk_config.check_admin_password("112233"))
        self.assertFalse(qk_config.check_admin_password("x"))
        os.environ["QEUKAO_ADMIN_PASSWORD"] = "envpw1"
        self.assertTrue(qk_config.check_admin_password("envpw1"))
        self.assertFalse(qk_config.check_admin_password("112233"))
        qk_config.set_admin_password("newpass")
        self.assertTrue(qk_config.check_admin_password("newpass"))
        self.assertFalse(qk_config.check_admin_password("envpw1"))
        h = qk_config.load()["passwordHash"]
        self.assertRegex(h, r"^pbkdf2\$200000\$[0-9a-f]+\$[0-9a-f]{64}$")

    def test_set_password_length_bounds(self):
        for bad in ("abc", "x" * 65, ""):
            with self.assertRaises(ValueError):
                qk_config.set_admin_password(bad)
        with self.assertRaises(ValueError):
            qk_config.set_admin_password("112233")  # 公开的默认密码不能被“设置”为新密码（网页和控制面板都走这里）
        qk_config.set_admin_password("abcd")
        qk_config.set_admin_password("x" * 64)
        self.assertTrue(qk_config.check_admin_password("x" * 64))

    def test_session_secret_env_overrides_config(self):
        stored = qk_config.session_secret()
        os.environ["QEUKAO_SESSION_SECRET"] = "from-env"
        self.assertEqual(qk_config.session_secret(), "from-env")
        del os.environ["QEUKAO_SESSION_SECRET"]
        self.assertEqual(qk_config.session_secret(), stored)

    def test_regenerate_enroll_key_persists(self):
        old = qk_config.enroll_key()
        new = qk_config.regenerate_enroll_key()
        self.assertNotEqual(old, new)
        self.assertEqual(qk_config.enroll_key(), new)


class SaveTests(ConfigTestCase):
    def test_backup_hours_migrate_and_preserve_existing_settings(self):
        self.assertEqual(qk_config.load()["backup"]["everyHours"], 72)
        self.assertEqual(qk_config.load()["backup"]["keepCount"], 0)
        qk_config.CONFIG_PATH.write_text(json.dumps({"backup": {
            "everyDays": 7, "dir": "custom", "enabled": False, "retentionDays": 42}}))
        migrated = qk_config.load()["backup"]
        self.assertEqual(migrated, {"everyDays": 7, "everyHours": 168, "keepCount": 0,
                                    "dir": "custom", "enabled": False, "retentionDays": 42})
        migrated["everyHours"] = 5
        qk_config.CONFIG_PATH.write_text(json.dumps({"backup": migrated}))
        self.assertEqual(qk_config.load()["backup"]["everyHours"], 5)
        out = qk_config.save({"backup": {"everyHours": 25}})["backup"]
        self.assertEqual((out["everyHours"], out["everyDays"], out["retentionDays"]), (25, 2, 42))
        self.assertEqual(qk_config.save({"backup": {"everyDays": 4}})["backup"]["everyHours"], 96)
        for hours, count, days in ((1, 0, 0), (8760, 1000, 3650)):
            out = qk_config.save({"backup": {"everyHours": hours, "keepCount": count,
                                            "retentionDays": days}})["backup"]
            self.assertEqual((out["everyHours"], out["keepCount"], out["retentionDays"]), (hours, count, days))

    def test_unknown_keys_ignored_and_nested_deep_merged(self):
        qk_config.load()
        out = qk_config.save({"evil": 1, "port": 9000,
                              "roomRule": {"octet": 4},
                              "backup": {"everyDays": 7}})
        self.assertNotIn("evil", out)
        self.assertNotIn("evil", json.loads(self.raw()))
        self.assertEqual(out["roomRule"], {"octet": 4, "prefix": ""})
        self.assertEqual(out["backup"]["everyDays"], 7)
        self.assertEqual(out["backup"]["retentionDays"], 90)
        self.assertEqual(qk_config.load()["port"], 9000)

    def test_invalid_values_raise_and_leave_file_untouched(self):
        qk_config.load()
        before = self.raw()
        bad_patches = [
            {"port": 0}, {"port": 65536}, {"port": "80"}, {"port": True},
            {"host": ""}, {"host": "  "},
            {"backup": {"everyDays": 0}}, {"backup": {"everyDays": 366}},
            {"backup": {"retentionDays": -1}}, {"backup": {"retentionDays": 3651}},
            *({"backup": {"everyHours": v}} for v in (0, 8761, True, "1")),
            *({"backup": {"keepCount": v}} for v in (-1, 1001, True, "1")),
            {"roomRule": {"octet": 5}}, {"roomRule": {"prefix": "abc"}},
            # a valid key in the same patch must not be applied either
            {"serverName": "changed", "port": 70000},
        ]
        for patch in bad_patches:
            with self.subTest(patch=patch):
                with self.assertRaises(ValueError):
                    qk_config.save(patch)
                self.assertEqual(self.raw(), before)

    def test_corrupt_config_is_renamed_not_overwritten(self):
        qk_config.CONFIG_PATH.write_text("{not json", encoding="utf-8")
        cfg = qk_config.load()
        self.assertEqual(cfg["port"], 8000)
        bad = list(Path(self.tmp).glob("config.json.bad-*"))
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0].read_text(encoding="utf-8"), "{not json")
        json.loads(self.raw())  # rebuilt file is valid


class RoomRuleTests(ConfigTestCase):
    def test_default_rule(self):
        # 默认不限网段：任何网段都按 IP 第 3 段认教室
        for ip in ("10.10.7.23", "192.168.7.5", "172.16.7.200"):
            self.assertEqual(qk_config.room_from_ip(ip), {"roomName": "七教室", "roomNumber": 7}, ip)
        self.assertEqual(qk_config.room_from_ip("10.10.30.1")["roomNumber"], 30)
        for ip in ("10.10.0.5", "10.10.31.5",
                   "10.10.7", "10.10.7.999", "", "::1", "10.10.7.23.1", "a.b.c.d"):
            with self.subTest(ip=ip):
                self.assertIsNone(qk_config.room_from_ip(ip))

    def test_custom_rule_octet4_and_empty_prefix(self):
        qk_config.save({"roomRule": {"octet": 4, "prefix": "192.168.5."}})
        self.assertEqual(qk_config.room_from_ip("192.168.5.12")["roomNumber"], 12)
        self.assertIsNone(qk_config.room_from_ip("192.168.6.12"))
        qk_config.save({"roomRule": {"octet": 1, "prefix": ""}})
        self.assertEqual(qk_config.room_from_ip("9.1.1.1")["roomNumber"], 9)

    def test_validate_room_rule(self):
        self.assertEqual(qk_config.validate_room_rule({"octet": 3, "prefix": " 10.10. "}),
                         {"octet": 3, "prefix": "10.10."})
        self.assertEqual(qk_config.validate_room_rule({"octet": 1, "prefix": ""}),
                         {"octet": 1, "prefix": ""})
        for bad in ({"octet": 0, "prefix": ""}, {"octet": 5, "prefix": ""},
                    {"octet": "3", "prefix": ""}, {"octet": 3, "prefix": "10.10"},
                    {"octet": 3, "prefix": "10.300."}, {"octet": 3, "prefix": "1.2.3.4."},
                    "x"):
            with self.subTest(rule=bad):
                with self.assertRaises(ValueError):
                    qk_config.validate_room_rule(bad)

    def test_suggest_room_rule(self):
        self.assertIsNone(qk_config.suggest_room_rule([]))
        self.assertIsNone(qk_config.suggest_room_rule(["::1", "bad"]))
        ips = ["10.10.%d.%d" % (r, 100 + r) for r in range(1, 11)]
        self.assertEqual(qk_config.suggest_room_rule(ips),
                         {"octet": 3, "prefix": "10.10.", "matched": 10, "total": 10})
        # octet 4 has more distinct in-range values than octet 3
        ips = ["10.10.5.%d" % n for n in range(1, 21)]
        self.assertEqual(qk_config.suggest_room_rule(ips)["octet"], 4)
        self.assertEqual(qk_config.suggest_room_rule(ips)["prefix"], "10.10.5.")
        # tie (192.168.5.7: octet3=5, octet4=7) -> octet 3 wins
        self.assertEqual(qk_config.suggest_room_rule(["192.168.5.7"]),
                         {"octet": 3, "prefix": "192.168.", "matched": 1, "total": 1})
        # IPv6 / garbage ignored; prefix empty when leading segments differ
        r = qk_config.suggest_room_rule(["10.1.3.200", "11.1.4.200", "::1", "x"])
        self.assertEqual((r["octet"], r["prefix"], r["total"]), (3, "", 2))
        # below the 90% threshold everywhere -> None
        self.assertIsNone(qk_config.suggest_room_rule(["40.50.99.99", "41.51.98.98"]))


class ClassroomNamesTests(ConfigTestCase):
    """教室名单现在只有一处来源：site 配置（空名单 = 按数量自动生成「一教室…N教室」）。"""

    def test_default_generator_matches_the_original_thirty_names(self):
        original = ["一教室", "二教室", "三教室", "四教室", "五教室", "六教室", "七教室", "八教室", "九教室", "十教室",
                    "十一教室", "十二教室", "十三教室", "十四教室", "十五教室", "十六教室", "十七教室", "十八教室",
                    "十九教室", "二十教室", "二十一教室", "二十二教室", "二十三教室", "二十四教室", "二十五教室",
                    "二十六教室", "二十七教室", "二十八教室", "二十九教室", "三十教室"]
        self.assertEqual(qk_config.room_names(), original)

    def test_generator_boundaries_for_larger_counts(self):
        for n, want in ((31, "三十一教室"), (40, "四十教室"), (99, "九十九教室"), (100, "一百教室"), (101, "一百零一教室"),
                        (110, "一百一十教室"), (111, "一百一十一教室"), (120, "一百二十教室"), (205, "二百零五教室"), (500, "五百教室")):
            self.assertEqual(qk_config.default_room_name(n), want, n)

    def test_room_count_drives_ip_matching_and_names_are_validated(self):
        qk_config.save({"site": {"roomCount": 3, "roomNames": ["甲", "乙", "丙"]}})
        self.assertEqual(qk_config.room_from_ip("10.10.2.9"), {"roomName": "乙", "roomNumber": 2})
        self.assertIsNone(qk_config.room_from_ip("10.10.4.9"))
        qk_config.save({"site": {"roomCount": 40}})  # 只改数量 = 重新自动生成，不留旧名单
        self.assertEqual(qk_config.room_from_ip("10.10.40.9")["roomName"], "四十教室")
        for bad in ({"roomCount": 0}, {"roomCount": 501}, {"roomCount": 2, "roomNames": ["a"]}, {"roomNames": ["a", "a"], "roomCount": 2}, {"roomNotice": "x" * 81}):
            with self.assertRaises(ValueError, msg=bad):
                qk_config.save({"site": bad})
        self.assertEqual(qk_config.load()["site"]["roomCount"], 40, "校验失败不能落盘")


if __name__ == "__main__":
    unittest.main()
