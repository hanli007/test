"""
账号执行器（Worker）：一个账号对应一个 Worker，封装 MAA 的 Controller + Resource + Tasker。

职责边界：
    Worker 只负责“这个号怎么做一件事”：连接设备、加载资源、执行某个 Pipeline 入口、停止、重启游戏。
    “什么时候做、做哪个、几个号怎么配合”由 orchestrator / scheduler / team 负责。

提供两种实现：
    MaaWorker   真实执行，基于 maafw
    FakeWorker  演练模式（--dry-run），不连接设备，随机模拟耗时和成败，用来验证编排逻辑
"""

from __future__ import annotations

import random
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from .config import AccountConfig, AppConfig
from .logger import get_logger

if TYPE_CHECKING:
    from .runtime import Runtime


@dataclass
class TaskResult:
    """一次任务运行的结果。"""

    success: bool
    message: str = ""
    last_node: str = ""      # 最后执行到的节点名，失败时用于排查


class BaseWorker(ABC):
    """Worker 抽象基类，定义编排层依赖的全部接口。"""

    def __init__(self, account: AccountConfig):
        self.account = account
        self.log = get_logger(f"acc.{account.name}")
        self._heartbeat = time.monotonic()   # 最近一次有执行动作的时间，看门狗据此判断卡死
        self.current_node = ""               # 当前正在执行的节点名
        self.current_task = ""               # 当前正在执行的任务名
        self.busy = False                    # 是否正在执行任务
        self.task_started: Optional[float] = None   # 当前任务开始时间（monotonic），看门狗计算超时
        self.task_timeout: Optional[float] = None   # 当前任务允许的最长秒数
        self.team_context: Optional[tuple[str, str]] = None  # 组队时为 (队伍名, 角色 leader|member)，单人为 None

    # ---- 心跳 ----

    def touch(self, node: str = "") -> None:
        """刷新心跳；每执行一个节点都会调用。"""
        self._heartbeat = time.monotonic()
        if node:
            self.current_node = node

    @property
    def idle_seconds(self) -> float:
        """距离上次心跳过去了多少秒。"""
        return time.monotonic() - self._heartbeat

    # ---- 子类实现 ----

    @abstractmethod
    def connect(self) -> bool:
        """连接设备并加载资源，成功返回 True。可重复调用（断线重连）。"""

    @abstractmethod
    def run_task(self, entry: str, override: Optional[dict[str, Any]] = None) -> TaskResult:
        """同步执行一个 Pipeline 入口，直到任务结束或被 stop()。"""

    @abstractmethod
    def stop(self) -> None:
        """请求停止当前任务（线程安全，可由看门狗在其他线程调用）。"""

    @abstractmethod
    def restart_app(self) -> bool:
        """重启游戏客户端（关闭再打开）。"""

    @property
    @abstractmethod
    def connected(self) -> bool:
        """设备当前是否处于连接状态。"""


class MaaWorker(BaseWorker):
    """基于 MaaFramework 的真实 Worker。"""

    def __init__(self, account: AccountConfig, app: AppConfig, runtime: "Runtime"):
        """
        参数:
            account: 账号配置
            app:     全局配置（用于解析资源路径、adb 路径等）
            runtime: 运行时共享对象（状态库、队伍协调器），注册自定义动作时注入
        """
        super().__init__(account)
        self.app = app
        self.runtime = runtime
        self._tasker = None
        self._controller = None
        self._resource = None
        self._sink = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ 连接

    def _create_controller(self):
        """根据 device.type 创建对应的 MAA 控制器。"""
        from maa.controller import AdbController, Win32Controller
        from maa.define import MaaAdbInputMethodEnum, MaaAdbScreencapMethodEnum, MaaWin32InputMethodEnum, \
            MaaWin32ScreencapMethodEnum

        dev = self.account.device
        if dev.type == "adb":
            screencap = MaaAdbScreencapMethodEnum.Default
            if self.app.emulator.screencap_extras:
                # 模拟器专用截图（MuMu12 / 雷电9）速度最快，MAA 会自动测速并在不可用时回退
                screencap |= MaaAdbScreencapMethodEnum.EmulatorExtras
            return AdbController(
                adb_path=self.app.emulator.adb_path,
                address=dev.address,
                screencap_methods=screencap,
                input_methods=MaaAdbInputMethodEnum.Default,
            )
        if dev.type == "win32":
            # 找到（或启动）该账号的游戏窗口；多开时由 PcClientManager 保证不同账号绑定不同窗口
            hwnd = self.runtime.pc.ensure_running(self.account)
            if hwnd is None:
                raise RuntimeError(f"找不到游戏窗口（标题 {dev.window_title!r}，类名 {dev.window_class!r}）")
            self._warn_admin_once()
            screencap = 0
            for name in dev.screencap.split("|"):
                screencap |= getattr(MaaWin32ScreencapMethodEnum, name.strip())
            return Win32Controller(
                hwnd,
                screencap_method=screencap,
                mouse_method=getattr(MaaWin32InputMethodEnum, dev.mouse_input),
                keyboard_method=getattr(MaaWin32InputMethodEnum, dev.keyboard_input),
            )
        if dev.type == "debug":
            # 图片目录控制器：轮播目录中的截图，点击只记录不执行，用于离线调试 Pipeline
            from .image_controller import ImageFolderController

            return ImageFolderController(self.app.resolve(dev.image_dir))
        raise RuntimeError(f"不支持的设备类型 {dev.type}")

    _admin_warned = False

    def _warn_admin_once(self) -> None:
        """端游输入没反应最常见的原因是游戏以管理员运行而本程序不是，首次连接时提示一次。"""
        from . import win32

        if not MaaWorker._admin_warned and not win32.is_admin():
            MaaWorker._admin_warned = True
            self.log.warning("本程序未以管理员身份运行；若游戏以管理员运行，点击和按键会被系统拦截，"
                             "请右键“以管理员身份运行”终端后再启动")

    def _create_resource(self):
        """创建资源对象：按顺序叠加加载 resource_dirs，并注册本账号的自定义识别/动作。"""
        from maa.resource import Resource

        from custom import register_all

        res = Resource()
        for d in self.account.effective_resource_dirs(self.app.global_.resource_dirs):
            path = self.app.resolve(d)
            if not res.post_bundle(path).wait().succeeded:
                raise RuntimeError(f"加载资源失败：{path}")
        # 每个账号一个 Resource，自定义动作可以绑定到具体账号（写状态库、队伍同步都要知道“我是谁”）
        register_all(res, self.runtime, self)
        return res

    def connect(self) -> bool:
        """连接设备、加载资源、绑定 Tasker。失败返回 False 并记录日志。"""
        from maa.tasker import Tasker

        with self._lock:
            try:
                controller = self._create_controller()
                if not controller.post_connection().wait().succeeded:
                    self.log.error("连接设备失败：%s", self.account.device.address or self.account.device.type)
                    return False
                if self._resource is None:
                    self._resource = self._create_resource()
                tasker = Tasker()
                # 监听器对象必须保持引用，否则会被回收导致 C 回调访问野指针
                self._sink = _HeartbeatSink(self)
                tasker.add_context_sink(self._sink)
                if not tasker.bind(self._resource, controller):
                    self.log.error("Tasker 绑定失败")
                    return False
                if not tasker.inited:
                    self.log.error("Tasker 初始化失败")
                    return False
                self._controller, self._tasker = controller, tasker
                self.log.info("已连接，分辨率 %s", controller.resolution)
                self.touch()
                return True
            except Exception as e:  # noqa: BLE001 - 设备层错误类型繁多，统一记录后交给上层重试
                self.log.exception("连接异常：%s", e)
                return False

    @property
    def connected(self) -> bool:
        """设备是否已连接。"""
        if self._controller is None:
            return False
        if self.account.device.type == "win32" and not self.runtime.pc.alive(self.account):
            return False   # 游戏窗口已关闭（闪退 / 被结束）
        c = self._controller.connected
        # CustomController 的 connected 是方法，其余控制器是属性
        return bool(c() if callable(c) else c)

    # ------------------------------------------------------------------ 执行

    def run_task(self, entry: str, override: Optional[dict[str, Any]] = None) -> TaskResult:
        """
        同步执行 Pipeline 入口节点。

        参数:
            entry:    入口节点名
            override: pipeline_override，可在运行时修改节点参数（例如按账号改 OCR 期望文字）
        返回:
            TaskResult
        """
        if self._tasker is None and not self.connect():
            return TaskResult(False, "设备未连接")
        self.busy = True
        self.touch(entry)
        try:
            job = self._tasker.post_task(entry, self._base_override(override)).wait()
            detail = job.get()
            last_node = ""
            if detail is not None and detail.nodes:
                last_node = detail.nodes[-1].name
            if job.succeeded:
                return TaskResult(True, "完成", last_node)
            return TaskResult(False, "Pipeline 执行失败或被停止", last_node)
        except Exception as e:  # noqa: BLE001
            self.log.exception("执行 %s 异常", entry)
            return TaskResult(False, f"异常：{e}", self.current_node)
        finally:
            self.busy = False

    def _base_override(self, override: Optional[dict[str, Any]]) -> dict[str, Any]:
        """
        合并账号级默认覆盖和任务级覆盖：
            · 把账号的 package 注入到“通用_启动游戏”节点
            · 任务 override 中的同名节点字段优先
        """
        merged: dict[str, Any] = {}
        if self.account.package and self.account.device.type == "adb":
            merged["通用_启动游戏"] = {"package": self.account.package}
        for node, fields in (override or {}).items():
            merged[node] = {**merged.get(node, {}), **fields}
        return merged

    def stop(self) -> None:
        """请求停止当前任务，MAA 会在当前节点结束后退出。"""
        if self._tasker is not None and self._tasker.running:
            self.log.warning("请求停止当前任务（节点：%s）", self.current_node)
            self._tasker.post_stop().wait()

    def restart_app(self) -> bool:
        """
        关闭并重新打开游戏：
            端游：结束客户端进程 → 按 exe_path 重新启动 → 等窗口出现 → 重新连接（窗口句柄会变）
            手游：通过 adb 关闭并启动 package
        """
        if self.account.device.type == "win32":
            self.log.info("重启端游客户端")
            self.reset()
            if self.runtime.pc.restart(self.account) is None:
                return False
            return self.connect()
        if not self.account.package or self._controller is None:
            self.log.warning("未配置 package 或设备未连接，无法重启游戏")
            return False
        self.log.info("重启游戏 %s", self.account.package)
        self._controller.post_stop_app(self.account.package).wait()
        time.sleep(2)
        ok = self._controller.post_start_app(self.account.package).wait().succeeded
        self.touch()
        return ok

    def screencap(self):
        """截一张图（numpy BGR），用于调试或采集数据。"""
        if self._controller is None:
            return None
        return self._controller.post_screencap().wait().get()

    def reset(self) -> None:
        """丢弃当前连接，下一次 run_task 会重新连接（看门狗重启设备后调用）。"""
        with self._lock:
            self._tasker = None
            self._controller = None


class _HeartbeatSink:
    """
    MAA 上下文事件监听器：每当 Pipeline 进入一个节点或执行动作，就刷新 Worker 心跳并记录当前节点名。
    采用延迟导入的方式继承 ContextEventSink，避免在 dry-run 模式下强制依赖 maafw。
    """

    def __new__(cls, worker: BaseWorker):
        from maa.context import ContextEventSink

        class _Sink(ContextEventSink):
            def on_raw_notification(self, context, msg: str, details: dict[str, Any]) -> None:
                # 只有“真正进入节点 / 执行动作”才算有进展；单纯反复识别（等待）不刷新心跳，
                # 这样画面卡住、一直识别不到东西时，看门狗才能发现
                if msg.startswith(("Node.PipelineNode", "Node.Action")):
                    worker.touch(details.get("name", "") if isinstance(details, dict) else "")

        return _Sink()


class FakeWorker(BaseWorker):
    """
    演练模式 Worker：不连接任何设备。
    每次 run_task 随机睡 0.2~1 秒并以 fail_rate 概率失败，用于验证调度、组队、重试、看门狗逻辑。
    """

    def __init__(self, account: AccountConfig, runtime: Optional["Runtime"] = None, fail_rate: float = 0.1,
                 duration: tuple[float, float] = (0.2, 1.0)):
        super().__init__(account)
        self.runtime = runtime
        self.fail_rate = fail_rate
        self.duration = duration
        self._stop = threading.Event()
        self._connected = False
        self.history: list[str] = []      # 执行过的入口，测试用

    def connect(self) -> bool:
        self._connected = True
        self.touch()
        return True

    @property
    def connected(self) -> bool:
        return self._connected

    def run_task(self, entry: str, override: Optional[dict[str, Any]] = None) -> TaskResult:
        self.busy = True
        self._stop.clear()
        self.touch(entry)
        self.history.append(entry)
        try:
            # 分小段睡眠，以便 stop() 能及时打断
            end = time.monotonic() + random.uniform(*self.duration)
            while time.monotonic() < end:
                if self._stop.wait(0.05):
                    return TaskResult(False, "被停止", entry)
                self.touch()
            # 组队任务的同步点在真实环境由 Pipeline 中的 TeamBarrier 自定义动作触发，这里模拟同样的调用
            if self.team_context and self.runtime is not None:
                team, _role = self.team_context
                if not self.runtime.team.barrier(team, f"{self.current_task}:演练同步", self.account.name, timeout=10):
                    return TaskResult(False, "同步点超时或队伍已中止", entry)
            if random.random() < self.fail_rate:
                return TaskResult(False, "模拟失败", entry)
            return TaskResult(True, "模拟完成", entry)
        finally:
            self.busy = False

    def stop(self) -> None:
        self._stop.set()

    def restart_app(self) -> bool:
        self.touch()
        return True


def create_worker(account: AccountConfig, app: AppConfig, runtime: "Runtime", dry_run: bool) -> BaseWorker:
    """工厂方法：按是否演练创建 Worker。"""
    if dry_run:
        return FakeWorker(account, runtime)
    return MaaWorker(account, app, runtime)

