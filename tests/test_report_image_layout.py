import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "需要 node 才能跑前端纯函数检查")
class FrontendPureFunctionTests(unittest.TestCase):
    def run_node(self, name, env=None):
        done = subprocess.run(["node", str(ROOT / "tests" / name)], capture_output=True, text=True, timeout=120, env={**os.environ, **(env or {})})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a4_export_one_sheet_real_default_names(self):
        # 用 qk_config.default_room_name 生成真实的默认教室名（一教室…五百教室），导图每一档都必须完整画出每个名字（tests/report_image_layout.cjs）
        import qk_config
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "names.json"
            path.write_text(json.dumps([qk_config.default_room_name(i) for i in range(1, 501)], ensure_ascii=False), encoding="utf-8")
            self.run_node("report_image_layout.cjs", {"QK_ROOM_NAMES": str(path)})

    def test_charts_draw_all_data(self):
        # 图表不许静默截断：250 场考试、250 间教室都要画出来（tests/charts_all_data.cjs）
        self.run_node("charts_all_data.cjs")


if __name__ == "__main__":
    unittest.main()
