"""
队伍协调器：解决“多个账号（多个 MAA 实例）之间如何同步”的问题。

MAA 的 Pipeline 只管单个实例，组队玩法（梦幻/问道的 5 人队）需要：
    1. 同步点（barrier）：例如“全员到达 NPC 处”“全员进入战斗”后才继续，谁先到谁等。
    2. 共享黑板（blackboard）：队长把信息写进去（如当前任务目标、坐标），队员读取。
    3. 全队中止（abort）：任意一个号出错，通知其他号别再等了，整队停下来重试。

在 Pipeline 中通过自定义动作 TeamBarrier / TeamPublish / TeamWait 使用，见 custom/actions.py。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .logger import get_logger

log = get_logger("team")


@dataclass
class _TeamState:
    """单个队伍的运行时状态。"""

    members: set[str]                                     # 全部成员账号名
    cond: threading.Condition = field(default_factory=threading.Condition)
    arrived: dict[str, set[str]] = field(default_factory=dict)    # 同步点 -> 已到达的账号
    generation: dict[str, int] = field(default_factory=dict)      # 同步点 -> 第几轮（支持循环里重复使用同一个同步点）
    board: dict[str, Any] = field(default_factory=dict)           # 共享黑板
    aborted: Optional[str] = None                         # 非空表示本轮已中止，值为原因


class TeamCoordinator:
    """所有队伍的同步中心，线程安全。"""

    def __init__(self):
        self._teams: dict[str, _TeamState] = {}
        self._guard = threading.Lock()

    # ------------------------------------------------------------------ 生命周期

    def register(self, team: str, members: list[str]) -> None:
        """注册队伍。重复注册会重置该队伍状态。"""
        with self._guard:
            self._teams[team] = _TeamState(members=set(members))

    def names(self) -> list[str]:
        """已注册的全部队伍名。"""
        with self._guard:
            return list(self._teams)

    def begin_round(self, team: str) -> None:
        """开始新一轮组队任务：清空同步点、黑板和中止标记。"""
        st = self._state(team)
        with st.cond:
            st.arrived.clear()
            st.generation.clear()
            st.board.clear()
            st.aborted = None
            st.cond.notify_all()

    def _state(self, team: str) -> _TeamState:
        """获取队伍状态，不存在则抛异常。"""
        try:
            return self._teams[team]
        except KeyError:
            raise KeyError(f"队伍 {team} 未注册") from None

    # ------------------------------------------------------------------ 同步点

    def barrier(self, team: str, point: str, account: str, timeout: float = 120) -> bool:
        """
        到达同步点并等待全员到齐。

        参数:
            team:    队伍名
            point:   同步点名，如 "到达NPC" "进入战斗"
            account: 当前账号名
            timeout: 最长等待秒数
        返回:
            True  全员到齐
            False 超时或队伍已中止（超时会自动中止整队，避免其他人无限等待）
        """
        st = self._state(team)
        deadline = time.monotonic() + timeout
        with st.cond:
            if st.aborted:
                return False
            gen = st.generation.get(point, 0)
            arrived = st.arrived.setdefault(point, set())
            arrived.add(account)
            log.debug("[%s] %s 到达同步点 %s（%d/%d）", team, account, point, len(arrived), len(st.members))
            if arrived >= st.members:
                # 最后一个到达的人负责开启下一轮，并唤醒所有等待者
                st.generation[point] = gen + 1
                st.arrived[point] = set()
                st.cond.notify_all()
                return True
            while st.generation.get(point, 0) == gen and not st.aborted:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    missing = st.members - st.arrived.get(point, set())
                    self._abort_locked(st, team, f"同步点 {point} 超时，未到达：{sorted(missing)}")
                    return False
                st.cond.wait(remaining)
            return not st.aborted

    # ------------------------------------------------------------------ 黑板

    def publish(self, team: str, key: str, value: Any) -> None:
        """往共享黑板写一条数据，并唤醒等待该数据的人。"""
        st = self._state(team)
        with st.cond:
            st.board[key] = value
            st.cond.notify_all()

    def wait_for(self, team: str, key: str, timeout: float = 60) -> Any:
        """
        等待黑板上出现某个 key，返回其值。超时或队伍中止返回 None。
        """
        st = self._state(team)
        deadline = time.monotonic() + timeout
        with st.cond:
            while key not in st.board and not st.aborted:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                st.cond.wait(remaining)
            return st.board.get(key)

    def read(self, team: str, key: str, default: Any = None) -> Any:
        """非阻塞读取黑板。"""
        st = self._state(team)
        with st.cond:
            return st.board.get(key, default)

    # ------------------------------------------------------------------ 中止

    def abort(self, team: str, reason: str) -> None:
        """中止本轮组队，所有阻塞在 barrier / wait_for 的账号会立刻返回失败。"""
        st = self._state(team)
        with st.cond:
            self._abort_locked(st, team, reason)

    @staticmethod
    def _abort_locked(st: _TeamState, team: str, reason: str) -> None:
        """在已持有锁的情况下设置中止标记。只记录第一个原因。"""
        if not st.aborted:
            st.aborted = reason
            log.warning("[%s] 本轮中止：%s", team, reason)
        st.cond.notify_all()

    def aborted_reason(self, team: str) -> Optional[str]:
        """返回中止原因；未中止返回 None。"""
        st = self._state(team)
        with st.cond:
            return st.aborted
