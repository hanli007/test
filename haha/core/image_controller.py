"""
图片目录控制器：用一组截图代替真实设备，离线调试 Pipeline 和跑自动化测试。

MAA 自带的 DbgController 不在 pip 发行包中，因此基于 MAA 的 CustomController 自己实现：
    · screencap()  按文件名顺序轮播目录中的 PNG（单个文件则一直返回它）
    · click 等输入 只记录到 self.actions，不做任何事，便于断言“点了哪里”

截图请用 tools/capture.py 采集（1280x720 PNG），或自行准备 8 位 RGB/RGBA、非隔行扫描的 PNG。
"""

from __future__ import annotations

import struct
import threading
import zlib
from pathlib import Path
from typing import Optional

import numpy as np
from maa.controller import CustomController
from maa.define import MaaControllerFeatureEnum


def read_png(path: Path) -> np.ndarray:
    """
    解码 PNG 为 BGR numpy 数组（不依赖 OpenCV / PIL）。
    支持 8 位 RGB(2) / RGBA(6) / 灰度(0)，非隔行扫描；其他格式请先另存为普通 PNG。
    """
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} 不是 PNG 文件")
    pos, idat = 8, bytearray()
    width = height = bit_depth = color_type = interlace = 0
    while pos < len(data):
        length, tag = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
        pos += 12 + length

    channels = {0: 1, 2: 3, 6: 4}.get(color_type)
    if bit_depth != 8 or channels is None or interlace:
        raise ValueError(f"{path}：仅支持 8 位 RGB/RGBA/灰度、非隔行扫描的 PNG")

    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = np.zeros((height, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.int32)
    for y in range(height):
        f = raw[y * (stride + 1)]
        line = np.frombuffer(raw, np.uint8, stride, y * (stride + 1) + 1).astype(np.int32)
        if f == 0:                       # None
            cur = line
        elif f == 2:                     # Up
            cur = (line + prev) & 0xFF
        else:                            # Sub / Average / Paeth 需要逐像素依赖左侧，退化为逐字节计算
            cur = np.zeros(stride, dtype=np.int32)
            for i in range(stride):
                a = cur[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                if f == 1:
                    pred = a
                elif f == 3:
                    pred = (a + b) >> 1
                else:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                cur[i] = (line[i] + pred) & 0xFF
        out[y] = cur
        prev = cur

    img = out.reshape(height, width, channels)
    if channels == 1:
        img = np.repeat(img, 3, axis=2)
    return np.ascontiguousarray(img[:, :, 2::-1] if channels >= 3 else img)   # RGB(A) → BGR


class ImageFolderController(CustomController):
    """轮播图片目录的“假设备”。"""

    def __init__(self, path: Path):
        """
        参数:
            path: 图片目录或单个 PNG 文件
        """
        super().__init__()
        self.path = Path(path)
        self.frames: list[np.ndarray] = []
        self.index = 0
        self.actions: list[tuple] = []    # 记录收到的所有输入，测试时用于断言
        self._lock = threading.Lock()

    # ---- 连接 ----

    def connect(self) -> bool:
        """加载全部图片。目录为空或不存在返回 False。"""
        files = [self.path] if self.path.is_file() else sorted(self.path.glob("*.png"))
        self.frames = [read_png(f) for f in files]
        return bool(self.frames)

    def request_uuid(self) -> str:
        return f"image-folder:{self.path}"

    def get_features(self) -> int:
        # 直接使用 click / swipe 回调，而不是拆成 touch_down + touch_up
        return MaaControllerFeatureEnum.Null

    # ---- 截图 ----

    def screencap(self) -> np.ndarray:
        """返回下一帧。"""
        with self._lock:
            img = self.frames[self.index % len(self.frames)]
            if len(self.frames) > 1:
                self.index += 1
            return img

    # ---- 输入：全部只记录 ----

    def _record(self, *a) -> bool:
        with self._lock:
            self.actions.append(a)
        return True

    def start_app(self, intent: str) -> bool:
        return self._record("start_app", intent)

    def stop_app(self, intent: str) -> bool:
        return self._record("stop_app", intent)

    def click(self, x: int, y: int) -> bool:
        return self._record("click", x, y)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int) -> bool:
        return self._record("swipe", x1, y1, x2, y2, duration)

    def touch_down(self, contact: int, x: int, y: int, pressure: int) -> bool:
        return self._record("touch_down", contact, x, y)

    def touch_move(self, contact: int, x: int, y: int, pressure: int) -> bool:
        return self._record("touch_move", contact, x, y)

    def touch_up(self, contact: int) -> bool:
        return self._record("touch_up", contact)

    def click_key(self, keycode: int) -> bool:
        return self._record("click_key", keycode)

    def input_text(self, text: str) -> bool:
        return self._record("input_text", text)

    def key_down(self, keycode: int) -> bool:
        return self._record("key_down", keycode)

    def key_up(self, keycode: int) -> bool:
        return self._record("key_up", keycode)

    def clicks(self) -> list[tuple[int, int]]:
        """返回记录到的所有点击坐标。"""
        with self._lock:
            return [(a[1], a[2]) for a in self.actions if a[0] == "click"]

    def shell(self, cmd: str, timeout: int) -> Optional[str]:
        return ""
