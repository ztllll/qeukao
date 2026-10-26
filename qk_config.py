"""Windows 版配置：<DATA_DIR>/config.json 的读写、密码、教室识别规则。契约见 docs/windows-contract.md §2/§3。"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
from pathlib import Path


def _app_dir() -> Path:
    """可写数据的根目录。PyInstaller 单文件下 __file__ 在退出即删的临时目录里，须改用 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = _app_dir()

MAX_ROOMS = 500
# 教室名单与草稿的一致性锁：改名单（检查有无草稿 + 落盘）、老师提交（按名单验证 + 写草稿）、整库导入（换掉全部草稿）
# 三者必须互斥，否则草稿的 room_number/room_name 会和名单错位。服务端是单进程多线程，线程锁足够。
ROOM_LIST_LOCK = threading.RLock()
_DIGITS = "零一二三四五六七八九"


def _cn_number(n: int) -> str:
    """1..999 → 中文数字：1→一，10→十，11→十一，20→二十，21→二十一，100→一百，101→一百零一。"""
    if n < 10:
        return _DIGITS[n]
    if n < 20:
        return "十" + (_DIGITS[n - 10] if n > 10 else "")
    if n < 100:
        return _DIGITS[n // 10] + "十" + (_DIGITS[n % 10] if n % 10 else "")
    rest = n % 100
    tail = "" if rest == 0 else ("零" + _DIGITS[rest] if rest < 10 else _cn_number(rest) if rest >= 20 else "一" + _cn_number(rest))
    return _DIGITS[n // 100] + "百" + tail


def default_room_name(number: int) -> str:
    return _cn_number(number) + "教室"

_PBKDF2_ROUNDS = 200000
_FALLBACK_PASSWORD = "112233"  # 契约 §2：passwordHash 缺失时的最终回退；用它登录后必须先改密码才能用后台
DEFAULT_ROOM_NOTICE = "请确认选择的是本教室，选错会导致数据错误。"
_KNOWN_SAVE_KEYS = ("serverName", "host", "port", "roomRule", "site", "backup")
_PREFIX_RE = re.compile(r"^(?:[0-9]{1,3}\.){1,3}$")
_IPV4_RE = re.compile(r"^[0-9]{1,3}(?:\.[0-9]{1,3}){3}$")

DATA_DIR: Path
CONFIG_PATH: Path
DB_PATH: Path

_lock = threading.RLock()
_cache: dict | None = None
_cache_sig: tuple | None = None


def _reload_paths_for_tests() -> None:
    """按当前环境变量重算路径并清空缓存（仅测试使用）。"""
    global DATA_DIR, CONFIG_PATH, DB_PATH, _cache, _cache_sig
    with _lock:
        DATA_DIR = Path(os.environ.get("QEUKAO_DATA_DIR") or (BASE_DIR / "data"))
        CONFIG_PATH = DATA_DIR / "config.json"
        DB_PATH = Path(os.environ.get("QEUKAO_DB") or (DATA_DIR / "qeukao.sqlite3"))
        _cache = None
        _cache_sig = None


_reload_paths_for_tests()


def _defaults() -> dict:
    return {
        "version": 1,
        "serverName": "考务服务端",
        "host": "0.0.0.0",
        "port": 8000,
        "sessionSecret": secrets.token_hex(32),
        "enrollKey": secrets.token_urlsafe(18),
        # 前缀留空 = 不限网段，只按 IP 第 3 段认教室；后台「教室识别规则」可按已登记客户端一键推荐
        "roomRule": {"octet": 3, "prefix": ""},
        # 管理员在后台「基本信息」里维护：单位名称/地址（统计表抬头与页脚）、教室数量与名称（空名单=按「N教室」自动生成）、
        # 填报页选教室时的提醒语。单位名称首次安装为空，后台会提示先填写
        "site": {"orgName": "", "orgAddress": "", "roomCount": 30, "roomNames": [], "roomNotice": DEFAULT_ROOM_NOTICE},
        "backup": {"enabled": True, "dir": "", "everyDays": 3, "retentionDays": 90},
    }


def _sig() -> tuple | None:
    try:
        st = os.stat(CONFIG_PATH)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _write(cfg: dict) -> None:
    """原子写：同目录临时文件 + os.replace。调用方持锁。"""
    global _cache, _cache_sig
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_name("config.json.tmp-%d-%d" % (os.getpid(), threading.get_ident()))
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_PATH)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    _cache = copy.deepcopy(cfg)
    _cache_sig = _sig()


def _quarantine_corrupt() -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = CONFIG_PATH.with_name("config.json.bad-" + stamp)
    n = 1
    while target.exists():
        n += 1
        target = CONFIG_PATH.with_name("config.json.bad-%s-%d" % (stamp, n))
    os.replace(CONFIG_PATH, target)


def _merge_defaults(dst: dict, defaults: dict) -> bool:
    changed = False
    for k, v in defaults.items():
        if k not in dst:
            dst[k] = copy.deepcopy(v)
            changed = True
        elif isinstance(v, dict):
            if isinstance(dst[k], dict):
                changed = _merge_defaults(dst[k], v) or changed
            else:
                dst[k] = copy.deepcopy(v)
                changed = True
    return changed


def _current() -> dict:
    """返回内部缓存（不可外泄）。调用方持锁。"""
    global _cache, _cache_sig
    sig = _sig()
    if _cache is not None and sig is not None and sig == _cache_sig:
        return _cache
    cfg = None
    corrupt = False
    if sig is not None:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:  # 记事本另存为「带 BOM 的 UTF-8」也要能读
                cfg = json.load(f)
            if not isinstance(cfg, dict):
                raise ValueError("config root is not an object")
        except (ValueError, UnicodeDecodeError):
            _quarantine_corrupt()  # 不静默覆盖：坏文件改名保留
            cfg = None
            corrupt = True
    if cfg is None:
        cfg = _defaults()
        if corrupt:
            cfg["passwordLocked"] = True  # 坏配置不能把认证退回默认口令；在本机重设密码后解除
        _write(cfg)
        return _cache
    if _merge_defaults(cfg, _defaults()):
        _write(cfg)
        return _cache
    _cache, _cache_sig = cfg, sig
    return _cache


def load() -> dict:
    with _lock:
        return copy.deepcopy(_current())


def _int_in(value, lo: int, hi: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError("%s 必须是 %d..%d 的整数" % (name, lo, hi))
    return value


def validate_room_rule(rule: dict) -> dict:
    if not isinstance(rule, dict):
        raise ValueError("roomRule 必须是对象")
    octet = _int_in(rule.get("octet"), 1, 4, "octet")
    prefix = rule.get("prefix", "")
    if not isinstance(prefix, str):
        raise ValueError("prefix 必须是字符串")
    prefix = prefix.strip()
    if prefix:
        if not _PREFIX_RE.match(prefix) or any(int(p) > 255 for p in prefix.split(".")[:-1]):
            raise ValueError('prefix 应为空或形如 "10.10."')
    return {"octet": octet, "prefix": prefix}


def validate_site(site: dict) -> dict:
    if not isinstance(site, dict):
        raise ValueError("site 必须是对象")
    org = site.get("orgName")
    if not isinstance(org, str) or len(org.strip()) > 60:
        raise ValueError("单位名称最多 60 个字")
    address = site.get("orgAddress", "")
    if not isinstance(address, str) or len(address.strip()) > 120:
        raise ValueError("地址最多 120 个字")
    count = _int_in(site.get("roomCount"), 1, MAX_ROOMS, "教室数量")
    names = site.get("roomNames", [])
    if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
        raise ValueError("教室名称必须是文字列表")
    names = [n.strip() for n in names]
    if names:
        if len(names) != count:
            raise ValueError("教室名称个数（%d）必须等于教室数量（%d）" % (len(names), count))
        if any(not n or len(n) > 20 for n in names):
            raise ValueError("每个教室名称不能为空，最多 20 个字")
        if len(set(names)) != len(names):
            raise ValueError("教室名称不能重复")
    notice = site.get("roomNotice", DEFAULT_ROOM_NOTICE)
    if not isinstance(notice, str) or len(notice.strip()) > 80:
        raise ValueError("填报提醒最多 80 个字")
    return {"orgName": org.strip(), "orgAddress": address.strip(), "roomCount": count, "roomNames": names,
            "roomNotice": notice.strip()}


def names_of(site: dict) -> list:
    """一份 site 配置对应的教室名单：管理员配置的名单，或按数量自动生成「一教室…N教室」。"""
    return list(site["roomNames"]) or [default_room_name(i) for i in range(1, site["roomCount"] + 1)]


def merge_site(current: dict, patch: dict) -> dict:
    """把一次修改合并进当前 site 并校验。只改数量 = 重新自动生成名单，不能留着旧名单造成个数对不上。"""
    merged = dict(current)
    merged.update({k: v for k, v in patch.items() if k in current})
    if "roomCount" in patch and "roomNames" not in patch:
        merged["roomNames"] = []
    return validate_site(merged)


def room_names() -> list:
    """当前教室名单。IP 第几段=名单里第几间。"""
    return names_of(load()["site"])


def _validate_backup(b: dict) -> dict:
    if not isinstance(b, dict):
        raise ValueError("backup 必须是对象")
    if not isinstance(b.get("enabled"), bool):
        raise ValueError("backup.enabled 必须是布尔值")
    if not isinstance(b.get("dir"), str):
        raise ValueError("backup.dir 必须是字符串")
    return {
        "enabled": b["enabled"],
        "dir": b["dir"].strip(),
        "everyDays": _int_in(b.get("everyDays"), 1, 365, "backup.everyDays"),
        "retentionDays": _int_in(b.get("retentionDays"), 1, 3650, "backup.retentionDays"),
    }


def save(patch: dict) -> dict:
    """深合并 + 校验 + 原子写。只认 serverName/host/port/roomRule/backup，其它键忽略；非法值抛 ValueError 且不落盘。"""
    if not isinstance(patch, dict):
        raise ValueError("patch 必须是对象")
    with _lock:
        new = copy.deepcopy(_current())
        for key in _KNOWN_SAVE_KEYS:
            if key not in patch:
                continue
            val = patch[key]
            if key in ("roomRule", "backup", "site"):
                if not isinstance(val, dict):
                    raise ValueError("%s 必须是对象" % key)
                if key == "site":
                    new[key] = merge_site(new[key], val)
                    continue
                merged = dict(new[key])
                merged.update({k: v for k, v in val.items() if k in new[key]})
                new[key] = validate_room_rule(merged) if key == "roomRule" else _validate_backup(merged)
            elif key == "port":
                new[key] = _int_in(val, 1, 65535, "port")
            else:
                if not isinstance(val, str) or not val.strip():
                    raise ValueError("%s 不能为空" % key)
                new[key] = val.strip()
        _write(new)
        return copy.deepcopy(new)


# ---------------------------------------------------------------- 密码 / 密钥
def _hash_password(pw: str, salt_hex: str, rounds: int = _PBKDF2_ROUNDS) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt_hex), rounds).hex()


_MIN_ROUNDS, _MAX_ROUNDS = 1000, 2_000_000


def password_locked() -> bool:
    """配置文件曾损坏且尚未在本机重设密码：Web 登录一律拒绝。"""
    return bool(load().get("passwordLocked"))


def check_admin_password(pw: str) -> bool:
    if not isinstance(pw, str):
        return False
    cfg = load()
    if cfg.get("passwordLocked"):
        return False
    stored = cfg.get("passwordHash")
    if not stored:
        expected = os.environ.get("QEUKAO_ADMIN_PASSWORD") or _FALLBACK_PASSWORD
        return hmac.compare_digest(pw.encode("utf-8"), expected.encode("utf-8"))
    try:
        scheme, rounds, salt_hex, hash_hex = str(stored).split("$")
        n = int(rounds)
        if scheme != "pbkdf2" or not _MIN_ROUNDS <= n <= _MAX_ROUNDS:
            return False
        got = _hash_password(pw, salt_hex, n)
    except (ValueError, OverflowError):
        return False
    return hmac.compare_digest(got.encode("ascii"), hash_hex.encode("ascii", "replace"))


def must_change_password() -> bool:
    """还在用内置默认密码（没设过 passwordHash，也没用环境变量指定）：后台只允许改密码。"""
    return not load().get("passwordHash") and not os.environ.get("QEUKAO_ADMIN_PASSWORD")


def set_admin_password(new_pw: str) -> None:
    if not isinstance(new_pw, str) or not 4 <= len(new_pw) <= 64:
        raise ValueError("密码长度必须为 4..64 个字符")
    if new_pw == _FALLBACK_PASSWORD:
        raise ValueError("不能使用默认密码 %s，请换一个" % _FALLBACK_PASSWORD)
    salt = secrets.token_hex(16)
    value = "pbkdf2$%d$%s$%s" % (_PBKDF2_ROUNDS, salt, _hash_password(new_pw, salt))
    with _lock:
        cfg = copy.deepcopy(_current())
        cfg["passwordHash"] = value
        cfg.pop("passwordLocked", None)
        _write(cfg)


def session_secret() -> str:
    return os.environ.get("QEUKAO_SESSION_SECRET") or load()["sessionSecret"]


def enroll_key() -> str:
    return load()["enrollKey"]


def regenerate_enroll_key() -> str:
    key = secrets.token_urlsafe(18)
    with _lock:
        cfg = copy.deepcopy(_current())
        cfg["enrollKey"] = key
        _write(cfg)
    return key


# ---------------------------------------------------------------- 教室识别
def parse_ipv4(ip) -> list | None:
    if not isinstance(ip, str) or not _IPV4_RE.match(ip):
        return None
    parts = ip.split(".")
    if any(len(p) > 1 and p[0] == "0" for p in parts):
        return None
    nums = [int(p) for p in parts]
    return nums if all(n <= 255 for n in nums) else None


def room_from_ip(ip: str, rule: dict | None = None) -> dict | None:
    """rule 缺省取已保存的规则；GUI/Web 预览传「待保存」的规则，保证预览与真实识别同一套逻辑。"""
    nums = parse_ipv4(ip)
    if nums is None:
        return None
    rule = rule or load()["roomRule"]
    if not ip.startswith(rule["prefix"]):
        return None
    n = nums[rule["octet"] - 1]
    names = room_names()
    if not 1 <= n <= len(names):
        return None
    return {"roomName": names[n - 1], "roomNumber": n}


def suggest_room_rule(ips: list) -> dict | None:
    rows = [n for n in (parse_ipv4(i) for i in ips or []) if n is not None]
    if not rows:
        return None
    total = len(rows)
    best = None  # (distinct, octet)
    for octet in (1, 2, 3, 4):
        vals = [r[octet - 1] for r in rows if 1 <= r[octet - 1] <= len(room_names())]
        if len(vals) * 10 < total * 9:
            continue
        key = (len(set(vals)), 1 if octet == 3 else 0, -octet)  # 并列优先 octet=3，其次靠前的段
        if best is None or key > best[0]:
            best = (key, octet, len(vals))
    if best is None:
        return None
    _, octet, matched = best
    head = rows[0][: octet - 1]
    same = all(r[: octet - 1] == head for r in rows)
    prefix = "".join("%d." % p for p in head) if same else ""
    return {"octet": octet, "prefix": prefix, "matched": matched, "total": total}


# ---------------------------------------------------------------- 本机地址
def lan_ipv4_addresses() -> list:
    found = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    try:  # UDP connect 不发包，只让系统选出默认出口地址
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            found.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    out = []
    for ip in found:
        nums = parse_ipv4(ip)
        if nums is None or nums[0] in (0, 127) or nums[:2] == [169, 254] or ip in out:
            continue
        out.append(ip)

    def private(ip: str) -> bool:
        a, b = parse_ipv4(ip)[:2]
        return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)

    return sorted(out, key=lambda ip: 0 if private(ip) else 1)  # sorted 稳定


def access_urls(port: int) -> list:
    return [
        {"ip": ip, "fillUrl": "http://%s:%d/" % (ip, port), "adminUrl": "http://%s:%d/admin" % (ip, port)}
        for ip in lan_ipv4_addresses()
    ]
