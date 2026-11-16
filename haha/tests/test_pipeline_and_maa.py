"""
Pipeline 静态检查 + MaaFramework 真实集成测试。

集成测试使用 MAA 的 DbgController（用图片目录代替真实设备），
在合成截图上验证：资源加载、模板匹配、自定义识别/动作注册与调用、FarmLoop 循环、组队同步。
未安装 maafw 时自动跳过集成部分。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np
import pytest

from core.config import AccountConfig, DeviceConfig
from core.runtime import Runtime
from core.state_store import StateStore
from core.team import TeamCoordinator
from tests.conftest import ROOT
from tools.capture import save_png
from tools.pipeline_check import check_resource, strip_jsonc

maa = pytest.importorskip("maa")


# ------------------------------------------------------------------ 静态检查

def test_strip_jsonc_keeps_strings():
    text = '{"a": "http://x//y", // 注释\n "b": [1, 2,], /* 块 */ "c": "/*不是注释*/"}'
    assert json.loads(strip_jsonc(text)) == {"a": "http://x//y", "b": [1, 2], "c": "/*不是注释*/"}


def test_repo_resource_has_no_errors():
    """仓库自带 Pipeline 不能有引用错误（占位图警告允许存在）。"""
    from core.config import load_config

    cfg = load_config(ROOT / "config" / "config.example.yaml")
    entries = [e for t in cfg.tasks.values() for e in (t.entry, t.leader_entry, t.member_entry) if e]
    rep = check_resource([ROOT / "resource" / "base"], entries)
    errors = [e for e in rep.errors if "OCR 模型缺失" not in e]   # CI 环境可能没下载模型
    assert errors == []


def test_check_detects_broken_refs(tmp_path):
    (tmp_path / "pipeline").mkdir()
    (tmp_path / "pipeline" / "a.json").write_text(json.dumps({
        "A": {"next": ["[JumpBack]不存在"], "action": "Custom", "custom_action": "没注册"},
        "B": {"recognition": "TemplateMatch", "template": "x.png", "action": "Click", "target": "幽灵"},
    }), encoding="utf-8")
    rep = check_resource([tmp_path], ["入口"])
    joined = "\n".join(rep.errors)
    for word in ("不存在", "没注册", "x.png", "幽灵", "入口"):
        assert word in joined


# ------------------------------------------------------------------ 集成测试

def _scene(seed: int = 0) -> np.ndarray:
    """生成一张 1280x720 的随机纹理“游戏画面”。"""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8)


@pytest.fixture
def maa_env(tmp_path):
    """
    搭建一套临时资源 + 截图目录：
        截图：随机纹理，左上角 (60,22) 画一段只有 20% 红色的“血条”
        模板：从截图 (600,300) 处裁剪 40x40 作为“怪物”
    """
    img = _scene()
    img[22:32, 70:230] = (40, 40, 40)
    img[22:32, 70:102] = (0, 0, 220)              # 血条只剩 32/160 = 20%
    shots = tmp_path / "shots"
    shots.mkdir()
    save_png(img, shots / "frame.png")

    res = tmp_path / "res"
    (res / "image").mkdir(parents=True)
    (res / "pipeline").mkdir()
    save_png(img[300:340, 600:640].copy(), res / "image" / "怪物.png")
    pipeline = {
        "测试_找怪": {
            "recognition": "TemplateMatch", "template": "怪物.png", "threshold": 0.95,
            "action": "Click", "next": ["测试_记录"],
        },
        "测试_记录": {
            "action": "Custom", "custom_action": "SaveKv",
            "custom_action_param": {"key": "看到怪物", "value": True},
            "next": ["测试_血量低"],
        },
        "测试_血量低": {
            "recognition": "Custom", "custom_recognition": "BarBelow",
            "custom_recognition_param": {"roi": [70, 22, 160, 10], "lower": [0, 0, 150],
                                         "upper": [90, 90, 255], "below": 0.35},
            "action": "Custom", "custom_action": "SaveKv",
            "custom_action_param": {"key": "血量低", "value": True},
            "timeout": 3000,
        },
        "测试_不存在的东西": {
            "recognition": "TemplateMatch", "template": "怪物.png", "roi": [0, 0, 100, 100],
            "threshold": 0.95,
        },
        "测试_挂机": {
            "action": "Custom", "custom_action": "FarmLoop",
            "custom_action_param": {"duration_sec": 1.5, "monster_node": "测试_找怪_仅点击",
                                    "hp_low_node": "测试_血量低_仅识别", "potion_node": "测试_吃药",
                                    "attack_wait_ms": 100},
        },
        "测试_找怪_仅点击": {"recognition": "TemplateMatch", "template": "怪物.png", "threshold": 0.95,
                         "action": "Click"},
        "测试_血量低_仅识别": {"recognition": "Custom", "custom_recognition": "BarBelow",
                          "custom_recognition_param": {"roi": [70, 22, 160, 10], "below": 0.35}},
        "测试_吃药": {"action": "Click", "target": [980, 640, 50, 50]},
        "测试_组队": {
            "action": "Custom", "custom_action": "TeamBarrier",
            "custom_action_param": {"point": "集合", "timeout": 10},
        },
    }
    (res / "pipeline" / "test.json").write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")
    return shots, res


def _worker(name, shots, res, runtime_cfg_dirs):
    """构造一个使用 DbgController 的真实 MaaWorker。"""
    from core.config import AppConfig, EmulatorConfig, GlobalConfig
    from core.worker import MaaWorker

    acc = AccountConfig(name=name, device=DeviceConfig(type="debug", image_dir=str(shots)))
    app = AppConfig(GlobalConfig(resource_dirs=[str(res)]), EmulatorConfig(), {name: acc}, {}, {}, ROOT)
    return MaaWorker(acc, app, runtime_cfg_dirs)


@pytest.fixture
def runtime():
    return Runtime(None, StateStore(":memory:"), TeamCoordinator())


def test_maa_pipeline_with_custom_modules(maa_env, runtime):
    shots, res = maa_env
    w = _worker("甲", shots, res, runtime)
    assert w.connect()
    assert w.connected

    r = w.run_task("测试_找怪")
    assert r.success, r.message
    assert r.last_node == "测试_血量低"
    assert runtime.store.get_kv("甲", "看到怪物") is True
    assert runtime.store.get_kv("甲", "血量低") is True   # BarBelow 识别到 20% < 35%

    # 识别不到的节点：作为入口时 DirectHit 之外的识别不命中 → 任务失败
    r = w.run_task("测试_不存在的东西")
    assert not r.success


def test_maa_farm_loop(maa_env, runtime):
    shots, res = maa_env
    w = _worker("乙", shots, res, runtime)
    assert w.connect()
    r = w.run_task("测试_挂机")
    assert r.success, r.message
    assert w.idle_seconds < 5      # 循环期间持续刷新心跳
    clicks = w._controller.clicks()
    # 点到了怪物（模板位于 600,300 起的 40x40）和药品栏（980,640 起的 50x50）
    assert any(600 <= x < 640 and 300 <= y < 340 for x, y in clicks)
    assert any(980 <= x < 1030 and 640 <= y < 690 for x, y in clicks)


def _encode_png_with_filters(img: np.ndarray) -> bytes:
    """用 PNG 的 5 种行过滤器轮流编码（测试解码器用）。"""
    import struct
    import zlib

    rgb = img[:, :, ::-1].astype(np.int32)
    h, w = rgb.shape[:2]
    bpp, rows, prev = 3, [], np.zeros(w * 3, np.int32)
    for y in range(h):
        cur = rgb[y].reshape(-1)
        f = y % 5
        left = np.concatenate([np.zeros(bpp, np.int32), cur[:-bpp]])
        ul = np.concatenate([np.zeros(bpp, np.int32), prev[:-bpp]])
        if f == 0:
            line = cur
        elif f == 1:
            line = cur - left
        elif f == 2:
            line = cur - prev
        elif f == 3:
            line = cur - ((left + prev) >> 1)
        else:
            p = left + prev - ul
            pa, pb, pc = abs(p - left), abs(p - prev), abs(p - ul)
            pred = np.where((pa <= pb) & (pa <= pc), left, np.where(pb <= pc, prev, ul))
            line = cur - pred
        rows.append(bytes([f]) + (line & 0xFF).astype(np.uint8).tobytes())
        prev = cur

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def test_read_png_all_filters(tmp_path):
    from core.image_controller import read_png

    img = _scene(3)[:20, :30].copy()
    p = tmp_path / "f.png"
    p.write_bytes(_encode_png_with_filters(img))
    assert np.array_equal(read_png(p), img)
    save_png(img, tmp_path / "g.png")
    assert np.array_equal(read_png(tmp_path / "g.png"), img)


def test_maa_team_barrier_across_instances(maa_env, runtime):
    """两个独立 MAA 实例通过 TeamBarrier 自定义动作同步。"""
    shots, res = maa_env
    runtime.team.register("队", ["甲", "乙"])
    runtime.team.begin_round("队")
    workers = {n: _worker(n, shots, res, runtime) for n in ("甲", "乙")}
    results = {}

    def go(n):
        w = workers[n]
        assert w.connect()
        w.team_context = ("队", "leader" if n == "甲" else "member")
        results[n] = w.run_task("测试_组队").success

    ts = [threading.Thread(target=go, args=(n,)) for n in workers]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    assert results == {"甲": True, "乙": True}


def test_maa_team_barrier_timeout(maa_env, runtime):
    """只有一个人到达同步点 → 超时失败，Pipeline 任务失败。"""
    shots, res = maa_env
    runtime.team.register("队", ["甲", "缺席者"])
    runtime.team.begin_round("队")
    w = _worker("甲", shots, res, runtime)
    assert w.connect()
    w.team_context = ("队", "leader")
    r = w.run_task("测试_组队", {"测试_组队": {"custom_action_param": {"point": "集合", "timeout": 0.5}}})
    assert not r.success
    assert "缺席者" in runtime.team.aborted_reason("队")


def test_repo_resource_loads_in_maa():
    """仓库自带资源能被 MAA 真实加载（需要先下载 OCR 模型）。"""
    if not (ROOT / "resource" / "base" / "model" / "ocr" / "rec.onnx").is_file():
        pytest.skip("未下载 OCR 模型")
    from maa.resource import Resource

    assert Resource().post_bundle(ROOT / "resource" / "base").wait().succeeded
