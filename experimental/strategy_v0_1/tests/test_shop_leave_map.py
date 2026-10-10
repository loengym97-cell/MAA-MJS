"""复现 10:22 已返回地图、但旧的“休息”局部 OCR 漏判。"""

import runpy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "千里策略试验版.py"
NAMESPACE = runpy.run_path(str(SCRIPT))
TrialShop = NAMESPACE["TrialShop"]
TrialState = NAMESPACE["TrialState"]


def result(text, box):
    return SimpleNamespace(text=text, box=box)


class ShopLeaveMapTest(unittest.TestCase):
    def run_scenario(self, *, reaches_map):
        state = {"page": "shop", "clicks": []}
        shop = [
            result("巴清小铺子", (210, 65, 220, 35)),
            result("信物专区", (856, 117, 115, 25)),
        ]
        confirm = shop + [result("确认", (512, 444, 56, 29))]
        map_results = [
            result("千里单骑·无尽70", (48, 54, 221, 22)),
            result("当前挑战：14层", (124, 180, 162, 26)),
            result("休息", (920, 161, 54, 19)),
            result("武将", (1017, 160, 35, 23)),
            result("结束挑战", (1037, 567, 101, 23)),
        ]

        def screen(_context):
            return state["page"]

        def ocr(_context, image, roi=(0, 0, 1280, 720)):
            source = {"shop": shop, "confirm": confirm, "map": map_results}[image]
            # 10:22:40–43 的真实日志：局部 ROI 连续八次只识别到“武将”，
            # 即使地图全屏 OCR 能识别“当前挑战”和“结束挑战”。
            if image == "map" and roi == (850, 100, 210, 160):
                return [map_results[3]]
            x0, y0, width, height = roi
            return [r for r in source if x0 <= r.box[0] < x0 + width and y0 <= r.box[1] < y0 + height]

        def click_point(_context, x, y):
            state["clicks"].append((x, y))
            state["page"] = "confirm"

        def click(_context, box):
            state["clicks"].append(box)
            state["page"] = "map" if reaches_map else "shop"

        globals_ = TrialShop.run.__globals__
        with patch.dict(globals_, {
            "_screen": screen, "_ocr": ocr, "_click": click,
            "_click_point": click_point, "time": SimpleNamespace(sleep=lambda _: None),
        }):
            succeeded = TrialShop(TrialState(catalog={}))._leave(object())
        return succeeded, state

    def test_accepts_map_without_rest_in_old_right_hand_roi(self):
        succeeded, state = self.run_scenario(reaches_map=True)
        self.assertTrue(succeeded)
        self.assertEqual(state["page"], "map")
        self.assertEqual(state["clicks"], [(1215, 97), (512, 444, 56, 29)])

    def test_does_not_claim_success_if_shop_remains_open(self):
        succeeded, state = self.run_scenario(reaches_map=False)
        self.assertFalse(succeeded)
        self.assertEqual(state["page"], "shop")


if __name__ == "__main__":
    unittest.main()
