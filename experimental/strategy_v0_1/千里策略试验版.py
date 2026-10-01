"""千里走单骑「策略by兔兔」（v1.4.2 正式版）。

在主界面中与原策略共存；选择专用资源时叠加本目录的策略节点。
目录名和节点名保留「试验版」仅为兼容既有入口。
默认只打印计划；加 --run 才会连接安卓设备并操作游戏。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from maa.controller import AdbController
from maa.custom_action import CustomAction
from maa.agent_client import AgentClient
from maa.pipeline import JOCR, JRecognitionType, JTemplateMatch
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit


# PDF《千里单骑自动化策略》1.3 节的核心档位，加上用户指定的弃牌流信物。
# 章邯、子婴暂不在旧 XLSX 中；新版信物名称按用户提供的对应关系补入。
DISCARD_RELICS = {"龙且": "将印", "章邯": "衔枚", "子婴": "传国玺"}
# 发布包不携带用户提供的 XLSX；这些运行必需的信物名随策略代码提供。
# 本地若有原表，load_catalog 仍会读取完整表并覆盖对应名称。
BUNDLED_RELICS = {
    "龙且": "将印", "章邯": "衔枚", "子婴": "传国玺",
    "十常侍": "西园帐薄", "吕布": "飞将翎", "关羽": "纱锦囊",
    "周勃": "薄曲", "萧何": "九章律", "马超": "出手法",
    "贾诩": "雷震鼓", "王异": "麻衣", "刘表": "典籍",
    "甘宁": "铃铛", "刘邦": "白蛇皮", "许褚": "牛尾",
    "张春华": "簪刀", "司马懿": "龟甲", "孙策": "调兵符",
    "范增": "玉珏", "刘禅": "金蝉", "鲁肃": "箭盾",
    "曹丕": "典论", "虞姬": "美人草",
    "霍去病": "祭天金人", "李广": "大黄", "刘彻": "五铢钱",
}
# 新增人物中，只有用户明确给权重的信物参与主动购买。
ADDED_GENERAL_RELIC_SCORE = {
    "刘彻": 1, "卫青": 0, "霍去病": 2, "李广": 3,
    "董仲舒": 0, "张骞": 0, "陈阿娇": 0, "卫子夫": 0,
    "孙权": 0,
}
ADDED_GENERAL_STYLES = {
    "刘彻": "受伤减免", "卫青": "坐骑杀", "霍去病": "技能成长",
    "李广": "出杀连击", "董仲舒": "战法牌加伤", "张骞": "手牌交换",
    "陈阿娇": "复制", "卫子夫": "武将牌复制", "孙权": "张骞驰援组合",
}
RELIC_SCORE = {
    **{name: 4 for name in DISCARD_RELICS},
    "十常侍": 4, "吕布": 4,
    "关羽": 4, "周勃": 4, "萧何": 4,
    "马超": 3, "贾诩": 3, "王异": 3, "刘表": 3,
    "甘宁": 3, "刘邦": 3, "许褚": 3,
    "张春华": 3, "司马懿": 3, "孙策": 3,
    **ADDED_GENERAL_RELIC_SCORE,
}
SUPPORT_SCORE = {
    "范增": 4, "龙且": 4, "刘禅": 4, "马超": 4,
    "萧何": 3, "鲁肃": 3, "曹丕": 3, "周勃": 3, "虞姬": 3,
    # 张骞＋孙权、刘彻＋周勃互相配合；先拿到其中一人才能凑齐组合。
    "张骞": 3, "孙权": 3, "刘彻": 3, "卫子夫": 3,
}
FUNDING_SCORE = {"刘彻": 2, "陈阿娇": 2, "卫子夫": 2, "霍去病": 2}
RELIC_ALIASES = {
    "十常侍": ("西园帐薄", "西园账簿", "西园帐簿", "西园账薄"),
}
GENERAL_ALIASES = {"甄宓": "甄姬", "子桓": "曹丕", "公嗣": "刘禅"}
GIFT_ROI = (150, 490, 1000, 190)
GIFT_DETAIL_ROI = (380, 120, 540, 455)
GIFT_KINDS = ("信物", "驰援", "资助", "武将牌", "并肩作战")
RETRY_LIMIT = 10
ACTION_WAIT_SECONDS = 1.0


def clean(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"[《》〈〉\s·•:：。.,，]", "", value)


def general_name(value: str, catalog: dict[str, str]) -> str | None:
    text = clean(value)
    if text.endswith("赠礼"):
        name = text.removesuffix("赠礼")
        if re.fullmatch(r"[\u4e00-\u9fff]{1,6}", name):
            return GENERAL_ALIASES.get(name, name)
    if text in catalog:
        return GENERAL_ALIASES.get(text, text)
    return None


def load_catalog() -> dict[str, str]:
    source = ROOT / "西楚版本无尽千里全赠礼全事件.xlsx"
    mapping = dict(BUNDLED_RELICS)
    if not source.is_file():
        print("[试验版] 未找到原 XLSX，使用内置高分信物映射")
        return mapping
    from openpyxl import load_workbook

    book = load_workbook(source, read_only=True, data_only=True)
    try:
        sheet = book["千里信物"]
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if len(row) < 3 or not row[1] or not row[2]:
                continue
            name, relic = clean(row[1]), clean(row[2])
            if name and relic and not relic.startswith("=DISPIMG"):
                mapping[name] = relic
        for name, relic in DISCARD_RELICS.items():
            mapping.setdefault(name, relic)
        return mapping
    finally:
        book.close()


def rank_people(names: list[str], owned_relics: set[str], owned_supports: set[str]) -> list[str]:
    """按可获得的最高价值排序，同分时优先未持有的高分信物。"""
    return sorted(
        names,
        key=lambda name: (
            max(0 if name in owned_supports else SUPPORT_SCORE.get(name, 0),
                0 if name in owned_relics else RELIC_SCORE.get(name, 0),
                FUNDING_SCORE.get(name, 0)),
            0 if name in owned_relics else RELIC_SCORE.get(name, 0),
            0 if name in owned_supports else SUPPORT_SCORE.get(name, 0),
            FUNDING_SCORE.get(name, 0),
        ),
        reverse=True,
    )


def choose_gift_kind(name: str, available: set[str], owned_relics: set[str],
                     owned_supports: set[str] | None = None) -> str | None:
    if owned_supports is None:
        owned_supports = set()
    relic = 0 if name in owned_relics else RELIC_SCORE.get(name, 0)
    support = 0 if name in owned_supports else SUPPORT_SCORE.get(name, 0)
    if "信物" in available and relic >= 3 and relic >= support:
        return "信物"
    if "驰援" in available and support >= 3:
        return "驰援"
    if "信物" in available and relic >= 3:
        return "信物"
    if "资助" in available and FUNDING_SCORE.get(name, 0):
        return "资助"
    if "信物" in available and relic >= 2:
        return "信物"
    # 非目标武将也要完成强制选礼；优先不占信物格子的收益。
    fallback = ("资助", "并肩作战", "武将牌", "信物", "驰援") if name in owned_supports else (
        "驰援", "资助", "并肩作战", "武将牌", "信物"
    )
    for kind in fallback:
        if kind in available:
            return kind
    return None


def ranked_shop_relics(catalog: dict[str, str], owned: set[str]) -> list[tuple[int, str, str]]:
    return sorted(
        (
            (score, name, relic)
            for name, score in RELIC_SCORE.items()
            if score >= 3 and catalog.get(name) and name not in owned
            for relic in (catalog[name],)
        ),
        key=lambda item: (-item[0], item[1]),
    )


def check_policy(catalog):
    assert general_name("萧何赠礼", catalog) == "萧何"
    assert general_name("甄宓赠礼", catalog) == "甄姬"
    assert general_name("董仲舒赠礼", catalog) == "董仲舒"
    assert general_name("子桓赠礼", catalog) == "曹丕"
    assert choose_gift_kind("萧何", {"信物", "驰援"}, set()) == "信物"
    assert choose_gift_kind("萧何", {"信物", "驰援"}, {"萧何"}) == "驰援"
    assert choose_gift_kind("项羽", {"信物"}, set()) == "信物"
    assert choose_gift_kind("刘禅", {"信物"}, set(), {"刘禅"}) == "信物"
    assert choose_gift_kind("刘彻", {"信物", "资助"}, set()) == "资助"
    assert choose_gift_kind("刘彻", {"驰援", "资助"}, set()) == "驰援"
    assert choose_gift_kind("刘彻", {"驰援", "资助"}, set(), {"刘彻"}) == "资助"
    assert choose_gift_kind("李广", {"信物", "资助"}, set()) == "信物"
    assert choose_gift_kind("张骞", {"驰援", "信物"}, set()) == "驰援"
    assert choose_gift_kind("孙权", {"驰援", "信物"}, set()) == "驰援"
    assert choose_gift_kind("陈阿娇", {"驰援", "资助"}, set()) == "资助"
    assert choose_gift_kind("卫子夫", {"驰援", "资助"}, set()) == "驰援"
    assert choose_gift_kind("霍去病", {"信物", "资助"}, set()) == "资助"
    assert choose_gift_kind("霍去病", {"信物", "驰援"}, set()) == "信物"
    assert catalog["十常侍"] == "西园帐薄"
    assert catalog["吕布"] == "飞将翎"
    assert catalog["霍去病"] == "祭天金人"
    assert catalog["李广"] == "大黄"
    assert catalog["刘彻"] == "五铢钱"


@dataclass
class TrialState:
    catalog: dict[str, str]
    owned_relics: set[str] = field(default_factory=set)
    owned_supports: set[str] = field(default_factory=set)
    min_shop_score: int = 3
    max_relic_per_shop: int = 2


def _screen(context):
    job = context.tasker.controller.post_screencap().wait()
    if not job.succeeded:
        raise RuntimeError("截图失败")
    return context.tasker.controller.cached_image


def _ocr(context, image, roi=(0, 0, 1280, 720)):
    detail = context.run_recognition_direct(
        JRecognitionType.OCR, JOCR(roi=roi, expected=[]), image
    )
    return list(detail.all_results) if detail else []


def _find(results, word, *, x_min=0, x_max=1280, y_min=0, y_max=720):
    wanted = clean(word)
    for result in results:
        x, y, _, _ = result.box
        if x_min <= x <= x_max and y_min <= y <= y_max and clean(result.text) == wanted:
            return result
    return None


def _has(results, word):
    wanted = clean(word)
    return any(wanted in clean(result.text) for result in results)


def _click(context, box):
    x, y, width, height = box
    job = context.tasker.controller.post_click(x + width // 2, y + height // 2).wait()
    if not job.succeeded:
        raise RuntimeError(f"点击失败：{box}")


def _click_point(context, x, y):
    if not context.tasker.controller.post_click(x, y).wait().succeeded:
        raise RuntimeError(f"点击失败：({x},{y})")


def _number_near(results, *, x_min, x_max, y_min, y_max):
    numbers = []
    for result in results:
        x, y, _, _ = result.box
        if x_min <= x <= x_max and y_min <= y <= y_max:
            for raw in re.findall(r"\d{1,5}", clean(result.text)):
                numbers.append(int(raw))
    return numbers


class TrialReset(CustomAction):
    def __init__(self, state):
        super().__init__()
        self.state = state

    def run(self, context, argv):
        self.state.owned_relics.clear()
        self.state.owned_supports.clear()
        print("[试验版] 新一局：重置信物和驰援记录")
        return True


class TrialDismissStats(CustomAction):
    """只在识别到武将属性浮层时，点击地图下方空白区并确认已关闭。"""

    def run(self, context, argv):
        roi = (530, 105, 680, 95)
        for attempt in range(RETRY_LIMIT):
            results = _ocr(context, _screen(context), roi)
            if not (_has(results, "武将技能") or _has(results, "武将信息")):
                return True
            print(f"[试验版] 关闭武将属性浮层，第 {attempt + 1}/{RETRY_LIMIT} 次")
            _click_point(context, 640, 650)
            time.sleep(ACTION_WAIT_SECONDS)
        results = _ocr(context, _screen(context), roi)
        if _has(results, "武将技能") or _has(results, "武将信息"):
            print("[试验版] 武将属性浮层连续 10 次未关闭，停止任务")
            return False
        return True


class TrialOpenRun(CustomAction):
    """开局卡片没有打开选将时重试；仅在确认仍是开局页时补点。"""

    @staticmethod
    def _still_on_start_page(context, image):
        detail = context.run_recognition_direct(
            JRecognitionType.TemplateMatch,
            JTemplateMatch(
                template=["开始挑战.png"],
                roi=(1001, 573, 224, 86),
                threshold=[0.75],
            ),
            image,
        )
        return bool(detail and detail.hit)

    def run(self, context, argv):
        points = ((1109, 397), (1110, 440), (1085, 360))
        for attempt in range(RETRY_LIMIT):
            image = _screen(context)
            # 选将页可能仍显示其他“开始挑战”文字，先查目标页面。
            if _has(_ocr(context, image, (100, 506, 1107, 173)), "吕布"):
                print("[试验版] 已进入选将，停止补点开局卡片")
                return True
            if not self._still_on_start_page(context, image):
                print("[试验版] 已离开开局页，交给后续节点")
                return True
            x, y = points[attempt % len(points)]
            print(f"[试验版] 开局卡片未生效，第 {attempt + 1}/{RETRY_LIMIT} 次补点（{x},{y}）")
            _click_point(context, x, y)
            time.sleep(ACTION_WAIT_SECONDS)
        image = _screen(context)
        if _has(_ocr(context, image, (100, 506, 1107, 173)), "吕布") or not self._still_on_start_page(context, image):
            return True
        print("[试验版] 开局卡片连续 10 次未生效，停止任务")
        return False


class TrialScreenAudit(CustomAction):
    """关键节点即将超时时，限时辨认常见页面，不盲点屏幕。"""

    def run(self, context, argv):
        page_markers = (
            ("赠礼详情", "一项赠礼"),
            ("赠礼选人", "接受谁的"),
            ("属性浮层", "武将技能"),
            ("属性浮层", "武将信息"),
            ("商店", "信物专区"),
            ("领取奖励", "领取奖励"),
            ("结算", "点击空白"),
            ("结算", "下一步"),
            ("战斗入口", "开始对局"),
            ("战斗托管", "托管中"),
            ("地图", "当前挑战"),
            ("千里开局", "选择开始挑战"),
            ("确认页", "确认"),
        )
        last_text = []
        for attempt in range(RETRY_LIMIT):
            results = _ocr(context, _screen(context))
            last_text = [r.text for r in results[:15]]
            for page, marker in page_markers:
                if _has(results, marker):
                    print(f"[试验版] 常见界面巡检：第 {attempt + 1} 次识别到{page}（{marker}），交给对应节点")
                    return True
            if results:
                print(f"[试验版] 常见界面巡检：未归类文字界面，继续逐项识别；文字：{last_text}")
                return True
            if attempt < RETRY_LIMIT - 1:
                time.sleep(ACTION_WAIT_SECONDS)
        print(f"[试验版] 常见界面巡检 10 次仍未识别，停止任务；最后文字：{last_text}")
        return False


class TrialGift(CustomAction):
    def __init__(self, state, detail_only=False):
        super().__init__()
        self.state = state
        self.detail_only = detail_only

    def _wait_detail_options(self, context, name):
        """等待人物详情完成转场；连续两帧识别到同一组选项才点击。"""
        previous = set()
        last_text = []
        for attempt in range(12):
            options = _ocr(context, _screen(context), GIFT_DETAIL_ROI)
            available = {kind for kind in GIFT_KINDS if _find(options, kind)}
            if available and available == previous:
                return options, available
            previous = available
            if options:
                last_text = [result.text for result in options]
            if attempt < 11:
                time.sleep(ACTION_WAIT_SECONDS)
        print(f"[试验版] {name} 赠礼详情等待超时，最后识别：{last_text}")
        return None, set()

    def _handle_direct_detail(self, context):
        """地图节点可能直接打开赠礼详情，不经过选武将列表。"""
        full = _ocr(context, _screen(context))
        if not _has(full, "一项赠礼"):
            return True  # 已转场，由后续节点识别当前页面
        title = next(
            (clean(r.text) for r in full
             if 75 <= r.box[1] <= 175 and clean(r.text).endswith("赠礼")),
            "",
        )
        name = general_name(title, self.state.catalog) or title.removesuffix("赠礼") or "未知武将"
        options, available = self._wait_detail_options(context, name)
        if options is None:
            return False
        kind = choose_gift_kind(name, available, self.state.owned_relics, self.state.owned_supports)
        if not kind:
            print(f"[试验版] {name} 直接赠礼页无可安全选择的礼物：{[r.text for r in options]}")
            return False
        print(f"[试验版] 直接赠礼：选择 {name} / {kind}")
        if not self._choose_with_retry(context, name, kind, options):
            return False
        if kind == "信物":
            self.state.owned_relics.add(name)
        elif kind == "驰援":
            self.state.owned_supports.add(name)
        return True

    def run(self, context, argv):
        if self.detail_only:
            return self._handle_direct_detail(context)
        for round_no in range(4):
            results = _ocr(context, _screen(context), GIFT_ROI)
            if not _has(results, "请选择接受谁的赠礼"):
                # 选择后的黑屏只是转场；最多等待约 8 秒确认下一个画面。
                for _ in range(20):
                    time.sleep(ACTION_WAIT_SECONDS)
                    full = _ocr(context, _screen(context))
                    if _has(full, "请选择接受谁的赠礼"):
                        break
                    if _has(full, "一项赠礼"):
                        return self._handle_direct_detail(context)
                    if any(_has(full, marker) for marker in ("当前挑战", "休息", "武将技能", "点击空白")):
                        return True
                else:
                    print("[试验版] 赠礼标题消失，但未确认已回到后续界面")
                    return False
                continue

            offers = {}
            for result in results:
                x, y, _, _ = result.box
                if 490 <= y <= 570 and "赠礼" in clean(result.text):
                    name = general_name(result.text, self.state.catalog)
                    if name:
                        offers[name] = result
            if not offers:
                print("[试验版] 赠礼页没有识别出可点击的人物名称，停止本次任务")
                return False

            candidates = [
                name for name in offers
                if name not in self.state.owned_supports
                or (name not in self.state.owned_relics and RELIC_SCORE.get(name, 0) >= 3)
                or FUNDING_SCORE.get(name, 0) > 0
            ]
            if not candidates:
                print("[试验版] 三人都没有剩余高优先级赠礼，选择其中一人完成强制赠礼")
                candidates = list(offers)
            for name in rank_people(candidates, self.state.owned_relics, self.state.owned_supports):
                print(f"[试验版] 查看 {name} 的赠礼")
                options, available = None, set()
                for open_attempt in range(1, RETRY_LIMIT + 1):
                    current_offer = offers.get(name)
                    if not current_offer:
                        print(f"[试验版] {name} 的入口已消失，不再补点")
                        return False
                    _click(context, current_offer.box)
                    time.sleep(ACTION_WAIT_SECONDS)
                    options, available = self._wait_detail_options(context, name)
                    if options is not None:
                        break
                    source = _ocr(context, _screen(context), GIFT_ROI)
                    if not _has(source, "请选择接受谁的赠礼"):
                        print("[试验版] 赠礼入口后画面不明，不能安全重试")
                        return False
                    offers = {
                        general_name(r.text, self.state.catalog): r
                        for r in source
                        if "赠礼" in clean(r.text) and general_name(r.text, self.state.catalog)
                    }
                    if open_attempt < RETRY_LIMIT:
                        print(f"[试验版] {name} 入口未生效，准备第 {open_attempt + 1} 次")
                if options is None:
                    print(f"[试验版] {name} 入口尝试 {RETRY_LIMIT} 次仍未打开")
                    return False
                kind = choose_gift_kind(name, available, self.state.owned_relics, self.state.owned_supports)
                if not kind:
                    print(f"[试验版] {name} 没识别到可选礼物：{[r.text for r in options]}")
                    return False
                print(f"[试验版] 选择 {name} / {kind}（信物 {RELIC_SCORE.get(name, 0)} 分，驰援 {SUPPORT_SCORE.get(name, 0)} 分）")
                if not self._choose_with_retry(context, name, kind, options):
                    return False
                if kind == "信物":
                    self.state.owned_relics.add(name)
                elif kind == "驰援":
                    self.state.owned_supports.add(name)
                break
        print("[试验版] 赠礼界面超过 4 轮仍未结束")
        return False

    def _choose_with_retry(self, context, name, kind, options):
        """仅在仍能确认同一赠礼详情时重复点击；绝不在转场黑屏盲点。"""
        for attempt in range(1, RETRY_LIMIT + 1):
            target = _find(options, kind)
            if not target:
                print(f"[试验版] {name} / {kind} 已不在当前详情页，停止补点")
                return False
            _click(context, target.box)
            time.sleep(ACTION_WAIT_SECONDS)
            unchanged = 0
            for _ in range(12):
                image = _screen(context)
                after = _ocr(context, image, GIFT_DETAIL_ROI)
                if _has(after, "背包已满") or _has(after, "信物已满"):
                    print("[试验版] 背包容量提示，停止以免误记已获得信物")
                    return False
                if _find(after, kind):
                    unchanged += 1
                    if unchanged >= 3:
                        options = after
                        break
                else:
                    full = _ocr(context, image)
                    if _has(full, "背包已满") or _has(full, "信物已满"):
                        print("[试验版] 背包容量提示，停止以免误记已获得信物")
                        return False
                    if _has(full, "请选择接受谁的赠礼") or any(
                        _has(full, marker) for marker in ("当前挑战", "休息", "武将技能", "点击空白")
                    ):
                        return True
                    unchanged = 0
                time.sleep(ACTION_WAIT_SECONDS)
            else:
                print(f"[试验版] {name} / {kind} 点击后画面不明，不盲目重试")
                return False
            print(f"[试验版] {name} / {kind} 未生效，第 {attempt} 次")
        print(f"[试验版] {name} / {kind} 尝试 {RETRY_LIMIT} 次仍未生效")
        return False


class TrialShop(CustomAction):
    def __init__(self, state):
        super().__init__()
        self.state = state

    @staticmethod
    def _shop_ready(results):
        return (
            (_has(results, "信物专区") or _has(results, "武将牌专区"))
            and (_has(results, "巴清") or _has(results, "吕不韦"))
            and not _find(results, "取消", x_min=650, x_max=950, y_min=420, y_max=590)
        )

    def _wait_shop(self, context, checks=3):
        for _ in range(checks):
            results = _ocr(context, _screen(context))
            if self._shop_ready(results):
                return results
            time.sleep(ACTION_WAIT_SECONDS)
        return None

    def _retry_shop_entry_once(self, context):
        """仅在仍是选关地图、商人头像还在时补点一次。"""
        image = _screen(context)
        if not _has(_ocr(context, image, (0, 100, 390, 180)), "当前挑战"):
            print("[试验版] 商店未验证且不确定仍在地图，不补点")
            return False

        matches = []
        for merchant in ("巴清", "吕不韦"):
            detail = context.run_recognition_direct(
                JRecognitionType.TemplateMatch,
                JTemplateMatch(
                    template=[f"{merchant}.png"],
                    roi=(407, 209, 374, 336),
                    threshold=[0.85],
                    order_by="Score",
                ),
                image,
            )
            if detail and detail.hit and detail.best_result:
                matches.append((detail.best_result.score, merchant, detail.best_result.box))
        if not matches:
            print("[试验版] 商店未打开，但地图上未找到可确认的商人头像")
            return False

        _, merchant, box = max(matches, key=lambda match: match[0])
        print(f"[试验版] 仍在地图，补点一次 {merchant} 头像中心")
        _click(context, box)
        return True

    def _buy(self, context, name, item):
        # 先确认商品卡片，再验证弹窗商品名和价格；价格可能每次不同。
        print(f"[试验版] 查看商品：{item}")
        for open_attempt in range(1, RETRY_LIMIT + 1):
            _click(context, name.box)
            time.sleep(ACTION_WAIT_SECONDS)
            image = _screen(context)
            popup = _ocr(context, image)
            modal_item = _ocr(context, image, (300, 140, 670, 310))
            modal_title = _ocr(context, image, (300, 100, 670, 140))
            if _has(modal_item, item) and _has(modal_title, "购买"):
                break
            if _find(popup, "取消", x_min=650, x_max=950, y_min=420, y_max=590):
                print(f"[试验版] 打开了非目标商品弹窗，取消后重试 {item}")
                if not self._cancel(context, popup):
                    return False
            elif not self._shop_ready(popup):
                print(f"[试验版] {item} 点击后画面不明，停止补点")
                return False
            current = self._wait_shop(context)
            name = _find(current or [], item, x_min=560, y_min=90, y_max=620)
            if not name:
                print(f"[试验版] {item} 已不在商店，停止补点")
                return False
            print(f"[试验版] {item} 弹窗未打开，第 {open_attempt} 次")
        else:
            print(f"[试验版] {item} 尝试 {RETRY_LIMIT} 次仍未打开弹窗")
            return False
        if clean(item) == "行囊" and not _has(modal_item, "背包格数"):
            print("[试验版] 行囊弹窗没有识别到背包扩容说明，不付款")
            self._cancel(context, popup)
            return False

        wallet_results = _ocr(context, image, (1000, 0, 250, 150))
        wallet_values = _number_near(wallet_results, x_min=1000, x_max=1279, y_min=10, y_max=120)
        buttons = _ocr(context, image, (380, 450, 480, 145))
        purchase = next(
            (r for r in buttons if "购买" in clean(r.text) and r.box[0] < 650), None
        )
        if not purchase:
            print("[试验版] 未找到弹窗左侧购买按钮")
            self._cancel(context, popup)
            return False
        prices = _number_near(buttons, x_min=390, x_max=660, y_min=450, y_max=590)
        if not wallet_values or not prices:
            print("[试验版] 钱或价格未识别清楚，不付款")
            self._cancel(context, popup)
            return False
        wallet, price = max(wallet_values), min(prices)
        if wallet < price:
            print(f"[试验版] {item} 价格 {price}，余额 {wallet}，跳过")
            self._cancel(context, popup)
            return False

        for buy_attempt in range(1, RETRY_LIMIT + 1):
            print(f"[试验版] 购买 {item}：{price} / 余额 {wallet}，第 {buy_attempt} 次")
            _click(context, purchase.box)
            time.sleep(ACTION_WAIT_SECONDS)
            after_image = _screen(context)
            after_popup = _ocr(context, after_image)
            after_wallet = _number_near(
                _ocr(context, after_image, (1000, 0, 250, 150)),
                x_min=1000, x_max=1279, y_min=10, y_max=120,
            )
            if after_wallet and max(after_wallet) < wallet:
                return True
            if not after_wallet or max(after_wallet) != wallet:
                print("[试验版] 购买后余额无法核实，不重复付款")
                return False
            if self._shop_ready(after_popup):
                print("[试验版] 弹窗已消失但余额未下降，不重复付款")
                return False
            if not (_has(_ocr(context, after_image, (300, 140, 670, 310)), item) and _find(
                after_popup, "取消", x_min=650, x_max=950, y_min=420, y_max=590
            )):
                print("[试验版] 购买后弹窗状态不明，不重复付款")
                return False
            time.sleep(ACTION_WAIT_SECONDS)
            stable_image = _screen(context)
            stable_popup = _ocr(context, stable_image)
            stable_wallet = _number_near(
                _ocr(context, stable_image, (1000, 0, 250, 150)),
                x_min=1000, x_max=1279, y_min=10, y_max=120,
            )
            if stable_wallet and max(stable_wallet) < wallet:
                return True
            if not stable_wallet or max(stable_wallet) != wallet or not _has(
                _ocr(context, stable_image, (300, 140, 670, 310)), item
            ):
                print("[试验版] 购买后状态变化但结果不明，不重复付款")
                return False
            purchase = _find(stable_popup, f"{price}购买", x_min=390, x_max=660, y_min=450, y_max=590)
            if not purchase:
                print("[试验版] 左侧购买按钮已变化，不重复付款")
                return False
        print(f"[试验版] {item} 付款尝试 {RETRY_LIMIT} 次仍未生效")
        self._cancel(context, stable_popup)
        return False

    def _cancel(self, context, popup):
        # 取消后有退场动画。未确认弹窗消失前不能再点；否则第二下会穿透到
        # 弹窗后面的武将牌（2026-09-26 余额不足实测）。
        for attempt in range(RETRY_LIMIT):
            current = popup if attempt == 0 else _ocr(context, _screen(context))
            cancel = _find(current, "取消", x_min=650, x_max=950, y_min=420, y_max=590)
            if not cancel:
                return bool(self._wait_shop(context))
            _click(context, cancel.box)
            stable = 0
            for _ in range(3):
                time.sleep(ACTION_WAIT_SECONDS)
                current = _ocr(context, _screen(context))
                stable = stable + 1 if self._shop_ready(current) else 0
                if stable >= 2:
                    return True
            print(f"[试验版] 取消购买弹窗后仍未关闭，第 {attempt + 1} 次")
        return False

    def _leave(self, context):
        for attempt in range(1, RETRY_LIMIT + 1):
            current = _ocr(context, _screen(context))
            # 不依赖右上导航栏局部 OCR 的“休息”。
            if _has(current, "当前挑战") and (
                _has(current, "结束挑战") or _has(current, "千里单骑")
            ):
                return True
            confirm = _find(current, "确认", x_min=400, x_max=750, y_min=350, y_max=560)
            if confirm:
                _click(context, confirm.box)
            elif self._shop_ready(current):
                _click_point(context, 1215, 97)
            else:
                print("[试验版] 退出商店时画面不明，等待恢复")
            time.sleep(ACTION_WAIT_SECONDS)
            print(f"[试验版] 返回地图未确认，第 {attempt} 次")
        current = _ocr(context, _screen(context))
        if _has(current, "当前挑战") and (
            _has(current, "结束挑战") or _has(current, "千里单骑")
        ):
            return True
        print(f"[试验版] 返回尝试 {RETRY_LIMIT} 次仍未验证到地图")
        return False

    def run(self, context, argv):
        results = self._wait_shop(context)
        for _ in range(RETRY_LIMIT):
            if results:
                break
            if not self._retry_shop_entry_once(context):
                break
            time.sleep(ACTION_WAIT_SECONDS)
            results = self._wait_shop(context)
        if not results:
            print("[试验版] 商店页面未验证，停止本次任务")
            return False
        bought_relics = 0
        attempted = set()
        while bought_relics < self.state.max_relic_per_shop:
            # 每买完一件重新截图和排序；不要沿用购买前的商品位置与余额。
            results = self._wait_shop(context, checks=RETRY_LIMIT)
            if not results:
                return False
            candidate = None
            for score, owner, item in ranked_shop_relics(self.state.catalog, self.state.owned_relics):
                if score < self.state.min_shop_score:
                    break
                if item in attempted:
                    continue
                for alias in RELIC_ALIASES.get(owner, (item,)):
                    product = _find(results, alias, x_min=560, y_min=90, y_max=620)
                    if product:
                        candidate = (owner, item, product)
                        break
                if candidate:
                    break
            if not candidate:
                break
            owner, item, product = candidate
            attempted.add(item)
            if self._buy(context, product, product.text):
                self.state.owned_relics.add(owner)
                bought_relics += 1
            elif not self._wait_shop(context):
                # _buy 已取消弹窗；若仍不在可验证的商店，不能点下一件。
                return False

        # 信物全部处理完后再取一张新截图，避免最后一笔购买改变商品布局。
        results = self._wait_shop(context, checks=RETRY_LIMIT)
        if not results:
            return False
        # 用户指定：有需要的高分信物先买；之后遇到能买的行囊就买，跨商店不设总次数。
        bag = _find(results, "行囊", x_min=560, y_min=90, y_max=620)
        if bag:
            self._buy(context, bag, "行囊")
            if not self._wait_shop(context, checks=RETRY_LIMIT):
                print("[试验版] 行囊处理后购买弹窗未安全关闭")
                return False
        return self._leave(context)


def _pipeline_override():
    import json

    with (ROOT / "resource/pipeline/继续挑战.json").open(encoding="utf-8") as file:
        normal = json.load(file)
    with (ROOT / "resource/pipeline/临时战斗.json").open(encoding="utf-8") as file:
        battle = json.load(file)
    next_nodes = ["试验版赠礼详情", "选择赠礼", "属性变化", "试验版商店页面"] + [
        "试验版巴清" if name == "巴清" else
        "试验版吕不韦" if name == "吕不韦" else name
        for name in normal["继续战斗"]["next"]
        if name != "属性变化"
    ]
    return {
        # 试验版无限层：开局不经过旧限层节点；保留兜底覆盖以防其他分支跳入。
        "千里开局": {
            "action": {"type": "Custom", "param": {"custom_action": "trial_open_run"}},
            "next": ["自定义选将", "退出选将", "开始挑战"],
            "on_error": [],
        },
        "开始挑战": {"next": ["开始挑战", "初始战斗"]},
        "限制冲榜": {"action": {"type": "DoNothing"}},
        "节点中检测限制冲榜": {"action": {"type": "DoNothing"}},
        "继续战斗": {"next": next_nodes, "on_error": ["试验版常见界面巡检"]},
        "默认战斗": {
            "next": ["试验版赠礼详情", "选择赠礼", "属性变化", "试验版商店页面",
                     "领取奖励截图", "点击空白", "重复确认", "开始对局", "默认战斗"],
            "on_error": ["试验版常见界面巡检"],
        },
        "临时战斗": {
            "next": ["试验版赠礼详情", "试验版商店页面", "千里开局", *battle["临时战斗"]["next"]]
        },
        "动态选择赠礼": {
            "action": {"type": "Custom", "param": {"custom_action": "trial_gift"}},
            "next": ["试验版赠礼详情", "属性变化", "继续战斗"],
            "on_error": [],
        },
        "属性变化": {
            "recognition": {
                "type": "OCR",
                "param": {"roi": [530, 105, 680, 95], "expected": ["武将技能", "武将信息"]},
            },
            "action": {"type": "Custom", "param": {"custom_action": "trial_dismiss_stats"}},
            "next": ["属性变化", "事件确认", "继续战斗"],
            "on_error": [],
        },
        "点击空白": {"next": ["点击空白", "试验版重置局状态"]},
    }


def run_agent(identifier, min_shop_score, max_relic_per_shop, owned_relics):
    # 只在 Agent 子进程导入旧模块。Maa AgentServer 与 MaaFramework Core
    # 在同一进程不能同时创建 Resource，必须严格分离。
    from agent import main as old  # noqa: F401，导入即注册正式 CustomAction
    from maa.agent.agent_server import AgentServer

    state = TrialState(
        catalog=load_catalog(),
        owned_relics=set(owned_relics),
        min_shop_score=min_shop_score,
        max_relic_per_shop=max_relic_per_shop,
    )
    for name, action in (
        ("trial_reset_run", TrialReset(state)),
        ("trial_dismiss_stats", TrialDismissStats()),
        ("trial_open_run", TrialOpenRun()),
        ("trial_page_audit", TrialScreenAudit()),
        ("trial_gift", TrialGift(state)),
        ("trial_gift_detail", TrialGift(state, detail_only=True)),
        ("trial_shop", TrialShop(state)),
    ):
        if not AgentServer.register_custom_action(name, action):
            raise RuntimeError(f"注册试验动作失败：{name}")
    if not AgentServer.start_up(identifier):
        raise RuntimeError("启动试验 AgentServer 失败")
    AgentServer.join()
    AgentServer.shut_down()


def run_game(state, entry, device_address):
    devices = Toolkit.find_adb_devices()
    if device_address:
        devices = [device for device in devices if device.address == device_address]
    if len(devices) != 1:
        print("[试验版] 找到的设备：", [(d.name, d.address) for d in devices])
        raise RuntimeError("必须只有一台安卓设备；多台时用 --device 指定地址")
    device = devices[0]

    Tasker.set_log_dir(str(Path(__file__).parent / "debug"))
    resource = Resource()
    for path in (ROOT / "resource", Path(__file__).parent / "resource"):
        job = resource.post_bundle(path).wait()
        if not job.succeeded:
            raise RuntimeError(f"加载资源失败：{path}")
    controller = AdbController(
        device.adb_path, device.address, device.screencap_methods,
        device.input_methods, device.config,
    )
    if not controller.set_screenshot_target_short_side(720):
        raise RuntimeError("设置 720p 截图失败")
    if not controller.post_connection().wait().succeeded:
        raise RuntimeError(f"连接设备失败：{device.address}")
    tasker = Tasker()
    if not tasker.bind(resource, controller):
        raise RuntimeError("绑定资源与控制器失败")
    client = AgentClient()
    if not client.bind(resource) or not client.register_sink(resource, controller, tasker):
        raise RuntimeError("绑定试验 Agent 失败")
    client.set_timeout(15000)
    child = subprocess.Popen(
        [
            sys.executable, "-u", str(Path(__file__).resolve()),
            "--agent", client.identifier,
            "--min-shop-score", str(state.min_shop_score),
            "--max-relic-per-shop", str(state.max_relic_per_shop),
            "--owned-relics", ",".join(sorted(state.owned_relics)),
        ],
        cwd=str(ROOT),
    )
    try:
        if not client.connect():
            raise RuntimeError("连接试验 Agent 失败")
        needed = {"trial_reset_run", "trial_dismiss_stats", "trial_open_run", "trial_page_audit", "trial_gift", "trial_gift_detail", "trial_shop"}
        if not needed.issubset(set(client.custom_action_list)):
            raise RuntimeError(f"试验 Agent 缺少动作：{needed - set(client.custom_action_list)}")
        entry_name = "千里走单骑" if entry == "start" else "继续战斗"
        job = tasker.post_task(entry_name, _pipeline_override()).wait()
        print(f"[试验版] 任务结束：{job.status}，详情：{job.get()}")
        return 0 if job.succeeded else 1
    finally:
        if client.connected:
            client.disconnect()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.terminate()
            child.wait(timeout=5)


def check_agent(state):
    """离线验证资源叠加与 Agent 注册，不连接设备。"""
    resource = Resource()
    for path in (ROOT / "resource", Path(__file__).parent / "resource"):
        if not resource.post_bundle(path).wait().succeeded:
            raise RuntimeError(f"资源加载失败：{path}")
    expected_nodes = {"试验版巴清", "试验版吕不韦", "试验版商店处理", "试验版重置局状态"}
    if not expected_nodes.issubset(set(resource.node_list)):
        raise RuntimeError(f"试验节点缺失：{expected_nodes - set(resource.node_list)}")
    client = AgentClient()
    if not client.bind(resource):
        raise RuntimeError("Agent 无法绑定试验资源")
    client.set_timeout(15000)
    child = subprocess.Popen(
        [
            sys.executable, "-u", str(Path(__file__).resolve()),
            "--agent", client.identifier,
            "--min-shop-score", str(state.min_shop_score),
            "--max-relic-per-shop", str(state.max_relic_per_shop),
            "--owned-relics", ",".join(sorted(state.owned_relics)),
        ],
        cwd=str(ROOT),
    )
    try:
        if not client.connect():
            raise RuntimeError("Agent 离线连接失败")
        needed = {"trial_reset_run", "trial_gift", "trial_shop"}
        missing = needed - set(client.custom_action_list)
        if missing:
            raise RuntimeError(f"Agent 动作缺失：{missing}")
        print(f"[试验版] 离线检查通过：{len(resource.node_list)} 个节点，{len(client.custom_action_list)} 个动作")
    finally:
        if client.connected:
            client.disconnect()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.terminate()
            child.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description="千里走单骑策略by兔兔（v1.4.2 正式版）")
    parser.add_argument("--run", action="store_true", help="实际连接安卓设备并开始任务")
    parser.add_argument("--check-agent", action="store_true", help="离线验证资源与 Agent，不连接游戏")
    parser.add_argument("--agent", help=argparse.SUPPRESS)
    parser.add_argument("--entry", choices=("start", "continue"), default="start")
    parser.add_argument("--device", help="安卓设备地址；多设备时必填")
    parser.add_argument("--owned-relics", default="", help="续打时已有信物的武将名，英文逗号分隔")
    parser.add_argument("--min-shop-score", type=int, choices=(3, 4), default=3)
    parser.add_argument("--max-relic-per-shop", type=int, default=9)
    args = parser.parse_args()

    if args.agent:
        owned = [clean(name) for name in args.owned_relics.split(",") if clean(name)]
        run_agent(args.agent, args.min_shop_score, args.max_relic_per_shop, owned)
        return 0

    catalog = load_catalog()
    check_policy(catalog)
    if args.max_relic_per_shop < 0:
        raise ValueError("--max-relic-per-shop 不能小于 0")
    missing = sorted((RELIC_SCORE.keys() | SUPPORT_SCORE.keys()) - catalog.keys() - ADDED_GENERAL_RELIC_SCORE.keys())
    if missing:
        raise RuntimeError(f"评分表有武将未在 XLSX 找到：{missing}")
    unknown_shop_names = sorted(
        name for name, score in ADDED_GENERAL_RELIC_SCORE.items()
        if score >= args.min_shop_score and not catalog.get(name)
    )
    if unknown_shop_names:
        print(f"[试验版] 信物商店名未确认，暂不自动购买：{unknown_shop_names}")
    owned = {clean(name) for name in args.owned_relics.split(",") if clean(name)}
    known_generals = catalog.keys() | ADDED_GENERAL_RELIC_SCORE.keys()
    if owned - known_generals:
        raise ValueError(f"--owned-relics 中没有资料的武将：{sorted(owned - known_generals)}")
    state = TrialState(
        catalog=catalog,
        owned_relics=owned,
        min_shop_score=args.min_shop_score,
        max_relic_per_shop=args.max_relic_per_shop,
    )
    print("[策略by兔兔 v1.4.2] 商店信物优先级：")
    for score, owner, relic in ranked_shop_relics(catalog, set()):
        if score >= state.min_shop_score:
            print(f"  {score} 分 {owner} → {relic}")
    print("[策略by兔兔 v1.4.2] 商店不买武将牌；高分信物后买行囊，每次商店最多一件行囊。")
    if args.check_agent:
        check_agent(state)
        return 0
    if not args.run:
        print("当前只显示计划；实际运行需加 --run。")
        return 0
    if args.entry == "continue" and not owned:
        print("[试验版] 续打未提供已有信物名单；可能再次考虑已有信物。")
    return run_game(state, args.entry, args.device)


if __name__ == "__main__":
    raise SystemExit(main())
