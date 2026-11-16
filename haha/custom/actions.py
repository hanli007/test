"""
自定义动作：Pipeline 中需要“跨实例协作”“读写状态”“实时循环”的部分，用 Python 实现。

在 Pipeline 中这样引用：
    "action": "Custom",
    "custom_action": "TeamBarrier",
    "custom_action_param": {"point": "全员到达NPC", "timeout": 120}

动作一览：
    TeamBarrier    组队同步点：全队到齐才继续（不在组队中时直接通过）
    TeamPublish    队长把识别到的文字/固定值写到队伍黑板
    TeamWait       队员等待黑板上出现某个值
    SaveKv         把固定值或 OCR 文字写入账号状态库
    SaveProgress   从 OCR 文字（如“师门 7/20”）解析进度写入状态库
    FarmLoop       即时制挂机打怪循环（传奇类）：检测怪物 → 攻击 → 捡物 → 吃药 → 背包满退出
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any, Optional

from maa.context import Context
from maa.custom_action import CustomAction

from .recognitions import parse_param

if TYPE_CHECKING:
    from core.runtime import Runtime
    from core.worker import BaseWorker


def reco_text(argv: CustomAction.RunArg) -> str:
    """取出前序识别（通常是 OCR）的文字；没有文字返回空串。"""
    detail = argv.reco_detail
    if detail is None or detail.best_result is None:
        return ""
    return getattr(detail.best_result, "text", "") or ""


class _Bound(CustomAction):
    """绑定了账号和运行时的动作基类。"""

    def __init__(self, worker: "BaseWorker", runtime: "Runtime"):
        super().__init__()
        self.worker = worker
        self.runtime = runtime

    @property
    def me(self) -> str:
        """当前账号名。"""
        return self.worker.account.name

    @property
    def team_name(self) -> Optional[str]:
        """当前所在队伍名；不在组队任务中返回 None。"""
        return self.worker.team_context[0] if self.worker.team_context else None


class TeamBarrier(_Bound):
    """
    组队同步点。

    参数:
        point:   同步点名称（同一任务里不同位置用不同名字）
        timeout: 等待秒数，默认 120；超时会中止整队本轮
    返回:
        全员到齐 True；超时/队伍中止 False（Pipeline 会走 on_error）
    """

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        p = parse_param(argv.custom_action_param)
        if self.team_name is None:
            return True
        point = p.get("point", argv.node_name)
        self.worker.log.info("等待队友：%s", point)
        # 等待期间持续刷新心跳，避免看门狗误判卡死
        self.worker.touch(argv.node_name)
        ok = self.runtime.team.barrier(self.team_name, point, self.me, float(p.get("timeout", 120)))
        self.worker.touch(argv.node_name)
        return ok


class TeamPublish(_Bound):
    """
    往队伍黑板写数据（一般由队长执行）。

    参数:
        key:   键名
        value: 固定值；不填则使用前序 OCR 识别到的文字
    """

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        p = parse_param(argv.custom_action_param)
        if self.team_name is None:
            return True
        value = p["value"] if "value" in p else reco_text(argv)
        self.runtime.team.publish(self.team_name, p["key"], value)
        self.worker.log.info("黑板写入 %s=%r", p["key"], value)
        return True


class TeamWait(_Bound):
    """
    等待队伍黑板上出现某个键（一般由队员执行），值会同时存入账号 kv，便于后续节点使用。

    参数:
        key:     键名
        timeout: 等待秒数，默认 60
    """

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        p = parse_param(argv.custom_action_param)
        if self.team_name is None:
            return True
        self.worker.touch(argv.node_name)
        value = self.runtime.team.wait_for(self.team_name, p["key"], float(p.get("timeout", 60)))
        self.worker.touch(argv.node_name)
        if value is None:
            return False
        self.runtime.store.set_kv(self.me, f"team.{p['key']}", value)
        return True


class SaveKv(_Bound):
    """
    把数据写入账号状态库。

    参数:
        key:   键名
        value: 固定值；不填则使用前序 OCR 文字
    """

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        p = parse_param(argv.custom_action_param)
        value = p["value"] if "value" in p else reco_text(argv)
        self.runtime.store.set_kv(self.me, p["key"], value)
        return True


class SaveProgress(_Bound):
    """
    从 OCR 文字中解析“当前/总数”进度并写入状态库，例如“师门任务(7/20)” → {"cur": 7, "total": 20}。
    达到总数时返回成功并可配合 next 跳转到“结束”节点。

    参数:
        key:   键名，如 "师门进度"
        regex: 解析用正则，需包含两个分组，默认 r"(\\d+)\\s*/\\s*(\\d+)"
    """

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        p = parse_param(argv.custom_action_param)
        text = reco_text(argv)
        m = re.search(p.get("regex", r"(\d+)\s*/\s*(\d+)"), text)
        if not m:
            self.worker.log.warning("无法从 %r 解析进度", text)
            return True   # 解析失败不影响主流程
        cur, total = int(m.group(1)), int(m.group(2))
        self.runtime.store.set_kv(self.me, p["key"], {"cur": cur, "total": total})
        self.worker.log.info("%s：%d/%d", p["key"], cur, total)
        return True


class FarmLoop(_Bound):
    """
    即时制挂机打怪循环（传奇类游戏）。所有识别/点击都引用 Pipeline 中定义好的节点，
    这样换游戏只需要改 Pipeline 和模板图，不用改代码。

    参数（均为节点名，除数值外都可省略）:
        duration_sec:   最长挂机时间，默认 1800
        monster_node:   识别怪物的节点（TemplateMatch 或 NeuralNetworkDetect），动作为 Click 目标
        loot_node:      识别掉落物的节点，动作为 Click 目标
        hp_low_node:    血量低的识别节点（通常是 Custom: BarBelow）
        potion_node:    吃药动作节点（ClickKey 或 Click 药品栏）
        bag_full_node:  背包已满的识别节点，命中后写 kv “背包已满”=true 并结束
        dead_node:      角色死亡的识别节点，命中后结束并返回失败
        wander_node:    连续 idle_limit 轮没怪时执行的换位置动作节点
        attack_wait_ms: 点怪后等待多久再进行下一轮，默认 1500
        idle_limit:     连续多少轮没识别到怪就换位置，默认 10
        interval_ms:    每轮最短间隔，默认 300
    返回:
        正常到时或背包满 True；死亡/被停止/截图失败 False
    """

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        p = parse_param(argv.custom_action_param)
        tasker = context.tasker
        ctrl = tasker.controller
        deadline = time.monotonic() + float(p.get("duration_sec", 1800))
        attack_wait = float(p.get("attack_wait_ms", 1500)) / 1000
        interval = float(p.get("interval_ms", 300)) / 1000
        idle_limit = int(p.get("idle_limit", 10))
        idle = 0
        kills = 0

        def hit(node: Optional[str], image) -> Any:
            """对节点做一次识别，命中返回识别详情，否则返回 None。"""
            if not node:
                return None
            d = context.run_recognition(node, image)
            return d if d is not None and d.hit else None

        def act(node: Optional[str], box=(0, 0, 0, 0)) -> None:
            """执行节点上定义的动作。"""
            if node:
                context.run_action(node, box)

        self.worker.log.info("开始挂机，最长 %d 秒", int(deadline - time.monotonic()))
        while time.monotonic() < deadline:
            if tasker.stopping:
                return False
            loop_start = time.monotonic()
            self.worker.touch(argv.node_name)
            image = ctrl.post_screencap().wait().get()
            if image is None or image.size == 0:
                self.worker.log.error("截图失败")
                return False

            if hit(p.get("dead_node"), image):
                self.worker.log.warning("角色死亡，结束挂机")
                return False
            if hit(p.get("bag_full_node"), image):
                self.worker.log.info("背包已满，结束挂机（本次击杀约 %d）", kills)
                self.runtime.store.set_kv(self.me, "背包已满", True)
                return True
            if hit(p.get("hp_low_node"), image):
                act(p.get("potion_node"))

            loot = hit(p.get("loot_node"), image)
            if loot:
                act(p["loot_node"], loot.box)
                continue

            monster = hit(p.get("monster_node"), image)
            if monster:
                idle = 0
                kills += 1
                act(p["monster_node"], monster.box)
                time.sleep(attack_wait)
                continue

            idle += 1
            if idle >= idle_limit:
                idle = 0
                act(p.get("wander_node"))
            # 控制循环频率，避免空转占满 CPU
            rest = interval - (time.monotonic() - loop_start)
            if rest > 0:
                time.sleep(rest)

        self.worker.log.info("挂机到时，击杀约 %d", kills)
        return True
