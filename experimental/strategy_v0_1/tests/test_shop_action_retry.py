"""商店可逆点击最多十次；付款只有原弹窗和原余额稳定时才重试。"""

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


class ShopActionRetryTest(unittest.TestCase):
    def run_buy(self, *, open_on=1, buy_on=1, lose_wallet_after_buy=False):
        state = {"page": "shop", "wallet": 100, "opens": 0, "buys": 0}
        card = result("行囊", (673, 165, 49, 25))

        def screen(_context):
            return state["page"]

        def ocr(_context, image, roi=None):
            if lose_wallet_after_buy and state["buys"]:
                if roi == (1000, 0, 250, 150):
                    return []
            shop = [
                result("巴清小铺子", (210, 66, 223, 35)),
                result("信物专区", (856, 117, 115, 25)),
                card,
                result(str(state["wallet"]), (1136, 77, 24, 20)),
            ]
            popup = shop + [
                result("购买", (609, 177, 60, 25)),
                result("背包格数+1。", (541, 250, 109, 30)),
                result("30购买", (478, 483, 86, 27)),
                result("取消", (744, 481, 58, 29)),
            ]
            return popup if image == "popup" else shop

        def click(_context, box):
            if box[0] == 673:
                state["opens"] += 1
                if state["opens"] >= open_on:
                    state["page"] = "popup"
            elif box[0] == 478:
                state["buys"] += 1
                if state["buys"] >= buy_on:
                    state["wallet"] = 70
                    state["page"] = "shop"

        globals_ = TrialShop.run.__globals__
        with patch.dict(globals_, {
            "_screen": screen, "_ocr": ocr, "_click": click,
            "time": SimpleNamespace(sleep=lambda _: None),
        }):
            succeeded = TrialShop(TrialState(catalog={}))._buy(object(), card, "行囊")
        return succeeded, state

    def test_retries_opening_product_and_guarded_payment(self):
        succeeded, state = self.run_buy(open_on=3, buy_on=3)
        self.assertTrue(succeeded)
        self.assertEqual((state["opens"], state["buys"]), (3, 3))

    def test_does_not_repeat_payment_without_wallet_reading(self):
        succeeded, state = self.run_buy(buy_on=11, lose_wallet_after_buy=True)
        self.assertFalse(succeeded)
        self.assertEqual(state["buys"], 1)

    def test_retries_shop_exit_and_confirmation(self):
        state = {"page": "shop", "back": 0, "confirm": 0}

        def ocr(_context, image, roi=None):
            return {
                "shop": [result("巴清小铺子", (210, 66, 223, 35)), result("信物专区", (856, 117, 115, 25))],
                "confirm": [result("确认", (512, 444, 56, 29))],
                "map": [result("当前挑战：14层", (124, 180, 162, 26)), result("结束挑战", (1037, 567, 101, 23))],
            }[image]

        def click_point(_context, x, y):
            state["back"] += 1
            if state["back"] >= 2:
                state["page"] = "confirm"

        def click(_context, box):
            state["confirm"] += 1
            if state["confirm"] >= 2:
                state["page"] = "map"

        globals_ = TrialShop.run.__globals__
        with patch.dict(globals_, {
            "_screen": lambda _context: state["page"],
            "_ocr": ocr, "_click": click, "_click_point": click_point,
            "time": SimpleNamespace(sleep=lambda _: None),
        }):
            succeeded = TrialShop(TrialState(catalog={}))._leave(object())
        self.assertTrue(succeeded)
        self.assertEqual((state["back"], state["confirm"]), (2, 2))


if __name__ == "__main__":
    unittest.main()
