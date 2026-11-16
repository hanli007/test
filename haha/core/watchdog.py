"""
看门狗：独立线程，定期巡检所有正在执行任务的 Worker。

判定卡死的两种情况：
    1. 心跳超时：stuck_sec 秒内没有进入任何新节点（画面卡住、弹窗挡住、识别一直失败但没超时等）
    2. 任务超时：单次任务运行超过 task.timeout_min 分钟

处理方式：调用 worker.stop() 让当前任务退出，并把该账号标记为“需要恢复”。
真正的恢复动作（重启游戏 → 重启模拟器）由 orchestrator 在任务返回后执行，
这样不会在任务线程还在跑的时候去动设备，避免并发冲突。
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from .logger import get_logger
from .worker import BaseWorker

log = get_logger("watchdog")


class Watchdog:
    """卡死检测线程。"""

    def __init__(self, workers: dict[str, BaseWorker], stuck_sec: float, on_stuck: Callable[[str, str], None],
                 interval: float = 5.0):
        """
        参数:
            workers:   账号名 -> Worker
            stuck_sec: 心跳超时阈值（秒）
            on_stuck:  判定卡死后的回调 (账号名, 原因)，由 orchestrator 记录“需要恢复”
            interval:  巡检间隔（秒）
        """
        self.workers = workers
        self.stuck_sec = stuck_sec
        self.on_stuck = on_stuck
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="watchdog", daemon=True)

    def start(self) -> None:
        """启动巡检线程。"""
        self._thread.start()

    def shutdown(self) -> None:
        """停止巡检线程。"""
        self._stop.set()
        self._thread.join(timeout=self.interval * 2)

    def check_once(self) -> list[str]:
        """
        执行一次巡检，返回本次判定为卡死的账号名列表（便于单元测试）。
        """
        stuck: list[str] = []
        now = time.monotonic()
        for name, w in self.workers.items():
            if not w.busy:
                continue
            reason = ""
            if w.idle_seconds > self.stuck_sec:
                reason = f"{int(w.idle_seconds)} 秒无进展，卡在节点 {w.current_node or '?'}"
            elif w.task_started is not None and w.task_timeout and now - w.task_started > w.task_timeout:
                reason = f"任务 {w.current_task} 超过 {int(w.task_timeout // 60)} 分钟"
            if reason:
                log.warning("[%s] 判定卡死：%s，强制停止", name, reason)
                stuck.append(name)
                self.on_stuck(name, reason)
                w.stop()
        return stuck

    def _loop(self) -> None:
        """巡检主循环。"""
        while not self._stop.wait(self.interval):
            try:
                self.check_once()
            except Exception:  # noqa: BLE001 - 看门狗自身绝不能崩
                log.exception("巡检异常")
