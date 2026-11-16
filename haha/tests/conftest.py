"""测试公共夹具：构造最小配置、演练用账号等。"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config import load_config  # noqa: E402


@pytest.fixture
def write_config(tmp_path):
    """写一份 yaml 配置到临时目录并加载，返回 AppConfig。"""

    def _write(text: str):
        p = tmp_path / "config.yaml"
        p.write_text(textwrap.dedent(text), encoding="utf-8")
        return load_config(p)

    return _write


@pytest.fixture
def team_config(write_config):
    """3 人队 + 1 个单人账号，全部使用 debug 设备，适合演练。"""
    return write_config(
        """
        global:
          state_db: ":memory:"
          max_parallel: 10
          loop_interval_sec: 1
          stuck_sec: 30
        tasks:
          日常:
            entry: 日常_开始
            daily_limit: 2
            priority: 20
            retry_cooldown_min: 0
          副本:
            team: true
            leader_entry: 副本_队长
            member_entry: 副本_队员
            daily_limit: 1
            priority: 10
            retry_cooldown_min: 0
        accounts:
          - {name: A, device: {type: debug}, tasks: [日常]}
          - {name: B, device: {type: debug}, tasks: [日常]}
          - {name: C, device: {type: debug}, tasks: []}
          - {name: D, device: {type: debug}, tasks: [日常]}
        teams:
          - {name: T, leader: A, members: [B, C], tasks: [副本]}
        """
    )
