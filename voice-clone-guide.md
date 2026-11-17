# 用自己的声音训练模型：GPT-SoVITS + RVC 实操手册

目标：
- **B 线**：用 GPT-SoVITS 训练 TTS 模型，输入文字直接生成你的口播。
- **C 线**：用 RVC（Applio）训练音色转换模型，把歌曲或人声换成你的音色。

两条线共用同一批录音，各训练一次。

> 说明：这两个项目更新很快，界面文字和安装参数可能与本文略有出入。出入时以仓库 README 为准：
> - GPT-SoVITS：https://github.com/RVC-Boss/GPT-SoVITS
> - Applio：https://github.com/IAHispano/Applio

---

## 0. 总流程

```
录音 → 本地整理(转格式/检查) → 租GPU并安装 → 上传数据
     → [B线] 切分→转写→校对→格式化→训练SoVITS→训练GPT→推理
     → [C线] 预处理→提特征→训练→生成index→推理
     → 下载模型到本地保存
```

预计耗时：录音 1–3 小时，安装 30 分钟，B 线训练 1–2 小时，C 线训练 0.5–1 小时。

---

## 1. 录音

### 1.1 设备与环境

- 麦克风：能用电容麦最好，没有就用手机，贴近嘴 10–20cm。
- 环境：安静、没有回声。衣柜里或被子围起来的小空间效果很好。
- 关闭空调、风扇，关掉手机通知声。
- 不要加混响、降噪、美颜音效等任何后期处理。

### 1.2 录多少、录什么

| 用途 | 内容 | 时长 |
|---|---|---|
| B 线（口播） | 自然朗读各类文本：新闻、故事、对话、问句、感叹句，长短句都要有 | 15–30 分钟 |
| C 线（歌声） | 清唱几首完整的歌，高低音都覆盖，不要有伴奏 | 10–20 分钟（只做口播转换可跳过） |

录音要求：
- 语速、情绪自然，像平时说话，不要刻意播音腔，除非你要的就是播音腔。
- 每句话中间停顿 1 秒左右，方便后面切分。
- 出错就停一下重读，后面切掉错误片段即可。
- 读错的字不要紧，但不要吞字、含糊。

### 1.3 导出格式

WAV，单声道，44.1kHz 或 48kHz，16bit 或 24bit。不要用 mp3。

---

## 2. 本地整理数据

把原始录音放在 `raw/`，用下面的脚本统一转格式和响度。

### 2.1 安装 ffmpeg

- macOS：`brew install ffmpeg`
- Ubuntu/Debian：`sudo apt update && sudo apt install -y ffmpeg`
- Windows：从 https://ffmpeg.org 下载，把 `bin` 目录加入 PATH

### 2.2 转换脚本

保存为 `prep.sh`：

```bash
#!/usr/bin/env bash
# 用法：bash prep.sh raw/ clean/
set -euo pipefail
in_dir="$1"; out_dir="$2"
mkdir -p "$out_dir"
for f in "$in_dir"/*; do
  name="$(basename "${f%.*}")"
  ffmpeg -y -i "$f" -ac 1 -ar 44100 -sample_fmt s16 \
    -af "loudnorm=I=-20:TP=-2:LRA=11" "$out_dir/$name.wav"
done
echo "done"
```

运行：

```bash
bash prep.sh raw/ clean/
```

### 2.3 检查

- 用 Audacity 之类的软件听一遍，确认没有爆音、咳嗽、手机提示音、背景音乐。
- 口播和歌声分别放在 `clean/speech/` 和 `clean/singing/`。
- 打包准备上传：`zip -r dataset.zip clean/`

---

## 3. 租 GPU 并安装（没有本地 N 卡时）

### 3.1 租机器（以 AutoDL 为例，其他平台类似）

1. 注册并充值几十元。
2. 租用实例：
   - GPU：RTX 3090 或 4090（显存 24GB），够用且便宜。
   - 镜像：选带 PyTorch 的基础镜像，Python 3.10，CUDA 12.x。
   - 数据盘：至少 50GB。
3. 开机后记下 SSH 地址、端口、密码。

### 3.2 连接并建立端口转发

云平台通常不直接开放 WebUI 端口，用 SSH 隧道最通用。在**本地终端**执行（把 HOST、PORT 换成实例信息）：

```bash
ssh -p PORT -L 9874:127.0.0.1:9874 -L 6969:127.0.0.1:6969 root@HOST
```

连上以后，本地浏览器访问：
- GPT-SoVITS：http://127.0.0.1:9874
- Applio：http://127.0.0.1:6969

> 如果你本地是 Windows + N 卡，不用租机器，直接用官方整合包。看各仓库 README 的 Windows 说明即可。

### 3.3 上传数据

在**本地终端**执行：

```bash
scp -P PORT dataset.zip root@HOST:/root/autodl-tmp/
```

在服务器上解压：

```bash
cd /root/autodl-tmp && unzip dataset.zip
```

（`/root/autodl-tmp` 是 AutoDL 的数据盘路径，其他平台换成对应的数据盘目录。）

### 3.4 安装 GPT-SoVITS

在服务器上执行：

```bash
cd /root/autodl-tmp
apt update && apt install -y git ffmpeg libsox-dev unzip

git clone https://github.com/RVC-Boss/GPT-SoVITS.git
cd GPT-SoVITS

# 创建环境
conda create -n GPTSoVits python=3.10 -y
conda activate GPTSoVits

# 安装依赖并下载预训练模型
# --device: CU126 / CU128 / CPU，按服务器 CUDA 版本选
# --source: HF（国外）/ HF-Mirror / ModelScope（国内推荐）
bash install.sh --device CU126 --source ModelScope --download-uvr5
```

启动 WebUI：

```bash
python webui.py zh_CN
```

看到 `Running on local URL: http://0.0.0.0:9874` 就说明成功了。

### 3.5 安装 Applio

另开一个 SSH 终端，执行：

```bash
cd /root/autodl-tmp
git clone https://github.com/IAHispano/Applio.git
cd Applio

# Linux 一键安装脚本，会自己创建环境并装依赖
chmod +x run-install.sh
./run-install.sh
```

启动：

```bash
chmod +x run-applio.sh
./run-applio.sh
```

浏览器打开 http://127.0.0.1:6969 即可（若端口不同，以终端输出为准）。

> 两个 WebUI 不要同时训练，显存会不够。一个训练完再开下一个。

---

## 4. B 线：GPT-SoVITS 训练口播模型

浏览器打开 http://127.0.0.1:9874。顶部标签页依次操作。

### 4.1 切分（0-前置数据集获取工具）

1. 如果录音里有背景噪音：用 **0a UVR5 人声分离**，选去混响、去噪模型。录音很干净就跳过。
2. **0b 语音切分**：
   - 输入路径：`/root/autodl-tmp/clean/speech`
   - 输出路径：`/root/autodl-tmp/output/slicer_opt`
   - 参数先用默认值，目标是切出 3–10 秒的片段。
   - 点开始切分。

### 4.2 自动转写（0c）

1. 输入路径填 `/root/autodl-tmp/output/slicer_opt`。
2. 中文选 **FunASR**；英文用 Faster Whisper。
3. 输出得到一个 `.list` 文件，默认在 `output/asr_opt/` 下。

### 4.3 校对文本（0d，重要）

1. 勾选「是否开启打标 WebUI」，打开校对页面。
2. 逐条听音频，修正文字：错字、漏字、标点、多音字。
3. 保存。文字错一个，生成时就可能发错音。
4. 删除噪音多、读错、太短的片段。

### 4.4 数据格式化（1A）

切到 **1-GPT-SoVITS-TTS** 标签：

1. 填 **实验/模型名**，比如 `myvoice`。
2. 文本标注文件：选上一步校对后的 `.list`。
3. 训练集音频文件目录：`/root/autodl-tmp/output/slicer_opt`。
4. 底模版本选最新的（下拉里最高的版本）。
5. 点 **一键三连**，等待完成，日志里无报错。

### 4.5 微调训练（1B）

先 SoVITS，后 GPT：

| 项 | 建议 |
|---|---|
| SoVITS batch size | 显存 24GB 可设 8–12，OOM 就调小 |
| SoVITS 总训练轮数 | 8–16 |
| 保存频率 | 4 |
| GPT batch size | 8 左右 |
| GPT 总训练轮数 | 10–15 |
| 保存频率 | 5 |

1. 点 **开启 SoVITS 训练**，等完成。
2. 再点 **开启 GPT 训练**，等完成。
3. 数据少（不到 10 分钟）就用较低轮数，避免过拟合。

> 如果提示显存不足（OOM），把 batch size 调小一半。

### 4.6 推理（1C）

1. 勾选 **开启 TTS 推理 WebUI**，会弹出新页面（端口通常 9872，需要再加一个 SSH 端口转发：`-L 9872:127.0.0.1:9872`）。
2. 选择你训练的 **GPT 模型** 和 **SoVITS 模型**（选最后几个 epoch 的权重，也可以多试几个对比）。
3. 上传 **参考音频**（5–10 秒，你自己的、语气清晰的片段），并填入对应的**参考文本**。
4. 在下方输入要合成的文字，点合成。
5. 参考音频的语气会影响输出：想要平静就选平静的片段，想要有感情就选有感情的片段。

调参提示：
- 声音发抖、断句怪：换参考音频，或调低 `top_k`、`temperature`。
- 语速不对：调语速参数。
- 个别字发音错：先在训练文本里确认，再用拼音标注或换说法。

---

## 5. C 线：RVC（Applio）训练音色转换模型

浏览器打开 http://127.0.0.1:6969。

### 5.1 训练

1. 进入 **Train** 标签。
2. 填写：
   - **Model Name**：`myvoice_rvc`
   - **Sampling rate**：40k 或 48k（歌声用 48k 更细致）
3. **Preprocess Dataset**：
   - Dataset path：`/root/autodl-tmp/clean/singing`（只做口播转换用 `speech`，两者都要就把两个目录的 wav 放到同一目录）
   - 点 Preprocess。
4. **Extract Features**：
   - F0 方法选 **rmvpe**。
   - 点 Extract。
5. **Training**：
   - Total Epoch：200–400（数据越多可越少）
   - Save Every Epoch：50
   - Batch Size：显存 24GB 可设 8–16
   - 勾选 Save Only Latest 可以省磁盘，但想对比不同 epoch 就不勾
   - Pretrained：使用默认底模
6. 点 **Start Training**，等待完成。
7. 点 **Generate Index** 生成索引文件，能提升音色相似度。

> 训练过程中不要一味追求 epoch 越多越好，过多会过拟合，出现电音和吞字。保存几个中间版本，到推理阶段对比挑选。

### 5.2 推理（转换人声）

1. 进入 **Inference** 标签。
2. 选你的模型文件（`.pth`）和 index 文件。
3. 上传要转换的音频（必须是**干净的人声**，不能带伴奏）。
4. 参数：
   - **Pitch**：原唱和你同性别用 0；男声转女声一般 +12，女转男 -12。
   - **Index Rate**：0.3–0.7，越大越像你但越容易有杂音。
   - **Protect**：0.33 左右，保护清辅音，减少撕裂感。
   - F0 方法选 **rmvpe**。
5. 点转换，试听并微调参数。

### 5.3 歌曲完整流程

```
原曲 → UVR5 分离人声/伴奏 → （可选）去混响/去和声
     → RVC 转换人声 → 与伴奏混音 → 导出
```

- UVR5 在 GPT-SoVITS 的 0a 里就有，也可以用 Applio 自带的分离插件。
- 混音用 Audacity、Reaper 或任何 DAW，把转换后的人声和原伴奏叠在一起，音量适当调整。

### 5.4 B + C 组合（想让 TTS 声音风格更稳）

先用 GPT-SoVITS 生成口播，再用 RVC 过一遍，可以把音色再贴近一点。通常 GPT-SoVITS 已经够像，这一步按需使用。

---

## 6. 保存与下载模型

**训练完务必把模型下载回本地，云机器关机后数据可能被清除。**

需要保存的文件：

| 项目 | 路径 |
|---|---|
| GPT-SoVITS 的 SoVITS 权重 | `GPT-SoVITS/SoVITS_weights*/myvoice_*.pth` |
| GPT-SoVITS 的 GPT 权重 | `GPT-SoVITS/GPT_weights*/myvoice-*.ckpt` |
| 参考音频与参考文本 | 你自己选的那几段 |
| RVC 模型 | `Applio/logs/myvoice_rvc/` 下的 `.pth` 和 `.index` |

下载命令（本地终端）：

```bash
scp -P PORT -r root@HOST:/root/autodl-tmp/GPT-SoVITS/SoVITS_weights_v2Pro ./models/
scp -P PORT -r root@HOST:/root/autodl-tmp/GPT-SoVITS/GPT_weights_v2Pro ./models/
scp -P PORT -r root@HOST:/root/autodl-tmp/Applio/logs/myvoice_rvc ./models/
```

（目录名里的版本后缀以实际生成的为准，用 `ls` 查看。）

之后再次使用时，重新租机器，装好项目，把这些文件放回对应目录即可推理，不用重新训练。

---

## 7. 常见问题

| 现象 | 处理 |
|---|---|
| 显存不足（CUDA OOM） | batch size 减半；关掉另一个 WebUI |
| 浏览器打不开 WebUI | 检查 SSH 隧道是否还连着、端口是否一致 |
| 生成的声音不像 | 数据太少或不干净；换更好的参考音频；多录一些 |
| 生成有杂音/电音 | 过拟合，换更早的 epoch；降低 Index Rate |
| 发音错、漏字 | 校对训练文本；缩短单句长度 |
| 语气平淡 | 参考音频选有情绪的；训练数据里加入有情绪的朗读 |
| 歌声破音 | 检查音高设置；原唱音域超出你的训练音域，调 Pitch |
| 安装报错 | 先看报错信息，对照仓库 Issues；确认 Python 3.10、CUDA 版本匹配 |
| 下载模型很慢 | 换 `--source ModelScope` 或 `HF-Mirror` |

---

## 8. 使用须知

- 只用你自己的声音训练，或已经获得本人同意的声音。
- 用模型生成的内容不要用于冒充他人、诈骗或误导。
- 发布 AI 生成的音频时，建议标注是 AI 合成。

---

## 9. 清单（做完打勾）

- [ ] 录好 15–30 分钟口播（+ 可选 10–20 分钟清唱）
- [ ] 用 `prep.sh` 转成 44.1kHz 单声道 WAV
- [ ] 租好 GPU，SSH 隧道可用
- [ ] 上传数据
- [ ] 安装 GPT-SoVITS 并成功打开 WebUI
- [ ] 切分 → 转写 → 校对 → 一键三连
- [ ] 训练 SoVITS 和 GPT
- [ ] 推理测试，选出最佳权重
- [ ] 安装 Applio，预处理 → 提特征 → 训练 → 生成 index
- [ ] 推理测试，调好参数
- [ ] 下载所有模型到本地备份
