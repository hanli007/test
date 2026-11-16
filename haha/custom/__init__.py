"""
自定义识别与动作的注册入口。

每个账号的 Resource 都会调用一次 register_all，把绑定了该账号的实例注册进去，
Pipeline 里通过名字（如 "TeamBarrier"）引用。新增自定义模块时在这里登记即可。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maa.resource import Resource

    from core.runtime import Runtime
    from core.worker import BaseWorker


def register_all(resource: "Resource", runtime: "Runtime", worker: "BaseWorker") -> None:
    """
    向资源注册全部自定义识别和动作。

    参数:
        resource: 该账号的 MAA Resource
        runtime:  运行时（状态库、队伍协调器）
        worker:   该账号的 Worker
    """
    from . import actions, recognitions

    recos = {
        "BarBelow": recognitions.BarBelow(),
        "TeamRole": recognitions.TeamRole(worker),
        "KvCompare": recognitions.KvCompare(worker, runtime),
        "TeamFlag": recognitions.TeamFlag(worker, runtime),
    }
    acts = {
        "TeamBarrier": actions.TeamBarrier(worker, runtime),
        "TeamPublish": actions.TeamPublish(worker, runtime),
        "TeamWait": actions.TeamWait(worker, runtime),
        "SaveKv": actions.SaveKv(worker, runtime),
        "SaveProgress": actions.SaveProgress(worker, runtime),
        "FarmLoop": actions.FarmLoop(worker, runtime),
    }
    for name, obj in recos.items():
        if not resource.register_custom_recognition(name, obj):
            raise RuntimeError(f"注册自定义识别 {name} 失败")
    for name, obj in acts.items():
        if not resource.register_custom_action(name, obj):
            raise RuntimeError(f"注册自定义动作 {name} 失败")
