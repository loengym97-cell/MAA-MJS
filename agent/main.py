"""
赠礼选择 Agent — 状态管理
=======================
全局变量：
  _claimed_cat1: set[str]   — 已拿到信物并排除的武将名
  _claimed_cat2: set[str]   — 已拿到"驰援"并排除的武将名
"""

from datetime import datetime
import json
import os
import sys
import threading
import time

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context
from maa.pipeline import JRecognitionType, JOCR
import cv2

from maa.tasker import Tasker

# 默认武将列表（当所有来源都为空时回退）
CAT1_DEFAULT = [
    "韩信",
    "马超",
    "吕布",
    "关羽",
    "张春华",
    "黄忠",
    "司马懿",
    "孙策",
]
CAT2_DEFAULT = ["刘禅", "马超", "曹丕", "萧何"]

# 本地配置文件的路径（与当前 py 同目录）
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(CONFIG_DIR, "gift_config.json")

# ==================== 全局状态 ====================

_claimed_cat1: set[str] = set()
_claimed_cat2: set[str] = set()
_claimed_cat1_lock = threading.Lock()
_claimed_cat2_lock = threading.Lock()


# ==================== 辅助函数 ====================


# 读取自定义赠礼默认配置
def _read_config() -> dict | None:
    """读取 gift_config.json，失败或不存在时返回 None"""
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# 识别自定义赠礼
def _parse_list(raw: str, default: list[str]) -> list[str]:
    """
    把 "马超,吕布,关羽" 格式的逗号分隔字符串解析为列表
    raw 为空或非字符串时返回 default 的副本
    """
    if not raw or not isinstance(raw, str):
        return list(default)
    items = [x.strip() for x in raw.split(",") if x.strip()]
    return items if items else list(default)


# 获取动态赠礼列表
def _get_active_list(category: str, list_str: str = "") -> list[str]:
    """
    获取排除了已领取武将后的活跃列表（用于 OCR expected）。
    优先级：list_str（来自 UI） > gift_config.json > 代码默认列表
    """
    if list_str:
        # 优先级 1：用户通过 UI 输入的列表（最优先）
        full = _parse_list(
            list_str, CAT1_DEFAULT if category == "cat1" else CAT2_DEFAULT
        )
    else:
        # 优先级 2：从本地配置文件中读取
        config = _read_config()
        if config:
            key = "cat1_list" if category == "cat1" else "cat2_list"
            full = _parse_list(
                config.get(key, ""),
                CAT1_DEFAULT if category == "cat1" else CAT2_DEFAULT,
            )
        else:
            # 优先级 3：代码内置默认列表
            full = CAT1_DEFAULT if category == "cat1" else CAT2_DEFAULT

    # 排除已领取的武将（加锁读取）
    claimed = _claimed_cat1 if category == "cat1" else _claimed_cat2
    lock = _claimed_cat1_lock if category == "cat1" else _claimed_cat2_lock
    with lock:
        return [n for n in full if n not in claimed]


# 识别选择赠礼
def _ocr_active_general(context: Context, category: str, list_str: str = ""):
    """
    在底部武将选择栏 ([179, 509, 929, 49]) 做 OCR，
    返回最佳匹配的 OCRResult，没匹配到返回 None。
    """
    active = _get_active_list(category, list_str)
    if not active:
        return None

    try:
        image = context.tasker.controller.cached_image
    except RuntimeError:
        return None

    # 主动调用 OCR 识别
    reco = context.run_recognition(
        "ocr",
        image,
        {
            "ocr": {
                "recognition": "OCR",
                "roi": [179, 509, 929, 49],
                "expected": active,
                "order_by": "Expected",
            }
        },
    )

    if reco and reco.hit and reco.best_result and hasattr(reco.best_result, "text"):
        return reco.best_result
    return None


# 验证消失
def _click_general_until_gone(context, category, list_str):
    """
    循环 _ocr_active_general（动态排除已领取）→ 点击 → 验证武将消失。
    返回最后一次点击的武将名，无匹配武将时返回 None。
    """
    last_name = None
    for _ in range(15):
        context.tasker.controller.post_screencap().wait()
        result = _ocr_active_general(context, category, list_str)
        if not result:
            break  # 武将已消失 → 点击生效了
        _click_and_wait(context, result.box)
        last_name = result.text
        time.sleep(0.1)
    return last_name


# 点击赠礼
def _click_and_wait(context, box):
    cx = box[0] + box[2] // 2
    cy = box[1] + box[3] // 2
    context.tasker.controller.post_click(cx, cy).wait()


# 循环点击验证
def _click_until_gone(context, roi, expected, click_delay=0.5, max_tries=15):
    last_text = None
    found_once = False
    for _ in range(max_tries):
        context.tasker.controller.post_screencap().wait()
        try:
            image = context.tasker.controller.cached_image
        except RuntimeError:
            time.sleep(0.2)
            continue
        reco = context.run_recognition(
            "_click_until_gone",
            image,
            {
                "_click_until_gone": {
                    "recognition": "OCR",
                    "roi": roi,
                    "expected": expected,
                    "order_by": "Expected",
                }
            },
        )
        if not reco or not reco.hit or not reco.best_result:
            if found_once:
                break
            time.sleep(0.05)
            continue
        _click_and_wait(context, reco.best_result.box)
        last_text = reco.best_result.text
        found_once = True
        time.sleep(click_delay)
    return last_text


# 截图识别
def _poll_ocr(context, roi, expected, timeout=6.0, interval=0.2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        context.tasker.controller.post_screencap().wait()
        try:
            image = context.tasker.controller.cached_image
        except RuntimeError:
            time.sleep(interval)
            continue
        reco = context.run_recognition(
            "_poll",
            image,
            {
                "_poll": {
                    "recognition": "OCR",
                    "roi": roi,
                    "expected": expected,
                    "order_by": "Expected",
                }
            },
        )
        if reco and reco.hit and reco.best_result:
            return reco.best_result
        time.sleep(interval)
    return None


# 保存截图
@AgentServer.custom_action("save_reward_screenshot")
class SaveRewardScreenshot(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        # 定义 ROI 范围
        roi = [544, 596, 192, 62]
        try:
            # 获取当前截图
            image = context.tasker.controller.cached_image
        except RuntimeError:
            print("[RewardScreenshot] 获取截图失败")
            return False
        # 使用 OCR 识别"领取奖励"
        reco = context.run_recognition(
            "check_reward",
            image,
            {
                "check_reward": {
                    "recognition": "OCR",
                    "roi": roi,
                    "expected": ["领取奖励"],
                }
            },
        )
        # 如果识别到"领取奖励"，保存截图
        if reco and reco.hit:
            # 创建目录
            reward_dir = os.path.join(CONFIG_DIR, "logs", "奖励")
            os.makedirs(reward_dir, exist_ok=True)

            # 生成文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_领取奖励.png"
            filepath = os.path.join(reward_dir, filename)

            # 保存图片
            cv2.imwrite(filepath, image)
            print(f"[RewardScreenshot] 截图已保存: {filepath}")
            return True

        return False


# 限制冲榜
@AgentServer.custom_action("CheckNumberAndStop")
class CheckNumberAndStop(CustomAction):
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> bool:
        # 获取当前截图
        image = context.tasker.controller.cached_image

        # 使用 OCR 识别左上角数字
        reco_detail = context.run_recognition_direct(
            JRecognitionType.OCR,
            JOCR(
                roi=[239, 45, 42, 49],
                expected=[],  # 可以留空匹配所有数字
            ),
            image,
        )

        if reco_detail and reco_detail.hit:
            # 从识别结果中提取数字文本
            text = reco_detail.best_result.text
            print(f"当前层数为{text}")

            try:
                # 尝试将文本转换为数字
                number = int(text)
                if number > 100:
                    print(f"{number}")
                    print("超过限制65，不允许冲榜")
                    # 停止整个任务
                    context.tasker.post_stop()
                    return True
            except ValueError:
                print("这层有bug，请换一层")
        return True


# 重置冲榜查询
@AgentServer.custom_action("ClearHitCountAction")
class ClearHitCountAction(CustomAction):  
    def run(self, context: Context, argv: CustomAction.RunArg):  
        # 清除目标节点的命中计数  
        context.clear_hit_count("节点中检测限制冲榜")  
        return CustomAction.RunResult(success=True)  
  
# ============ 主循环盲点兜底 ============
# 盲点位置序列（720p 坐标）：依次尝试，覆盖常见弹窗关闭/确认区。
# 每次"卡住触发"推进一个位置；主循环恢复正常（中间有节点命中）后从 ① 重新开始。
_FALLBACK_POINTS = [
    (960, 180),  # ① 右上角（弹窗 X / 关闭按钮区）
    (960, 540),  # ② 右下（常见确认/关闭区，十常侍弹窗附近）
    (640, 360),  # ③ 屏幕中心（点空白）
    (640, 650),  # ④ 底部中央（选项区）
    (480, 200),  # ⑤ 左上（弹窗关闭区）
    (480, 540),  # ⑥ 左中（弹窗选项区）
    (300, 400),  # ⑦ 左中偏上
    (900, 400),  # ⑧ 右中
]
_fallback_state = {"count": 0, "last_ts": 0.0, "seq_idx": 0}


@AgentServer.custom_action("SafeFallbackClick")
class SafeFallbackClick(CustomAction):
    """主循环连续 N 轮无任何识别命中时，点一下固定空白位置（结算界面兜底）。

    参数（custom_action_param）: x, y = 点击坐标; interval = 连续失败多少轮触发
    """

    def run(self, context: Context, argv: CustomAction.RunArg):
        try:
            params = (
                json.loads(argv.custom_action_param)
                if isinstance(argv.custom_action_param, str)
                else (argv.custom_action_param or {})
            )
        except Exception:
            params = {}
        interval = int(params.get("interval", 30))

        # 盲点序列：优先自定义 points，其次兼容旧 x/y 单点，最后默认序列
        points = _FALLBACK_POINTS
        raw_points = params.get("points")
        if raw_points:
            try:
                parsed = (
                    json.loads(raw_points) if isinstance(raw_points, str) else raw_points
                )
                if (
                    isinstance(parsed, list)
                    and parsed
                    and all(isinstance(p, (list, tuple)) and len(p) == 2 for p in parsed)
                ):
                    points = [(int(p[0]), int(p[1])) for p in parsed]
            except Exception:
                pass
        elif "x" in params or "y" in params:
            points = [
                (int(params.get("x", 960)), int(params.get("y", 180))),
            ]

        # 已托管（离开中/托管中）→ 不点任何地方，重置计数，继续等待战斗结束
        try:
            reco = context.run_recognition_direct(
                JRecognitionType.OCR,
                JOCR(roi=[400, 430, 480, 240], expected=["离开中", "托管中"]),
                context.tasker.controller.cached_image,
            )
            if reco and reco.hit:
                _fallback_state["count"] = 0
                _fallback_state["last_ts"] = time.time()
                return CustomAction.RunResult(success=True)
        except Exception:
            pass

        now = time.time()
        # 距上次调用超过 5 秒 = 中间有别的节点执行过 → 恢复正常 → 计数与序列都重置
        if now - _fallback_state["last_ts"] > 5.0:
            _fallback_state["count"] = 0
            _fallback_state["seq_idx"] = 0
        _fallback_state["last_ts"] = now
        _fallback_state["count"] += 1

        if _fallback_state["count"] >= interval:
            _fallback_state["count"] = 0
            idx = _fallback_state["seq_idx"]
            px, py = points[idx % len(points)]
            _fallback_state["seq_idx"] = idx + 1
            try:
                context.tasker.controller.post_click(px, py)
                print(
                    f"[兜底点击] 主循环连续 {interval} 轮无识别且未托管，"
                    f"盲点序列#{idx + 1}/{len(points)} ({px},{py})"
                )
            except Exception as e:
                print(f"[兜底点击] 点击失败: {e}")

        # 永远返回成功：识别成功+action失败会被 MaaFramework 判为任务失败
        # 这里"不点击"也是正常流程（计数未到），必须返回 True
        return CustomAction.RunResult(success=True)
  


# 选择赠礼
@AgentServer.custom_action("handle_gift_selection")
class HandleGiftSelection(CustomAction):
    def run(self, context, argv):
        params = (
            json.loads(argv.custom_action_param)
            if isinstance(argv.custom_action_param, str)
            else (argv.custom_action_param or {})
        )
        cat1_list = params.get("cat1_list", "")
        cat2_list = params.get("cat2_list", "")
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{current_time}] [GiftAgent] 原始 cat1_list: {cat1_list}")
        print(f"[{current_time}] [GiftAgent] 原始 cat2_list: {cat2_list}")
        print(f"[{current_time}] [GiftAgent] 已领取 cat1: {_claimed_cat1}")
        print(f"[{current_time}] [GiftAgent] 已领取 cat2: {_claimed_cat2}")

        for outer in range(10):
            # 外层：验证赠礼界面是否还开着
            context.tasker.controller.post_screencap().wait()
            try:
                image = context.tasker.controller.cached_image
            except RuntimeError:
                continue
            reco = context.run_recognition(
                "_check_gift",
                image,
                {
                    "_check_gift": {
                        "recognition": "OCR",
                        "roi": [450, 540, 400, 150],
                        "expected": ["接受谁的"],
                    }
                },
            )
            if not (reco and reco.hit and reco.best_result):
                print(f"[{current_time}] [GiftAgent] 赠礼完成")
                return True

            # ========== cat1 分支 ==========
            name = _click_general_until_gone(context, "cat1", cat1_list)
            if name:
                print(f"[{current_time}] [GiftAgent] cat1 选中 {name}")
                # 内层：选奖励（优先信物/驰援，找到就点；都没有才选兜底）
                _click_until_gone(context, [400, 140, 500, 450], ["信物", "驰援"], 0.4, 6)
                _click_until_gone(context, [400, 140, 500, 450], ["资助", "武将牌", "并肩作战"], 0.4, 4)
                with _claimed_cat1_lock:
                    _claimed_cat1.add(name)
                continue

            # ========== cat2 分支 ==========
            name = _click_general_until_gone(context, "cat2", cat2_list)
            if name:
                print(f"[{current_time}] [GiftAgent] cat2 选中 {name}")
                _click_until_gone(context, [400, 140, 500, 450], ["信物", "驰援"], 0.4, 6)
                _click_until_gone(context, [400, 140, 500, 450], ["资助", "武将牌", "并肩作战"], 0.4, 4)
                with _claimed_cat2_lock:
                    _claimed_cat2.add(name)
                continue

            # ========== fallback 分支 ==========
            if _click_until_gone(context, [400, 470, 500, 130], ["赠礼"], 0.4, 10):
                print(f"[{current_time}] [GiftAgent] fallback 选中赠礼")
                _click_until_gone(context, [400, 140, 500, 450], ["信物", "驰援"], 0.4, 6)
                _click_until_gone(context, [400, 140, 500, 450], ["资助", "武将牌", "并肩作战"], 0.4, 4)

        # 外层 10 轮耗尽，保底退出
        return True


# 赠礼选择失败
@AgentServer.custom_action("handle_gift_fallback")
class HandleGiftFallback(CustomAction):
    """
    赠礼选择失败时的 fallback 处理
    识别屏幕上的选项（资助、武将牌、驰援、信物、并肩作战）并点击
    """

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{current_time}] [GiftFallback] 开始执行 fallback 处理")

        # 先尝试点击"赠礼"按钮
        fallback = _poll_ocr(context, [400, 470, 500, 130], ["赠礼"], timeout=3)
        if fallback:
            _click_and_wait(context, fallback.box)
            # 等待界面加载
            time.sleep(1.0)

            # 识别并点击可用选项
            sort = _poll_ocr(
                context,
                [522, 171, 171, 377],
                ["信物", "驰援", "资助", "武将牌", "并肩作战"],
                timeout=3,
            )
            if sort:
                _click_and_wait(context, sort.box)
                time.sleep(0.5)
                print(f"[{current_time}] [GiftFallback] 成功选择选项: {sort.text}")
                return True
            else:
                print(f"[{current_time}] [GiftFallback] 未识别到任何选项")
        else:
            print(f"[{current_time}] [GiftFallback] 未识别到'赠礼'按钮")

        return False


# 重置赠礼标记
@AgentServer.custom_action("reset_gift_state")
class ResetGiftState(CustomAction):
    """
    重置赠礼状态 — 每次千里开局选将后执行一次。
    pipeline 中配 DirectHit + Custom，不依赖任何前序识别结果。
    """

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        with _claimed_cat1_lock:
            _claimed_cat1.clear()
        with _claimed_cat2_lock:
            _claimed_cat2.clear()
        print(f"[Reset] 重置赠礼状态，清空已领取武将")
        return True


def main():
    # 获取当前脚本路径并设置工作目录
    current_file_path = os.path.abspath(__file__)
    current_script_dir = os.path.dirname(current_file_path)

    # 将脚本所在目录设置为工作目录
    if os.getcwd() != current_script_dir:
        os.chdir(current_script_dir)
    print(f"[GiftAgent] set cwd: {os.getcwd()}")

    # 将脚本目录添加到 sys.path，以便导入模块
    if current_script_dir not in sys.path:
        sys.path.insert(0, current_script_dir)

    Tasker.set_log_dir("./debug")

    if len(sys.argv) < 2:
        print("Usage: python gift_agent.py <socket_id>")
        print("socket_id is provided by AgentIdentifier.")
        exit(1)

    socket_id = sys.argv[-1]

    AgentServer.start_up(socket_id)
    AgentServer.join()
    AgentServer.shut_down()


if __name__ == "__main__":
    main()
    # version = sys.argv[1]
    # os_name = sys.argv[2]
    # arch = sys.argv[3]
    # install_maafw(os_name, arch)
    # install_resource(version)
    # install_chores()
    # install_agent(os_name)
