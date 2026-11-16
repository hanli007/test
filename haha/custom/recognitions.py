"""
自定义识别：Pipeline 内置算法（找图、OCR、YOLO 检测）不好表达的判断，用 Python 实现。

在 Pipeline 中这样引用：
    "recognition": "Custom",
    "custom_recognition": "HpBarLow",
    "custom_recognition_param": {"roi": [60, 20, 150, 10], "lower": [0, 0, 150], "upper": [80, 80, 255], "below": 0.35}

每个类都绑定到具体账号（worker）和运行时（runtime），所以能读写状态库、判断队伍角色。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import numpy as np
from maa.context import Context
from maa.custom_recognition import CustomRecognition

if TYPE_CHECKING:
    from core.runtime import Runtime
    from core.worker import BaseWorker


def parse_param(raw: Any) -> dict[str, Any]:
    """把 custom_*_param 统一解析成字典（MAA 传进来的是 JSON 字符串）。"""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        val = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return val if isinstance(val, dict) else {"value": val}


def crop(image: np.ndarray, roi: list[int] | tuple[int, ...]) -> np.ndarray:
    """按 [x, y, w, h] 裁剪图像；roi 为空或全 0 时返回原图。"""
    if not roi or not any(roi):
        return image
    x, y, w, h = (int(v) for v in roi)
    return image[max(y, 0): y + h, max(x, 0): x + w]


def color_ratio(image: np.ndarray, lower: list[int], upper: list[int]) -> float:
    """
    计算图像中颜色落在 [lower, upper]（BGR）范围内的像素占比，0~1。
    用于血条、蓝条、经验条、进度条等“按颜色长度”判断的场景。
    """
    if image.size == 0:
        return 0.0
    lo = np.array(lower, dtype=np.uint8)
    hi = np.array(upper, dtype=np.uint8)
    mask = np.all((image >= lo) & (image <= hi), axis=-1)
    return float(mask.mean())


class BarBelow(CustomRecognition):
    """
    条形值（血/蓝/体力）低于阈值时命中。

    参数:
        roi:   [x, y, w, h] 条形区域（720p 坐标）
        lower: BGR 下限，例如红色血条 [0, 0, 150]
        upper: BGR 上限，例如 [80, 80, 255]
        below: 阈值 0~1，比例低于它则命中，默认 0.3
    命中时 box 为条形区域，detail 中带实际比例。
    """

    def analyze(self, context: Context, argv: CustomRecognition.AnalyzeArg):
        p = parse_param(argv.custom_recognition_param)
        roi = p.get("roi") or list(argv.roi)
        ratio = color_ratio(crop(argv.image, roi), p.get("lower", [0, 0, 150]), p.get("upper", [80, 80, 255]))
        hit = ratio < float(p.get("below", 0.3))
        return CustomRecognition.AnalyzeResult(box=tuple(roi) if hit else None, detail={"ratio": round(ratio, 3)})


class TeamRole(CustomRecognition):
    """
    判断当前账号在队伍中的角色，命中即“是该角色”。可让同一份 Pipeline 按队长/队员走不同分支。

    参数:
        role: "leader" | "member" | "solo"（solo 表示当前不在组队任务中）
    """

    def __init__(self, worker: "BaseWorker"):
        super().__init__()
        self.worker = worker

    def analyze(self, context: Context, argv: CustomRecognition.AnalyzeArg):
        want = parse_param(argv.custom_recognition_param).get("role", "leader")
        ctx = self.worker.team_context
        actual = ctx[1] if ctx else "solo"
        return CustomRecognition.AnalyzeResult(box=(0, 0, 1, 1) if actual == want else None,
                                               detail={"role": actual})


class KvCompare(CustomRecognition):
    """
    根据状态库中账号的自定义数据做判断，命中即条件成立。
    例如背包满了就去清包：{"key": "背包已满", "op": "eq", "value": true}

    参数:
        key:   kv 键名
        op:    eq | ne | lt | le | gt | ge | exists
        value: 比较值
    """

    _OPS = {
        "eq": lambda a, b: a == b, "ne": lambda a, b: a != b,
        "lt": lambda a, b: a is not None and a < b, "le": lambda a, b: a is not None and a <= b,
        "gt": lambda a, b: a is not None and a > b, "ge": lambda a, b: a is not None and a >= b,
        "exists": lambda a, b: a is not None,
    }

    def __init__(self, worker: "BaseWorker", runtime: "Runtime"):
        super().__init__()
        self.worker = worker
        self.runtime = runtime

    def analyze(self, context: Context, argv: CustomRecognition.AnalyzeArg):
        p = parse_param(argv.custom_recognition_param)
        cur = self.runtime.store.get_kv(self.worker.account.name, p["key"])
        ok = self._OPS[p.get("op", "eq")](cur, p.get("value"))
        return CustomRecognition.AnalyzeResult(box=(0, 0, 1, 1) if ok else None, detail={"current": cur})


class TeamFlag(CustomRecognition):
    """
    队伍黑板上存在某个键（且值为真）时命中。队员用它感知队长发出的信号（如“抓鬼结束”）。
    不在组队任务中时永远不命中。

    参数:
        key: 黑板键名
    """

    def __init__(self, worker: "BaseWorker", runtime: "Runtime"):
        super().__init__()
        self.worker = worker
        self.runtime = runtime

    def analyze(self, context: Context, argv: CustomRecognition.AnalyzeArg):
        key = parse_param(argv.custom_recognition_param).get("key", "")
        ctx = self.worker.team_context
        value = self.runtime.team.read(ctx[0], key) if ctx else None
        return CustomRecognition.AnalyzeResult(box=(0, 0, 1, 1) if value else None, detail={"value": value})
