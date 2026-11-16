"""
占位图生成工具：为 Pipeline 中引用但还不存在的模板图生成占位图（16x16 品红色），
让资源能被 MAA 正常加载，便于先跑通流程。占位图不会匹配到任何真实画面。

用法：
    python tools/make_placeholders.py            # 为 resource/base 补齐缺失的模板
    python tools/make_placeholders.py --list     # 只列出缺失/占位中的模板，不生成

截图替换方法：用 MAA 的 VSCode 插件 / MFA 工具箱 / tools/capture.py 截 1280x720 原图，
裁剪出目标区域，保存为同名文件覆盖占位图即可。
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_SIZE = 16
_COLOR = (255, 0, 255)   # 品红：游戏画面中几乎不会出现的纯色


def placeholder_png() -> bytes:
    """生成固定内容的 16x16 品红色 PNG（不依赖 PIL / OpenCV）。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    row = b"\x00" + bytes(_COLOR) * _SIZE
    raw = row * _SIZE
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", _SIZE, _SIZE, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def missing_templates(resource_dir: Path) -> list[tuple[str, bool]]:
    """
    找出 Pipeline 中引用但不存在的模板。
    返回 [(模板相对路径, 是否为文件夹)]，没有扩展名的视为文件夹。
    """
    from tools.pipeline_check import _as_list, _field, _type, check_resource

    rep = check_resource([resource_dir])
    result: list[tuple[str, bool]] = []
    for node in rep.nodes.values():
        if _type(node, "recognition") not in ("TemplateMatch", "FeatureMatch"):
            continue
        for tpl in _as_list(_field(node, "template", "recognition")):
            p = resource_dir / "image" / tpl
            is_dir = Path(tpl).suffix == ""
            if not p.exists() or (is_dir and not any(p.iterdir())):
                result.append((tpl, is_dir))
    return sorted(set(result))


def main() -> None:
    """命令行入口。"""
    ap = argparse.ArgumentParser(description="为缺失的模板图生成占位图")
    ap.add_argument("--resource", default=str(ROOT / "resource" / "base"), help="资源目录")
    ap.add_argument("--list", action="store_true", help="只列出，不生成")
    args = ap.parse_args()

    res = Path(args.resource)
    todo = missing_templates(res)
    if not todo:
        print("没有缺失的模板")
        return
    data = placeholder_png()
    for tpl, is_dir in todo:
        target = res / "image" / tpl / "占位.png" if is_dir else res / "image" / tpl
        print(("[缺失] " if args.list else "[生成] ") + str(target.relative_to(res)))
        if not args.list:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


if __name__ == "__main__":
    main()
