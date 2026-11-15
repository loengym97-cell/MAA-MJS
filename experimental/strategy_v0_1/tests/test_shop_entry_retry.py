"""地图商人漏点时，只在仍能确认地图商人时重试最多十次。"""

import runpy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = Path(__file__).resolve().parents[1] / "千里策略试验版.py"
NAMESPACE = runpy.run_path(str(SCRIPT))
TrialShop = NAMESPACE["TrialShop"]
TrialState = NAMESPACE["TrialState"]


def result(text, box=(0, 0, 30, 20)):
    return SimpleNamespace(text=text, box=box)


class FakeContext:
    def __init__(self, merchant_visible=True):
        self.merchant_visible = merchant_visible
        self.template_calls = []

    def run_recognition_direct(self, reco_type, param, image):
        self.template_calls.append((reco_type, param.template, image))
        found = self.merchant_visible and param.template == ["吕不韦.png"]
        return SimpleNamespace(
            hit=found,
            best_result=SimpleNamespace(box=(716, 474, 41, 33), score=0.98) if found else None,
        )


class ShopEntryRetryTest(unittest.TestCase):
    def run_scenario(
        self, *, starts_in_shop=False, merchant_visible=True, map_visible=True,
        retry_click_works=True, shop_visible_after_polls=None,
    ):
        state = {"entered": starts_in_shop, "clicks": [], "polls": 0}
        context = FakeContext(merchant_visible)

        def screen(_context):
            state["polls"] += 1
            arrived = shop_visible_after_polls is not None and state["polls"] >= shop_visible_after_polls
            return "shop" if state["entered"] or arrived else "map"

        def ocr(_context, image, roi=None):
            if image == "shop":
                return [result("吕不韦小铺子"), result("信物专区")]
            return [result("当前挑战：3层")] if map_visible else []

        def click(_context, box):
            state["clicks"].append(box)
            state["entered"] = retry_click_works

        globals_ = TrialShop.run.__globals__
        with patch.dict(
            globals_,
            {"_screen": screen, "_ocr": ocr, "_click": click, "time": SimpleNamespace(sleep=lambda _: None)},
        ), patch.object(TrialShop, "_leave", return_value=True):
            succeeded = TrialShop(TrialState(catalog={}, max_relic_per_shop=0)).run(context, {})
        return succeeded, state["clicks"], context.template_calls

    def test_retries_once_when_first_click_left_map_unchanged(self):
        succeeded, clicks, template_calls = self.run_scenario()
        self.assertTrue(succeeded)
        self.assertEqual(clicks, [(716, 474, 41, 33)])
        self.assertTrue(template_calls)

    def test_waits_for_slow_shop_transition_before_retrying(self):
        succeeded, clicks, _ = self.run_scenario(shop_visible_after_polls=5)
        self.assertTrue(succeeded)
        self.assertEqual(clicks, [])

    def test_task_entries_can_resume_open_shop(self):
        for path in (
            ROOT / "resource/pipeline/策略by兔兔专属节点.json",
            ROOT / "experimental/strategy_v0_1/resource/pipeline/试验版覆盖.json",
        ):
            nodes = json.loads(path.read_text(encoding="utf-8"))
            for entry in ("策略by兔兔从主页开局", "策略by兔兔地图续打"):
                with self.subTest(path=path, entry=entry):
                    self.assertIn("试验版商店页面", nodes[entry]["next"])

    def test_does_not_click_again_if_shop_is_already_open(self):
        succeeded, clicks, _ = self.run_scenario(starts_in_shop=True)
        self.assertTrue(succeeded)
        self.assertEqual(clicks, [])

    def test_stops_after_ten_retries_if_shop_still_does_not_open(self):
        succeeded, clicks, _ = self.run_scenario(retry_click_works=False)
        self.assertFalse(succeeded)
        self.assertEqual(clicks, [(716, 474, 41, 33)] * 10)

    def test_does_not_retry_without_confirmed_map_and_merchant(self):
        for kwargs in ({"merchant_visible": False}, {"map_visible": False}):
            with self.subTest(kwargs=kwargs):
                succeeded, clicks, _ = self.run_scenario(**kwargs)
                self.assertFalse(succeeded)
                self.assertEqual(clicks, [])


if __name__ == "__main__":
    unittest.main()
