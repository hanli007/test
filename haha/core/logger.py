"""
日志模块：统一日志格式，每个账号的日志带上账号名前缀，同时输出到控制台和按天滚动的文件。
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_FMT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"


def setup_logging(log_dir: Path, level: int = logging.INFO) -> None:
    """
    初始化根日志器。只需在程序入口调用一次。

    参数:
        log_dir: 日志目录，会自动创建
        level:   日志级别
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FMT, "%H:%M:%S"))
    root.addHandler(console)

    # 每天零点切分一个新文件，保留 14 天
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_dir / "mmo-auto.log", when="midnight", backupCount=14, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(_FMT))
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """获取带名字的日志器，账号相关日志统一用 get_logger(f'acc.{账号名}')。"""
    return logging.getLogger(name)
