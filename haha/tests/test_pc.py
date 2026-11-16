"""
端游（win32）相关测试。

Win32 API 和 MAA 的 Win32Controller 只能在 Windows 上运行，这里测试的是可以跨平台验证的部分：
窗口筛选规则、客户端管理逻辑（注入假的系统接口）、配置校验、端游资源覆盖层在真实 MAA 中的加载结果。
"""

from __future__ import annotations

import logging

import pytest

from core.config import WIN32_INPUT_METHODS, WIN32_SCREENCAP_METHODS, AccountConfig, ConfigError, DeviceConfig
from core.pc_client import PcClientManager
from core.win32 import WindowInfo, select_window
from tests.conftest import ROOT
from tools.pipeline_check import check_resource


# ------------------------------------------------------------------ 窗口筛选

def _w(hwnd, title="梦幻西游 - 账号", pid=None, cls="GameWnd", visible=True):
    return WindowInfo(hwnd, title, cls, pid if pid is not None else hwnd * 10, visible)


def test_select_window_rules():
    wins = [_w(300), _w(100), _w(200, visible=False), _w(400, title=""), _w(500, title="记事本", cls="Notepad")]
    assert select_window(wins, "^梦幻").hwnd == 100                 # 按句柄排序，忽略隐藏和无标题窗口
    assert select_window(wins, "^梦幻", index=1).hwnd == 300
    assert select_window(wins, "^梦幻", index=2) is None
    assert select_window(wins, class_pattern="Notepad").hwnd == 500
    assert select_window(wins, "^梦幻", pid=3000).hwnd == 300
    assert select_window(wins, "不存在") is None


# ------------------------------------------------------------------ 客户端管理（假系统接口）

class FakeWin:
    """模拟 Windows：维护窗口列表，launch 会在下一次轮询时“弹出”一个新进程的窗口。"""

    def __init__(self, windows=()):
        self.windows = list(windows)
        self.next_hwnd = 1000
        self.launched, self.killed, self.resized = [], [], []
        self.sizes = {}

    def list_windows(self):
        return list(self.windows)

    def launch(self, exe, args="", cwd=""):
        self.launched.append(exe)
        self.next_hwnd += 1
        # 模拟“登录器拉起游戏进程”：窗口所属 pid 与 launch 返回值无关
        self.windows.append(_w(self.next_hwnd, pid=self.next_hwnd * 10))
        return 1

    def kill_pid(self, pid):
        self.killed.append(pid)
        self.windows = [w for w in self.windows if w.pid != pid]
        return True

    def kill_name(self, name):
        self.killed.append(name)
        return True

    def is_window(self, hwnd):
        return any(w.hwnd == hwnd for w in self.windows)

    def restore_window(self, hwnd):
        pass

    def client_size(self, hwnd):
        return self.sizes.get(hwnd, (1024, 768))

    def set_client_size(self, hwnd, w, h):
        self.resized.append((hwnd, w, h))
        self.sizes[hwnd] = (w, h)
        return True


def _acc(name, **dev):
    dev.setdefault("window_title", "^梦幻")
    dev.setdefault("launch_wait_sec", 2)
    return AccountConfig(name=name, device=DeviceConfig(type="win32", **dev))


def test_multi_open_binds_different_windows():
    api = FakeWin([_w(100), _w(200)])
    pc = PcClientManager(api, poll_sec=0.01)
    a, b, c = _acc("A"), _acc("B"), _acc("C")
    assert pc.ensure_running(a) == 100
    assert pc.ensure_running(b) == 200            # 自动跳过已被 A 占用的窗口
    assert pc.ensure_running(c) is None           # 没有空闲窗口且未配置 exe_path
    assert pc.ensure_running(a) == 100            # 再次调用仍是同一个窗口
    assert (100, 1280, 720) in api.resized        # 客户区被调整为 1280x720


def test_window_index_is_respected():
    api = FakeWin([_w(100), _w(200)])
    pc = PcClientManager(api, poll_sec=0.01)
    assert pc.ensure_running(_acc("A", window_index=1)) == 200


def test_launch_when_missing_and_ignore_existing_process():
    api = FakeWin([_w(100)])
    pc = PcClientManager(api, poll_sec=0.01)
    pc.ensure_running(_acc("A"))                                  # A 占用 100
    hwnd = pc.ensure_running(_acc("B", exe_path="C:/game.exe"))   # B 没有空闲窗口 → 启动
    assert api.launched == ["C:/game.exe"]
    assert hwnd == 1001 and hwnd != 100


def test_launch_timeout_returns_none():
    api = FakeWin()
    api.launch = lambda *a, **k: 1          # 启动后永远不出现窗口
    pc = PcClientManager(api, poll_sec=0.01)
    assert pc.ensure_running(_acc("A", exe_path="C:/game.exe", launch_wait_sec=0.1)) is None


def test_restart_kills_only_own_process():
    api = FakeWin([_w(100), _w(200)])
    pc = PcClientManager(api, poll_sec=0.01)
    a = _acc("A", exe_path="C:/game.exe")
    b = _acc("B", exe_path="C:/game.exe")
    pc.ensure_running(a)
    pc.ensure_running(b)
    new = pc.restart(a, wait_sec=0)
    assert api.killed == [1000]             # 只结束 A 的进程（hwnd 100 → pid 1000）
    assert new == 1001
    assert pc.alive(b) and pc.alive(a)


def test_alive_detects_closed_window():
    api = FakeWin([_w(100)])
    pc = PcClientManager(api, poll_sec=0.01)
    a = _acc("A")
    pc.ensure_running(a)
    assert pc.alive(a)
    api.windows.clear()                     # 客户端闪退
    assert not pc.alive(a)


def test_rebind_follows_process_when_hwnd_changes():
    """客户端重建窗口（句柄变化、进程不变）时，仍绑定到同一进程的新窗口。"""
    api = FakeWin([_w(100, pid=7), _w(200, pid=8)])
    pc = PcClientManager(api, poll_sec=0.01)
    a = _acc("A")
    pc.ensure_running(a)
    api.windows = [_w(150, pid=7), _w(200, pid=8)]
    assert pc.ensure_running(a) == 150


# ------------------------------------------------------------------ 配置校验

def test_win32_config_validation(write_config, caplog):
    def cfg(dev):
        return write_config(f"""
        accounts:
          - {{name: P, device: {dev}}}
        """)

    with pytest.raises(ConfigError, match="window_title"):
        cfg("{type: win32}")
    with pytest.raises(ConfigError, match="screencap"):
        cfg("{type: win32, window_title: x, screencap: 'FramePool|XXX'}")
    with pytest.raises(ConfigError, match="mouse_input"):
        cfg("{type: win32, window_title: x, mouse_input: Click}")
    with pytest.raises(ConfigError, match="正则"):
        cfg("{type: win32, window_title: '[abc'}")
    with caplog.at_level(logging.WARNING):
        c = cfg("{type: win32, window_title: x, screencap: 'FramePool|PrintWindow', client_size: [1024, 768]}")
    assert "不是 16:9" in caplog.text
    assert c.accounts["P"].device.mouse_input == "PostMessage"


def test_method_names_match_maa_enums():
    """配置允许的方式名必须与 maafw 枚举一一对应，否则运行时 getattr 会失败。"""
    pytest.importorskip("maa")
    from maa.define import MaaWin32InputMethodEnum, MaaWin32ScreencapMethodEnum

    for n in WIN32_SCREENCAP_METHODS:
        assert hasattr(MaaWin32ScreencapMethodEnum, n), n
    for n in WIN32_INPUT_METHODS:
        assert hasattr(MaaWin32InputMethodEnum, n), n


# ------------------------------------------------------------------ 端游资源覆盖层

def test_pc_overlay_static_check():
    dirs = [ROOT / "resource" / "base", ROOT / "resource" / "pc"]
    rep = check_resource(dirs)
    assert [e for e in rep.errors if "OCR 模型缺失" not in e] == []
    # 模拟 MAA 合并规则：改了识别类型后，旧的 template 参数被丢弃
    skill = rep.nodes["战斗_选择技能"]
    assert skill["recognition"] == "DirectHit" and "template" not in skill and skill["key"] == 112


def test_pc_overlay_loads_in_maa():
    """在真实 MAA 中叠加 base + pc，确认覆盖结果符合预期。"""
    pytest.importorskip("maa")
    if not (ROOT / "resource" / "base" / "model" / "ocr" / "rec.onnx").is_file():
        pytest.skip("未下载 OCR 模型")
    from maa.resource import Resource

    res = Resource()
    assert res.post_bundle(ROOT / "resource" / "base").wait().succeeded
    assert res.post_bundle(ROOT / "resource" / "pc").wait().succeeded

    move = res.get_node_data("挂机_换位置")["action"]
    assert move["type"] == "LongPress"
    assert move["param"]["target"] == [560, 160, 160, 80] and move["param"]["contact"] == 1

    potion = res.get_node_data("挂机_吃药")["action"]
    assert potion["type"] == "ClickKey" and potion["param"]["key"] == [112]

    assert res.get_node_data("通用_启动游戏")["action"]["type"] == "DoNothing"
    # 未覆盖的字段沿用 base
    back = res.get_node_data("通用_返回按钮")
    assert back["recognition"]["type"] == "TemplateMatch"
    assert back["action"]["type"] == "ClickKey"
