"""
OCR 模型下载工具：从 MaaCommonAssets 下载 PaddleOCR v5 中文模型（ONNX），
放到 resource/base/model/ocr/ 下（det.onnx、rec.onnx、keys.txt），约 21MB。

用法：
    python tools/download_ocr.py
    python tools/download_ocr.py --mirror https://ghfast.top/   # 国内网络慢时加 GitHub 加速前缀
"""

from __future__ import annotations

import argparse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "https://raw.githubusercontent.com/MaaXYZ/MaaCommonAssets/main/OCR/ppocr_v5/zh_cn/"
FILES = ["det.onnx", "rec.onnx", "keys.txt"]


def download(url: str, dest: Path) -> None:
    """下载单个文件，先写临时文件再改名，避免中断留下损坏文件。"""
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 16):
            f.write(chunk)
    tmp.replace(dest)


def main() -> None:
    """命令行入口。"""
    ap = argparse.ArgumentParser(description="下载 OCR 模型")
    ap.add_argument("--dest", default=str(ROOT / "resource" / "base" / "model" / "ocr"), help="保存目录")
    ap.add_argument("--mirror", default="", help="GitHub 加速前缀，如 https://ghfast.top/")
    ap.add_argument("--force", action="store_true", help="已存在也重新下载")
    args = ap.parse_args()

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = dest / name
        if target.exists() and not args.force:
            print(f"[跳过] {name} 已存在")
            continue
        url = args.mirror + BASE_URL + name
        print(f"[下载] {url}")
        download(url, target)
        print(f"       → {target}（{target.stat().st_size // 1024} KB）")


if __name__ == "__main__":
    main()
