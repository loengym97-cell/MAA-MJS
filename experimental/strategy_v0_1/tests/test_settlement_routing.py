import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class SettlementRoutingTest(unittest.TestCase):
    def test_gift_page_after_settlement_is_reachable(self):
        for path in (
            ROOT / "resource/pipeline/策略by兔兔专属节点.json",
            ROOT / "experimental/strategy_v0_1/resource/pipeline/试验策略节点.json",
        ):
            nodes = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(path=path):
                self.assertIn("选择赠礼", nodes["试验版重置局状态"]["next"])

        for path in (
            ROOT / "resource/pipeline/策略by兔兔专属节点.json",
            ROOT / "experimental/strategy_v0_1/resource/pipeline/试验版覆盖.json",
        ):
            nodes = json.loads(path.read_text(encoding="utf-8"))
            for entry in ("策略by兔兔从主页开局", "策略by兔兔地图续打"):
                with self.subTest(path=path, entry=entry):
                    self.assertIn("选择赠礼", nodes[entry]["next"])

        gift = json.loads((ROOT / "resource/pipeline/选择赠礼.json").read_text(encoding="utf-8"))["选择赠礼"]
        roi = gift["recognition"]["param"]["roi"]
        # 14:35 的失败截图中，OCR 已在 [520,609,247,23] 读到赠礼页标题。
        self.assertTrue(roi[0] <= 520 and roi[1] <= 609 and roi[0] + roi[2] >= 767 and roi[1] + roi[3] >= 632)
        self.assertIn("动态选择赠礼", gift["next"])

    def test_saved_tutu_queue_has_settlement_route(self):
        for path in (ROOT / "config/instances").glob("*.json"):
            saved = json.loads(path.read_text(encoding="utf-8"))
            for task in saved.get("TaskItems", []):
                if "策略by兔兔" in task["name"]:
                    with self.subTest(instance=path.name, task=task["name"]):
                        nodes = task["pipeline_override"]
                        self.assertIn("结算确定", nodes["临时战斗"]["next"])
                        self.assertLess(nodes["临时战斗"]["next"].index("结算确定"), nodes["临时战斗"]["next"].index("兜底点击"))
                        self.assertEqual(nodes["结算确定"]["next"][0], "结算确定")

    def test_tutu_tasks_can_confirm_reward_screen(self):
        tasks = json.loads((ROOT / "interface.json").read_text(encoding="utf-8"))["task"]
        confirmation = json.loads((ROOT / "resource/pipeline/临时战斗.json").read_text(encoding="utf-8"))["结算确定"]
        battle = json.loads((ROOT / "resource/pipeline/临时战斗.json").read_text(encoding="utf-8"))
        strategy = json.loads((ROOT / "resource/pipeline/策略by兔兔专属节点.json").read_text(encoding="utf-8"))
        experimental = json.loads((ROOT / "experimental/strategy_v0_1/resource/pipeline/试验版覆盖.json").read_text(encoding="utf-8"))
        roi = confirmation["recognition"]["param"]["roi"]
        # 05:16:50 的 Maa OCR 日志：奖励页“确定”位于 [608,620,62,29]。
        self.assertTrue(roi[0] <= 608 and roi[1] <= 620 and roi[0] + roi[2] >= 670 and roi[1] + roi[3] >= 649)
        # 06:30 的失败页按钮位于约 [610,575,60,28]；旧 ROI 从 y=600 起，OCR 只读到“_”。
        self.assertTrue(roi[0] <= 610 and roi[1] <= 575 and roi[0] + roi[2] >= 670 and roi[1] + roi[3] >= 603)
        self.assertIn("结算确定", strategy["试验版常见界面巡检"]["next"])
        self.assertEqual(confirmation["next"][0], "结算确定")
        self.assertGreaterEqual(confirmation["post_delay"], 1500)
        self.assertNotIn("x", battle["兜底点击"]["action"]["param"]["custom_action_param"])
        for task in tasks:
            if "策略by兔兔" not in task["name"]:
                continue
            with self.subTest(task=task["name"]):
                override = task["pipeline_override"]
                self.assertIn("结算确定", override["临时战斗"]["next"])
                self.assertLess(override["临时战斗"]["next"].index("结算确定"), override["临时战斗"]["next"].index("兜底点击"))
                self.assertIn("结算确定", override["默认战斗"]["next"])
                self.assertIn("结算确定", override["点击空白"]["next"])
                self.assertIn("试验版重置局状态", override["结算确定"]["next"])
                self.assertEqual(override["结算确定"]["next"][0], "结算确定")
                entry = strategy[task["entry"]]
                self.assertIn("结算确定", entry["next"])
                self.assertIn("结算确定", experimental[task["entry"]]["next"])


if __name__ == "__main__":
    unittest.main()
