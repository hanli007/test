"""
端游客户端管理：负责“找到账号对应的游戏窗口”，找不到就启动客户端，卡死时重启客户端。

和模拟器的 EmulatorManager 对应：
    模拟器   EmulatorManager  启动/重启模拟器实例 → 通过 adb 地址连接
    端游     PcClientManager  启动/重启游戏进程   → 通过窗口句柄连接

多开同名客户端时如何区分窗口（按优先级）：
    1. 本程序启动的客户端：记住窗口所属进程号，之后只认这个进程的窗口
    2. 配置了 window_index：取第 N 个匹配窗口（按句柄排序）
    3. 都没有：取第一个“还没被其他账号占用”的匹配窗口
"""

from __future__ import annotations

import threading
import time
from types import ModuleType
from typing import Optional

from . import win32 as _win32
from .config import AccountConfig
from .logger import get_logger

log = get_logger("pc")


class PcClientManager:
    """端游窗口与进程管理，线程安全。"""

    def __init__(self, backend: ModuleType | object = _win32, poll_sec: float = 2.0):
        """
        参数:
            backend:  提供 list_windows / launch / kill_pid / kill_name / is_window / set_client_size /
                      restore_window / client_size 的对象，默认是 core.win32；测试时可注入假实现
            poll_sec: 等待窗口出现时的轮询间隔
        """
        self.api = backend
        self.poll_sec = poll_sec
        self._claimed: dict[str, _win32.WindowInfo] = {}   # 账号名 -> 已绑定窗口
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ 查找

    def _others_hwnds(self, account: str) -> set[int]:
        """其他账号已占用的窗口句柄。"""
        return {w.hwnd for name, w in self._claimed.items() if name != account}

    def find(self, acc: AccountConfig, exclude_pids: frozenset[int] = frozenset()) -> Optional[_win32.WindowInfo]:
        """
        按账号配置查找窗口（不启动客户端）。

        参数:
            acc:          账号配置
            exclude_pids: 需要排除的进程号（启动新客户端时排除已存在的同名进程）
        """
        dev = acc.device
        with self._lock:
            windows = [w for w in self.api.list_windows() if w.pid not in exclude_pids]
            prev = self._claimed.get(acc.name)
            # 1. 已绑定过的进程：只认该进程的窗口（客户端可能重建窗口，句柄会变，进程号不变）
            if prev is not None:
                w = _win32.select_window(windows, dev.window_title, dev.window_class, pid=prev.pid)
                if w is not None:
                    return w
            # 2. 指定序号
            if dev.window_index is not None:
                return _win32.select_window(windows, dev.window_title, dev.window_class, index=dev.window_index)
            # 3. 第一个未被占用的
            taken = self._others_hwnds(acc.name)
            free = [w for w in windows if w.hwnd not in taken]
            return _win32.select_window(free, dev.window_title, dev.window_class)

    # ------------------------------------------------------------------ 启动 / 绑定

    def _claim(self, acc: AccountConfig, w: _win32.WindowInfo) -> int:
        """绑定窗口到账号，并做连接前准备：恢复最小化、调整客户区尺寸。"""
        dev = acc.device
        self._claimed[acc.name] = w
        self.api.restore_window(w.hwnd)
        if dev.client_size:
            width, height = dev.client_size
            if tuple(self.api.client_size(w.hwnd)) != (width, height):
                if not self.api.set_client_size(w.hwnd, width, height):
                    log.warning("[%s] 调整窗口尺寸失败（游戏可能锁定了窗口大小）", acc.name)
        log.info("[%s] 绑定窗口 %r（hwnd=%s, pid=%s）", acc.name, w.title, w.hwnd, w.pid)
        return w.hwnd

    def ensure_running(self, acc: AccountConfig) -> Optional[int]:
        """
        确保账号的游戏窗口存在并返回句柄：已有窗口直接绑定；没有且配置了 exe_path 则启动客户端并等待窗口出现。

        返回:
            窗口句柄；失败返回 None
        """
        dev = acc.device
        with self._lock:
            w = self.find(acc)
            if w is not None:
                return self._claim(acc, w)
            if not dev.exe_path:
                log.error("[%s] 找不到窗口（标题 %r），且未配置 exe_path，无法自动启动", acc.name, dev.window_title)
                return None
            # 启动前记下已存在的同名窗口所属进程，新窗口必须来自新进程，避免抢到别的账号的窗口
            existing = frozenset(x.pid for x in self.api.list_windows()
                                 if _win32.select_window([x], dev.window_title, dev.window_class))
            log.info("[%s] 启动客户端 %s %s", acc.name, dev.exe_path, dev.exe_args)
            try:
                self.api.launch(dev.exe_path, dev.exe_args, dev.work_dir)
            except OSError as e:
                log.error("[%s] 启动失败：%s", acc.name, e)
                return None

        # 等待窗口出现时释放锁，允许其他账号同时启动
        deadline = time.monotonic() + dev.launch_wait_sec
        while time.monotonic() < deadline:
            time.sleep(self.poll_sec)
            with self._lock:
                w = self.find(acc, exclude_pids=existing)
                if w is not None:
                    return self._claim(acc, w)
        log.error("[%s] %s 秒内未出现游戏窗口", acc.name, dev.launch_wait_sec)
        return None

    # ------------------------------------------------------------------ 关闭 / 重启

    def close(self, acc: AccountConfig) -> None:
        """
        关闭账号的客户端：优先按已绑定窗口的进程号结束（只影响这一个号）；
        没有绑定记录时才按 process_name 结束（会结束所有同名进程，多开时慎用）。
        """
        with self._lock:
            w = self._claimed.pop(acc.name, None)
        if w is not None:
            log.info("[%s] 结束客户端进程 %s", acc.name, w.pid)
            self.api.kill_pid(w.pid)
        elif acc.device.process_name:
            log.warning("[%s] 无绑定记录，按进程名结束 %s", acc.name, acc.device.process_name)
            self.api.kill_name(acc.device.process_name)

    def restart(self, acc: AccountConfig, wait_sec: float = 5.0) -> Optional[int]:
        """重启客户端并返回新窗口句柄（看门狗恢复时调用）。"""
        if not acc.device.exe_path:
            log.error("[%s] 未配置 exe_path，无法重启客户端", acc.name)
            return None
        self.close(acc)
        time.sleep(wait_sec)
        return self.ensure_running(acc)

    def alive(self, acc: AccountConfig) -> bool:
        """账号绑定的窗口是否仍然存在。"""
        with self._lock:
            w = self._claimed.get(acc.name)
        return w is not None and bool(self.api.is_window(w.hwnd))

    def release(self, acc: AccountConfig) -> None:
        """解除绑定（不结束进程）。"""
        with self._lock:
            self._claimed.pop(acc.name, None)
