"""配置、状态库、调度器的单元测试。"""

from __future__ import annotations

from datetime import datetime, time

import pytest

from core.config import ConfigError, TimeWindow, load_config
from core.scheduler import Scheduler, team_key
from core.state_store import StateStore
from tests.conftest import ROOT


# ------------------------------------------------------------------ 配置

def test_example_config_loads():
    """仓库自带的示例配置必须能通过校验。"""
    cfg = load_config(ROOT / "config" / "config.example.yaml")
    assert "梦幻1" in cfg.accounts
    assert cfg.teams["一队"].all_accounts == ["梦幻1", "梦幻2", "梦幻3", "梦幻4", "梦幻5"]
    assert cfg.team_of("梦幻3").name == "一队"
    assert cfg.team_of("传奇1") is None
    assert cfg.base_dir == ROOT


def test_unknown_field_rejected(write_config):
    with pytest.raises(ConfigError, match="未知字段"):
        write_config("""
        global: {max_paralel: 3}
        """)


def test_team_task_requires_both_entries(write_config):
    with pytest.raises(ConfigError, match="leader_entry"):
        write_config("""
        tasks:
          副本: {team: true, leader_entry: X}
        """)


def test_account_cannot_be_in_two_teams(write_config):
    with pytest.raises(ConfigError, match="同时属于"):
        write_config("""
        accounts:
          - {name: A, device: {type: debug}}
          - {name: B, device: {type: debug}}
        teams:
          - {name: T1, leader: A, members: [B]}
          - {name: T2, leader: B, members: [A]}
        """)


def test_time_window_cross_midnight():
    w = TimeWindow(time(23, 0), time(1, 0))
    assert w.contains(time(23, 30))
    assert w.contains(time(0, 30))
    assert not w.contains(time(12, 0))


# ------------------------------------------------------------------ 状态库

def test_today_respects_reset_hour():
    store = StateStore(":memory:", daily_reset_hour=5)
    assert store.today(datetime(2026, 11, 16, 4, 59)) == "2026-11-15"
    assert store.today(datetime(2026, 11, 16, 5, 0)) == "2026-11-16"


def test_progress_counters():
    store = StateStore(":memory:")
    now = datetime(2026, 11, 16, 12, 0)
    store.mark_done("A", "师门", now=now)
    store.mark_done("A", "师门", now=now)
    store.mark_fail("A", "师门", now=now)
    p = store.get_progress("A", "师门", now)
    assert (p["done_count"], p["fail_count"]) == (2, 1)
    store.set_done("A", "师门", 7, now=now)
    assert store.get_progress("A", "师门", now)["done_count"] == 7
    # 第二天重新计数
    assert store.get_progress("A", "师门", datetime(2026, 11, 17, 12, 0))["done_count"] == 0


def test_kv_roundtrip():
    store = StateStore(":memory:")
    store.set_kv("A", "师门进度", {"cur": 3, "total": 20})
    assert store.get_kv("A", "师门进度") == {"cur": 3, "total": 20}
    assert store.get_kv("A", "不存在", "默认") == "默认"


# ------------------------------------------------------------------ 调度

def test_scheduler_priority_limit_retry(team_config):
    store = StateStore(":memory:")
    sch = Scheduler(team_config, store)
    now = datetime(2026, 11, 16, 12, 0)

    # 组队任务优先级 10，先于单人任务
    assert sch.next_team("T", now).name == "副本"
    store.mark_done(team_key("T"), "副本", now=now)
    assert sch.next_team("T", now) is None          # 达到每日上限

    assert sch.next_solo("A", now).name == "日常"
    store.mark_done("A", "日常", now=now)
    store.mark_done("A", "日常", now=now)
    assert sch.next_solo("A", now) is None

    # 失败超过 max_retry(2) 次后放弃
    for _ in range(3):
        store.mark_fail("B", "日常", now=now)
    assert sch.next_solo("B", now) is None
    assert not sch.has_pending(["A", "B", "C"], [team_config.teams["T"]], now)
    assert sch.has_pending(["D"], [], now)


def test_scheduler_cooldown_and_window(write_config):
    cfg = write_config("""
    tasks:
      活动: {entry: X, windows: ["20:00-21:00"], retry_cooldown_min: 10}
    accounts:
      - {name: A, device: {type: debug}, tasks: [活动]}
    """)
    store = StateStore(":memory:")
    sch = Scheduler(cfg, store)
    assert sch.next_solo("A", datetime(2026, 11, 16, 19, 59)) is None
    t = datetime(2026, 11, 16, 20, 5)
    assert sch.next_solo("A", t).name == "活动"
    store.mark_fail("A", "活动", now=t)
    assert sch.next_solo("A", datetime(2026, 11, 16, 20, 10)) is None      # 冷却中
    assert sch.has_pending(["A"], [], datetime(2026, 11, 16, 20, 10))        # 但仍算待做
    assert sch.next_solo("A", datetime(2026, 11, 16, 20, 16)).name == "活动"
