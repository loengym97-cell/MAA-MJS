"""回放实际日志中转盘按钮的 OCR 结果，检查识别和续打入口。"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class DogWheelTest(unittest.TestCase):
    def test_recognizes_observed_button_and_waits_ten_seconds(self):
        pipeline = json.loads((ROOT / "resource/pipeline/继续挑战.json").read_text(encoding="utf-8"))
        node = pipeline["停止转动"]
        for text in ("停止转动", "亭止转动"):
            self.assertTrue(any(re.search(pattern, text) for pattern in node["recognition"]["param"]["expected"]), text)
        self.assertEqual(node["pre_delay"], 10000)

    def test_resume_and_audit_can_reach_wheel(self):
        interface = json.loads((ROOT / "interface.json").read_text(encoding="utf-8"))
        nodes = json.loads((ROOT / "resource/pipeline/策略by兔兔专属节点.json").read_text(encoding="utf-8"))
        self.assertIn("停止转动", nodes["策略by兔兔地图续打"]["next"])
        self.assertIn("停止转动", nodes["试验版常见界面巡检"]["next"])
        for task in interface["task"]:
            if "策略by兔兔" in task["name"]:
                self.assertIn("停止转动", task["pipeline_override"]["继续战斗"]["on_error"])


if __name__ == "__main__":
    unittest.main()
