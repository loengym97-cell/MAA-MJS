"""赠礼入口点击后，黑屏转场不能被当作没有可选赠礼。"""

import runpy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "千里策略试验版.py"
NAMESPACE = runpy.run_path(str(SCRIPT))
TrialGift = NAMESPACE["TrialGift"]
TrialState = NAMESPACE["TrialState"]


def result(text, box=(500, 300, 80, 25)):
    return SimpleNamespace(text=text, box=box)


class GiftTransitionTest(unittest.TestCase):
    def run_with_frames(self, frames):
        frames = iter(frames)
        clicks = []
        source = [
            result("曹操赠礼", (233, 516, 88, 28)),
            result("请选择接受谁的赠礼？", (498, 609, 270, 24)),
        ]
        details = [
            result("信物", (570, 180, 65, 30)),
            result("并肩作战", (570, 325, 130, 30)),
            result("驰援", (570, 470, 65, 30)),
        ]
        observed = {
            "source": source,
            "transition": [],
            "partial": details[:1],
            "details": details,
            "map": [result("休息", (916, 152, 51, 34))],
        }
        globals_ = TrialGift.run.__globals__
        with patch.dict(
            globals_,
            {
                "_screen": lambda _context: next(frames, "map"),
                "_ocr": lambda _context, image, roi=None: observed[image],
                "_click": lambda _context, box: clicks.append(box),
                "time": SimpleNamespace(sleep=lambda _seconds: None),
            },
        ):
            action = TrialGift(TrialState(catalog={"曹操": "孟德新书"}))
            succeeded = action.run(object(), {})
        return succeeded, clicks

    def test_waits_through_black_transition_before_selecting(self):
        succeeded, clicks = self.run_with_frames(
            ["source", "transition", "partial", "details", "details", "map", "map", "map"]
        )
        self.assertTrue(succeeded)
        self.assertEqual(clicks, [(233, 516, 88, 28), (570, 470, 65, 30)])

    def test_stays_safe_if_detail_never_appears(self):
        succeeded, clicks = self.run_with_frames(["source"] + ["transition"] * 30)
        self.assertFalse(succeeded)
        self.assertEqual(clicks, [(233, 516, 88, 28)])

    def test_waits_through_black_transition_after_selecting(self):
        succeeded, clicks = self.run_with_frames(
            ["source", "details", "details"] + ["transition"] * 7 + ["map"]
        )
        self.assertTrue(succeeded)
        self.assertEqual(len(clicks), 2)

    def test_waits_for_selection_animation_to_clear(self):
        succeeded, clicks = self.run_with_frames(
            ["source", "details", "details", "details", "details", "transition", "map", "map"]
        )
        self.assertTrue(succeeded)
        self.assertEqual(len(clicks), 2)


if __name__ == "__main__":
    unittest.main()
