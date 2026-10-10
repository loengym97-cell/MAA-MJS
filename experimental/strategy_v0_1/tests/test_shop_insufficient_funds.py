"""余额不足时取消购买弹窗，不能连点到背后的武将牌。"""

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


class ShopInsufficientFundsTest(unittest.TestCase):
    def test_cancel_waits_for_popup_to_close_before_returning(self):
        state = {"page": "shop", "transition_frames": 0, "cancel_clicks": 0, "card_opened": False}
        shop = [
            result("巴清小铺子", (210, 65, 220, 35)),
            result("信物专区", (856, 117, 115, 25)),
            result("行囊", (673, 165, 48, 26)),
        ]
        popup = shop + [
            result("购买", (609, 177, 60, 25)),
            result("背包格数+1。", (541, 250, 109, 30)),
            result("15", (1136, 77, 24, 20)),
            result("30购买", (478, 483, 86, 27)),
            result("取消", (744, 481, 58, 29)),
        ]

        def screen(_context):
            if state["transition_frames"]:
                state["transition_frames"] -= 1
                return "popup"
            return state["page"]

        def ocr(_context, image, roi=None):
            return {
                "shop": shop,
                "popup": popup,
                "map": [
                    result("千里单骑·无尽70", (48, 54, 221, 22)),
                    result("当前挑战：14层", (124, 180, 162, 26)),
                    result("结束挑战", (1037, 567, 101, 23)),
                ],
            }[image]

        def click(_context, box):
            x, y, _, _ = box
            if x == 673:
                state["page"] = "popup"
            elif x == 744:
                state["cancel_clicks"] += 1
                if state["cancel_clicks"] == 1:
                    state["page"] = "shop"
                    state["transition_frames"] = 2
                else:
                    state["page"] = "popup"
                    state["card_opened"] = True

        def click_point(_context, x, y):
            if (x, y) == (1215, 97) and state["page"] == "shop":
                state["page"] = "map"

        globals_ = TrialShop.run.__globals__
        with patch.dict(globals_, {
            "_screen": screen, "_ocr": ocr, "_click": click,
            "_click_point": click_point, "time": SimpleNamespace(sleep=lambda _: None),
        }):
            succeeded = TrialShop(TrialState(catalog={}, max_relic_per_shop=0)).run(object(), {})

        self.assertTrue(succeeded)
        self.assertEqual(state["cancel_clicks"], 1)
        self.assertFalse(state["card_opened"])
        self.assertEqual(state["page"], "map")


if __name__ == "__main__":
    unittest.main()
