"""
资源检查工具：在真正连设备之前，静态检查 Pipeline 和配置里的常见错误。

检查项：
    1. JSON 语法（支持 // 和 /* */ 注释，与 MAA 一致）
    2. 节点重名（跨文件）
    3. next / on_error 引用了不存在的节点
    4. Click.target 等引用了不存在的节点
    5. template 引用的图片/文件夹不存在，或仍是占位图
    6. Custom 识别/动作名未在 custom/__init__.py 中注册
    7. config.yaml 中任务入口节点不存在
    8. 使用了 OCR 但缺少 OCR 模型（错误，MAA 会加载失败）
    9. NeuralNetworkDetect 模型文件不存在（警告）

既可以被 main.py check 调用，也被单元测试直接使用。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

# 已注册的自定义模块名，需与 custom/__init__.py 保持一致
CUSTOM_RECOGNITIONS = {"BarBelow", "TeamRole", "KvCompare", "TeamFlag"}
CUSTOM_ACTIONS = {"TeamBarrier", "TeamPublish", "TeamWait", "SaveKv", "SaveProgress", "FarmLoop"}

# FarmLoop 参数中引用节点的字段
_FARM_NODE_KEYS = ("monster_node", "loot_node", "hp_low_node", "potion_node", "bag_full_node", "dead_node",
                   "wander_node")

_ATTR_PREFIX = re.compile(r"^(\[[A-Za-z]+\])+")
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp"}


@dataclass
class CheckReport:
    """检查结果。errors 必须修复；warnings 可运行但功能可能不正常。"""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def strip_jsonc(text: str) -> str:
    """去掉 JSON 中的 // 行注释和 /* */ 块注释（字符串内的不处理）。"""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    # 去掉尾随逗号（jsonc 常见写法）
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def load_jsonc(path: Path) -> Any:
    """读取 jsonc 文件。"""
    return json.loads(strip_jsonc(path.read_text(encoding="utf-8")))


def node_name(ref: Any) -> Optional[str]:
    """把 next 列表中的元素（"[JumpBack]A" 或 {"name": "A"}）解析成节点名。"""
    if isinstance(ref, str):
        return _ATTR_PREFIX.sub("", ref)
    if isinstance(ref, dict):
        return ref.get("name")
    return None


def _as_list(v: Any) -> list[Any]:
    """字段可能是单个值或列表，统一成列表。"""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def placeholder_bytes() -> bytes:
    """占位图的字节内容（与 tools/make_placeholders.py 生成的完全一致），用于识别“还没替换的图”。"""
    from tools.make_placeholders import placeholder_png

    return placeholder_png()


def _images_under(path: Path) -> Iterable[Path]:
    """列出文件或文件夹下的所有图片。"""
    if path.is_file():
        yield path
    elif path.is_dir():
        for p in sorted(path.rglob("*")):
            if p.suffix.lower() in _IMAGE_EXT:
                yield p


def _field(node: dict[str, Any], key: str, kind: str) -> Any:
    """
    兼容 Pipeline v1/v2 读取识别或动作参数。
    kind: "recognition" | "action"
    """
    v = node.get(kind)
    if isinstance(v, dict):    # v2 格式
        return (v.get("param") or {}).get(key)
    return node.get(key)


def _type(node: dict[str, Any], kind: str) -> str:
    """读取节点的识别/动作类型（v1/v2 兼容），默认 DirectHit / DoNothing。"""
    v = node.get(kind)
    if isinstance(v, dict):
        return v.get("type", "")
    return v or ("DirectHit" if kind == "recognition" else "DoNothing")


# v1 写法中属于“识别参数”/“动作参数”的字段，用于模拟 MAA 改类型时丢弃旧参数的行为
_RECO_KEYS = {"roi", "roi_offset", "template", "threshold", "method", "green_mask", "order_by", "index",
              "expected", "replace", "only_rec", "model", "labels", "color_filter", "engine", "lower", "upper",
              "count", "connected", "detector", "ratio", "custom_recognition", "custom_recognition_param",
              "all_of", "any_of", "box_index", "sub_name"}
_ACTION_KEYS = {"target", "target_offset", "contact", "pressure", "duration", "begin", "begin_offset", "end",
                "end_offset", "end_hold", "only_hover", "swipes", "key", "input_text", "package", "exec", "args",
                "detach", "cmd", "custom_action", "custom_action_param", "dx", "dy", "auto_up", "filename",
                "format", "quality", "shell_timeout"}


def merge_node(old: Optional[dict[str, Any]], new: dict[str, Any]) -> dict[str, Any]:
    """
    模拟 MAA 多资源叠加时同名节点的合并规则（已在 maafw 5.16 实测）：
        · 字段级合并，新值覆盖旧值
        · 若新节点改变了 recognition / action 类型，旧类型的参数全部丢弃
    """
    if not old:
        return dict(new)
    merged = dict(old)
    for kind, keys in (("recognition", _RECO_KEYS), ("action", _ACTION_KEYS)):
        if kind in new and _type(new, kind) != _type(old, kind):
            for k in keys:
                merged.pop(k, None)
    merged.update(new)
    return merged


def check_resource(resource_dirs: list[Path], entries: Iterable[str] = ()) -> CheckReport:
    """
    对一组资源目录做静态检查。

    参数:
        resource_dirs: 资源目录列表（按加载顺序）
        entries:       需要存在的入口节点名（来自 config.yaml）
    """
    rep = CheckReport()
    where: dict[str, tuple[Path, Path]] = {}
    ph = placeholder_bytes()

    # ---- 读取所有节点 ----
    for rd in resource_dirs:
        pdir = rd / "pipeline"
        if not pdir.is_dir():
            rep.errors.append(f"资源目录缺少 pipeline 文件夹：{rd}")
            continue
        for f in sorted(pdir.rglob("*.json")):
            try:
                data = load_jsonc(f)
            except (ValueError, OSError) as e:
                rep.errors.append(f"{f.name} JSON 解析失败：{e}")
                continue
            for name, node in data.items():
                if name.startswith("$"):
                    continue
                # 多资源目录叠加时同名节点是合法的“覆盖”，同一资源目录内重名才是错误
                if name in where and where[name][0] == rd and where[name][1] != f:
                    rep.errors.append(f"节点重名：{name}（{where[name][1].name} 与 {f.name}）")
                where[name] = (rd, f)
                rep.nodes[name] = merge_node(rep.nodes.get(name), node or {})

    # ---- 逐节点检查 ----
    for name, node in rep.nodes.items():
        for key in ("next", "on_error"):
            for ref in _as_list(node.get(key)):
                target = node_name(ref)
                if target not in rep.nodes:
                    rep.errors.append(f"{name}.{key} 引用了不存在的节点：{target}")

        target = _field(node, "target", "action")
        if isinstance(target, str):
            t = target.removeprefix("[Anchor]")
            if not target.startswith("[Anchor]") and t not in rep.nodes:
                rep.errors.append(f"{name}.target 引用了不存在的节点：{t}")

        reco, act = _type(node, "recognition"), _type(node, "action")
        if reco == "Custom":
            cr = _field(node, "custom_recognition", "recognition")
            if cr not in CUSTOM_RECOGNITIONS:
                rep.errors.append(f"{name} 使用了未注册的自定义识别：{cr}")
        if act == "Custom":
            ca = _field(node, "custom_action", "action")
            if ca not in CUSTOM_ACTIONS:
                rep.errors.append(f"{name} 使用了未注册的自定义动作：{ca}")
            if ca == "FarmLoop":
                param = _field(node, "custom_action_param", "action") or {}
                for k in _FARM_NODE_KEYS:
                    ref = param.get(k)
                    if ref and ref not in rep.nodes:
                        rep.errors.append(f"{name}.custom_action_param.{k} 引用了不存在的节点：{ref}")

        if reco in ("TemplateMatch", "FeatureMatch"):
            key = "template"
            for tpl in _as_list(_field(node, key, "recognition")):
                found = [p for rd in resource_dirs for p in _images_under(rd / "image" / tpl)]
                if not found:
                    rep.errors.append(f"{name} 的模板不存在：image/{tpl}")
                elif all(p.read_bytes() == ph for p in found):
                    rep.warnings.append(f"{name} 的模板仍是占位图，需要截图替换：image/{tpl}")

        if reco == "NeuralNetworkDetect" and node.get("enabled", True):
            model = _field(node, "model", "recognition")
            if not any((rd / "model" / "detect" / model).is_file() for rd in resource_dirs):
                rep.warnings.append(f"{name} 的模型不存在：model/detect/{model}（未训练前不要启用该节点）")

        if reco == "OCR":
            # 缺少 OCR 模型时 MAA 加载资源会直接失败，所以算错误
            if not any((rd / "model" / "ocr" / "rec.onnx").is_file() for rd in resource_dirs):
                msg = "OCR 模型缺失：请运行 python tools/download_ocr.py"
                if msg not in rep.errors:
                    rep.errors.append(msg)

    for e in entries:
        if e and e not in rep.nodes:
            rep.errors.append(f"config.yaml 中的入口节点不存在：{e}")
    return rep
