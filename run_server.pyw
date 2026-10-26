# -*- coding: utf-8 -*-
"""双击启动（pythonw，无控制台）。未捕获异常写 %LOCALAPPDATA%\\QeukaoServer\\gui-error.log 并弹窗。"""
import os
import sys
import traceback

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())


def _report(text):
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "QeukaoServer", "gui-error.log")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        path = "(日志写入失败)"
    try:
        import tkinter
        from tkinter import messagebox
        r = tkinter.Tk()
        r.withdraw()
        messagebox.showerror("缺考上报服务端出错", "程序发生错误，详情已写入：\n%s\n\n%s" % (path, text.strip().splitlines()[-1]))
        r.destroy()
    except Exception:
        pass


try:
    import server_gui
    sys.exit(server_gui.main())
except SystemExit:
    raise
except BaseException:
    _report(traceback.format_exc())
    sys.exit(1)
