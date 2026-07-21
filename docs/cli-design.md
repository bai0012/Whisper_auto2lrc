# CLI 接口设计

- 状态：提案
- 目标版本：下一个功能版本
- 适用 Python：3.14+
- 入口文件：计划新增 `cli.py`
- 核心依赖：`core.TranscriptionRunner`

## 1. 背景与目标

项目已经有 PyQt6 桌面界面和 REST 批处理 API，两者共享无 Qt 的 `core.py`。CLI 应成为第三个薄适配层：负责解析参数、校验用户输入、把核心回调呈现为终端输出，以及将核心完成状态映射为进程退出码；扫描、模型加载、转录、输出写入、冲突处理和模型缓存仍由核心层负责。

首版 CLI 的目标是：

1. 在服务器、容器、计划任务和 shell 脚本中直接执行一次文件夹批处理。
2. 与桌面端和 API 使用相同的后端、模型、语言、格式、遍历和“不覆盖已有文件”规则。
3. 同时提供适合人阅读的文本输出和适合程序消费的稳定 JSON Lines 输出。
4. 使用明确且可测试的退出码表达完整成功、部分失败、参数错误、运行失败和取消。
5. 不导入 PyQt6，也不通过 `main.Worker` 或 API 的队列间接调用核心。

## 2. 首版范围

### 2.1 包含

- 递归处理一个本地文件夹。
- `openai-whisper` 和 `faster-whisper` 两种后端。
- 内置模型和本地模型。
- 自动语言检测或显式 Whisper 语言代码。
- LRC、SRT、VTT、TXT、TSV、JSON，可一次选择多种格式。
- Faster Whisper 的设备和计算精度选择。
- 英文和简体中文消息。
- 文本、静默和 JSON Lines 三种输出模式。
- `SIGINT`/`SIGTERM` 协作式取消。
- 查询当前程序支持的后端、模型和格式。

### 2.2 不包含

- 单个文件、标准输入、URL 或对象存储输入。
- 覆盖已有输出、指定独立输出目录或修改输出文件名模板。
- 多个模型或任务的并行执行。
- REST 服务管理、后台守护进程或持久任务队列。
- 全局/项目配置文件和自定义环境变量。
- 下载管理、下载进度、模型转换或模型仓库搜索。
- 音频切片、说话人分离、翻译和字幕后处理。

这些能力以后可以通过新增参数或子命令设计，不应让首版 CLI 复制或绕过核心逻辑。

## 3. 命令结构

开发仓库中的规范调用方式为：

```bash
python cli.py <command> [options]
```

如果以后增加 Python 包元数据，可额外注册 `whisper-auto2lrc` console script；它必须调用同一个 `main(argv=None) -> int`，不能形成第二套解析逻辑。

首版提供两个子命令：

```text
python cli.py transcribe FOLDER [options]
python cli.py capabilities [--json]
```

顶层还提供：

```text
python cli.py --help
python cli.py --version
```

必须显式填写子命令。不要把省略子命令隐式解释为 `transcribe`，这样以后增加命令时不会产生位置参数歧义。

## 4. `transcribe` 参数契约

### 4.1 基本参数

| 参数 | 类型与默认值 | 规则 |
| --- | --- | --- |
| `FOLDER` | 必填路径 | 展开 `~` 并解析为绝对路径；必须是已有目录。核心会递归扫描支持的媒体文件。 |
| `--backend` | `openai-whisper`，默认；或 `faster-whisper` | 决定模型列表、本地模型类型和运行参数。 |
| `--model` | 模型名 | 未指定 `--local-model` 时使用；默认取 `core.BACKEND_DEFAULT_MODELS[backend]`，而不是在解析器中重复写死。 |
| `--local-model PATH` | 路径，默认无 | 与显式 `--model` 互斥。OpenAI Whisper 要求 checkpoint 文件；Faster Whisper 要求 CTranslate2 模型目录。 |
| `--language`, `-l` | `auto`，或 Whisper 语言代码 | 空字符串不作为 CLI 值；`auto` 转换为核心使用的自动检测。英文专用内置模型只接受 `en`。 |
| `--format`, `-f` | 可重复 choice，未提供时为 `lrc` | 每次提供一个格式，例如 `-f lrc -f srt`；一旦显式提供就替换默认值，保持用户顺序去重，至少选择一种。实现时使用 `None` 作为 parser 默认值，再在解析后补 `lrc`，避免 `action="append"` 把显式格式追加到默认 LRC。 |
| `--locale` | `auto`、`en`、`zh_CN`；默认 `auto` | `auto` 根据系统 locale 选择简体中文或英文；无法识别时回退英文。只影响 CLI 消息，不影响转录语言。 |

建议帮助信息：

```text
usage: cli.py transcribe FOLDER [--backend BACKEND]
                         [--model MODEL | --local-model PATH]
                         [-l LANGUAGE] [-f FORMAT]
                         [--device DEVICE] [--compute-type TYPE]
                         [--output-mode {text,quiet,json}]
```

### 4.2 Faster Whisper 参数

| 参数 | 默认值 | 允许值与行为 |
| --- | --- | --- |
| `--device` | `auto` | `auto`、`cpu`、`cuda`，映射到核心的 `faster_device_mode`。 |
| `--compute-type` | `auto` | `auto`，或所选设备在 `core.FASTER_COMPUTE_TYPES` 中允许的值。 |

当后端为 `openai-whisper` 时，如果用户显式设置了非默认的 `--device` 或 `--compute-type`，CLI 应报参数错误并以状态码 2 退出，不应静默忽略。默认值可以继续传给核心，保持构造接口简单。

运行组合继续遵守核心规则：

- `auto/auto`：检测到 CUDA 时使用 CUDA + FP16，否则使用 CPU + INT8。
- 自动 CUDA 模型加载失败时，核心只重试一次 CPU + INT8。
- 强制 `cuda` 时不自动退回 CPU。
- 本地 Faster Whisper 模型以 `local_files_only=True` 加载。

### 4.3 输出模式

| 参数 | 默认值 | 行为 |
| --- | --- | --- |
| `--output-mode` | `text` | `text`、`quiet` 或 `json`。三种模式互斥。 |
| `--no-color` | false | 禁用 ANSI 颜色。设置 `NO_COLOR` 环境变量时效果相同。 |

不再增加独立的 `--quiet` 和 `--json` 布尔参数，以免产生 `--quiet --json` 的冲突组合。

## 5. 参数解析与校验顺序

CLI 应使用标准库 `argparse`，不为首版增加 Typer/Click 等运行依赖。推荐按以下顺序处理：

1. 解析语法、choice 和互斥参数；此阶段错误由 `argparse` 输出并返回 2。
2. 解析并验证文件夹。
3. 根据 `--backend` 动态确定默认模型。
4. 验证内置模型是否属于 `core.BACKEND_MODELS[backend]`，或调用 `core.validate_local_model()` 验证本地模型。
5. 调用 `core.validate_language()` 验证语言和英文专用模型组合。
6. 根据 `core.FASTER_COMPUTE_TYPES` 验证设备与精度组合。
7. 检查运行依赖。OpenAI Whisper 需要可导入 `whisper` 且系统 `PATH` 中存在 FFmpeg；Faster Whisper 需要可导入 `faster_whisper`。这部分检查应提取为无 Qt 的核心辅助函数，供桌面端、CLI 和 API 复用，避免 CLI 反向导入 `main.py`。
8. 所有前置校验通过后才构造 `TranscriptionRunner`，避免无效请求触发模型加载。

首版不读取自动发现的配置文件，也不定义 `WHISPER_AUTO2LRC_*` 环境变量。因此有效值只来自命令行参数和内置默认值。已有后端依赖使用的标准环境变量（例如 Hugging Face 缓存和 CUDA 变量）保持原行为，但不属于本 CLI 的配置契约。

## 6. 核心层集成

CLI 入口建议保持以下边界：

```python
def build_parser() -> argparse.ArgumentParser: ...

def main(argv: list[str] | None = None) -> int: ...

def run_transcribe(args: argparse.Namespace) -> int: ...

def run_capabilities(args: argparse.Namespace) -> int: ...
```

`run_transcribe()` 只负责将已校验参数映射到核心：

```python
runner = core.TranscriptionRunner(
    folder_path=folder,
    model_name=resolved_model,
    language=args.language,
    output_formats=args.formats,
    backend_name=args.backend,
    faster_device_mode=args.device,
    faster_compute_type=args.compute_type,
    is_local_model=args.local_model is not None,
    progress_callback=reporter.progress,
    error_callback=reporter.error,
    message_formatter=core.core_message_formatter(locale_name),
)
status = runner.run()
return EXIT_CODES[status]
```

约束：

- `cli.py` 可以导入 `core`，不能导入 `main`、PyQt6、`api`、FastAPI 或 Uvicorn。
- CLI 不创建额外工作线程；一次进程同步执行一次 `runner.run()`。
- 不自行扫描媒体文件，不自行加载模型，不自行生成或写入字幕。
- 不解析核心消息文本来判断结果，只读取 `completion_status`。
- 如果后续把参数模型提取成核心 dataclass，桌面端、API 和 CLI 应共同使用该模型；在此之前 CLI 必须直接调用现有核心校验函数。

## 7. 文本输出协议

程序生成的是文件，因此 stdout 不承载字幕正文。不同模式的流约定如下：

### 7.1 `text`

- 进度和普通状态写入 stderr，防止污染脚本可能使用的 stdout。
- 错误以 `ERROR:`（中文 locale 为 `错误：`）开头并写入 stderr。
- 交互终端可以使用 `\r` 原地刷新进度；非交互终端每次进度变化输出一行。
- 同一进度值下的模型加载、缓存命中和回退消息仍应显示，不能只按百分比去重。
- 结束时输出一行摘要，包括状态、最终进度和错误数量。
- 默认使用颜色的前提是 stderr 为 TTY、未传 `--no-color` 且未设置 `NO_COLOR`；脚本不能依赖颜色码。

示例：

```text
[  0%] Loading Faster Whisper model: base...
[  0%] Found 3 files to process...
[ 33%] Processing: 01.mp3 (1/3)
[ 66%] Processing: 02.mp3 (2/3)
[100%] Processing: 03.mp3 (3/3)
Completed: progress=100 errors=0
```

### 7.2 `quiet`

- 不显示普通进度。
- 错误和最终摘要仍写入 stderr。
- 退出码仍是首要的机器判断依据。

### 7.3 `json`

- 每个事件是一行 UTF-8 JSON，写入 stdout；禁止输出 ANSI、进度条或额外说明文字。
- stderr 只保留 `argparse` 在无法识别 JSON 模式前产生的语法错误，以及无法序列化事件的进程级故障。
- 字段可以在后续版本中新增；现有字段的含义和类型不能静默改变。
- 所有事件都包含 `type`，进度和错误事件包含当时的单调 `progress`。
- 正常进入执行阶段后，无论成功、部分失败、运行失败或取消，最后一行必须是 `result`。
- parser 已识别 `--output-mode json` 后发生的路径或选项语义校验错误，应输出 `error` 和状态为 `invalid_arguments` 的最终 `result`，然后返回 2；不能退回普通文本错误。
- 唯一允许缺少最终 `result` 的情况是用户发送第二次取消信号强制终止；消费者必须同时检查进程退出码和 JSON Lines 是否完整。

事件结构：

```json
{"type":"progress","progress":33,"message":"Processing: 01.mp3 (1/3)"}
{"type":"error","progress":66,"message":"Error processing 02.mp3: ..."}
{"type":"result","status":"completed_with_errors","progress":100,"error_count":1}
```

JSON 序列化使用 `ensure_ascii=False`，一条事件严格占一行。`message` 是展示文本，不是稳定错误代码；自动化应依赖 `type`、`status`、`progress`、`error_count` 和进程退出码。未来若需要结构化错误代码，应新增字段而不是解析 `message`。

`error_count` 由 CLI reporter 对 `error_callback` 调用计数，不要求核心暴露或复制错误列表。

JSON 模式必须绕过 Windows 文本流的本地代码页，直接向 `sys.stdout.buffer` 写入 `json.dumps(..., ensure_ascii=False)` 编码后的 UTF-8 bytes，并在每个事件后写入 `b"\n"` 和 flush。不能只依赖 `PYTHONUTF8`、终端代码页或 `TextIOWrapper` 的默认 encoding。

## 8. 完成状态与退出码

| 核心/CLI 状态 | 退出码 | 含义 |
| --- | ---: | --- |
| `completed` | 0 | 全部处理成功，或没有需要生成的新输出。 |
| `completed_with_errors` | 1 | 部分文件、冲突组或输出格式失败，其余工作已完成。 |
| 参数、路径或选项校验失败 | 2 | 调用方式错误；与 `argparse` 默认退出码一致。 |
| `failed` | 3 | 模型加载、依赖或核心初始化等导致任务无法完成。 |
| `cancelled`（SIGINT） | 130 | 收到 Ctrl+C；遵循 shell 的常见约定。 |
| `cancelled`（SIGTERM） | 143 | 收到 SIGTERM，即 `128 + 15`；Windows 不承诺支持。 |
| 未捕获的 CLI 适配层异常 | 70 | 内部软件错误，对应 `EX_SOFTWARE` 的常用值。 |

CLI 的 `main()` 返回整数，由文件末尾执行 `raise SystemExit(main())`。测试直接调用 `main([...])` 时不应被强制终止解释器。

`completed_with_errors` 必须是非零退出码，避免 CI 把丢失输出、同名媒体冲突或空转录误判为完整成功。

## 9. 取消和信号

CLI 在开始执行前注册 `SIGINT` 和平台可用时的 `SIGTERM`：

1. CLI 自己持有一个 `threading.Event` 和不可变的首次信号原因。第一次信号先记录 `SIGINT` 或 `SIGTERM` 并设置事件；如果 runner 已构造，再调用 `runner.stop()`，等待核心到达协作式取消点。
2. 扫描阶段会在遍历项之间检查停止事件；文件批处理会在文件之间检查。
3. 当前模型加载或单个媒体转录不能被核心抢占，因此第一次信号后可能需要等待当前调用返回。
4. runner 返回后，只要存在首次信号原因，CLI 就必须把最终状态覆盖为 `cancelled`，即使模型加载或转录同时返回了 `failed`；仍可在取消结果前输出已收到的错误事件。SIGINT 返回 130，SIGTERM 返回 143。
5. 第二次取消信号表示强制终止：第二次 SIGINT 立即抛出 `KeyboardInterrupt` 并返回 130，第二次 SIGTERM 立即返回 143。此路径明确豁免 JSON 最终 `result` 保证。原子/独占输出写入保证未完成的临时文件不会替代目标文件。
6. 如果信号发生在 runner 构造前，CLI 应在前置校验的下一个检查点直接生成取消结果；如果 runner 已经开始构造，则构造完成后立刻调用 `stop()`，不能遗漏取消。
7. 信号处理器只记录信号、设置停止状态并调用 runner 的轻量 `stop()`；不直接写输出文件、清理模型或执行复杂业务逻辑。

Windows 不保证提供与 POSIX 完全相同的 `SIGTERM` 行为；Ctrl+C 的退出契约必须保持一致。

## 10. 遍历与输出行为

CLI 不增加自己的遍历开关，完全继承核心行为：

- 递归查找 `core.AUDIO_EXTENSIONS` 中的媒体扩展名。
- 使用稳定的、不区分大小写优先的路径排序。
- 每个媒体文件只转录一次，再生成全部缺失的所选格式。
- 已存在的目标文件不覆盖。
- 扫描后才加载模型；没有任务时不应下载或加载模型。
- 同目录同 stem 的多个媒体文件映射到相同输出时，整个冲突组跳过并报告。
- 空时间戳结果、单文件转录异常和单格式写入异常都计为错误；遍历继续，并最终返回 `completed_with_errors`。
- 每个访问过的任务只推进一次完成百分比；进度不能倒退，完整或部分失败批次最终为 100。

## 11. `capabilities` 子命令

`capabilities` 不导入或加载模型，只展示静态能力：

```text
Backends:
  openai-whisper (default model: base)
  faster-whisper (default model: base)
Formats: lrc, srt, vtt, txt, tsv, json
Devices: auto, cpu, cuda
```

`python cli.py capabilities --json` 输出单个 JSON 对象。实现时应在核心层新增一个共享能力对象生成函数；CLI 原样输出该对象，REST API 在同一对象上只追加 API 专有的 `queue_mode`。这会给现有 API 的 backend 项增加 `default_model`，属于向后兼容的字段扩展：

```json
{
  "backends": {
    "openai-whisper": {"models": ["tiny", "base"], "default_model": "base", "local_model": "file"},
    "faster-whisper": {"models": ["tiny", "base"], "default_model": "base", "local_model": "directory"}
  },
  "formats": ["lrc", "srt", "vtt", "txt", "tsv", "json"],
  "languages": ["auto", "af", "...", "zh"],
  "faster_whisper": {
    "devices": ["auto", "cpu", "cuda"],
    "compute_types": {"auto": ["auto"], "cpu": ["int8", "float32"], "cuda": ["float16", "int8_float16", "int8"]}
  }
}
```

示例中的模型列表为缩写；真实输出必须直接读取核心常量，不能在 CLI 中维护副本。共享能力函数由 REST API 和 CLI 共同序列化，防止两个入口的 schema 漂移。

## 12. 调用示例

OpenAI Whisper、自动语言、默认 LRC：

```bash
python cli.py transcribe ./audio
```

Faster Whisper，同时生成 LRC、SRT 和 VTT：

```bash
python cli.py transcribe ./audio \
  --backend faster-whisper \
  --model large-v3-turbo \
  --language auto \
  --device auto \
  -f lrc -f srt -f vtt
```

OpenAI Whisper 本地 checkpoint：

```bash
python cli.py transcribe ./audio \
  --backend openai-whisper \
  --local-model ./models/medium.pt \
  --language zh \
  -f lrc -f txt
```

Faster Whisper 本地 CTranslate2 模型，强制 CPU：

```bash
python cli.py transcribe ./audio \
  --backend faster-whisper \
  --local-model ./models/faster-large-v3 \
  --device cpu \
  --compute-type int8 \
  -f srt
```

脚本消费 JSON Lines，并保留正确退出码：

```bash
python cli.py transcribe ./audio --output-mode json -f lrc -f srt \
  | tee transcription-events.jsonl
status=${PIPESTATUS[0]}
exit "$status"
```

PowerShell：

```powershell
python cli.py transcribe C:\Audio `
  --backend faster-whisper `
  --model base `
  --output-mode json `
  -f lrc -f srt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

## 13. 依赖与分发

- CLI 使用两个 Whisper 后端，因此源码安装可复用 `requirements-core.txt`，不需要 PyQt6、FastAPI 或 Uvicorn。
- 建议增加 `requirements-cli.txt`，首版内容只引用 `requirements-core.txt`；即使暂时没有额外依赖，也能明确安装意图。
- PyInstaller 桌面包是否包含 CLI 不属于首版设计。若以后发布独立 CLI，可增加 console 模式构建，不能复用 `--windowed` 的桌面可执行文件。
- `--version` 的值应来自单一版本源。实现前应新增轻量版本模块或包元数据，GitHub Actions 输入版本必须与该版本源校验一致，避免 CLI、tag 和 Release 显示不同版本。

## 14. 测试计划

计划新增 `tests/test_cli.py`，测试不得下载模型或读取真实音频。

### 14.1 解析和校验

- 无子命令、缺少文件夹、未知参数和未知 choice 返回 2。
- 后端动态默认模型正确。
- `--model` 与 `--local-model` 互斥。
- 多个 `-f` 保持顺序并去重；无格式无法进入核心；只传 `-f srt` 时结果不包含默认的 `lrc`。
- 非目录路径、本地模型类型、语言代码、英文专用模型和设备/精度组合校验。
- OpenAI 后端拒绝显式的 Faster 专用参数。

### 14.2 核心映射

- monkeypatch `core.TranscriptionRunner`，断言所有构造参数映射正确。
- CLI 模块导入后 `sys.modules` 中没有 PyQt6、FastAPI 和 Uvicorn。
- runner 只调用一次，CLI 不执行自己的目录遍历或输出写入。

### 14.3 输出协议

- text 模式 stdout 为空，进度、错误和摘要位于 stderr。
- quiet 模式隐藏普通进度但保留错误和摘要。
- JSON 模式每行都能独立解析、事件顺序正确；除第二次信号强制终止外，最后一行始终是 result。
- 中文包含原始 Unicode，输出无 ANSI。
- 将 stdout 包装成非 UTF-8 文本编码或模拟 Windows 重定向时，JSON bytes 仍严格为 UTF-8。
- 非 TTY 输出不使用 `\r` 覆盖行。

### 14.4 状态、异常和信号

- 完成、校验和信号状态映射到 0、1、2、3、130、143。
- 适配层未捕获异常映射到 70，并在 JSON 模式尽可能产生失败 result。
- 第一次 Ctrl+C 调用 runner.stop；第二次 Ctrl+C 立即退出 130。
- 首次信号发生在模型加载失败前时，取消原因覆盖 runner 的 `failed`；SIGINT/SIGTERM 分别返回 130/143。
- 第二次强制取消允许没有 JSON result，测试必须验证该例外不会扩散到单次取消。
- 扫描期间取消不会加载模型或处理部分任务。

### 14.5 能力输出

- text 和 JSON 能力输出都直接反映核心常量。
- JSON 字段与 REST API 能力响应的共享部分一致。

CI 应继续在 Python 3.14 下运行全部测试和 Ruff，并把 `cli.py` 加入 lint、编译和无 Qt 导入检查。

## 15. 实施顺序与验收标准

建议按以下顺序实施：

1. 把后端运行依赖检查和能力对象生成提取到 `core.py`，为三个适配层提供统一入口。
2. 新增 `cli.py` 的 parser、reporter、信号处理和退出码映射。
3. 新增 `requirements-cli.txt` 和 `tests/test_cli.py`。
4. 更新 CI、README 和 README-CN，加入安装与快速使用说明。
5. 如需随 Release 分发，另行设计 console PyInstaller 产物和版本单一来源。

首版验收必须同时满足：

- CLI 导入和运行不需要 Qt 或 Web 依赖。
- 所有参数组合在模型加载前完成校验。
- 文本输出适合终端，JSON Lines 输出可以稳定被脚本逐行消费。
- `completed_with_errors` 返回非零，SIGINT 取消返回 130，SIGTERM 取消返回 143。
- Ctrl+C 不覆盖已有输出，也不遗留会替代目标文件的临时产物。
- CLI、桌面端和 API 对同一参数组合使用同一个核心执行路径。
- 单元测试不依赖网络、真实模型或真实音频内容。
