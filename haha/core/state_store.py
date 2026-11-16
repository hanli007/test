"""
账号状态库（SQLite）：持久化每个账号“今天”的任务进度、失败次数、运行记录和自定义数据。

为什么要单独存状态：
    MAA 的 Pipeline 本身是无状态的，一次 post_task 跑完就结束了。
    “今天师门做了几轮”“背包是否已满”“上次失败是几点”这些跨任务、跨重启的信息，
    需要编排层自己记住，程序崩溃重启后也能接着做。

表结构：
    progress   (day, account, task) -> done_count, fail_count, last_fail_at, last_done_at
    kv         (account, key) -> value(JSON)，账号自定义数据（如金币数、背包状态），由自定义动作写入
    run_log    每次任务运行的流水记录，用于统计和排查

“今天”的定义：以 daily_reset_hour 为界。例如 reset=5，则凌晨 4:59 仍算前一天。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS progress (
    day          TEXT NOT NULL,
    account      TEXT NOT NULL,
    task         TEXT NOT NULL,
    done_count   INTEGER NOT NULL DEFAULT 0,
    fail_count   INTEGER NOT NULL DEFAULT 0,
    last_done_at TEXT,
    last_fail_at TEXT,
    PRIMARY KEY (day, account, task)
);
CREATE TABLE IF NOT EXISTS kv (
    account    TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account, key)
);
CREATE TABLE IF NOT EXISTS run_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT NOT NULL,
    account    TEXT NOT NULL,
    task       TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at   TEXT NOT NULL,
    success    INTEGER NOT NULL,
    message    TEXT
);
CREATE INDEX IF NOT EXISTS idx_run_log_day ON run_log(day, account);
"""


class StateStore:
    """
    线程安全的 SQLite 状态库。所有账号线程共用一个实例，内部用锁串行化写操作。
    """

    def __init__(self, db_path: Path, daily_reset_hour: int = 0):
        """
        参数:
            db_path:          数据库文件路径，目录不存在会自动创建；传 ':memory:' 用于测试
            daily_reset_hour: 每日重置小时
        """
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()
        self._reset_hour = daily_reset_hour

    # ------------------------------------------------------------------ 日期

    def today(self, now: Optional[datetime] = None) -> str:
        """返回按重置时间计算的“游戏日”，格式 YYYY-MM-DD。"""
        now = now or datetime.now()
        return (now - timedelta(hours=self._reset_hour)).strftime("%Y-%m-%d")

    # ------------------------------------------------------------------ 进度

    def get_progress(self, account: str, task: str, now: Optional[datetime] = None) -> dict[str, Any]:
        """
        查询账号某任务今天的进度。

        返回:
            {'done_count': int, 'fail_count': int, 'last_done_at': str|None, 'last_fail_at': str|None}
        """
        row = self._conn.execute(
            "SELECT done_count, fail_count, last_done_at, last_fail_at FROM progress "
            "WHERE day=? AND account=? AND task=?",
            (self.today(now), account, task),
        ).fetchone()
        if row is None:
            return {"done_count": 0, "fail_count": 0, "last_done_at": None, "last_fail_at": None}
        return dict(row)

    def mark_done(self, account: str, task: str, count: int = 1, now: Optional[datetime] = None) -> None:
        """记录任务完成 count 次。"""
        now = now or datetime.now()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO progress(day, account, task, done_count, last_done_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(day, account, task) DO UPDATE SET "
                "done_count = done_count + excluded.done_count, last_done_at = excluded.last_done_at",
                (self.today(now), account, task, count, now.isoformat(timespec="seconds")),
            )

    def set_done(self, account: str, task: str, count: int, now: Optional[datetime] = None) -> None:
        """
        直接设置完成次数。用于从游戏界面 OCR 读到真实进度（如“师门 7/20”）后校准，
        防止程序记录与游戏实际不一致。
        """
        now = now or datetime.now()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO progress(day, account, task, done_count, last_done_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(day, account, task) DO UPDATE SET "
                "done_count = excluded.done_count, last_done_at = excluded.last_done_at",
                (self.today(now), account, task, count, now.isoformat(timespec="seconds")),
            )

    def mark_fail(self, account: str, task: str, now: Optional[datetime] = None) -> None:
        """记录任务失败一次。"""
        now = now or datetime.now()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO progress(day, account, task, fail_count, last_fail_at) VALUES(?,?,?,1,?) "
                "ON CONFLICT(day, account, task) DO UPDATE SET "
                "fail_count = fail_count + 1, last_fail_at = excluded.last_fail_at",
                (self.today(now), account, task, now.isoformat(timespec="seconds")),
            )

    def reset_day(self, account: Optional[str] = None, now: Optional[datetime] = None) -> int:
        """
        清空今天的进度（手动重做用）。

        参数:
            account: 只清某个账号；None 表示全部
        返回:
            删除的行数
        """
        sql, args = "DELETE FROM progress WHERE day=?", [self.today(now)]
        if account:
            sql += " AND account=?"
            args.append(account)
        with self._lock, self._conn:
            return self._conn.execute(sql, args).rowcount

    # ------------------------------------------------------------------ 自定义键值

    def set_kv(self, account: str, key: str, value: Any) -> None:
        """保存账号自定义数据，value 需可 JSON 序列化。"""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO kv(account, key, value, updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(account, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (account, key, json.dumps(value, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
            )

    def get_kv(self, account: str, key: str, default: Any = None) -> Any:
        """读取账号自定义数据，不存在返回 default。"""
        row = self._conn.execute("SELECT value FROM kv WHERE account=? AND key=?", (account, key)).fetchone()
        return default if row is None else json.loads(row["value"])

    # ------------------------------------------------------------------ 运行记录

    def log_run(
        self, account: str, task: str, started_at: datetime, ended_at: datetime, success: bool, message: str = ""
    ) -> None:
        """写入一条运行流水。"""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO run_log(day, account, task, started_at, ended_at, success, message) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    self.today(started_at),
                    account,
                    task,
                    started_at.isoformat(timespec="seconds"),
                    ended_at.isoformat(timespec="seconds"),
                    int(success),
                    message,
                ),
            )

    def summary(self, now: Optional[datetime] = None) -> list[dict[str, Any]]:
        """返回今天全部账号的进度列表，用于 status 命令展示。"""
        rows = self._conn.execute(
            "SELECT account, task, done_count, fail_count, last_done_at, last_fail_at FROM progress "
            "WHERE day=? ORDER BY account, task",
            (self.today(now),),
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        """关闭数据库连接。"""
        self._conn.close()
