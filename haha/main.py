"""
命令行入口。

    python main.py run                 常驻运行：按时间窗口持续调度所有账号/队伍
    python main.py run --once          做完当前能做的任务就退出（适合配合系统计划任务）
    python main.py run --dry-run       演练模式：不连设备，验证调度/组队/重试逻辑
    python main.py task 账号 入口节点   在单个账号上执行一次指定入口（调试 Pipeline 用）
    python main.py status              查看今天各账号进度
    python main.py reset [--account X] 清空今天的进度（重做）
    python main.py devices             列出本机可用的模拟器 / 窗口
    python main.py check               静态检查配置和 Pipeline

全局参数：-c/--config 指定配置文件，默认 config/config.yaml
"""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.config import AppConfig, ConfigError, load_config  # noqa: E402
from core.logger import get_logger, setup_logging  # noqa: E402

log = get_logger("main")


def _maa_init(cfg: AppConfig) -> None:
    """初始化 MAA 全局选项：日志目录、调试模式。"""
    from maa.tasker import Tasker
    from maa.toolkit import Toolkit

    Toolkit.init_option(str(cfg.resolve("data/maa")))
    Tasker.set_log_dir(str(cfg.resolve(cfg.global_.log_dir) / "maa"))
    Tasker.set_debug_mode(cfg.global_.maa_debug)
    Tasker.set_save_on_error(True)   # 任务出错时保存截图，方便排查


# ---------------------------------------------------------------------- 子命令

def cmd_run(cfg: AppConfig, args) -> int:
    """运行编排器。"""
    from core.orchestrator import Orchestrator

    if not args.dry_run:
        _maa_init(cfg)
    orch = Orchestrator(cfg, dry_run=args.dry_run)

    def on_signal(signum, frame):
        log.info("收到退出信号")
        orch.stop_event.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    log.info("启动：%d 个账号，%d 个队伍%s", len(orch.workers), len(cfg.teams), "（演练模式）" if args.dry_run else "")
    orch.run(once=args.once)
    _print_status(orch.store)
    return 0


def cmd_task(cfg: AppConfig, args) -> int:
    """在单个账号上执行一次入口节点（不记进度），用于调试 Pipeline。"""
    from core.runtime import Runtime
    from core.state_store import StateStore
    from core.team import TeamCoordinator
    from core.worker import MaaWorker

    if args.account not in cfg.accounts:
        log.error("账号不存在：%s", args.account)
        return 2
    _maa_init(cfg)
    g = cfg.global_
    runtime = Runtime(cfg, StateStore(cfg.resolve(g.state_db), g.daily_reset_hour), TeamCoordinator())
    worker = MaaWorker(cfg.accounts[args.account], cfg, runtime)
    if not worker.connect():
        return 1
    result = worker.run_task(args.entry)
    log.info("结果：%s，%s（最后节点 %s）", "成功" if result.success else "失败", result.message, result.last_node)
    return 0 if result.success else 1


def _print_status(store) -> None:
    """以表格形式打印今天的进度。"""
    rows = store.summary()
    print(f"\n===== {store.today()} 进度 =====")
    if not rows:
        print("（暂无记录）")
        return
    print(f"{'账号':<14}{'任务':<12}{'完成':>6}{'失败':>6}  最后完成时间")
    for r in rows:
        print(f"{r['account']:<14}{r['task']:<12}{r['done_count']:>6}{r['fail_count']:>6}  {r['last_done_at'] or '-'}")


def cmd_status(cfg: AppConfig, args) -> int:
    """查看今天进度。"""
    from core.state_store import StateStore

    _print_status(StateStore(cfg.resolve(cfg.global_.state_db), cfg.global_.daily_reset_hour))
    return 0


def cmd_reset(cfg: AppConfig, args) -> int:
    """清空今天进度。"""
    from core.state_store import StateStore

    store = StateStore(cfg.resolve(cfg.global_.state_db), cfg.global_.daily_reset_hour)
    n = store.reset_day(args.account)
    print(f"已清除 {n} 条记录")
    return 0


def cmd_devices(cfg: AppConfig, args) -> int:
    """列出可用设备，方便填写 config.yaml。"""
    from maa.toolkit import Toolkit

    Toolkit.init_option(str(cfg.resolve("data/maa")))
    print("===== 模拟器 / 安卓设备 =====")
    for d in Toolkit.find_adb_devices():
        print(f"  {d.name:<20} address={d.address:<22} adb={d.adb_path}")
    if sys.platform == "win32":
        from core import win32

        print("===== 桌面窗口（填 window_title / window_class；多开同名窗口按 hwnd 从小到大即 window_index 0,1,2…） =====")
        for w in sorted(win32.list_windows(), key=lambda x: x.hwnd):
            if w.visible and w.title:
                print(f"  hwnd={w.hwnd:<10} pid={w.pid:<7} class={w.class_name:<28} title={w.title}")
        if not win32.is_admin():
            print("提示：当前未以管理员运行；若游戏以管理员运行，请用管理员终端运行本程序")
    return 0


def cmd_check(cfg: AppConfig, args) -> int:
    """静态检查资源；加 --load 时还会真正用 MAA 加载一次资源。"""
    from tools.pipeline_check import check_resource

    entries = [e for t in cfg.tasks.values() for e in (t.entry, t.leader_entry, t.member_entry) if e]
    # 不同账号可能叠加不同的资源层（如端游加载 base + pc），每种组合各检查一次
    combos: dict[tuple[str, ...], list[str]] = {}
    for acc in cfg.accounts.values():
        combos.setdefault(tuple(acc.effective_resource_dirs(cfg.global_.resource_dirs)), []).append(acc.name)
    if not combos:
        combos[tuple(cfg.global_.resource_dirs)] = []

    total_errors = 0
    for combo, users in combos.items():
        dirs = [cfg.resolve(d) for d in combo]
        rep = check_resource(dirs, entries)
        print(f"\n===== 资源 {' + '.join(combo)}（账号：{', '.join(users) or '-'}）共 {len(rep.nodes)} 个节点 =====")
        for w in rep.warnings:
            print(f"[警告] {w}")
        for e in rep.errors:
            print(f"[错误] {e}")
        total_errors += len(rep.errors)
        if args.load and rep.ok:
            from maa.resource import Resource

            res = Resource()
            for d in dirs:
                ok = res.post_bundle(d).wait().succeeded
                print(f"[MAA 加载] {d}：{'成功' if ok else '失败'}")
                if not ok:
                    total_errors += 1
                    break
    print("\n检查通过" if not total_errors else f"\n发现 {total_errors} 个错误")
    return 0 if not total_errors else 1


# ---------------------------------------------------------------------- 入口

def main(argv: list[str] | None = None) -> int:
    """解析命令行并分发到子命令。"""
    ap = argparse.ArgumentParser(description="MMO 多开自动化（MaaFramework + 自研编排）")
    ap.add_argument("-c", "--config", default=str(ROOT / "config" / "config.yaml"), help="配置文件路径")
    ap.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="运行")
    p.add_argument("--once", action="store_true", help="做完当前能做的任务就退出")
    p.add_argument("--dry-run", action="store_true", help="演练模式，不连接设备")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("task", help="单账号执行一次入口节点")
    p.add_argument("account")
    p.add_argument("entry")
    p.set_defaults(func=cmd_task)

    sub.add_parser("status", help="查看今日进度").set_defaults(func=cmd_status)

    p = sub.add_parser("reset", help="清空今日进度")
    p.add_argument("--account", default=None)
    p.set_defaults(func=cmd_reset)

    sub.add_parser("devices", help="列出可用设备").set_defaults(func=cmd_devices)

    p = sub.add_parser("check", help="检查配置与 Pipeline")
    p.add_argument("--load", action="store_true", help="同时用 MAA 实际加载资源")
    p.set_defaults(func=cmd_check)

    args = ap.parse_args(argv)
    try:
        cfg = load_config(args.config)
    except FileNotFoundError:
        print(f"找不到配置文件 {args.config}，请先复制 config/config.example.yaml 为 config/config.yaml")
        return 2
    except ConfigError as e:
        print(f"配置错误：{e}")
        return 2

    import logging

    setup_logging(cfg.resolve(cfg.global_.log_dir), logging.DEBUG if args.verbose else logging.INFO)
    return args.func(cfg, args)


if __name__ == "__main__":
    sys.exit(main())
