"""
模拟器管理：负责启动/关闭/重启模拟器实例，并等待 adb 设备就绪。

不同模拟器的命令行工具不同，因此通过配置里的命令模板适配，{index} 会替换为实例序号：
    MuMu 12 : launch_cmd   = '"C:/Program Files/Netease/MuMu/nx_main/MuMuManager.exe" control -v {index} launch'
              shutdown_cmd = '"C:/Program Files/Netease/MuMu/nx_main/MuMuManager.exe" control -v {index} shutdown'
    雷电 9   : launch_cmd   = '"D:/leidian/LDPlayer9/ldconsole.exe" launch --index {index}'
              shutdown_cmd = '"D:/leidian/LDPlayer9/ldconsole.exe" quit --index {index}'
"""

from __future__ import annotations

import shlex
import subprocess
import sys
import threading
import time

from .config import EmulatorConfig
from .logger import get_logger

log = get_logger("emulator")


class EmulatorManager:
    """模拟器实例的启动、关闭、健康检查。同一实例的操作通过锁串行化，避免多线程同时重启。"""

    def __init__(self, cfg: EmulatorConfig):
        self.cfg = cfg
        self._locks: dict[int, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ------------------------------------------------------------------ 内部工具

    def _lock(self, index: int) -> threading.Lock:
        """获取某个实例专属的锁。"""
        with self._locks_guard:
            return self._locks.setdefault(index, threading.Lock())

    def _run(self, cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
        """执行一条命令行；Windows 下直接交给 shell 解析带空格的路径。"""
        args = cmd if sys.platform == "win32" else shlex.split(cmd)
        return subprocess.run(
            args, shell=sys.platform == "win32", capture_output=True, text=True, timeout=timeout
        )

    def _adb(self, *args: str, timeout: int = 15) -> subprocess.CompletedProcess:
        """执行一条 adb 命令。"""
        return subprocess.run([self.cfg.adb_path, *args], capture_output=True, text=True, timeout=timeout)

    # ------------------------------------------------------------------ 对外接口

    def is_device_ready(self, address: str) -> bool:
        """
        判断 adb 设备是否已连接且安卓系统启动完成（sys.boot_completed == 1）。
        """
        try:
            self._adb("connect", address, timeout=10)
            r = self._adb("-s", address, "shell", "getprop", "sys.boot_completed", timeout=10)
            return r.returncode == 0 and r.stdout.strip() == "1"
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            log.debug("检查设备 %s 失败：%s", address, e)
            return False

    def launch(self, index: int, address: str) -> bool:
        """
        启动模拟器实例并等待就绪。设备已就绪则直接返回。

        参数:
            index:   模拟器实例序号
            address: 该实例对应的 adb 地址
        返回:
            是否在 boot_wait_sec 内就绪
        """
        with self._lock(index):
            if self.is_device_ready(address):
                return True
            if not self.cfg.launch_cmd:
                log.warning("未配置 emulator.launch_cmd，无法自动启动实例 %s，请手动打开", index)
                return False
            log.info("启动模拟器实例 %s", index)
            try:
                self._run(self.cfg.launch_cmd.format(index=index))
            except (subprocess.TimeoutExpired, OSError) as e:
                log.error("启动实例 %s 命令执行失败：%s", index, e)
                return False
            deadline = time.monotonic() + self.cfg.boot_wait_sec
            while time.monotonic() < deadline:
                if self.is_device_ready(address):
                    log.info("实例 %s 已就绪（%s）", index, address)
                    return True
                time.sleep(3)
            log.error("实例 %s 在 %s 秒内未就绪", index, self.cfg.boot_wait_sec)
            return False

    def shutdown(self, index: int) -> None:
        """关闭模拟器实例。"""
        with self._lock(index):
            if not self.cfg.shutdown_cmd:
                log.warning("未配置 emulator.shutdown_cmd，无法关闭实例 %s", index)
                return
            log.info("关闭模拟器实例 %s", index)
            try:
                self._run(self.cfg.shutdown_cmd.format(index=index))
            except (subprocess.TimeoutExpired, OSError) as e:
                log.error("关闭实例 %s 失败：%s", index, e)

    def restart(self, index: int, address: str) -> bool:
        """重启模拟器实例（看门狗在设备卡死时调用）。"""
        self.shutdown(index)
        time.sleep(5)
        return self.launch(index, address)
