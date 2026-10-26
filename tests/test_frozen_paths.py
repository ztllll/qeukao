"""打包成 PyInstaller 单文件 exe（sys.frozen）后的路径约定。

onefile 下 __file__ 指向每次启动都会被删除的临时解压目录（sys._MEIPASS）：
- 只读资源（static/）在 _MEIPASS 里；
- 可写数据（data/ 数据库与配置、backups/、client/dist/ 模板）必须落在 exe 所在目录，否则退出即丢。
用例把模块复制进一个伪 _MEIPASS 临时目录并在子进程里伪造 sys.frozen：即使实现回退，也只会写进临时目录，不会污染仓库。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = ("app.py", "qk_config.py", "qk_dbtools.py", "qk_agents.py")

SCRIPT = r'''
import json, sys
sys.frozen = True
sys._MEIPASS = {meipass!r}
sys.executable = {exe!r}
sys.path.insert(0, {meipass!r})
import qk_config
import app
import qk_dbtools
print(json.dumps({{
    "data": str(qk_config.DATA_DIR),
    "db": str(qk_config.DB_PATH),
    "static": str(app.STATIC_DIR),
    "backups": str(qk_dbtools._backup_dir()),
    "template": str(__import__("qk_agents").client_template_path()),
}}))
'''


class FrozenPathsTest(unittest.TestCase):
    def test_data_next_to_exe_static_from_bundle(self):
        with tempfile.TemporaryDirectory(prefix="qk-frozen-") as tmp:
            meipass = Path(tmp) / "_MEI123"
            exe_dir = Path(tmp) / "install"
            meipass.mkdir()
            exe_dir.mkdir()
            for name in MODULES:
                shutil.copy2(ROOT / name, meipass / name)
            exe = exe_dir / "QeukaoServer.exe"
            exe.write_bytes(b"")
            bundled = meipass / "client" / "dist"
            bundled.mkdir(parents=True)
            (bundled / "qeukao-client-template.exe").write_bytes(b"MZ")  # --add-data 带进包里的客户端模板
            out = subprocess.run(
                [sys.executable, "-c", SCRIPT.format(meipass=str(meipass), exe=str(exe))],
                capture_output=True, text=True, timeout=60,
                env={"PATH": "/usr/bin:/bin"},  # 不带 QEUKAO_DATA_DIR / QEUKAO_DB
                cwd=tmp,
            )
            self.assertEqual(out.returncode, 0, out.stderr[-800:])
            got = json.loads(out.stdout.strip().splitlines()[-1])
            self.assertEqual(got["data"], str(exe_dir / "data"))
            self.assertEqual(got["db"], str(exe_dir / "data" / "qeukao.sqlite3"))
            self.assertEqual(got["backups"], str(exe_dir / "backups"))
            self.assertEqual(got["static"], str(meipass / "static"))
            self.assertTrue((exe_dir / "data" / "config.json").is_file(), "配置应写到 exe 旁而不是临时目录")
            self.assertFalse((meipass / "data").exists(), "临时解压目录里不应出现 data/")
            self.assertEqual(got["template"], str(bundled / "qeukao-client-template.exe"), "exe 旁没有模板时应回退到包内的模板")


if __name__ == "__main__":
    unittest.main()