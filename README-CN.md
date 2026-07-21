# Whisper_auto2lrc

[![made-with-python](https://img.shields.io/badge/Made%20with-Python-1f425f.svg)](https://www.python.org/)
<img alt="GitHub Top Language" src="https://img.shields.io/github/languages/top/bai0012/Whisper_auto2lrc" />
<img alt="GitHub Last Commit" src="https://img.shields.io/github/last-commit/bai0012/Whisper_auto2lrc" />
<img alt="GitHub Commit Activity (Year)" src="https://img.shields.io/github/commit-activity/y/bai0012/Whisper_auto2lrc" />

使用 OpenAI Whisper 或 Faster Whisper 将文件夹（及子文件夹）中的媒体文件转换为一种或多种字幕/转录格式：LRC、SRT、VTT、TXT、TSV 和 JSON。已有输出文件不会被覆盖。

程序提供 PyQt6 桌面界面，并支持两个可切换的转录后端：

- **OpenAI Whisper** 使用 PyTorch 和系统中的 FFmpeg 可执行文件。
- **Faster Whisper** 使用 CTranslate2 和 PyAV，推理速度更快且内存效率更高。

## 这个程序能干什么？

它使用 OpenAI 发布的 Whisper 语音转文字模型。用户指定媒体文件夹后，程序会递归搜索支持的文件，并通过一次转录生成所有选中的输出格式。

适合有大量音频文件需要转录为字幕的用户。


## 程序截图
![](https://raw.githubusercontent.com/bai0012/Whisper_auto2lrc/main/demo.png)


## 如何安装

首先安装python，已经在python3.11上测试

`requirements.txt` 会同时安装两个支持的转录后端。

## 如何使用

### 使用源代码程序

拉取该repo，并且安装Python依赖项：

```git
git clone https://github.com/bai0012/Whisper_auto2lrc
```


```Powershell
cd Whisper_auto2lrc
```

```python
pip install -r requirements.txt 
```

使用 OpenAI Whisper 后端时，需要下载 FFmpeg，并将包含 ffmpeg.exe 的文件夹添加到系统变量中，如 [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds/releases)。Faster Whisper 通过 PyAV 解码媒体，不要求系统安装 FFmpeg。

使终端处于项目文件夹的基础上，运行

```Powershell
python main.py
```

在窗口中选择后端、模型、文件夹路径、转录语言以及一种或多种输出格式，点击开始即可。默认使用 OpenAI Whisper 的 `base` 模型。切换后端会刷新模型列表：两个后端都提供标准 Whisper 模型，Faster Whisper 还支持经过优化、仅限英语的 Distil-Whisper 模型。默认只选择 LRC。转录语言默认为 `auto`，由 Whisper 自动检测；留空也等同于 `auto`。

为避免处理时临时下载模型，可勾选“**使用本地模型**”。OpenAI Whisper 需选择已下载的权重文件（通常为 `.pt`）；Faster Whisper 需选择完整的本地 **CTranslate2 模型目录**，不能选 PyTorch 权重文件或 Hugging Face 缓存的上层目录。Faster Whisper 使用本地目录时会显式禁止下载。两个后端的启用状态和路径会分别记忆，本地模型路径也会纳入内存模型缓存键。

可选格式包括 LRC、SRT、VTT、TXT、TSV 和 JSON。每个媒体文件只会转录一次，所有选中格式均复用该结果；已有的选中格式会保留，只补充缺失格式。如果同一路径下多个媒体文件具有相同基础名称（例如 `song.mp3` 和 `song.wav`），程序会跳过整个冲突组并在日志中报告。

窗口顶部可随时在 English 和简体中文之间切换界面显示语言。程序会在下次启动时恢复界面设置，并缓存最近一次成功加载的“后端 + 模型 + 运行配置”组合；重复使用相同组合时无需重新加载，修改其中任一设置时旧模型会被替换。

Faster Whisper 提供 `Auto`、`CPU` 和 `CUDA` 三种设备选项。`Auto` 会在 CTranslate2 检测到可用 CUDA 设备时使用 CUDA + FP16，否则使用 CPU + INT8；如果自动初始化 CUDA 失败，程序会重试 CPU + INT8，并在日志中报告回退。选择 `CPU` 可强制使用兼容性较好的路径，选择 `CUDA` 则要求使用 GPU。

### REST 批处理 API

安装 API 依赖并启动本地服务：

```bash
pip install -r requirements-api.txt
python api.py
```

默认监听 `http://127.0.0.1:8000`；可使用 `--host` 和 `--port` 修改。提交递归处理文件夹的任务，然后轮询状态：

```bash
curl -X POST http://127.0.0.1:8000/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"folder_path":"/data/audio","backend":"faster-whisper","model":"base","language":"auto","formats":["lrc","srt"],"faster_device":"auto","faster_compute_type":"auto"}'

curl http://127.0.0.1:8000/v1/jobs/JOB_ID
curl -X POST http://127.0.0.1:8000/v1/jobs/JOB_ID/cancel
```

使用本地模型时，OpenAI Whisper 可增加 `"local_model_path":"/models/model.pt"`，Faster Whisper 则填写 CTranslate2 模型目录。`GET /v1/capabilities` 会列出有效的后端、模型、格式、语言、设备和精度。其他端点包括 `GET /health`、`GET /v1/jobs`、`GET /v1/jobs/{id}`；交互式 OpenAPI 文档位于 `/docs`。

任务进入最多容纳 100 个等待任务的单一内存队列，并始终串行执行，避免多个任务同时占用显存。内存中最多保留最近 1,000 条任务记录；`GET /v1/jobs` 支持 `limit`（最大 200）和 `offset`。进程重启后任务及历史记录会丢失。取消采用协作式机制，因此运行中任务可能保持 `cancelling`，直至当前模型加载或媒体转录调用返回。关闭服务时会取消排队任务，并等待活动 Worker 安全结束。

**安全警告：**API 没有身份验证，而且接受本地文件系统路径。请保留默认的本机回环监听地址。除非已部署带身份验证和访问控制的反向代理，并做好文件系统隔离，否则不要将它暴露到局域网或公网。

### 运行单元测试

测试不需要下载 Whisper 模型，也不需要真实音频文件：

```Powershell
pip install -r requirements-dev.txt
python -m ruff check main.py api.py tests
python -m pytest -s tests
```

### Windows 发布包

GitHub Release 提供 `Whisper_auto2lrc-windows-x64.zip`。它是 PyInstaller 的 **onedir** 构建：请完整解压，保持目录内所有文件的位置不变，然后运行解压目录中的 `Whisper_auto2lrc.exe`。采用目录形式可以避免单文件程序启动时的临时解压开销。


## 疑难解答

### 为什么后端只调用了 CPU？

OpenAI Whisper 使用 PyTorch。若它没有识别到 CUDA，请根据 [PyTorch 官网](https://pytorch.org/get-started/locally/)安装与你的显卡驱动匹配的 CUDA 版本。

```python 
pip uninstall torch
```

```python 
pip cache purge
```
然后安装适合当前系统的 PyTorch，例如：

如：
```python
pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
```

Faster Whisper 使用 CTranslate2；当前版本的 NVIDIA GPU 后端要求 CUDA 12 的 cuBLAS 和 cuDNN 9，详见 [Faster Whisper GPU 说明](https://github.com/SYSTRAN/faster-whisper#gpu)。无法完成 CUDA 探测时，程序会自动回退到 CPU + INT8。

### 为什么使用时 FFmpeg 报错？

只有 OpenAI Whisper 后端需要系统中的 FFmpeg 可执行文件。请在新的终端中运行 `ffmpeg -version`，确认 FFmpeg 已安装且可通过 `PATH` 找到；若命令不存在，请安装 FFmpeg、将其 `bin` 目录加入 `PATH`，然后重启程序。名为 `ffmpeg-python` 的 Python 包并不是 FFmpeg 可执行文件，本项目不需要它，也不能用它代替 FFmpeg 安装。

### 我应该选择什么模型，各个模型有什么区别？

参见[openai/whisper](https://github.com/openai/whisper#available-models-and-languages)
|  Size  | Parameters | English-only model | Multilingual model | Required VRAM | Relative speed |
|:------:|:----------:|:------------------:|:------------------:|:-------------:|:--------------:|
|  tiny  |    39 M    |     `tiny.en`      |       `tiny`       |     ~1 GB     |      ~10x      |
|  base  |    74 M    |     `base.en`      |       `base`       |     ~1 GB     |      ~7x       |
| small  |   244 M    |     `small.en`     |      `small`       |     ~2 GB     |      ~4x       |
| medium |   769 M    |    `medium.en`     |      `medium`      |     ~5 GB     |      ~2x       |
| large  |   1550 M   |        N/A         |      `large`       |    ~10 GB     |       1x       |
| turbo  |   809 M    |        N/A         |      `turbo`       |     ~6 GB     |      ~8x       |

请根据可用显存、期望精度和处理速度选择模型。通常模型越大越准确，但速度越慢、占用的内存或显存也越多；`turbo` 是兼顾速度与精度的优先选择。Faster Whisper 还可选择 Distil-Whisper 模型，并通过 INT8 降低内存占用。


### 在语言输入框中，我应该输入什么？

whsiper支持多种语言的语音转文字，常用的有：
|  语言  | 代码 |
|:-----:|:---:|
|  汉语  | zh |
|  英语  | en |
|  俄语  | ru |
|  日语  | ja |
|  韩语  | ko |
|  德语  | de |
|  意大利语  | it |

更多语言，请参考：[whisper/tokenizer.py](https://github.com/openai/whisper/blob/main/whisper/tokenizer.py)

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=bai0012/Whisper_auto2lrc&type=Date)](https://star-history.com/#bai0012/Whisper_auto2lrc&Date)


本程序在GPT 4指导下完成，特别感谢[chshkhr](https://github.com/chshkhr)的贡献。
