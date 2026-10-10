"""赠礼漏点时，在确认仍在原页面后最多尝试十次。"""

import runpy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "千里策略试验版.py"
NAMESPACE = runpy.run_path(str(SCRIPT))
TrialGift = NAMESPACE["TrialGift"]
TrialState = NAMESPACE["TrialState"]


def result(text, box):
    return SimpleNamespace(text=text, box=box)


class GiftClickRetryTest(unittest.TestCase):
    def run_scenario(self, *, open_on=1, choose_on=1):
        state = {"page": "offer", "open_clicks": 0, "choice_clicks": 0}
        offer = [
            result("曹操赠礼", (233, 516, 88, 28)),
            result("请选择接受谁的赠礼？", (498, 609, 270, 24)),
        ]
        detail = [
            result("孟德赠礼", (610, 113, 128, 30)),
            result("信物", (559, 183, 49, 28)),
            result("驰援", (559, 436, 49, 27)),
        ]
        game_map = [result("当前挑战：3层", (124, 180, 162, 26))]

        def click(_context, box):
            if box[0] == 233:
                state["open_clicks"] += 1
                if state["open_clicks"] >= open_on:
                    state["page"] = "detail"
            elif box[0] == 559:
                state["choice_clicks"] += 1
                if state["choice_clicks"] >= choose_on:
                    state["page"] = "map"

        globals_ = TrialGift.run.__globals__
        with patch.dict(globals_, {
            "_screen": lambda _context: state["page"],
            "_ocr": lambda _context, image, roi=None: {
                "offer": offer, "detail": detail, "map": game_map,
            }[image],
            "_click": click,
            "time": SimpleNamespace(sleep=lambda _: None),
        }):
            succeeded = TrialGift(TrialState(catalog={"曹操": "孟德新书"})).run(object(), {})
        return succeeded, state

    def test_retries_unchanged_detail_then_succeeds(self):
        succeeded, state = self.run_scenario(choose_on=3)
        self.assertTrue(succeeded)
        self.assertEqual(state["choice_clicks"], 3)

    def test_retries_unopened_character_then_succeeds(self):
        succeeded, state = self.run_scenario(open_on=3)
        self.assertTrue(succeeded)
        self.assertEqual(state["open_clicks"], 3)

    def test_stops_after_ten_choice_attempts(self):
        succeeded, state = self.run_scenario(choose_on=11)
        self.assertFalse(succeeded)
        self.assertEqual(state["choice_clicks"], 10)


if __name__ == "__main__":
    unittest.main()
