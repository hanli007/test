"""
运行时共享对象：把各模块都要用到的“全局单例”集中到一处，避免到处传参。

自定义动作（custom/actions.py）通过它访问状态库和队伍协调器。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import AppConfig
from .pc_client import PcClientManager
from .state_store import StateStore
from .team import TeamCoordinator


@dataclass
class Runtime:
    """运行时上下文。"""

    config: AppConfig
    store: StateStore
    team: TeamCoordinator
    pc: PcClientManager = field(default_factory=PcClientManager)   # 端游窗口/进程管理
