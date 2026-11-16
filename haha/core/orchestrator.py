"""
编排器：整个程序的“大脑”，把配置、调度器、Worker、队伍协调器、看门狗串起来。

运行模型：
    · 每个队伍是一个“单元”，每个不在队伍里的账号也是一个“单元”，每个单元一个线程。
    · 队伍单元：优先做组队任务（全员并行执行各自角色的入口，靠 TeamCoordinator 同步）；
               没有组队任务时，队员们并行做各自的单人任务。
    · 单人单元：循环做自己的单人任务。
    · 并发数受 max_parallel 限制（按账号数计），组队任务一次性申请全队名额，避免只上线一半人。
    · 看门狗发现卡死 → 停止任务 → 任务返回后由本模块执行恢复：先重启游戏，不行再重启模拟器。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Optional

from .config import AccountConfig, AppConfig, TaskConfig, TeamConfig
from .emulator import EmulatorManager
from .logger import get_logger
from .runtime import Runtime
from .scheduler import Scheduler, team_key
from .state_store import StateStore
from .team import TeamCoordinator
from .watchdog import Watchdog
from .worker import BaseWorker, TaskResult, create_worker

log = get_logger("orchestrator")


class SlotPool:
    """
    并发名额池。与 Semaphore 的区别：可以一次性原子地申请 n 个名额，
    保证组队任务要么全员拿到名额，要么都不拿，不会出现“抢到一半互相等”的死锁。
    """

    def __init__(self, size: int):
        self.size = size
        self._free = size
        self._cond = threading.Condition()

    def acquire(self, n: int, stop: threading.Event) -> bool:
        """申请 n 个名额；收到停止信号返回 False。n 大于池子总量时按总量申请。"""
        n = min(n, self.size)
        with self._cond:
            while self._free < n:
                if stop.is_set():
                    return False
                self._cond.wait(0.5)
            self._free -= n
            return True

    def release(self, n: int) -> None:
        """归还 n 个名额。"""
        n = min(n, self.size)
        with self._cond:
            self._free += n
            self._cond.notify_all()


class Orchestrator:
    """编排器主类。"""

    def __init__(self, config: AppConfig, dry_run: bool = False, store: Optional[StateStore] = None):
        """
        参数:
            config:  已加载的配置
            dry_run: 演练模式，使用 FakeWorker，不连接设备
            store:   可注入状态库（测试用），默认按配置创建
        """
        self.config = config
        self.dry_run = dry_run
        g = config.global_
        self.store = store or StateStore(config.resolve(g.state_db), g.daily_reset_hour)
        self.team = TeamCoordinator()
        self.runtime = Runtime(config, self.store, self.team)
        self.scheduler = Scheduler(config, self.store)
        self.emulator = EmulatorManager(config.emulator)
        self.slots = SlotPool(g.max_parallel)
        self.stop_event = threading.Event()

        self.workers: dict[str, BaseWorker] = {
            name: create_worker(acc, config, self.runtime, dry_run)
            for name, acc in config.accounts.items()
            if acc.enabled
        }
        for t in config.teams.values():
            self.team.register(t.name, t.all_accounts)

        self._need_recover: dict[str, str] = {}          # 账号名 -> 卡死原因
        self._recover_count: dict[tuple[str, str], int] = {}  # (游戏日, 账号) -> 当日已恢复次数
        self._guard = threading.Lock()
        self.watchdog = Watchdog(self.workers, g.stuck_sec, self._mark_stuck)
        self._threads: list[threading.Thread] = []

    # ================================================================== 生命周期

    def run(self, once: bool = False) -> None:
        """
        启动所有单元线程并阻塞，直到 shutdown() 被调用（或 once 模式下全部完成）。

        参数:
            once: True 表示做完当前能做的任务就退出；False 表示常驻，按时间窗口持续调度
        """
        self.watchdog.start()
        for team in self.config.teams.values():
            if all(n in self.workers for n in team.all_accounts):
                self._spawn(f"team-{team.name}", self._team_loop, team, once)
            else:
                log.warning("队伍 %s 有账号被禁用，跳过该队伍", team.name)
        for name, acc in self.config.accounts.items():
            if name in self.workers and self.config.team_of(name) is None:
                self._spawn(f"solo-{name}", self._solo_loop, acc, once)

        try:
            while any(t.is_alive() for t in self._threads):
                if self.stop_event.wait(0.5):
                    break
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """停止所有任务和线程（Ctrl+C 时调用）。可重复调用。"""
        if not self.stop_event.is_set():
            log.info("正在停止……")
        self.stop_event.set()
        for w in self.workers.values():
            if w.busy:
                w.stop()
        for t in self.team.names():   # 唤醒所有阻塞在同步点的线程
            self.team.abort(t, "程序退出")
        for t in self._threads:
            t.join(timeout=10)
        self.watchdog.shutdown()

    def _spawn(self, name: str, target, *args) -> None:
        """启动一个守护线程并记录。"""
        t = threading.Thread(target=self._guarded, args=(target, *args), name=name, daemon=True)
        self._threads.append(t)
        t.start()

    def _guarded(self, target, *args) -> None:
        """线程入口包装：单元线程异常时记录日志并在一段时间后重新进入循环，不拖垮整个程序。"""
        while not self.stop_event.is_set():
            try:
                target(*args)
                return
            except Exception:  # noqa: BLE001
                log.exception("单元线程异常，60 秒后重试")
                self.stop_event.wait(60)

    # ================================================================== 单元循环

    def _solo_loop(self, acc: AccountConfig, once: bool) -> None:
        """单人单元：循环选择并执行单人任务。"""
        while not self.stop_event.is_set():
            task = self.scheduler.next_solo(acc.name)
            if task is not None:
                self._run_solo(acc.name, task)
                continue
            if once and not self.scheduler.has_pending([acc.name], []):
                log.info("[%s] 当前没有待做任务，退出", acc.name)
                return
            self.stop_event.wait(self.config.global_.loop_interval_sec)

    def _team_loop(self, team: TeamConfig, once: bool) -> None:
        """队伍单元：优先组队任务，其次队员各自的单人任务。"""
        while not self.stop_event.is_set():
            task = self.scheduler.next_team(team.name)
            if task is not None:
                self._run_team(team, task)
                continue
            # 没有组队任务时，队员并行做各自的单人任务（每人一轮）
            solo_jobs = [(n, self.scheduler.next_solo(n)) for n in team.all_accounts]
            solo_jobs = [(n, t) for n, t in solo_jobs if t is not None]
            if solo_jobs:
                threads = [threading.Thread(target=self._run_solo, args=(n, t), name=f"solo-{n}") for n, t in solo_jobs]
                for th in threads:
                    th.start()
                for th in threads:
                    th.join()
                continue
            if once and not self.scheduler.has_pending(team.all_accounts, [team]):
                log.info("[%s] 当前没有待做任务，退出", team.name)
                return
            self.stop_event.wait(self.config.global_.loop_interval_sec)

    # ================================================================== 执行

    def _prepare(self, name: str) -> bool:
        """确保账号的设备已启动且 Worker 已连接。"""
        w = self.workers[name]
        dev = w.account.device
        if not self.dry_run and dev.type == "adb" and dev.emulator_index is not None:
            if not self.emulator.launch(dev.emulator_index, dev.address):
                return False
        return w.connected or w.connect()

    def _execute(self, name: str, task: TaskConfig, entry: str) -> TaskResult:
        """
        在指定账号上执行一次入口，负责计时、心跳、写运行流水，以及执行后的卡死恢复。
        不负责记 progress（单人/组队记账方式不同，由调用方处理）。
        """
        w = self.workers[name]
        started = datetime.now()
        w.current_task = task.name
        w.task_started = time.monotonic()
        w.task_timeout = task.timeout_min * 60
        w.log.info("开始 %s（入口 %s）", task.name, entry)
        try:
            result = w.run_task(entry, task.override)
        finally:
            w.task_started = None
            w.task_timeout = None
        stuck_reason = self._pop_stuck(name)
        if stuck_reason:
            result = TaskResult(False, f"看门狗中止：{stuck_reason}", result.last_node)
            self._recover(name)
        w.log.info("%s %s：%s（最后节点 %s）", task.name, "成功" if result.success else "失败",
                   result.message, result.last_node or "-")
        self.store.log_run(name, task.name, started, datetime.now(), result.success, result.message)
        return result

    def _run_solo(self, name: str, task: TaskConfig) -> None:
        """执行一次单人任务并记账。"""
        if not self.slots.acquire(1, self.stop_event):
            return
        try:
            if not self._prepare(name):
                self.store.mark_fail(name, task.name)
                return
            result = self._execute(name, task, task.entry)
            if self.stop_event.is_set() and not result.success:
                return   # 程序退出导致的中断不计失败
            if result.success:
                self.store.mark_done(name, task.name)
            else:
                self.store.mark_fail(name, task.name)
        finally:
            self.slots.release(1)

    def _run_team(self, team: TeamConfig, task: TaskConfig) -> None:
        """
        执行一轮组队任务：
            1. 一次性申请全队并发名额
            2. 确保全员设备就绪，任何一人失败则本轮记失败
            3. 队长执行 leader_entry，队员执行 member_entry，并行运行
            4. 任一账号失败 → abort 整队（其他人在同步点会立刻返回失败）
            5. 全员成功才记一次完成
        """
        members = team.all_accounts
        if not self.slots.acquire(len(members), self.stop_event):
            return
        key = team_key(team)
        try:
            not_ready = [n for n in members if not self._prepare(n)]
            if not_ready:
                log.error("[%s] 账号未就绪：%s，本轮跳过", team.name, not_ready)
                self.store.mark_fail(key, task.name)
                return

            self.team.begin_round(team.name)
            results: dict[str, TaskResult] = {}

            def member_run(n: str) -> None:
                role = "leader" if n == team.leader else "member"
                w = self.workers[n]
                w.team_context = (team.name, role)
                try:
                    entry = task.leader_entry if role == "leader" else task.member_entry
                    res = self._execute(n, task, entry)
                    results[n] = res
                    if not res.success:
                        self.team.abort(team.name, f"{n} 失败：{res.message}")
                        # 队友可能卡在不经过同步点的节点上，主动叫停
                        for other in members:
                            if other != n and self.workers[other].busy:
                                self.workers[other].stop()
                finally:
                    w.team_context = None

            threads = [threading.Thread(target=member_run, args=(n,), name=f"{team.name}-{n}") for n in members]
            for th in threads:
                th.start()
            for th in threads:
                th.join()

            if self.stop_event.is_set():
                return
            if all(r.success for r in results.values()) and len(results) == len(members):
                self.store.mark_done(key, task.name)
                log.info("[%s] 组队任务 %s 完成", team.name, task.name)
            else:
                self.store.mark_fail(key, task.name)
                log.warning("[%s] 组队任务 %s 失败：%s", team.name, task.name,
                            self.team.aborted_reason(team.name))
        finally:
            self.slots.release(len(members))

    # ================================================================== 卡死恢复

    def _mark_stuck(self, name: str, reason: str) -> None:
        """看门狗回调：记录需要恢复的账号；若在组队中，同时中止整队。"""
        with self._guard:
            self._need_recover[name] = reason
        ctx = self.workers[name].team_context
        if ctx:
            self.team.abort(ctx[0], f"{name} 卡死：{reason}")

    def _pop_stuck(self, name: str) -> Optional[str]:
        """取出并清除账号的卡死标记。"""
        with self._guard:
            return self._need_recover.pop(name, None)

    def _recover(self, name: str) -> bool:
        """
        卡死恢复，逐级升级：
            1. 重启游戏客户端（端游：结束进程后按 exe_path 重新启动）
            2. 仍未连接 → 重启模拟器并重连（仅模拟器）
        每个账号每天最多恢复 max_recover 次，超过后不再尝试（避免无限重启）。
        """
        day = self.store.today()
        with self._guard:
            cnt = self._recover_count.get((day, name), 0)
            if cnt >= self.config.global_.max_recover:
                log.error("[%s] 今日恢复次数已达上限 %d，不再自动恢复", name, cnt)
                return False
            self._recover_count[(day, name)] = cnt + 1

        w = self.workers[name]
        w.log.warning("开始第 %d 次恢复", cnt + 1)
        dev = w.account.device
        if dev.type == "win32":
            # 端游：窗口闪退或卡死都直接重启客户端进程
            return w.restart_app()
        if w.connected and w.restart_app():
            return True
        if not self.dry_run and dev.type == "adb" and dev.emulator_index is not None:
            if self.emulator.restart(dev.emulator_index, dev.address):
                if hasattr(w, "reset"):
                    w.reset()
                return w.connect()
        return False
