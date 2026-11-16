# mmo-auto：MMO 多开自动化框架（MaaFramework + 自研编排层）

面向传奇、梦幻西游、问道这类 2D MMO 的多开自动化框架：
**MAA 负责“一个号怎么做一件事”，自研编排层负责“哪个号什么时候做什么、几个号怎么配合”。**

```
自研编排层（core/）       多开管理 · 组队同步 · 账号状态库 · 调度 · 看门狗
        │
MAA（每个账号一个实例）    Pipeline 任务流程 · 截图/点击 · 模板匹配 · OCR · YOLO
        │
模拟器多开（adb）/ PC 窗口（win32）/ 图片目录（debug，离线调试）
```

> ⚠️ 风险提示：官服多开、组队挂机违反大多数游戏的用户协议，有封号风险；
> 用于工作室批量搬砖或出售脚本牟利可能触犯法律。本项目只做纯外部的图像识别 + 模拟输入，
> 不包含也不会提供读内存、改封包、绕过反作弊等功能。请仅在私服、自己搭的服或测试环境中使用。

---

## 一、目录结构

```
mmo-auto/
├── main.py                     命令行入口（run / task / status / reset / devices / check）
├── config/
│   └── config.example.yaml     配置示例（复制为 config.yaml 使用）
├── core/                       自研编排层
│   ├── config.py               配置加载与校验（未知字段、错误引用会直接报错）
│   ├── state_store.py          SQLite 状态库：每日进度、失败次数、自定义 kv、运行流水
│   ├── scheduler.py            调度器：按优先级 / 每日次数 / 时间窗口 / 失败冷却选任务
│   ├── team.py                 队伍协调器：同步点 barrier、共享黑板、全队中止
│   ├── worker.py               账号执行器：MaaWorker（真实）/ FakeWorker（演练）
│   ├── image_controller.py     图片目录控制器：用截图代替设备，离线调试 Pipeline
│   ├── emulator.py             模拟器管理：启动 / 关闭 / 重启 / 等待就绪
│   ├── pc_client.py            端游客户端管理：找窗口 / 多开区分 / 启动 / 重启 / 调窗口尺寸
│   ├── win32.py                Windows 窗口与进程接口（纯 ctypes）
│   ├── watchdog.py             看门狗：卡死检测（无进展 / 超时）
│   ├── orchestrator.py         编排器：串起以上所有模块，并发控制、组队执行、卡死恢复
│   ├── runtime.py              运行时共享对象
│   └── logger.py               日志
├── custom/                     MAA 自定义模块（Pipeline 中按名字引用）
│   ├── __init__.py             注册入口
│   ├── recognitions.py         BarBelow / TeamRole / KvCompare / TeamFlag
│   └── actions.py              TeamBarrier / TeamPublish / TeamWait / SaveKv / SaveProgress / FarmLoop
├── resource/base/              MAA 资源包
│   ├── default_pipeline.json   全局默认参数
│   ├── pipeline/
│   │   ├── common.json         通用：启动游戏、回主界面、关弹窗、断线重连、登录
│   │   ├── combat_turn.json    回合制战斗子流程（梦幻/问道）
│   │   ├── shimen.json         单人任务示例：师门
│   │   ├── team_zhuagui.json   组队任务示例：抓鬼（队长/队员两套入口）
│   │   └── farm.json           即时制挂机示例：传奇打怪、捡物、吃药、回城清包
│   ├── image/                  模板图（当前是占位图，需截图替换）
│   └── model/ocr|detect/       OCR 模型 / YOLO 模型
├── resource/pc/                端游覆盖层（叠加在 base 之后加载，只写与手游不同的部分）
│   ├── pipeline/               common_pc / combat_pc / farm_pc：快捷键出招、按键吃药、右键移动等
│   └── image/                  端游截图放这里，与 base 同路径即覆盖
├── tools/
│   ├── pipeline_check.py       静态检查 Pipeline（引用、模板、自定义模块名）
│   ├── make_placeholders.py    为缺失模板生成占位图
│   ├── download_ocr.py         下载 OCR 模型
│   ├── capture.py              设备截图采集（做模板 / 采集 YOLO 数据集）
│   ├── yolo_train.py           YOLO 训练 + 导出 ONNX（可选）
│   └── dataset.example.yaml    YOLO 数据集配置示例
└── tests/                      40 个测试，含真实 MAA 集成测试
```

## 二、快速开始

```bash
# 1. 安装依赖（Python 3.10+，Windows / Linux / macOS 均可）
pip install -r requirements.txt

# 2. 下载 OCR 模型（约 21MB；网络慢可加 --mirror https://ghfast.top/）
python tools/download_ocr.py

# 3. 复制配置并修改账号、设备地址、模拟器路径
copy config\config.example.yaml config\config.yaml     # Linux/macOS 用 cp

# 4. 查看本机模拟器的 adb 地址，填进 config.yaml
python main.py devices

# 5. 检查配置和 Pipeline
python main.py check --load

# 6. 先用演练模式验证调度/组队逻辑（不连设备）
python main.py run --dry-run --once

# 7. 单账号调试某个流程
python main.py task 梦幻1 通用_回到主界面

# 8. 正式运行
python main.py run            # 常驻，按时间窗口持续调度
python main.py run --once     # 做完当前能做的就退出（可配合 Windows 计划任务每天定时跑）
python main.py status         # 查看今天进度
python main.py reset          # 清空今天进度重做
```

## 三、适配到你的游戏（最主要的工作量）

示例 Pipeline 是按梦幻/问道/传奇的**通用界面逻辑**写的，坐标、文字、模板图都要按实际游戏调整：

1. **截模板图**：`python tools/capture.py 梦幻1` 截一张 1280x720 原图，裁剪出按钮/图标，
   覆盖 `resource/base/image/` 下的同名占位图。也可以用 MAA 的 VSCode 插件或 MFA 工具箱直接截图裁剪。
   `python main.py check` 会列出所有仍是占位图的模板。
2. **调 ROI 和文字**：OCR 节点的 `expected`（支持正则）和 `roi` 按实际界面修改。
3. **单步调试**：`python main.py task 账号 节点名` 运行单个入口；
   `config.yaml` 里 `maa_debug: true` 会把每次识别的截图保存到 `logs/maa/`。
4. **离线调试**：把截图放进一个目录，账号配置为 `device: {type: debug, image_dir: 截图目录}`，
   不开游戏也能反复验证 Pipeline 识别是否正确。
5. **可视化编辑**：Pipeline 是标准 MAA 格式，可以用 [MaaPipelineEditor](https://mpe.codax.site/stable/)
   或 VSCode 插件 `maa-support` 可视化编辑和调试。

### Pipeline 写法约定

- 坐标统一按 **1280x720**（MAA 会自动缩放截图）。
- 采用“**状态机**”写法：一个 `xxx_循环` 节点列出所有可能的界面状态，每个状态节点处理完回到循环节点，
  识别到“已完成”就结束。参考 `shimen.json`。
- 可复用的子流程（战斗、关弹窗）用 `"[JumpBack]节点名"` 引用，处理完自动回到原流程。
- 结束节点的 `next` 为空 → 任务成功；`next` 超时且 `on_error` 未接住 → 任务失败（编排层会按 `max_retry` 重试）。

## 四、核心机制说明

### 1. 调度规则（core/scheduler.py）
按以下条件为每个账号/队伍选任务：在时间窗口内 → 今日完成数 < `daily_limit` →
失败次数 ≤ `max_retry` → 已过失败冷却 → 取 `priority` 最小的。
组队任务优先于队员各自的单人任务；进度记在 `@队伍名` 下。

### 2. 组队同步（core/team.py + custom/actions.py）
| Pipeline 中的用法 | 作用 |
|---|---|
| `"custom_action": "TeamBarrier", "custom_action_param": {"point": "抓鬼开始"}` | 全队到齐才继续；超时则整队中止 |
| `"custom_action": "TeamPublish", "custom_action_param": {"key": "抓鬼结束", "value": true}` | 队长写黑板 |
| `"custom_recognition": "TeamFlag", "custom_recognition_param": {"key": "抓鬼结束"}` | 队员识别黑板信号 |
| `"custom_action": "TeamWait", "custom_action_param": {"key": "目标"}` | 队员阻塞等待黑板数据 |
| `"custom_recognition": "TeamRole", "custom_recognition_param": {"role": "leader"}` | 同一 Pipeline 按角色分支 |

任何一个账号失败或卡死 → 整队中止 → 其他人立即停止 → 本轮记失败，冷却后重试。
不在组队任务中时，这些动作直接通过，同一份 Pipeline 单人也能跑。

### 3. 看门狗与恢复（core/watchdog.py + orchestrator.py）
- **卡死判定**：`stuck_sec` 秒内没有进入新节点或执行动作（单纯反复识别不算进展），或单次任务超过 `timeout_min`。
- **恢复顺序**：停止任务 → 重启游戏 → 仍不行就重启模拟器并重连。每个账号每天最多恢复 `max_recover` 次。
- 长时间等待的节点（如队员跟随）要在循环里放一个会命中的“等待中”节点（参考 `抓鬼_队员_跟随中`），避免被误判卡死。

### 4. 即时制挂机（custom/actions.py: FarmLoop）
用 Python 高频循环处理“打怪 → 捡物 → 吃药 → 背包满回城”，每一步都引用 `farm.json` 中的节点做识别和点击，
**换游戏只改 Pipeline 和模板图，不用改代码**。

### 5. 账号状态库（core/state_store.py）
SQLite 文件 `data/state.db`，程序崩溃重启后接着做。自定义动作 `SaveKv` / `SaveProgress` 可以把
OCR 读到的信息（如“师门 7/20”）存进来，`KvCompare` 识别可以在 Pipeline 中按这些数据分支（如背包满了去清包）。

## 五、可选：YOLO 怪物识别

模板匹配识别怪物效果不好时（怪物外形多变、和背景混在一起）再用：

```bash
python tools/capture.py 传奇1 --count 500 --interval 3 --out dataset/raw   # 采集
# 用 X-AnyLabeling / Label Studio 标注，导出 YOLO 格式
pip install ultralytics
python tools/yolo_train.py --data tools/dataset.example.yaml --epochs 100  # 训练 + 导出 ONNX
```
然后把 `farm.json` 中 `FarmLoop` 参数的 `monster_node` 改为 `挂机_识别怪物_YOLO`。
MAA 官方说明支持 YOLOv8 / YOLO11 导出的 ONNX，所以脚本默认用 `yolo11n`。

## 六、端游支持（仅 Windows）

### 1. 配置账号
```yaml
- name: 端游1
  resource_dirs: [resource/base, resource/pc]   # 叠加端游覆盖层
  device:
    type: win32
    window_title: "^梦幻西游"          # 窗口标题正则（python main.py devices 查看）
    window_class: ""                  # 类名正则（可选，标题会变的游戏用类名更稳）
    window_index:                     # 多开时指定第几个窗口；不填则自动分配
    exe_path: "D:/Games/xx/my.exe"    # 填了才能自动启动、卡死重启
    client_size: [1280, 720]          # 自动调整客户区尺寸，与 Pipeline 坐标一致
    screencap: Background             # 截图方式
    mouse_input: PostMessage          # 鼠标输入方式
    keyboard_input: PostMessage       # 键盘输入方式
```

### 2. 多开怎么区分窗口
1. 本程序启动的客户端会记住进程号，之后只认这个进程的窗口（客户端重建窗口也不会串号）
2. 配置了 `window_index` 就取第 N 个匹配窗口（按句柄排序，`devices` 命令的输出顺序）
3. 都没有时，自动分配第一个“还没被其他账号占用”的窗口
4. 卡死重启时只结束**该账号自己的进程**，不影响其他多开窗口

### 3. 截图 / 输入方式怎么选
不同游戏引擎兼容性不同，没有通用答案，按下表逐个试：

| 现象 | 调整 |
|---|---|
| 截图黑屏 | `screencap` 依次试 `FramePool`、`PrintWindow`、`GDI`、`Foreground`（前台方式要求窗口不被遮挡） |
| 点击没反应 | `mouse_input` 依次试 `PostMessage` → `SendMessage` → `PostMessageWithCursorPos` → `Seize`（前台，会占用鼠标） |
| 按键没反应 | `keyboard_input` 同上 |
| 全都没反应 | 游戏以管理员运行 → 用管理员终端运行本程序 |

后台方式（PostMessage 等）支持多开窗口同时操作；`Seize` 前台方式同一时间只能操作一个窗口，
多开时需把 `global.max_parallel` 设为 1。
`FramePool` / `PrintWindow` 支持窗口最小化后截图，其他方式最小化会失败。

### 4. 端游资源覆盖层（resource/pc）
端游 UI 与手游不同，在 `resource/pc/` 里只写差异部分：
- **图片**：端游截图按与 base 相同的路径放到 `resource/pc/image/`，自动覆盖
- **节点**：同名节点按字段合并，只写要改的字段。
  ⚠️ 已实测：如果改了 `recognition` / `action` 的**类型**（如 `Click` 改 `LongPress`），
  该类型的旧参数会被丢弃，必须把新类型的参数写全
- 自带示例：ESC 关闭面板、F1 出招、F1 吃药、右键按住移动，快捷键请按游戏实际设置修改
- 非 16:9 的窗口（如老游戏 1024x768）会被 MAA 缩放为 960x720，示例坐标不再适用，需要单独写端游坐标

### 5. 恢复机制
看门狗判定卡死或窗口闪退 → 结束该账号的客户端进程 → 按 `exe_path` 重新启动 → 等待窗口出现 →
重新绑定并连接 → 下一轮任务从 `通用_回到主界面` 开始处理登录。

> 未在真实 Windows 端游上测试过：窗口筛选、客户端管理、配置校验、覆盖层加载都有自动化测试，
> 但 Win32 截图/输入与具体游戏的兼容性需要你实际验证。

## 七、测试

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```
包含：配置校验、状态库、调度规则、队伍同步（并发）、看门狗、演练模式完整编排、Pipeline 静态检查，
以及基于真实 MaaFramework 的集成测试（合成截图 → 模板匹配 → 自定义识别/动作 → FarmLoop → 跨实例组队同步）。

## 八、注意事项汇总

### 风险
- 官服多开、组队挂机违反大多数游戏的用户协议，**有封号风险**；纯图像方案同样会被行为检测发现。
- 工作室批量搬砖、出售/分发脚本牟利，**可能触犯法律**（国内已有梦幻西游脚本案判例）。
- 本项目只做外部截图识别 + 模拟输入，不提供读内存、改封包、绕过反作弊等功能。

### 当前状态
- 模板图全是**占位图**（16x16 品红色），不替换就识别不到任何东西。`python main.py check` 会列出所有占位图。
- 示例 Pipeline 是按梦幻/问道/传奇的**通用界面逻辑**写的，OCR 文字、坐标、快捷键都要按实际游戏调整。
- **没有在真实模拟器 / 真实游戏上跑过**。已验证的是：真实 MAA 上的资源加载、模板匹配、自定义模块、FarmLoop、跨实例组队同步（用合成截图），以及演练模式下的全部调度逻辑。
- 端游的 Win32 截图/输入只能在 Windows 上验证，与具体游戏的兼容性需要实际测试。

### 环境
- 必须先运行 `python tools/download_ocr.py` 下载 OCR 模型，**缺模型时 MAA 加载资源会直接失败**。
- pip 版 MaaFramework 不带官方调试控制器（DbgController），离线调试使用本项目的 `core/image_controller.py`（`device.type: debug`）。
- 游戏以管理员运行时，本程序也必须以管理员运行，否则点击/按键会被系统拦截（端游最常见的“没反应”原因）。

### Pipeline 编写
- 所有坐标按 **1280x720** 写；端游窗口非 16:9 时（如 1024x768）会被缩放为 960x720，坐标要单独写。
- 资源叠加（如 base + pc）时同名节点**按字段合并**；但改了 `recognition` / `action` 的**类型**，旧参数会全部丢弃，新参数必须写全。
- 结束节点 `next` 为空才算成功；`next` 超时且 `on_error` 没接住就算失败，编排层会按 `max_retry` 重试。
- 长时间等待的流程（如队员跟随）要在循环里放一个会命中的“等待中”节点，否则超过 `stuck_sec` 会被看门狗判定卡死。

### 运行
- 组队任务一次性占用全队的并发名额，`max_parallel` 不能小于最大队伍人数。
- 端游使用 `Seize` 等**前台输入方式**时，同一时间只能操作一个窗口，需把 `max_parallel` 设为 1（程序不会自动限制）。
- 每个账号每天最多自动恢复 `max_recover` 次，超过后该账号当天不再自动重启。
- 端游卡死重启依赖 `exe_path`；不填则只能绑定已打开的窗口，无法自动恢复。
- 按进程名结束（`process_name`）会结束**所有同名进程**，多开时只在没有绑定记录时才会用到，慎用。
- YOLO：MAA 官方只声明支持 YOLOv8 / YOLO11 导出的 ONNX，训练脚本默认 `yolo11n`；更新的 YOLO26 需自行验证。
