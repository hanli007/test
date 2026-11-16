"""队伍协调、看门狗、编排器（演练模式）的测试。"""

from __future__ import annotations

import threading
import time

from core.orchestrator import Orchestrator, SlotPool
from core.scheduler import team_key
from core.state_store import StateStore
from core.team import TeamCoordinator
from core.watchdog import Watchdog
from core.worker import FakeWorker


# ------------------------------------------------------------------ 队伍协调

def test_barrier_releases_when_all_arrive():
    tc = TeamCoordinator()
    tc.register("T", ["A", "B", "C"])
    results = {}

    def go(name, delay):
        time.sleep(delay)
        results[name] = tc.barrier("T", "集合", name, timeout=5)

    threads = [threading.Thread(target=go, args=(n, d)) for n, d in [("A", 0), ("B", 0.1), ("C", 0.3)]]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == {"A": True, "B": True, "C": True}


def test_barrier_reusable_in_loop():
    """同一个同步点可以在循环里重复使用（按轮次区分）。"""
    tc = TeamCoordinator()
    tc.register("T", ["A", "B"])
    counts = {"A": 0, "B": 0}

    def go(name):
        for _ in range(3):
            assert tc.barrier("T", "每回合", name, timeout=5)
            counts[name] += 1

    ts = [threading.Thread(target=go, args=(n,)) for n in counts]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert counts == {"A": 3, "B": 3}


def test_barrier_timeout_aborts_team():
    tc = TeamCoordinator()
    tc.register("T", ["A", "B"])
    assert tc.barrier("T", "集合", "A", timeout=0.2) is False
    assert "未到达" in tc.aborted_reason("T")
    # 中止后其他人立刻返回失败，不会再等
    assert tc.barrier("T", "集合", "B", timeout=5) is False
    tc.begin_round("T")
    assert tc.aborted_reason("T") is None


def test_publish_and_wait():
    tc = TeamCoordinator()
    tc.register("T", ["A", "B"])
    threading.Timer(0.1, tc.publish, args=("T", "目标", "钟馗")).start()
    assert tc.wait_for("T", "目标", timeout=2) == "钟馗"
    assert tc.wait_for("T", "没有", timeout=0.1) is None


def test_slot_pool_atomic_acquire():
    pool = SlotPool(3)
    stop = threading.Event()
    assert pool.acquire(2, stop)
    got = []
    t = threading.Thread(target=lambda: got.append(pool.acquire(3, stop)))
    t.start()
    time.sleep(0.2)
    assert not got            # 只剩 1 个，申请 3 个必须等待
    pool.release(2)
    t.join(2)
    assert got == [True]


# ------------------------------------------------------------------ 看门狗

def test_watchdog_flags_stale_worker(team_config):
    w = FakeWorker(team_config.accounts["A"])
    w.busy = True
    w._heartbeat -= 100
    flagged = []
    wd = Watchdog({"A": w}, stuck_sec=30, on_stuck=lambda n, r: flagged.append(n))
    assert wd.check_once() == ["A"]
    assert flagged == ["A"]
    assert w._stop.is_set()


def test_watchdog_task_timeout(team_config):
    w = FakeWorker(team_config.accounts["A"])
    w.busy = True
    w.task_started = time.monotonic() - 120
    w.task_timeout = 60
    wd = Watchdog({"A": w}, stuck_sec=300, on_stuck=lambda n, r: None)
    assert wd.check_once() == ["A"]


# ------------------------------------------------------------------ 编排器（演练）

def _orch(cfg, fail_rate=0.0):
    orch = Orchestrator(cfg, dry_run=True, store=StateStore(":memory:"))
    for w in orch.workers.values():
        w.fail_rate = fail_rate
        w.duration = (0.01, 0.05)
    return orch


def test_dry_run_completes_everything(team_config):
    orch = _orch(team_config)
    t = threading.Thread(target=orch.run, kwargs={"once": True})
    t.start()
    t.join(30)
    assert not t.is_alive(), "once 模式应在全部完成后退出"
    s = orch.store
    assert s.get_progress(team_key("T"), "副本")["done_count"] == 1
    for name in ("A", "B", "D"):
        assert s.get_progress(name, "日常")["done_count"] == 2
    # 组队时队长/队员分别执行了各自的入口
    assert "副本_队长" in orch.workers["A"].history
    assert "副本_队员" in orch.workers["B"].history
    assert "副本_队员" in orch.workers["C"].history
    assert "副本_队长" not in orch.workers["D"].history


def test_dry_run_team_failure_is_retried_and_capped(team_config):
    """队员每次都失败 → 整队记失败，重试 max_retry 次后放弃，且不会卡死。"""
    orch = _orch(team_config)
    orch.workers["C"].fail_rate = 1.0
    t = threading.Thread(target=orch.run, kwargs={"once": True})
    t.start()
    t.join(30)
    assert not t.is_alive()
    p = orch.store.get_progress(team_key("T"), "副本")
    assert p["done_count"] == 0
    assert p["fail_count"] == 3          # 首次 + 重试 2 次
    # 队伍失败不影响单人任务
    assert orch.store.get_progress("A", "日常")["done_count"] == 2
