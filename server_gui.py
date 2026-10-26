#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""缺考上报系统 - 服务端控制面板（tkinter/ttk，仅标准库，Python 3.9+）。

业务逻辑（备份/导入/规则校验/端口解析）写成不依赖 tkinter 的纯函数，--selftest 直接断言。
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime


if "--selftest" in sys.argv and not os.environ.get("QEUKAO_DATA_DIR"):
    # qk_config 在 import 时读取 QEUKAO_DATA_DIR，必须先于 import 设置临时目录
    import tempfile
    os.environ["QEUKAO_DATA_DIR"] = tempfile.mkdtemp(prefix="qk-gui-selftest-")
    _SELFTEST_TMP = os.environ["QEUKAO_DATA_DIR"]  # selftest 结束时清理
else:
    _SELFTEST_TMP = ""

import qk_config  # noqa: E402
import qk_dbtools  # noqa: E402

IS_WINDOWS = os.name == "nt"
DEFAULT_PASSWORD_HINT = "当前仍是默认密码 112233：登录网页后台后必须先修改"  # 仅作提示文案
LOCKED_PASSWORD_HINT = "配置文件曾损坏，Web 登录已锁定：请在下方重设管理密码"


# ───────────────────────── 纯函数（无 tkinter 依赖） ─────────────────────────
def parse_port(text):
    """解析端口文本，非法抛 ValueError（中文消息）。"""
    try:
        port = int(str(text).strip())
    except ValueError:
        raise ValueError("端口必须是数字")
    if not 1 <= port <= 65535:
        raise ValueError("端口范围应为 1-65535")
    return port


def format_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%d B" % n if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024


def format_mtime(ts):
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def describe_start_error(exc, port):
    """服务启动失败 → 中文提示。"""
    if isinstance(exc, OSError):
        code = getattr(exc, "errno", None)
        if code in (98, 10048, 48) or "Address already in use" in str(exc):
            return "端口 %d 已被其他程序占用，请换一个端口后重试" % port
        if code in (13, 10013):
            # Windows 上端口被别的程序独占、被系统保留（Hyper-V/WinNAT 排除段）、被防火墙拦截，bind 都报 10013，无法区分
            return "无法监听端口 %d：可能已被其他程序占用，或被系统保留/防火墙拦截。请换一个端口后重试" % port
    return "服务启动失败：%s" % exc


def op_backup():
    return str(qk_dbtools.backup_database())


def op_export(dest):
    return str(qk_dbtools.export_database(dest))


def op_import(src):
    """返回 (ok, 中文消息)。DbToolError 的消息直接展示。"""
    try:
        r = qk_dbtools.import_database(src)
    except qk_dbtools.DbToolError as e:
        return False, str(e)
    except Exception as e:  # 其它异常也不崩 UI
        return False, "导入失败：%s" % e
    return True, "导入成功，共 %s 条上报记录。\n导入前已自动备份到：\n%s" % (r.get("reportCount"), r.get("backupPath"))


def save_backup_settings(enabled, every_days, retention_days):
    try:
        every = int(str(every_days).strip())
        keep = int(str(retention_days).strip())
    except ValueError:
        raise ValueError("备份周期和保留天数必须是整数")
    if every < 1 or keep < 1:
        raise ValueError("备份周期和保留天数必须 ≥ 1")
    qk_config.save({"backup": {"enabled": bool(enabled), "everyDays": every, "retentionDays": keep}})


def validate_rule_input(octet_text, prefix_text):
    try:
        octet = int(str(octet_text).strip())
    except ValueError:
        raise ValueError("段位必须是 1-4 的数字")
    return qk_config.validate_room_rule({"octet": octet, "prefix": str(prefix_text).strip()})


def preview_room(rule_octet, rule_prefix, ip):
    """用「待保存」的规则预览某 IP 对应教室，返回展示文本。ip 为空返回提示。"""
    ip = (ip or "").strip()
    if not ip:
        return "输入一个 IP 查看对应教室"
    try:
        rule = validate_rule_input(rule_octet, rule_prefix)
    except ValueError as e:
        return "规则无效：%s" % e
    nums = qk_config.parse_ipv4(ip)  # 与真实识别同一套解析，不再自己拆字符串
    if nums is None:
        return "不是有效的 IPv4 地址"
    room = qk_config.room_from_ip(ip, rule)  # 用「待保存」的规则，不读已保存配置
    if room:
        return "→ 教室编号 %d" % room["roomNumber"]
    if not ip.startswith(rule["prefix"]):
        return "未匹配：IP 前缀不是 %s" % rule["prefix"]
    return "未匹配：第 %d 段的值 %d 不在 1-%d 内" % (rule["octet"], nums[rule["octet"] - 1], len(qk_config.room_names()))


def default_password_active():
    return not qk_config.load().get("passwordHash")


def reset_enroll_key():
    return qk_config.regenerate_enroll_key()


def open_in_file_manager(path):
    """打开目录；失败返回错误文本，不抛异常。"""
    try:
        os.makedirs(path, exist_ok=True)
        if IS_WINDOWS:
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return None
    except Exception as e:
        return "无法打开目录：%s" % e


def backup_dir():
    d = qk_config.load().get("backup", {}).get("dir") or ""
    return d or str(qk_config.BASE_DIR / "backups")


# ───────────────────────── 服务控制 ─────────────────────────
class ServerController:
    """在后台线程里跑 app.build_server(...).serve_forever()。"""

    def __init__(self):
        self.httpd = None
        self.thread = None
        self.port = None
        self.error = None
        self._lock = threading.Lock()

    @property
    def running(self):
        return self.httpd is not None

    def start(self, port, host=None):
        """成功返回 None，失败返回中文错误并保持停止状态。"""
        with self._lock:
            if self.httpd is not None:
                return None
            try:
                import app
                app.init_all()
                if host is None:
                    host = qk_config.load().get("host", "0.0.0.0")
                httpd = app.build_server(host, port)
            except Exception as e:
                self.error = describe_start_error(e, port)
                return self.error
            self.httpd, self.port, self.error = httpd, port, None
            self.thread = threading.Thread(target=httpd.serve_forever, name="qk-http", daemon=True)
            self.thread.start()
            return None

    def stop(self):
        with self._lock:
            httpd, self.httpd = self.httpd, None
        if httpd is None:
            return
        try:
            httpd.shutdown()
            httpd.server_close()
        except Exception:
            pass
        if self.thread:
            self.thread.join(timeout=5)


def http_get_json(url, timeout=3):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ───────────────────────── GUI ─────────────────────────
def build_gui(preferred_port=None):
    """构造并返回 Panel（延迟 import tkinter，便于纯函数在无 tk 环境使用）。"""
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog

    class Panel:
        def __init__(self):
            self.ctl = ServerController()
            self.root = tk.Tk()
            self.root.title("缺考上报系统 - 服务端")
            self.root.minsize(760, 640)
            self.root.geometry("820x700")
            self._closing = False
            self._bg_busy = False
            self._setup_style()
            cfg = qk_config.load()
            self.port = preferred_port or int(cfg.get("port", 8000))
            self._build()
            self.root.protocol("WM_DELETE_WINDOW", self.on_close)
            self.start_server(self.port)
            self.refresh_all()
            self._tick()

        # ---- 样式 ----
        def _setup_style(self):
            import tkinter.font as tkfont
            if IS_WINDOWS:
                for n in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkFixedFont"):
                    try:
                        tkfont.nametofont(n).configure(family="Microsoft YaHei UI", size=9)
                    except tk.TclError:
                        pass
            st = ttk.Style(self.root)
            try:
                st.theme_use("vista" if IS_WINDOWS else "clam")
            except tk.TclError:
                pass
            base = tkfont.nametofont("TkDefaultFont").actual()["family"]
            st.configure("Big.TButton", font=(base, 12, "bold"), padding=(10, 10))
            st.configure("Status.TLabel", font=(base, 12, "bold"))
            st.configure("Orange.TLabel", foreground="#d97706")
            st.configure("Ok.TLabel", foreground="#15803d")
            st.configure("Err.TLabel", foreground="#b91c1c")
            st.configure("Muted.TLabel", foreground="#6b7280")
            self._base_font = base

        # ---- 布局 ----
        def _build(self):
            outer = ttk.Frame(self.root, padding=10)
            outer.pack(fill="both", expand=True)
            nb = ttk.Notebook(outer)
            nb.pack(fill="both", expand=True)
            tabs = {}
            for key, title in (("main", "服务与客户端"), ("db", "数据库"), ("set", "密码与教室识别")):
                f = ttk.Frame(nb, padding=10)
                nb.add(f, text="  %s  " % title)
                tabs[key] = f
            self._build_service(tabs["main"])
            self._build_urls(tabs["main"])
            self._build_clients(tabs["main"])
            self._build_db(tabs["db"])
            self._build_password(tabs["set"])
            self._build_room(tabs["set"])
            self.bottom_msg = ttk.Label(outer, text="", style="Muted.TLabel")
            self.bottom_msg.pack(fill="x", pady=(6, 0))
            ttk.Button(outer, text="打开管理后台", style="Big.TButton", command=self.open_admin).pack(fill="x", pady=(4, 0))

        def card(self, parent, title):
            lf = ttk.LabelFrame(parent, text=" %s " % title, padding=10)
            lf.pack(fill="x", pady=(0, 8))
            return lf

        def say(self, text, style="Muted.TLabel"):
            self.bottom_msg.configure(text=text, style=style)

        def _build_service(self, p):
            c = self.card(p, "服务状态")
            row = ttk.Frame(c); row.pack(fill="x")
            self.status_lbl = ttk.Label(row, text="…", style="Status.TLabel")
            self.status_lbl.pack(side="left")
            self.toggle_btn = ttk.Button(row, text="停止", width=8, command=self.toggle_server)
            self.toggle_btn.pack(side="right")
            row2 = ttk.Frame(c); row2.pack(fill="x", pady=(8, 0))
            ttk.Label(row2, text="端口：").pack(side="left")
            self.port_var = tk.StringVar(value=str(self.port))
            ttk.Entry(row2, textvariable=self.port_var, width=8).pack(side="left")
            ttk.Button(row2, text="保存并重启服务", command=self.apply_port).pack(side="left", padx=8)
            ttk.Label(row2, text="修改端口需重启服务；其他电脑需放行防火墙（open_firewall.bat）", style="Muted.TLabel").pack(side="left")

        def _build_urls(self, p):
            self.urls_card = self.card(p, "访问地址")
            self.urls_body = ttk.Frame(self.urls_card)
            self.urls_body.pack(fill="x")

        def _url_row(self, parent, label, url):
            r = ttk.Frame(parent); r.pack(fill="x", pady=1)
            ttk.Label(r, text=label, width=18).pack(side="left")
            e = ttk.Entry(r); e.insert(0, url); e.configure(state="readonly")
            e.pack(side="left", fill="x", expand=True, padx=4)
            ttk.Button(r, text="复制", width=5, command=lambda u=url: self.copy(u)).pack(side="left", padx=2)
            ttk.Button(r, text="打开", width=5, command=lambda u=url: webbrowser.open(u)).pack(side="left")

        def refresh_urls(self):
            for w in self.urls_body.winfo_children():
                w.destroy()
            port = self.ctl.port or self.port
            self._url_row(self.urls_body, "本机", "http://127.0.0.1:%d/" % port)
            urls = []
            try:
                urls = qk_config.access_urls(port)
            except Exception:
                pass
            if not urls:
                ttk.Label(self.urls_body, text="未检测到局域网 IPv4 地址（请检查网线/Wi-Fi）", style="Orange.TLabel").pack(anchor="w", pady=2)
            for u in urls:
                self._url_row(self.urls_body, "填报 " + u["ip"], u["fillUrl"])
                self._url_row(self.urls_body, "管理", u["adminUrl"])

        def _build_clients(self, p):
            c = self.card(p, "客户端")
            row = ttk.Frame(c); row.pack(fill="x")
            self.client_lbl = ttk.Label(row, text="客户端：—")
            self.client_lbl.pack(side="left")
            ttk.Button(row, text="重置接入密钥", command=self.reset_key).pack(side="right")
            ttk.Button(row, text="生成绑定客户端…", command=self.gen_client).pack(side="right", padx=8)

        def _build_db(self, p):
            c = self.card(p, "备份与导入导出")
            row = ttk.Frame(c); row.pack(fill="x")
            for text, cmd in (("立即备份", self.do_backup), ("导出到…", self.do_export),
                              ("从文件导入…", self.do_import), ("打开备份目录", self.open_backup_dir)):
                ttk.Button(row, text=text, command=cmd).pack(side="left", padx=(0, 8))
            self.db_busy = ttk.Label(c, text="", style="Muted.TLabel"); self.db_busy.pack(anchor="w", pady=(6, 0))

            a = self.card(p, "自动备份")
            b = qk_config.load().get("backup", {})
            self.auto_var = tk.BooleanVar(value=bool(b.get("enabled", True)))
            self.every_var = tk.StringVar(value=str(b.get("everyDays", 3)))
            self.keep_var = tk.StringVar(value=str(b.get("retentionDays", 90)))
            r = ttk.Frame(a); r.pack(fill="x")
            ttk.Checkbutton(r, text="启用自动备份", variable=self.auto_var).pack(side="left")
            ttk.Label(r, text="　每").pack(side="left")
            ttk.Spinbox(r, from_=1, to=365, width=4, textvariable=self.every_var).pack(side="left")
            ttk.Label(r, text="天，保留").pack(side="left")
            ttk.Spinbox(r, from_=1, to=3650, width=5, textvariable=self.keep_var).pack(side="left")
            ttk.Label(r, text="天").pack(side="left")
            ttk.Button(r, text="保存", command=self.save_backup_cfg).pack(side="left", padx=10)

            l = ttk.LabelFrame(p, text=" 最近备份 ", padding=6); l.pack(fill="both", expand=True)
            cols = ("name", "size", "time")
            self.tree = ttk.Treeview(l, columns=cols, show="headings", height=8)
            for k, t, w in (("name", "名称", 360), ("size", "大小", 80), ("time", "时间", 150)):
                self.tree.heading(k, text=t); self.tree.column(k, width=w, anchor="w" if k == "name" else "e")
            sb = ttk.Scrollbar(l, orient="vertical", command=self.tree.yview)
            self.tree.configure(yscrollcommand=sb.set)
            self.tree.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")

        def _build_password(self, p):
            c = self.card(p, "Web 管理密码")
            self.pw_hint = ttk.Label(c, text="", style="Orange.TLabel"); self.pw_hint.pack(anchor="w")
            g = ttk.Frame(c); g.pack(fill="x", pady=(4, 0))
            self.pw1, self.pw2 = tk.StringVar(), tk.StringVar()
            ttk.Label(g, text="新密码：").grid(row=0, column=0, sticky="e", pady=2)
            ttk.Entry(g, textvariable=self.pw1, show="*", width=24).grid(row=0, column=1, sticky="w")
            ttk.Label(g, text="确认密码：").grid(row=1, column=0, sticky="e", pady=2)
            ttk.Entry(g, textvariable=self.pw2, show="*", width=24).grid(row=1, column=1, sticky="w")
            ttk.Button(g, text="修改密码", command=self.change_password).grid(row=1, column=2, padx=10)
            self.pw_msg = ttk.Label(c, text="", style="Muted.TLabel"); self.pw_msg.pack(anchor="w", pady=(4, 0))

        def _build_room(self, p):
            c = self.card(p, "教室识别（按访问 IP 推断）")
            r = ttk.Frame(c); r.pack(fill="x")
            rule = qk_config.load().get("roomRule", {})
            self.octet_var = tk.StringVar(value=str(rule.get("octet", 3)))
            self.prefix_var = tk.StringVar(value=str(rule.get("prefix", "")))
            ttk.Label(r, text="取 IP 第").pack(side="left")
            ttk.Spinbox(r, from_=1, to=4, width=3, textvariable=self.octet_var, command=self.update_preview).pack(side="left")
            ttk.Label(r, text="段为教室号，IP 前缀：").pack(side="left")
            ttk.Entry(r, textvariable=self.prefix_var, width=14).pack(side="left")
            ttk.Button(r, text="保存规则", command=self.save_rule).pack(side="left", padx=8)
            ttk.Button(r, text="按已登记客户端自动推荐", command=self.suggest_rule).pack(side="left")
            r2 = ttk.Frame(c); r2.pack(fill="x", pady=(8, 0))
            self.test_ip = tk.StringVar()
            ttk.Label(r2, text="测试 IP：").pack(side="left")
            ttk.Entry(r2, textvariable=self.test_ip, width=18).pack(side="left")
            self.preview_lbl = ttk.Label(r2, text="", style="Muted.TLabel"); self.preview_lbl.pack(side="left", padx=10)
            for v in (self.octet_var, self.prefix_var, self.test_ip):
                v.trace_add("write", lambda *_: self.update_preview())
            self.rule_msg = ttk.Label(c, text="", style="Muted.TLabel"); self.rule_msg.pack(anchor="w", pady=(4, 0))
            self.update_preview()

        # ---- 工具 ----
        def copy(self, text):
            self.root.clipboard_clear(); self.root.clipboard_append(text)
            self.say("已复制：%s" % text, "Ok.TLabel")

        def run_bg(self, work, done, busy_text="处理中…"):
            """work() 在线程里跑，done(result, exc) 回到主线程。"""
            if self._bg_busy:  # 备份/导出/导入互斥，避免两次导入交错
                self.say("上一个数据库操作还没结束，请稍候再试")
                return
            self._bg_busy = True
            self.db_busy.configure(text=busy_text)
            def target():
                res = exc = None
                try:
                    res = work()
                except Exception as e:
                    exc = e
                if not self._closing:
                    try:
                        self.root.after(0, lambda: (setattr(self, "_bg_busy", False), self.db_busy.configure(text=""), done(res, exc)))
                    except Exception:
                        pass
            threading.Thread(target=target, daemon=True).start()

        # ---- 服务 ----
        def start_server(self, port):
            err = self.ctl.start(port)
            if not err:
                self.port = port
            self.refresh_status()
            return err

        def toggle_server(self):
            if self.ctl.running:
                self.ctl.stop()
            else:
                self.start_server(self.port)
            self.refresh_status(); self.refresh_urls()

        def apply_port(self):
            try:
                port = parse_port(self.port_var.get())
            except ValueError as e:
                messagebox.showerror("端口无效", str(e)); return
            self.ctl.stop()
            err = self.start_server(port)
            if err:
                messagebox.showerror("启动失败", err)
            else:
                qk_config.save({"port": port})
                self.say("端口已保存为 %d，服务已重启" % port, "Ok.TLabel")
            self.refresh_urls()

        def refresh_status(self):
            if self.ctl.running:
                self.status_lbl.configure(text="● 运行中（端口 %d）" % self.ctl.port, style="Ok.TLabel")
                self.toggle_btn.configure(text="停止")
            else:
                msg = self.ctl.error or "已停止"
                self.status_lbl.configure(text="● " + msg, style="Err.TLabel")
                self.toggle_btn.configure(text="启动")
            self.status_lbl.configure(font=(self._base_font, 11, "bold"))

        def open_admin(self):
            webbrowser.open("http://127.0.0.1:%d/admin" % (self.ctl.port or self.port))

        # ---- 客户端 ----
        def refresh_clients(self):
            try:
                import qk_agents
                s = qk_agents.client_summary()
                self.client_lbl.configure(text="客户端：在线 %s / 已登记 %s" % (s.get("online", 0), s.get("total", 0)))
            except Exception as e:
                self.client_lbl.configure(text="客户端：统计不可用（%s）" % e)

        def gen_client(self):
            import qk_agents
            path = filedialog.asksaveasfilename(title="保存绑定客户端", defaultextension=".exe",
                                                initialfile="qeukao-client.exe", filetypes=[("可执行文件", "*.exe")])
            if not path:
                return
            port = self.ctl.port or self.port
            servers = ["http://%s:%d" % (ip, port) for ip in qk_config.lan_ipv4_addresses()] or ["http://127.0.0.1:%d" % port]
            try:
                out = qk_agents.build_client_exe(servers, path)
            except FileNotFoundError as e:
                messagebox.showerror("无法生成客户端", str(e)); return
            except Exception as e:
                messagebox.showerror("生成失败", str(e)); return
            messagebox.showinfo("已生成", "已生成绑定客户端：\n%s\n\n内含服务器地址：\n%s" % (out, "\n".join(servers)))

        def reset_key(self):
            if not messagebox.askyesno("重置接入密钥", "重置后，所有已部署的旧客户端将全部失效，\n需要重新生成并重新分发客户端。\n\n确定重置吗？", icon="warning"):
                return
            reset_enroll_key()
            self.say("接入密钥已重置，请重新生成绑定客户端", "Orange.TLabel")

        # ---- 数据库 ----
        def refresh_backups(self):
            for i in self.tree.get_children():
                self.tree.delete(i)
            try:
                items = qk_dbtools.list_backups()
            except Exception:
                items = []
            for it in items[:50]:
                self.tree.insert("", "end", values=(it["name"], format_size(it["size"]), format_mtime(it["mtime"])))

        def do_backup(self):
            def done(res, exc):
                if exc: messagebox.showerror("备份失败", str(exc))
                else: self.say("已备份：%s" % res, "Ok.TLabel")
                self.refresh_backups()
            self.run_bg(op_backup, done, "正在备份…")

        def do_export(self):
            path = filedialog.asksaveasfilename(title="导出数据库", defaultextension=".sqlite3",
                                                initialfile="qeukao-export-%s.sqlite3" % time.strftime("%Y%m%d-%H%M%S"),
                                                filetypes=[("SQLite 数据库", "*.sqlite3 *.db"), ("所有文件", "*.*")])
            if not path:
                return
            def done(res, exc):
                if exc: messagebox.showerror("导出失败", str(exc))
                else: messagebox.showinfo("导出完成", "已导出到：\n%s" % res)
            self.run_bg(lambda: op_export(path), done, "正在导出…")

        def do_import(self):
            path = filedialog.askopenfilename(title="选择要导入的数据库文件",
                                              filetypes=[("SQLite 数据库", "*.sqlite3 *.db *.sqlite"), ("所有文件", "*.*")])
            if not path:
                return
            if not messagebox.askyesno("确认导入", "将用所选文件覆盖当前数据库内容：\n%s\n\n导入前会先自动备份当前数据库。\n确定继续吗？" % path, icon="warning"):
                return
            def done(res, exc):
                ok, msg = res if res else (False, str(exc))
                (messagebox.showinfo if ok else messagebox.showerror)("导入完成" if ok else "导入失败", msg)
                self.refresh_backups()
            self.run_bg(lambda: op_import(path), done, "正在导入…")

        def open_backup_dir(self):
            err = open_in_file_manager(backup_dir())
            if err: messagebox.showerror("打开失败", err)

        def save_backup_cfg(self):
            try:
                save_backup_settings(self.auto_var.get(), self.every_var.get(), self.keep_var.get())
            except ValueError as e:
                messagebox.showerror("设置无效", str(e)); return
            self.say("自动备份设置已保存", "Ok.TLabel")

        # ---- 密码 ----
        def refresh_password_hint(self):
            self.pw_hint.configure(text=LOCKED_PASSWORD_HINT if qk_config.password_locked()
                                   else (DEFAULT_PASSWORD_HINT if default_password_active() else ""))

        def change_password(self):
            a, b = self.pw1.get(), self.pw2.get()
            if a != b:
                self.pw_msg.configure(text="两次输入不一致", style="Err.TLabel"); return
            try:
                qk_config.set_admin_password(a)
            except ValueError as e:
                self.pw_msg.configure(text=str(e), style="Err.TLabel"); return
            self.pw1.set(""); self.pw2.set("")
            self.pw_msg.configure(text="密码已修改，下次登录管理后台生效", style="Ok.TLabel")
            self.refresh_password_hint()

        # ---- 教室识别 ----
        def update_preview(self):
            self.preview_lbl.configure(text=preview_room(self.octet_var.get(), self.prefix_var.get(), self.test_ip.get()))

        def save_rule(self):
            try:
                rule = validate_rule_input(self.octet_var.get(), self.prefix_var.get())
            except ValueError as e:
                self.rule_msg.configure(text=str(e), style="Err.TLabel"); return
            qk_config.save({"roomRule": rule})
            self.rule_msg.configure(text="规则已保存", style="Ok.TLabel")

        def suggest_rule(self):
            try:
                import qk_agents
                s = qk_config.suggest_room_rule(qk_agents.recent_client_ips())
            except Exception as e:
                self.rule_msg.configure(text="推荐失败：%s" % e, style="Err.TLabel"); return
            if not s:
                messagebox.showinfo("暂无推荐", "已登记客户端的 IP 不足以推断规则（需要至少有客户端接入）。"); return
            self.octet_var.set(str(s["octet"])); self.prefix_var.set(s.get("prefix", ""))
            self.rule_msg.configure(text="已套用推荐（%s/%s 台匹配），确认无误后点“保存规则”" % (s.get("matched"), s.get("total")), style="Orange.TLabel")

        # ---- 刷新 / 生命周期 ----
        def refresh_all(self):
            self.refresh_status(); self.refresh_urls(); self.refresh_clients()
            self.refresh_backups(); self.refresh_password_hint(); self.update_preview()

        def _tick(self):
            if self._closing:
                return
            self.refresh_clients()
            self.root.after(3000, self._tick)

        def on_close(self):
            if not messagebox.askyesno("退出", "关闭将停止服务，所有客户端将离线。\n确定关闭吗？", icon="warning"):
                return
            self.shutdown()

        def shutdown(self):
            self._closing = True
            self.ctl.stop()
            try:
                self.root.destroy()
            except Exception:
                pass

    return Panel()


# ───────────────────────── selftest ─────────────────────────
def _free_port():
    for p in range(18000, 19000):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("18000-18999 无可用端口")


def selftest():
    import tempfile
    problems = []
    def check(cond, msg):
        if not cond:
            problems.append(msg)
    panel = None
    scratch = tempfile.mkdtemp(prefix="qkgui-")  # 导出文件与备份目录都放这里，finally 里整体删除
    try:
        # 纯函数
        check(parse_port("8000") == 8000, "parse_port")
        for bad in ("abc", "0", "70000"):
            try: parse_port(bad); problems.append("parse_port 应拒绝 " + bad)
            except ValueError: pass
        check("占用" in describe_start_error(OSError(98, "Address already in use"), 8000), "端口占用文案")
        # Windows 上端口被别的程序独占时，后来者 bind 报的是 10013(WSAEACCES) 而不是 10048：文案必须同时提到「占用」
        check("占用" in describe_start_error(OSError(10013, "access denied"), 8000), "10013 的文案应提到端口可能被占用")
        check("占用" in describe_start_error(OSError(13, "Permission denied"), 8000), "errno 13 的文案应提到端口可能被占用")
        check(format_size(1536) == "1.5 KB", "format_size")
        check(preview_room("3", "10.10.", "10.10.7.23") == "→ 教室编号 7", "preview 命中: " + preview_room("3", "10.10.", "10.10.7.23"))
        check(preview_room("3", "10.10.", "192.168.1.1").startswith("未匹配"), "preview 前缀不符")
        check(preview_room("9", "", "1.2.3.4").startswith("规则无效"), "preview 非法规则")
        try: save_backup_settings(True, "0", "5"); problems.append("backup 设置应拒绝 0")
        except ValueError: pass

        # 备份目录指到临时目录：默认是仓库下的 backups/，selftest 不得往仓库写文件
        qk_config.save({"backup": {"dir": os.path.join(scratch, "backups")}})
        panel = build_gui(_free_port())
        check(panel.ctl.running, "服务未运行: %s" % panel.ctl.error)
        port = panel.ctl.port
        h = http_get_json("http://127.0.0.1:%d/api/health" % port)
        ok = h.get("ok") or (h.get("data") or {}).get("ok") or h.get("success")
        check(ok, "health 非 ok: %r" % (h,))
        # 端口占用：另起控制器占同端口
        c2 = ServerController()
        err = c2.start(port)
        check(err and "占用" in err, "占用端口应返回中文提示: %r" % (err,))
        # 备份/导出/导入纯函数
        b = op_backup(); check(os.path.exists(b), "备份文件不存在")
        d = scratch
        e = op_export(os.path.join(d, "x.sqlite3")); check(os.path.exists(e), "导出失败")
        okk, msg = op_import(e); check(okk, "导入自身导出应成功: " + msg)
        bad = os.path.join(d, "bad.sqlite3")
        with open(bad, "wb") as f: f.write(b"not sqlite")
        okk, msg = op_import(bad); check((not okk) and msg, "非法文件应给中文失败原因")
        # 面板刷新
        panel.refresh_all(); panel.root.update()
        check(len(panel.tree.get_children()) >= 1, "备份列表为空")
        panel.toggle_server(); check(not panel.ctl.running, "停止失败")
        panel.toggle_server(); check(panel.ctl.running, "重新启动失败")
        panel.say("x"); panel.root.update()
    except Exception as e:
        import traceback
        problems.append("异常：%s\n%s" % (e, traceback.format_exc()))
    finally:
        if panel is not None:
            try: panel.shutdown()
            except Exception: pass
        import shutil
        shutil.rmtree(scratch, ignore_errors=True)
        if _SELFTEST_TMP:
            shutil.rmtree(_SELFTEST_TMP, ignore_errors=True)
    if problems:
        print("SELFTEST FAIL:\n - " + "\n - ".join(problems))
        return 1
    print("SELFTEST OK")
    return 0


def _enable_dpi():
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return selftest()
    _enable_dpi()
    panel = build_gui()
    panel.root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
