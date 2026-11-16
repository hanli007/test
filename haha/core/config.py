"""
配置模块：负责读取、校验 config.yaml，并转换成强类型的 dataclass。

配置分为四部分：
    global    全局设置（日志、每日重置时间、并发数等）
    emulator  模拟器管理（启动/关闭命令模板、adb 路径）
    accounts  账号列表（每个账号绑定一个设备：模拟器实例或 PC 窗口）
    teams     队伍列表（队长 + 队员，用于组队任务）
    tasks     任务定义（入口节点、每日次数、时间窗口、是否组队等）
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import time as dtime
from pathlib import Path
from typing import Any, Optional

import yaml


class ConfigError(ValueError):
    """配置内容不合法时抛出。"""


@dataclass
class GlobalConfig:
    """全局设置。"""

    log_dir: str = "logs"                 # 日志目录
    state_db: str = "data/state.db"       # SQLite 状态库路径
    resource_dirs: list[str] = field(default_factory=lambda: ["resource/base"])  # 资源目录，按顺序叠加加载
    daily_reset_hour: int = 0             # 游戏每日重置的小时（0-23），用于计算“今天”
    max_parallel: int = 10                # 最多同时运行的账号数
    maa_debug: bool = False               # 是否开启 MAA 调试模式（保存识别截图，较占磁盘）
    loop_interval_sec: int = 30           # 调度主循环的间隔（秒）
    stuck_sec: int = 300                  # 多久没有任何节点推进就判定为卡死（秒）
    max_recover: int = 3                  # 单个账号每天最多自动恢复（重启游戏/模拟器）次数


@dataclass
class EmulatorConfig:
    """模拟器管理设置。命令模板中的 {index} 会被替换成实例序号。"""

    adb_path: str = "adb"                 # adb 可执行文件路径
    launch_cmd: str = ""                  # 启动实例命令，如 MuMu: 'MuMuManager.exe control -v {index} launch'
    shutdown_cmd: str = ""                # 关闭实例命令
    boot_wait_sec: int = 60               # 启动实例后等待系统就绪的最长时间
    screencap_extras: bool = True         # 是否启用模拟器专用快速截图（MuMu12/雷电9）


# MAA Win32 控制器支持的截图方式（可用 | 组合，MAA 会测速选最快的）与输入方式（只能选一个）
WIN32_SCREENCAP_METHODS = {
    "GDI", "FramePool", "DXGI_DesktopDup", "DXGI_DesktopDup_Window", "PrintWindow", "ScreenDC",
    "Foreground", "Background", "All",
}
WIN32_INPUT_METHODS = {
    "Seize", "SendMessage", "PostMessage", "LegacyEvent", "PostThreadMessage",
    "SendMessageWithCursorPos", "PostMessageWithCursorPos", "SendMessageWithWindowPos",
    "PostMessageWithWindowPos", "Interception", "AnchoredTouch",
}


@dataclass
class DeviceConfig:
    """账号绑定的设备。type=adb 表示模拟器/手机，type=win32 表示 PC 端游窗口，type=debug 表示调试用图片目录。"""

    type: str = "adb"                     # adb | win32 | debug
    # ---- adb（模拟器 / 手机） ----
    address: str = ""                     # adb 地址，如 127.0.0.1:16384
    emulator_index: Optional[int] = None  # 模拟器实例序号（用于自动启动/重启）
    # ---- win32（端游）：找窗口 ----
    window_title: str = ""                # 窗口标题正则，如 "^梦幻西游"
    window_class: str = ""                # 窗口类名正则（可选，标题会变的游戏用类名更稳）
    window_index: Optional[int] = None    # 多个匹配窗口时取第几个；不填则自动取第一个未被其他账号占用的
    # ---- win32：启动 / 重启客户端 ----
    exe_path: str = ""                    # 客户端 exe 路径；填了才能自动启动和卡死重启
    exe_args: str = ""                    # 启动参数
    work_dir: str = ""                    # 工作目录，默认为 exe 所在目录
    process_name: str = ""                # 进程名（如 my.exe），仅在没有绑定记录时用于结束进程
    launch_wait_sec: int = 120            # 启动后等待窗口出现的最长秒数（含登录器更新时间）
    client_size: list[int] = field(default_factory=lambda: [1280, 720])  # 把客户区调成该尺寸；[] 表示不调整
    # ---- win32：截图与输入方式（不同游戏兼容性不同，不行就换） ----
    screencap: str = "Background"         # 截图方式，可用 | 组合，如 "FramePool|PrintWindow"
    mouse_input: str = "PostMessage"      # 鼠标输入：PostMessage/SendMessage 后台；Seize 前台抢鼠标（兼容性最好）
    keyboard_input: str = "PostMessage"   # 键盘输入，取值同上
    # ---- debug ----
    image_dir: str = ""                   # 截图图片目录


@dataclass
class AccountConfig:
    """单个账号。"""

    name: str                             # 账号唯一名（日志、状态库都用它做主键）
    device: DeviceConfig
    package: str = ""                     # 游戏包名（adb）或启动入口
    enabled: bool = True
    tasks: list[str] = field(default_factory=list)   # 该账号要做的单人任务名（引用 tasks 段）
    vars: dict[str, Any] = field(default_factory=dict)  # 账号私有变量，可在 pipeline_override 中使用
    resource_dirs: list[str] = field(default_factory=list)  # 账号专用资源目录（如端游叠加 resource/pc）；空则用全局

    def effective_resource_dirs(self, global_dirs: list[str]) -> list[str]:
        """该账号实际加载的资源目录。"""
        return self.resource_dirs or global_dirs


@dataclass
class TeamConfig:
    """组队配置。leader 带队，members 跟随。"""

    name: str
    leader: str
    members: list[str]
    tasks: list[str] = field(default_factory=list)   # 该队伍要做的组队任务名

    @property
    def all_accounts(self) -> list[str]:
        """队长 + 全部队员。"""
        return [self.leader, *self.members]


@dataclass
class TimeWindow:
    """时间窗口，例如 20:00-21:00；跨零点写成 23:00-01:00。"""

    start: dtime
    end: dtime

    def contains(self, t: dtime) -> bool:
        """判断某个时刻是否落在窗口内（支持跨零点）。"""
        if self.start <= self.end:
            return self.start <= t < self.end
        return t >= self.start or t < self.end


@dataclass
class TaskConfig:
    """任务定义。一个任务对应 Pipeline 中的一个（或一组按角色区分的）入口节点。"""

    name: str
    entry: str = ""                       # 单人任务的入口节点
    leader_entry: str = ""                # 组队任务：队长入口节点
    member_entry: str = ""                # 组队任务：队员入口节点
    team: bool = False                    # 是否为组队任务
    daily_limit: int = 1                  # 每日完成次数上限（每次 run 成功算 1 次）
    priority: int = 50                    # 优先级，越小越先做
    windows: list[TimeWindow] = field(default_factory=list)  # 允许执行的时间段，空表示全天
    timeout_min: int = 30                 # 单次运行超时（分钟），超时由看门狗强制停止
    max_retry: int = 2                    # 单日失败重试次数
    retry_cooldown_min: int = 5           # 失败后冷却多久再重试
    override: dict[str, Any] = field(default_factory=dict)  # 传给 post_task 的 pipeline_override

    def in_window(self, t: dtime) -> bool:
        """当前时间是否允许执行。"""
        return not self.windows or any(w.contains(t) for w in self.windows)


@dataclass
class AppConfig:
    """整个配置文件对应的对象。"""

    global_: GlobalConfig
    emulator: EmulatorConfig
    accounts: dict[str, AccountConfig]
    teams: dict[str, TeamConfig]
    tasks: dict[str, TaskConfig]
    base_dir: Path                        # 配置文件所在项目根目录，用于解析相对路径

    def resolve(self, p: str) -> Path:
        """把相对路径解析为相对项目根目录的绝对路径。"""
        path = Path(p)
        return path if path.is_absolute() else (self.base_dir / path).resolve()

    def team_of(self, account: str) -> Optional[TeamConfig]:
        """查询账号所属队伍（一个账号最多属于一个队伍）。"""
        for team in self.teams.values():
            if account in team.all_accounts:
                return team
        return None


_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def _parse_time(s: str) -> dtime:
    """把 'HH:MM' 解析成 time 对象。"""
    m = _TIME_RE.match(s.strip())
    if not m:
        raise ConfigError(f"时间格式错误：{s!r}，应为 HH:MM")
    h, mi = int(m.group(1)), int(m.group(2))
    if h == 24 and mi == 0:
        return dtime(23, 59, 59)
    if not (0 <= h < 24 and 0 <= mi < 60):
        raise ConfigError(f"时间超出范围：{s!r}")
    return dtime(h, mi)


def _parse_window(s: str) -> TimeWindow:
    """把 'HH:MM-HH:MM' 解析成 TimeWindow。"""
    parts = s.split("-")
    if len(parts) != 2:
        raise ConfigError(f"时间窗口格式错误：{s!r}，应为 HH:MM-HH:MM")
    return TimeWindow(_parse_time(parts[0]), _parse_time(parts[1]))


def _check_win32(acc: AccountConfig) -> None:
    """校验端游账号的设备配置。"""
    dev = acc.device
    if not (dev.window_title or dev.window_class):
        raise ConfigError(f"端游账号 {acc.name} 必须配置 window_title 或 window_class")
    for pat in (dev.window_title, dev.window_class):
        try:
            re.compile(pat)
        except re.error as e:
            raise ConfigError(f"端游账号 {acc.name} 的窗口正则 {pat!r} 无效：{e}") from None
    bad = [m for m in dev.screencap.split("|") if m.strip() not in WIN32_SCREENCAP_METHODS]
    if bad:
        raise ConfigError(f"端游账号 {acc.name} 的 screencap 含未知方式 {bad}，可选：{sorted(WIN32_SCREENCAP_METHODS)}")
    for key in ("mouse_input", "keyboard_input"):
        if getattr(dev, key) not in WIN32_INPUT_METHODS:
            raise ConfigError(f"端游账号 {acc.name} 的 {key} 无效，可选：{sorted(WIN32_INPUT_METHODS)}")
    if dev.client_size and (len(dev.client_size) != 2 or min(dev.client_size) <= 0):
        raise ConfigError(f"端游账号 {acc.name} 的 client_size 应为 [宽, 高]")
    if dev.client_size and abs(dev.client_size[0] / dev.client_size[1] - 16 / 9) > 0.01:
        # MAA 按短边 720 缩放截图，非 16:9（如老游戏 1024x768）时画面宽度不是 1280，
        # 示例 Pipeline 的坐标会对不上，需要按实际缩放后的尺寸（如 960x720）单独写一套端游 Pipeline
        logging.getLogger("config").warning(
            "端游账号 %s 的 client_size %s 不是 16:9，识别坐标需按短边 720 缩放后的尺寸编写", acc.name, dev.client_size)


def _build(cls, data: dict[str, Any], where: str):
    """用字典构造 dataclass，遇到未知字段直接报错，避免拼写错误被静默忽略。"""
    data = dict(data or {})
    known = set(cls.__dataclass_fields__)
    unknown = set(data) - known
    if unknown:
        raise ConfigError(f"{where} 存在未知字段：{sorted(unknown)}")
    return cls(**data)


def load_config(path: str | Path) -> AppConfig:
    """
    读取并校验配置文件。

    参数:
        path: config.yaml 路径
    返回:
        AppConfig
    异常:
        ConfigError: 字段缺失、引用不存在、格式错误等
    """
    path = Path(path).resolve()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # 约定配置放在 <项目>/config/ 下，项目根目录为其上级；否则以配置文件所在目录为根
    base_dir = path.parent.parent if path.parent.name == "config" else path.parent

    global_ = _build(GlobalConfig, raw.get("global"), "global")
    if not 0 <= global_.daily_reset_hour <= 23:
        raise ConfigError("global.daily_reset_hour 必须在 0-23 之间")
    emulator = _build(EmulatorConfig, raw.get("emulator"), "emulator")

    # ---- 任务 ----
    tasks: dict[str, TaskConfig] = {}
    for name, t in (raw.get("tasks") or {}).items():
        t = dict(t or {})
        t["windows"] = [_parse_window(w) for w in t.get("windows", [])]
        task = _build(TaskConfig, {"name": name, **t}, f"tasks.{name}")
        if task.team:
            if not (task.leader_entry and task.member_entry):
                raise ConfigError(f"组队任务 {name} 必须同时配置 leader_entry 和 member_entry")
        elif not task.entry:
            raise ConfigError(f"单人任务 {name} 必须配置 entry")
        tasks[name] = task

    # ---- 账号 ----
    accounts: dict[str, AccountConfig] = {}
    for a in raw.get("accounts") or []:
        a = dict(a)
        a["device"] = _build(DeviceConfig, a.get("device"), f"accounts.{a.get('name')}.device")
        acc = _build(AccountConfig, a, f"accounts.{a.get('name')}")
        if acc.name in accounts:
            raise ConfigError(f"账号名重复：{acc.name}")
        if acc.device.type not in ("adb", "win32", "debug"):
            raise ConfigError(f"账号 {acc.name} 的 device.type 只能是 adb / win32 / debug")
        if acc.device.type == "win32":
            _check_win32(acc)
        for tn in acc.tasks:
            if tn not in tasks:
                raise ConfigError(f"账号 {acc.name} 引用了不存在的任务 {tn}")
            if tasks[tn].team:
                raise ConfigError(f"账号 {acc.name} 的 tasks 里不能放组队任务 {tn}，请配置到 teams 中")
        accounts[acc.name] = acc

    # ---- 队伍 ----
    teams: dict[str, TeamConfig] = {}
    seen: dict[str, str] = {}
    for t in raw.get("teams") or []:
        team = _build(TeamConfig, t, f"teams.{t.get('name')}")
        for acc_name in team.all_accounts:
            if acc_name not in accounts:
                raise ConfigError(f"队伍 {team.name} 引用了不存在的账号 {acc_name}")
            if acc_name in seen:
                raise ConfigError(f"账号 {acc_name} 同时属于队伍 {seen[acc_name]} 和 {team.name}")
            seen[acc_name] = team.name
        for tn in team.tasks:
            if tn not in tasks or not tasks[tn].team:
                raise ConfigError(f"队伍 {team.name} 引用的 {tn} 不存在或不是组队任务")
        teams[team.name] = team

    return AppConfig(global_, emulator, accounts, teams, tasks, base_dir)
