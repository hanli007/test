"""
调度器：根据配置和状态库，决定“某个账号 / 某个队伍现在该做哪个任务”。

判定规则（按顺序）：
    1. 任务在允许的时间窗口内
    2. 今日完成次数 < daily_limit
    3. 今日失败次数 <= max_retry（超过就放弃，等明天）
    4. 距上次失败已过 retry_cooldown_min（冷却中则跳过）
    5. 满足条件的任务中，按 priority 从小到大取第一个

组队任务的进度记在虚拟账号名 "@队伍名" 下，因为是全队一起完成的。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from .config import AppConfig, TaskConfig, TeamConfig
from .state_store import StateStore


def team_key(team: TeamConfig | str) -> str:
    """组队任务在状态库中使用的账号键。"""
    name = team if isinstance(team, str) else team.name
    return f"@{name}"


class Scheduler:
    """无状态的选择器，所有状态都在 StateStore 中。"""

    def __init__(self, config: AppConfig, store: StateStore):
        self.config = config
        self.store = store

    def is_runnable(self, owner: str, task: TaskConfig, now: datetime) -> bool:
        """
        判断某任务对某账号（或 '@队伍'）当前是否可执行。

        参数:
            owner: 账号名，或 team_key(队伍)
            task:  任务配置
            now:   当前时间
        """
        if not task.in_window(now.time()):
            return False
        prog = self.store.get_progress(owner, task.name, now)
        if prog["done_count"] >= task.daily_limit:
            return False
        if prog["fail_count"] > task.max_retry:
            return False
        if prog["last_fail_at"]:
            last_fail = datetime.fromisoformat(prog["last_fail_at"])
            if now - last_fail < timedelta(minutes=task.retry_cooldown_min):
                return False
        return True

    def _pick(self, owner: str, task_names: list[str], now: datetime) -> Optional[TaskConfig]:
        """从候选任务中选出优先级最高且可执行的一个。"""
        candidates = sorted((self.config.tasks[n] for n in task_names), key=lambda t: t.priority)
        for task in candidates:
            if self.is_runnable(owner, task, now):
                return task
        return None

    def next_solo(self, account: str, now: Optional[datetime] = None) -> Optional[TaskConfig]:
        """账号下一个要做的单人任务；没有返回 None。"""
        acc = self.config.accounts[account]
        return self._pick(account, acc.tasks, now or datetime.now())

    def next_team(self, team: str, now: Optional[datetime] = None) -> Optional[TaskConfig]:
        """队伍下一个要做的组队任务；没有返回 None。"""
        t = self.config.teams[team]
        return self._pick(team_key(t), t.tasks, now or datetime.now())

    def has_pending(self, accounts: list[str], teams: list[TeamConfig], now: Optional[datetime] = None) -> bool:
        """
        判断这些账号/队伍在“当前时间窗口内”是否还有待做任务，用于 --once 模式决定何时退出。
        处于失败冷却中的任务仍算待做（会等冷却结束重试）；不在时间窗口内的任务不算。
        """
        now = now or datetime.now()

        def pending(owner: str, names: list[str]) -> bool:
            for n in names:
                task = self.config.tasks[n]
                if not task.in_window(now.time()):
                    continue
                prog = self.store.get_progress(owner, n, now)
                if prog["done_count"] < task.daily_limit and prog["fail_count"] <= task.max_retry:
                    return True
            return False

        if any(pending(a, self.config.accounts[a].tasks) for a in accounts):
            return True
        return any(pending(team_key(t), t.tasks) for t in teams)
