"""
Windows 窗口与进程工具（纯 ctypes 实现，不依赖 pywin32）。

端游和模拟器的本质区别是“脚本和游戏在同一个系统里”，所以端游需要自己处理：
    · 找窗口：按标题 / 类名正则、进程号、第 N 个匹配窗口来定位（多开同名客户端时必须区分）
    · 管进程：按 exe 路径启动客户端、按进程号或进程名结束客户端
    · 定尺寸：把窗口客户区调成固定大小（如 1280x720），保证截图比例和坐标与 Pipeline 一致

窗口筛选逻辑 select_window() 是纯函数，可以在任何平台上测试；
其余函数调用 Win32 API，只能在 Windows 上运行，其他平台调用会抛 RuntimeError。
"""

from __future__ import annotations

import ctypes
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

IS_WINDOWS = sys.platform == "win32"


@dataclass
class WindowInfo:
    """一个顶层窗口的信息。"""

    hwnd: int
    title: str
    class_name: str
    pid: int
    visible: bool


def _require_windows() -> None:
    """非 Windows 平台直接报错。"""
    if not IS_WINDOWS:
        raise RuntimeError("端游（win32）功能仅支持 Windows")


# ---------------------------------------------------------------------- 窗口

def list_windows() -> list[WindowInfo]:
    """枚举所有顶层窗口（按系统 Z 序，最上层在前）。"""
    _require_windows()
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    result: list[WindowInfo] = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        result.append(WindowInfo(int(hwnd), title.value, cls.value, int(pid.value), bool(user32.IsWindowVisible(hwnd))))
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return result


def select_window(
    windows: list[WindowInfo],
    title_pattern: str = "",
    class_pattern: str = "",
    pid: Optional[int] = None,
    index: int = 0,
) -> Optional[WindowInfo]:
    """
    从窗口列表中按条件挑出一个（纯函数，便于测试）。

    参数:
        windows:       候选窗口
        title_pattern: 标题正则，空表示不限
        class_pattern: 类名正则，空表示不限
        pid:           只要该进程的窗口；None 表示不限
        index:         多个匹配时取第几个（按句柄从小到大排序，比 Z 序稳定）
    返回:
        匹配的窗口；没有返回 None
    规则:
        只考虑可见且标题非空的窗口（隐藏的登录器、托盘窗口等会被排除）
    """
    t = re.compile(title_pattern) if title_pattern else None
    c = re.compile(class_pattern) if class_pattern else None
    matched = [
        w for w in windows
        if w.visible and w.title
        and (t is None or t.search(w.title))
        and (c is None or c.search(w.class_name))
        and (pid is None or w.pid == pid)
    ]
    matched.sort(key=lambda w: w.hwnd)
    return matched[index] if 0 <= index < len(matched) else None


def is_window(hwnd: int) -> bool:
    """窗口句柄是否仍然有效。"""
    _require_windows()
    return bool(ctypes.windll.user32.IsWindow(hwnd))


def set_client_size(hwnd: int, width: int, height: int) -> bool:
    """
    把窗口的客户区（不含标题栏和边框）调整为 width x height。
    根据当前边框尺寸反推外框大小，避免 DPI 缩放和不同系统主题造成偏差。
    """
    _require_windows()
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    win, cli = wintypes.RECT(), wintypes.RECT()
    if not (user32.GetWindowRect(hwnd, ctypes.byref(win)) and user32.GetClientRect(hwnd, ctypes.byref(cli))):
        return False
    border_w = (win.right - win.left) - (cli.right - cli.left)
    border_h = (win.bottom - win.top) - (cli.bottom - cli.top)
    SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0002, 0x0004, 0x0010
    return bool(user32.SetWindowPos(hwnd, 0, 0, 0, width + border_w, height + border_h,
                                    SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE))


def client_size(hwnd: int) -> tuple[int, int]:
    """返回窗口客户区的 (宽, 高)。"""
    _require_windows()
    from ctypes import wintypes

    cli = wintypes.RECT()
    ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(cli))
    return cli.right - cli.left, cli.bottom - cli.top


def restore_window(hwnd: int) -> None:
    """窗口最小化时恢复显示（不抢焦点）。部分截图方式在真正最小化时会黑屏。"""
    _require_windows()
    user32 = ctypes.windll.user32
    SW_SHOWNOACTIVATE = 4
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)


# ---------------------------------------------------------------------- 进程

def launch(exe_path: str, args: str = "", cwd: str = "") -> int:
    """
    启动游戏客户端，返回进程号。
    注意：很多游戏先启动“登录器/更新器”再拉起真正的游戏进程，这种情况下返回的 pid 不是游戏窗口的 pid，
    需要在配置中设置 window_title 按标题找窗口，而不是依赖 pid。
    """
    _require_windows()
    from pathlib import Path

    cmd = [exe_path, *(_split_args(args))]
    work_dir = cwd or str(Path(exe_path).parent)
    # DETACHED_PROCESS：客户端不依附本程序的控制台，本程序退出时游戏不会跟着退出
    proc = subprocess.Popen(cmd, cwd=work_dir, creationflags=0x00000008)
    return proc.pid


def _split_args(args: str) -> list[str]:
    """按 Windows 规则拆分命令行参数。"""
    if not args:
        return []
    import shlex

    return shlex.split(args, posix=False)


def kill_pid(pid: int) -> bool:
    """强制结束进程（含子进程）。"""
    _require_windows()
    r = subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, text=True)
    return r.returncode == 0


def kill_name(process_name: str) -> bool:
    """按进程名强制结束所有同名进程（如 my.exe）。多开时会全部结束，慎用。"""
    _require_windows()
    r = subprocess.run(["taskkill", "/F", "/T", "/IM", process_name], capture_output=True, text=True)
    return r.returncode == 0


def is_admin() -> bool:
    """当前进程是否以管理员身份运行。游戏以管理员运行时，本程序也必须以管理员运行，否则输入会被系统拦截。"""
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False
