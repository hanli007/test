"""
截图采集工具：连接某个账号的设备，按固定间隔截图保存（已缩放到 1280x720，与 MAA 识别坐标一致）。

两个用途：
    1. 制作模板图：截下原图后用画图工具裁剪出按钮/图标
    2. 采集 YOLO 训练集：挂着游戏跑一段时间，得到大量不同场景的截图，再去标注

用法：
    python tools/capture.py 账号名 --count 200 --interval 2 --out dataset/images
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def save_png(image, path: Path) -> None:
    """把 MAA 返回的 BGR numpy 图像保存为 PNG（不依赖 OpenCV）。"""
    import struct
    import zlib

    h, w = image.shape[:2]
    rgb = image[:, :, ::-1].astype("uint8")   # BGR → RGB
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    """命令行入口。"""
    from core.config import load_config
    from core.runtime import Runtime
    from core.state_store import StateStore
    from core.team import TeamCoordinator
    from core.worker import MaaWorker

    ap = argparse.ArgumentParser(description="设备截图采集")
    ap.add_argument("account", help="config.yaml 中的账号名")
    ap.add_argument("-c", "--config", default=str(ROOT / "config" / "config.yaml"))
    ap.add_argument("--count", type=int, default=1, help="截图张数")
    ap.add_argument("--interval", type=float, default=2.0, help="间隔秒数")
    ap.add_argument("--out", default=str(ROOT / "captures"), help="输出目录")
    args = ap.parse_args()

    cfg = load_config(args.config)
    acc = cfg.accounts[args.account]
    runtime = Runtime(cfg, StateStore(":memory:"), TeamCoordinator())
    worker = MaaWorker(acc, cfg, runtime)
    if not worker.connect():
        sys.exit("连接设备失败")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for i in range(args.count):
        img = worker.screencap()
        name = out / f"{args.account}_{datetime.now():%Y%m%d_%H%M%S}_{i:04d}.png"
        save_png(img, name)
        print(f"[{i + 1}/{args.count}] {name}  {img.shape[1]}x{img.shape[0]}")
        if i + 1 < args.count:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
