import gc
import csv
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import traceback
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from PyQt6.QtCore import QLocale, QSettings, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    import whisper
except ImportError:
    whisper = None

try:
    from faster_whisper import WhisperModel as FasterWhisperModel
except ImportError:
    FasterWhisperModel = None

try:
    import ctranslate2
except ImportError:
    ctranslate2 = None


try:
    BASE_PATH = Path(os.getcwdb().decode("utf-8")).resolve()
except Exception:
    BASE_PATH = Path.cwd().resolve()

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".mkv", ".mp4"}
OUTPUT_FORMATS = ("lrc", "srt", "vtt", "txt", "tsv", "json")
BACKEND_OPENAI = "openai-whisper"
BACKEND_FASTER = "faster-whisper"
DEFAULT_BACKEND = BACKEND_OPENAI
BACKEND_MODELS = {
    BACKEND_OPENAI: (
        "tiny", "tiny.en", "base", "base.en", "small", "small.en",
        "medium", "medium.en", "large-v1", "large-v2", "large-v3", "large",
        "large-v3-turbo", "turbo",
    ),
    BACKEND_FASTER: (
        "tiny", "tiny.en", "base", "base.en", "small", "small.en", "distil-small.en",
        "medium", "medium.en", "distil-medium.en", "large-v1", "large-v2", "large-v3",
        "large", "distil-large-v2", "distil-large-v3", "distil-large-v3.5",
        "large-v3-turbo", "turbo",
    ),
}
BACKEND_DEFAULT_MODELS = {BACKEND_OPENAI: "base", BACKEND_FASTER: "base"}
FASTER_DEVICE_MODES = ("auto", "cpu", "cuda")
FASTER_COMPUTE_TYPES = {
    "auto": ("auto",),
    "cpu": ("int8", "float32"),
    "cuda": ("float16", "int8_float16", "int8"),
}
ENGLISH_ONLY_MODELS = {
    model
    for models in BACKEND_MODELS.values()
    for model in models
    if model.endswith(".en") or model.startswith("distil-")
}
SUPPORTED_LANGUAGE_CODES = {
    "af", "am", "ar", "as", "az", "ba", "be", "bg", "bn", "bo", "br", "bs",
    "ca", "cs", "cy", "da", "de", "el", "en", "es", "et", "eu", "fa", "fi",
    "fo", "fr", "gl", "gu", "ha", "haw", "he", "hi", "hr", "ht", "hu", "hy",
    "id", "is", "it", "ja", "jw", "ka", "kk", "km", "kn", "ko", "la", "lb",
    "ln", "lo", "lt", "lv", "mg", "mi", "mk", "ml", "mn", "mr", "ms", "mt",
    "my", "ne", "nl", "nn", "no", "oc", "pa", "pl", "ps", "pt", "ro", "ru",
    "sa", "sd", "si", "sk", "sl", "sn", "so", "sq", "sr", "su", "sv", "sw",
    "ta", "te", "tg", "th", "tk", "tl", "tr", "tt", "uk", "ur", "uz", "vi",
    "yi", "yo", "yue", "zh",
}

if getattr(sys, "frozen", False):
    APP_BASE_DIR = Path(sys.executable).parent
else:
    APP_BASE_DIR = Path(__file__).resolve().parent


TRANSLATIONS = {
    "en": {
        "window_title": "Audio Subtitle Exporter (Whisper)",
        "display_language": "Display Language:",
        "english": "English",
        "chinese": "Simplified Chinese",
        "audio_folder": "Audio Folder:",
        "folder_placeholder": "Select a folder containing audio files",
        "select_folder": "Select Folder...",
        "backend": "Whisper Backend:",
        "model": "Whisper Model:",
        "use_local_model": "Use Local Model",
        "local_model_path": "Local Model:",
        "local_model_placeholder": "Select a local model checkpoint or directory",
        "browse_local_model": "Browse...",
        "faster_device_label": "Faster Device:",
        "faster_compute_label": "Compute Type:",
        "device_auto": "Auto",
        "device_cpu": "CPU",
        "device_cuda": "CUDA",
        "language": "Transcription Language:",
        "language_placeholder": "e.g. en, ja, auto (blank also means auto-detect)",
        "output_formats": "Output Formats:",
        "select_output_warning": "Please select at least one output format.",
        "log": "Log:",
        "start": "Start Processing",
        "stop": "Stop",
        "state_idle": "State: Idle.",
        "state_initializing": "State: Initializing...",
        "state_error": "State: Error occurred (see log).",
        "state_stopped": "State: Stopped by user.",
        "state_failed": "State: Failed (see log).",
        "state_finished_errors": "State: Finished with errors (see log).",
        "state_finished": "State: Finished!",
        "state_stopping": "State: Stopping; waiting for the current transcription to finish...",
        "dialog_select_folder": "Select Audio Folder",
        "input_error": "Input Error",
        "select_folder_warning": "Please select an audio folder.",
        "invalid_folder": "Selected path is not a valid folder:\n{path}",
        "invalid_language": "Unsupported transcription language code: {language}",
        "select_local_model_warning": "Please select a local model path.",
        "invalid_openai_local_model": "The OpenAI Whisper local model must be a checkpoint file:\n{path}",
        "invalid_faster_local_model": "The Faster Whisper local model must be a CTranslate2 model directory:\n{path}",
        "dialog_select_openai_model": "Select an OpenAI Whisper checkpoint",
        "dialog_select_faster_model": "Select a Faster Whisper CTranslate2 model directory",
        "english_only_model": "Model '{model}' only supports English; language '{language}' is not valid.",
        "error": "Error",
        "ffmpeg_missing": "FFmpeg was not found in the system PATH.\nCannot proceed without FFmpeg.",
        "confirm_exit": "Confirm Exit",
        "confirm_exit_text": "Processing is ongoing. Stop and exit?\n(The current file may finish first.)",
        "log_base_path": "Base path: {path}",
        "log_starting": "Starting processing...",
        "log_folder": "Folder: {path}",
        "log_backend": "Backend: {backend}",
        "log_model": "Model: {model}",
        "log_language": "Transcription language: {language}",
        "log_output_formats": "Output formats: {formats}",
        "log_stopping": "Attempting to stop processing (the current file may finish first)...",
        "log_close_wait": "The application will close after the worker thread exits safely.",
        "log_error_prefix": "[ERROR] {message}",
        "log_stopped": "Processing stopped.",
        "log_failed": "Processing failed.",
        "log_finished_errors": "Processing finished with errors.",
        "log_finished": "Processing finished.",
        "loading_model": "Loading {backend} model: {model}...",
        "using_cached_model": "Using cached {backend} model: {model}.",
        "model_loaded": "{backend} model '{model}' loaded and cached.",
        "model_load_failed": "Failed to load {backend} model '{model}': {error}",
        "faster_device": "Faster Whisper runtime: {device} / {compute_type}.",
        "faster_cpu_fallback": (
            "CUDA model loading failed ({error}). Auto mode is retrying once with CPU / int8."
        ),
        "cancelled": "Processing cancelled.",
        "conflict": (
            "Multiple media files map to the same output name; all were skipped:\n"
            "Output base: {target}\nSources:\n{sources}"
        ),
        "no_unambiguous": "No unambiguous audio files found; conflicts were skipped.",
        "no_new_files": "No new audio files found to process.",
        "found_files": "Found {count} files to process...",
        "processing": "Processing: {name} ({current}/{total})",
        "empty_result": "Whisper produced no timestamped text for {name}.",
        "target_appeared": "Skipped existing output for {source}: {target}",
        "processing_error": "Error processing {name}: {error}\n{traceback}",
        "worker_error": "An unexpected error occurred in worker setup: {error}\n{traceback}",
        "startup_error": "Startup Error",
        "whisper_missing": "Could not import 'whisper'.\nInstall it with: pip install -U openai-whisper",
        "faster_whisper_missing": "Could not import 'faster_whisper'.\nInstall it with: pip install -U faster-whisper",
        "startup_ffmpeg_missing": (
            "FFmpeg was not found. Whisper requires it to process audio.\n"
            "Install FFmpeg and add it to PATH.\n\nhttps://ffmpeg.org/download.html"
        ),
    },
    "zh_CN": {
        "window_title": "音频字幕导出工具（Whisper）",
        "display_language": "显示语言：",
        "english": "English",
        "chinese": "简体中文",
        "audio_folder": "音频文件夹：",
        "folder_placeholder": "选择包含音频文件的文件夹",
        "select_folder": "选择文件夹...",
        "backend": "Whisper 后端：",
        "model": "Whisper 模型：",
        "use_local_model": "使用本地模型",
        "local_model_path": "本地模型：",
        "local_model_placeholder": "选择本地模型权重文件或目录",
        "browse_local_model": "浏览...",
        "faster_device_label": "Faster 设备：",
        "faster_compute_label": "计算精度：",
        "device_auto": "自动",
        "device_cpu": "CPU",
        "device_cuda": "CUDA",
        "language": "转录语言：",
        "language_placeholder": "例如 en、ja、auto（留空也会自动检测）",
        "output_formats": "输出格式：",
        "select_output_warning": "请至少选择一种输出格式。",
        "log": "日志：",
        "start": "开始处理",
        "stop": "停止",
        "state_idle": "状态：空闲。",
        "state_initializing": "状态：正在初始化...",
        "state_error": "状态：发生错误（请查看日志）。",
        "state_stopped": "状态：已由用户停止。",
        "state_failed": "状态：处理失败（请查看日志）。",
        "state_finished_errors": "状态：处理完成，但存在错误（请查看日志）。",
        "state_finished": "状态：处理完成！",
        "state_stopping": "状态：正在停止，等待当前转录安全结束...",
        "dialog_select_folder": "选择音频文件夹",
        "input_error": "输入错误",
        "select_folder_warning": "请选择音频文件夹。",
        "invalid_folder": "所选路径不是有效文件夹：\n{path}",
        "invalid_language": "不支持的转录语言代码：{language}",
        "select_local_model_warning": "请选择本地模型路径。",
        "invalid_openai_local_model": "OpenAI Whisper 本地模型必须是权重文件：\n{path}",
        "invalid_faster_local_model": "Faster Whisper 本地模型必须是 CTranslate2 模型目录：\n{path}",
        "dialog_select_openai_model": "选择 OpenAI Whisper 权重文件",
        "dialog_select_faster_model": "选择 Faster Whisper CTranslate2 模型目录",
        "english_only_model": "模型“{model}”仅支持英语，不能使用语言“{language}”。",
        "error": "错误",
        "ffmpeg_missing": "系统 PATH 中未找到 FFmpeg。\n没有 FFmpeg 无法继续。",
        "confirm_exit": "确认退出",
        "confirm_exit_text": "处理仍在进行。是否停止并退出？\n（当前文件可能会先处理完。）",
        "log_base_path": "程序路径：{path}",
        "log_starting": "开始处理...",
        "log_folder": "文件夹：{path}",
        "log_backend": "后端：{backend}",
        "log_model": "模型：{model}",
        "log_language": "转录语言：{language}",
        "log_output_formats": "输出格式：{formats}",
        "log_stopping": "正在请求停止处理（当前文件可能会先处理完）...",
        "log_close_wait": "工作线程安全退出后，程序将自动关闭。",
        "log_error_prefix": "[错误] {message}",
        "log_stopped": "处理已停止。",
        "log_failed": "处理失败。",
        "log_finished_errors": "处理完成，但存在错误。",
        "log_finished": "处理完成。",
        "loading_model": "正在加载 {backend} 模型：{model}...",
        "using_cached_model": "正在使用已缓存的 {backend} 模型：{model}。",
        "model_loaded": "{backend} 模型“{model}”已加载并缓存。",
        "model_load_failed": "无法加载 {backend} 模型“{model}”：{error}",
        "faster_device": "Faster Whisper 运行配置：{device} / {compute_type}。",
        "faster_cpu_fallback": "CUDA 模型加载失败（{error}）。自动模式将使用 CPU / int8 重试一次。",
        "cancelled": "处理已取消。",
        "conflict": "多个媒体文件对应同一个输出名称，已全部跳过：\n输出基础名称：{target}\n来源：\n{sources}",
        "no_unambiguous": "未找到无冲突的音频文件；冲突文件已跳过。",
        "no_new_files": "没有需要处理的新音频文件。",
        "found_files": "找到 {count} 个待处理文件...",
        "processing": "正在处理：{name}（{current}/{total}）",
        "empty_result": "Whisper 没有为 {name} 生成带时间戳的文本。",
        "target_appeared": "已跳过 {source} 的现有输出：{target}",
        "processing_error": "处理 {name} 时出错：{error}\n{traceback}",
        "worker_error": "工作线程初始化时发生意外错误：{error}\n{traceback}",
        "startup_error": "启动错误",
        "whisper_missing": "无法导入“whisper”。\n请运行：pip install -U openai-whisper",
        "faster_whisper_missing": "无法导入“faster_whisper”。\n请运行：pip install -U faster-whisper",
        "startup_ffmpeg_missing": "未找到 FFmpeg。Whisper 需要它处理音频。\n请安装 FFmpeg 并加入 PATH。\n\nhttps://ffmpeg.org/download.html",
    },
}


def normalize_locale(locale_name: str | None) -> str:
    return "zh_CN" if locale_name and locale_name.lower().replace("-", "_").startswith("zh") else "en"


def system_locale() -> str:
    return normalize_locale(QLocale.system().name())


def translate(locale_name: str, key: str, **values) -> str:
    template = TRANSLATIONS[normalize_locale(locale_name)][key]
    return template.format(**values)


def create_settings() -> QSettings:
    return QSettings("Whisper_auto2lrc", "Whisper_auto2lrc")


def settings_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def validate_transcription_language(
    model_name: str, language: str, locale_name: str, is_local_model: bool = False
) -> tuple[str, str] | None:
    normalized_language = language.strip().lower()
    if not normalized_language or normalized_language == "auto":
        return None
    if normalized_language not in SUPPORTED_LANGUAGE_CODES:
        return (
            translate(locale_name, "input_error"),
            translate(
                locale_name, "invalid_language", language=normalized_language
            ),
        )
    if (
        not is_local_model
        and model_name in ENGLISH_ONLY_MODELS
        and normalized_language != "en"
    ):
        return (
            translate(locale_name, "input_error"),
            translate(
                locale_name,
                "english_only_model",
                model=model_name,
                language=normalized_language,
            ),
        )
    return None


def resolved_model_reference(model_name: str, is_local_model: bool) -> str:
    if not is_local_model:
        return model_name
    return str(Path(model_name).expanduser().resolve())


def validate_local_model_path(
    backend_name: str, model_path: str, locale_name: str
) -> tuple[str, str] | None:
    if not model_path.strip():
        return (
            translate(locale_name, "input_error"),
            translate(locale_name, "select_local_model_warning"),
        )
    resolved_path = Path(model_path).expanduser().resolve()
    if backend_name == BACKEND_OPENAI and not resolved_path.is_file():
        key = "invalid_openai_local_model"
    elif backend_name == BACKEND_FASTER and not resolved_path.is_dir():
        key = "invalid_faster_local_model"
    else:
        return None
    return (
        translate(locale_name, "input_error"),
        translate(locale_name, key, path=resolved_path),
    )


def format_lrc_time(seconds: float) -> str:
    """Convert non-negative seconds to an LRC timestamp rounded to centiseconds."""
    seconds_decimal = Decimal(str(seconds))
    if seconds_decimal < 0:
        raise ValueError("non-negative timestamp expected")

    centiseconds = int((seconds_decimal * 100).to_integral_value(rounding=ROUND_HALF_UP))
    minutes, remainder = divmod(centiseconds, 6_000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f"{minutes:02d}:{whole_seconds:02d}.{fraction:02d}"


def normalize_segment_text(raw_text) -> str:
    return " ".join(str(raw_text).split()) if raw_text else ""


def generate_lrc_content(transcription_result: dict) -> str:
    """Generate ordinary line-timestamped LRC directly from Whisper segments."""
    lines = []
    for segment in transcription_result.get("segments", []):
        text = normalize_segment_text(segment.get("text"))
        if text:
            lines.append(f"[{format_lrc_time(segment['start'])}]{text}")
    return "\n".join(lines) + ("\n" if lines else "")


def format_subtitle_time(seconds: float, separator: str = ",") -> str:
    """Convert non-negative seconds to an SRT/VTT timestamp rounded to milliseconds."""
    seconds_decimal = Decimal(str(seconds))
    if seconds_decimal < 0:
        raise ValueError("non-negative timestamp expected")
    milliseconds = int(
        (seconds_decimal * 1_000).to_integral_value(rounding=ROUND_HALF_UP)
    )
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, fraction = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{fraction:03d}"


def timestamped_segments(transcription_result: dict):
    for segment in transcription_result.get("segments", []):
        text = normalize_segment_text(segment.get("text"))
        if text:
            yield segment, text


def generate_srt_content(transcription_result: dict) -> str:
    blocks = []
    for index, (segment, text) in enumerate(timestamped_segments(transcription_result), 1):
        start = format_subtitle_time(segment["start"], ",")
        end = format_subtitle_time(segment["end"], ",")
        blocks.append(f"{index}\n{start} --> {end}\n{text.replace('-->', '->')}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def generate_vtt_content(transcription_result: dict) -> str:
    blocks = []
    for segment, text in timestamped_segments(transcription_result):
        start = format_subtitle_time(segment["start"], ".")
        end = format_subtitle_time(segment["end"], ".")
        blocks.append(f"{start} --> {end}\n{text.replace('-->', '->')}")
    return "WEBVTT\n\n" + "\n\n".join(blocks) + ("\n" if blocks else "")


def generate_txt_content(transcription_result: dict) -> str:
    lines = [text for _segment, text in timestamped_segments(transcription_result)]
    return "\n".join(lines) + ("\n" if lines else "")


def generate_tsv_content(transcription_result: dict) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(("start", "end", "text"))
    for segment, text in timestamped_segments(transcription_result):
        start = int((Decimal(str(segment["start"])) * 1_000).to_integral_value(ROUND_HALF_UP))
        end = int((Decimal(str(segment["end"])) * 1_000).to_integral_value(ROUND_HALF_UP))
        writer.writerow((start, end, text))
    return output.getvalue()


def generate_output_content(output_format: str, transcription_result: dict) -> str:
    generators = {
        "lrc": generate_lrc_content,
        "srt": generate_srt_content,
        "vtt": generate_vtt_content,
        "txt": generate_txt_content,
        "tsv": generate_tsv_content,
        "json": lambda result: json.dumps(result, ensure_ascii=False, indent=2) + "\n",
    }
    try:
        generator = generators[output_format]
    except KeyError as error:
        raise ValueError(f"unsupported output format: {output_format}") from error
    return generator(transcription_result)


def write_text_atomically(target_path: Path, content: str) -> None:
    """Write UTF-8 text beside the target, then atomically replace the target."""
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, target_path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def write_text_exclusively(target_path: Path, content: str) -> bool:
    """Atomically publish a new UTF-8 file without ever replacing an existing one."""
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        try:
            os.link(temp_path, target_path)
        except FileExistsError:
            return False
        return True
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def discover_audio_tasks(folder_path: Path, output_formats) -> tuple[list, list]:
    """Return unambiguous media tasks and same-stem conflicts without loading a model."""
    candidate_files = sorted(
        (
            path
            for path in folder_path.rglob("*")
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
        ),
        key=lambda path: (str(path).casefold(), str(path)),
    )
    files_by_output_base = {}
    for audio_file in candidate_files:
        output_base = audio_file.with_suffix("")
        if any(
            not audio_file.with_suffix(f".{output_format}").exists()
            for output_format in output_formats
        ):
            files_by_output_base.setdefault(output_base, []).append(audio_file)

    tasks = []
    conflicts = []
    for output_base, source_files in sorted(
        files_by_output_base.items(),
        key=lambda item: (str(item[0]).casefold(), str(item[0])),
    ):
        if len(source_files) > 1:
            conflicts.append((output_base, tuple(source_files)))
            continue
        audio_file = source_files[0]
        missing_formats = tuple(
            output_format
            for output_format in output_formats
            if not audio_file.with_suffix(f".{output_format}").exists()
        )
        tasks.append((audio_file, missing_formats))
    return tasks, conflicts


def faster_whisper_runtime(
    device_mode: str = "auto", compute_type: str = "auto"
) -> tuple[str, str]:
    """Resolve requested Faster Whisper settings to an actual runtime."""
    if device_mode not in FASTER_DEVICE_MODES:
        raise ValueError(f"unsupported Faster Whisper device: {device_mode}")
    if device_mode != "auto":
        legal_compute_types = FASTER_COMPUTE_TYPES[device_mode]
        if compute_type == "auto":
            compute_type = legal_compute_types[0]
        if compute_type not in legal_compute_types:
            raise ValueError(
                f"compute type '{compute_type}' is not valid for {device_mode}"
            )
        return device_mode, compute_type

    try:
        cuda_available = bool(
            ctranslate2 is not None
            and getattr(ctranslate2, "get_cuda_device_count", lambda: 0)() > 0
        )
    except Exception:
        cuda_available = False
    return ("cuda", "float16") if cuda_available else ("cpu", "int8")


def release_unused_model_memory() -> None:
    """Collect released models and return unused PyTorch CUDA memory when available."""
    gc.collect()
    torch_module = sys.modules.get("torch")
    try:
        if torch_module is not None and torch_module.cuda.is_available():
            torch_module.cuda.empty_cache()
    except Exception:
        pass


class OpenAIWhisperBackend:
    name = BACKEND_OPENAI

    def cache_key(self, model_name: str, is_local_model: bool = False) -> tuple[str, str]:
        return self.name, resolved_model_reference(model_name, is_local_model)

    def load_model(self, model_name: str, is_local_model: bool = False):
        if whisper is None:
            raise RuntimeError(translate("en", "whisper_missing"))
        return whisper.load_model(resolved_model_reference(model_name, is_local_model))

    def transcribe(self, model, audio_file: Path, language: str | None) -> dict:
        return model.transcribe(str(audio_file), language=language, verbose=False)


class FasterWhisperBackend:
    name = BACKEND_FASTER

    def __init__(self, device_mode: str = "auto", compute_type: str = "auto"):
        self.device_mode = device_mode
        self.requested_compute_type = compute_type
        self.device, self.compute_type = faster_whisper_runtime(
            device_mode, compute_type
        )

    @property
    def can_fallback_to_cpu(self) -> bool:
        return self.device_mode == "auto" and self.device == "cuda"

    def fallback_to_cpu(self) -> None:
        if not self.can_fallback_to_cpu:
            raise RuntimeError("CPU fallback is only available from CUDA in Auto mode")
        self.device = "cpu"
        self.compute_type = "int8"

    def cache_key(
        self, model_name: str, is_local_model: bool = False
    ) -> tuple[str, str, str, str]:
        return (
            self.name,
            resolved_model_reference(model_name, is_local_model),
            self.device,
            self.compute_type,
        )

    def load_model(self, model_name: str, is_local_model: bool = False):
        if FasterWhisperModel is None:
            raise RuntimeError(translate("en", "faster_whisper_missing"))
        options = {"device": self.device, "compute_type": self.compute_type}
        if is_local_model:
            options["local_files_only"] = True
        return FasterWhisperModel(
            resolved_model_reference(model_name, is_local_model), **options
        )

    def transcribe(self, model, audio_file: Path, language: str | None) -> dict:
        segments, info = model.transcribe(str(audio_file), language=language)
        normalized_segments = []
        text_parts = []
        # Faster Whisper returns a generator; consuming it performs the transcription.
        for segment in segments:
            text = str(segment.text)
            text_parts.append(text)
            normalized_segments.append(
                {"start": float(segment.start), "end": float(segment.end), "text": text}
            )
        return {
            "text": "".join(text_parts).strip(),
            "segments": normalized_segments,
            "language": getattr(info, "language", language),
        }


def create_backend(
    backend_name: str,
    faster_device_mode: str = "auto",
    faster_compute_type: str = "auto",
):
    if backend_name == BACKEND_OPENAI:
        return OpenAIWhisperBackend()
    if backend_name == BACKEND_FASTER:
        return FasterWhisperBackend(faster_device_mode, faster_compute_type)
    raise ValueError(f"unsupported backend: {backend_name}")


def backend_display_name(backend_name: str) -> str:
    return "OpenAI Whisper" if backend_name == BACKEND_OPENAI else "Faster Whisper"


class ModelCache:
    """Thread-safe cache that keeps at most the last requested backend/model.

    The previous model is released before a different one is loaded so switching
    models does not temporarily require enough RAM/VRAM for both models.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._model_name = None
        self._model = None

    def get_or_load(self, model_name, loader):
        """Return (model, cache_hit); a failed load never enters the cache."""
        with self._lock:
            if self._model_name == model_name and self._model is not None:
                return self._model, True

            previous_model = self._model
            self._model_name = None
            self._model = None
            del previous_model
            release_unused_model_memory()
            try:
                model = loader(model_name)
            except Exception:
                release_unused_model_memory()
                raise
            self._model_name = model_name
            self._model = model
            return model, False

    def clear(self):
        with self._lock:
            previous_model = self._model
            self._model_name = None
            self._model = None
            del previous_model
            release_unused_model_memory()


WHISPER_MODEL_CACHE = ModelCache()


class Worker(QThread):
    progress = pyqtSignal(str, int)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        folder_path: Path,
        model_name: str,
        language: str,
        locale_name: str = "en",
        output_formats=None,
        backend_name: str = DEFAULT_BACKEND,
        faster_device_mode: str = "auto",
        faster_compute_type: str = "auto",
        is_local_model: bool = False,
    ):
        super().__init__()
        self.folder_path = folder_path
        self.model_name = model_name
        self.is_local_model = is_local_model
        self.backend_name = backend_name
        self.backend = create_backend(
            backend_name, faster_device_mode, faster_compute_type
        )
        normalized_language = language.strip().lower() if language else ""
        self.language = (
            normalized_language
            if normalized_language and normalized_language != "auto"
            else None
        )
        self.locale_name = normalize_locale(locale_name)
        selected_formats = output_formats if output_formats is not None else ("lrc",)
        self.output_formats = tuple(
            output_format
            for output_format in OUTPUT_FORMATS
            if output_format in selected_formats
        )
        self._is_running = True
        self.completion_status = "running"
        self.had_errors = False
        self.whisper_model = None

    def tr(self, key: str, **values) -> str:
        return translate(self.locale_name, key, **values)

    def stop(self):
        self._is_running = False

    def report_error(self, message: str):
        self.had_errors = True
        self.error_occurred.emit(message)

    def run(self):
        try:
            language_error = validate_transcription_language(
                self.model_name,
                self.language or "auto",
                self.locale_name,
                self.is_local_model,
            )
            if language_error:
                self.report_error(language_error[1])
                self.completion_status = "failed"
                return

            audio_files, conflicts = discover_audio_tasks(
                self.folder_path, self.output_formats
            )
            for output_base, source_files in conflicts:
                sources = "\n".join(f"- {source_file}" for source_file in source_files)
                self.report_error(
                    self.tr("conflict", target=output_base, sources=sources)
                )

            total_files = len(audio_files)
            if not self._is_running:
                self.progress.emit(self.tr("cancelled"), 0)
                self.completion_status = "cancelled"
                return
            if total_files == 0:
                if self.had_errors:
                    self.progress.emit(self.tr("no_unambiguous"), 0)
                    self.completion_status = "completed_with_errors"
                else:
                    self.progress.emit(self.tr("no_new_files"), 0)
                    self.completion_status = "completed"
                return

            availability_error = check_backend_availability(
                self.backend_name, self.locale_name
            )
            if availability_error:
                self.report_error(availability_error[1])
                self.completion_status = "failed"
                return

            backend_label = backend_display_name(self.backend_name)
            def report_faster_runtime():
                self.progress.emit(
                    self.tr(
                        "faster_device",
                        device=self.backend.device,
                        compute_type=self.backend.compute_type,
                    ),
                    0,
                )
            if isinstance(self.backend, FasterWhisperBackend):
                report_faster_runtime()
            self.progress.emit(
                self.tr("loading_model", backend=backend_label, model=self.model_name), 0
            )
            try:
                self.whisper_model, cache_hit = WHISPER_MODEL_CACHE.get_or_load(
                    self.backend.cache_key(self.model_name, self.is_local_model),
                    lambda _cache_key: self.backend.load_model(
                        self.model_name, self.is_local_model
                    ),
                )
            except Exception as model_load_error:
                if (
                    isinstance(self.backend, FasterWhisperBackend)
                    and self.backend.can_fallback_to_cpu
                ):
                    self.progress.emit(
                        self.tr("faster_cpu_fallback", error=model_load_error), 0
                    )
                    self.backend.fallback_to_cpu()
                    report_faster_runtime()
                    try:
                        self.whisper_model, cache_hit = WHISPER_MODEL_CACHE.get_or_load(
                            self.backend.cache_key(
                                self.model_name, self.is_local_model
                            ),
                            lambda _cache_key: self.backend.load_model(
                                self.model_name, self.is_local_model
                            ),
                        )
                    except Exception as fallback_error:
                        model_load_error = fallback_error
                    else:
                        model_load_error = None
                if model_load_error is None:
                    pass
                else:
                    self.report_error(
                        self.tr(
                            "model_load_failed",
                            backend=backend_label,
                            model=self.model_name,
                            error=model_load_error,
                        )
                    )
                    self.whisper_model = None
                    self.completion_status = "failed"
                    return

            progress_key = "using_cached_model" if cache_hit else "model_loaded"
            self.progress.emit(
                self.tr(progress_key, backend=backend_label, model=self.model_name), 0
            )

            if not self._is_running:
                self.progress.emit(self.tr("cancelled"), 0)
                self.completion_status = "cancelled"
                return

            self.progress.emit(self.tr("found_files", count=total_files), 0)

            for index, (audio_file, missing_formats) in enumerate(audio_files):
                if not self._is_running:
                    self.progress.emit(self.tr("cancelled"), int((index / total_files) * 100))
                    break

                progress_text = self.tr(
                    "processing", name=audio_file.name, current=index + 1, total=total_files
                )
                self.progress.emit(progress_text, int((index / total_files) * 100))

                try:
                    result = self.backend.transcribe(
                        self.whisper_model, audio_file, self.language
                    )
                    if not any(timestamped_segments(result)):
                        self.report_error(self.tr("empty_result", name=audio_file.name))
                        continue

                    for output_format in missing_formats:
                        target_path = audio_file.with_suffix(f".{output_format}")
                        try:
                            content = generate_output_content(output_format, result)
                            if not write_text_exclusively(target_path, content):
                                self.report_error(
                                    self.tr(
                                        "target_appeared",
                                        source=audio_file,
                                        target=target_path,
                                    )
                                )
                        except Exception as output_error:
                            self.report_error(
                                self.tr(
                                    "processing_error",
                                    name=f"{audio_file.name} -> {output_format.upper()}",
                                    error=output_error,
                                    traceback=traceback.format_exc(),
                                )
                            )
                except Exception as error:
                    self.report_error(
                        self.tr(
                            "processing_error",
                            name=audio_file.name,
                            error=error,
                            traceback=traceback.format_exc(),
                        )
                    )
                    continue

                self.progress.emit(progress_text, int(((index + 1) / total_files) * 100))

            if not self._is_running:
                self.completion_status = "cancelled"
            elif self.had_errors:
                self.completion_status = "completed_with_errors"
            else:
                self.completion_status = "completed"
        except Exception as error:
            self.report_error(
                self.tr("worker_error", error=error, traceback=traceback.format_exc())
            )
            self.completion_status = "failed"


class App(QWidget):
    def __init__(
        self, locale_name: str | None = None, settings: QSettings | None = None
    ):
        super().__init__()
        self.settings = settings or create_settings()
        self.worker = None
        self._close_when_worker_finishes = False
        saved_locale = self.settings.value("display_language", system_locale())
        self.locale_name = normalize_locale(locale_name or saved_locale)
        self._status_key = "state_idle"
        self._status_values = {}
        self.initUI()

    def tr(self, key: str, **values) -> str:
        return translate(self.locale_name, key, **values)

    def initUI(self):
        icon_path = APP_BASE_DIR / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.resize(750, 550)
        self.setMinimumSize(600, 400)
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.display_language_select = QComboBox()
        self.display_language_select.addItem("English", "en")
        self.display_language_select.addItem("简体中文", "zh_CN")
        locale_index = self.display_language_select.findData(self.locale_name)
        self.display_language_select.setCurrentIndex(max(0, locale_index))
        self.display_language_select.currentIndexChanged.connect(self.change_display_language)
        self.display_language_label = QLabel()
        form_layout.addRow(self.display_language_label, self.display_language_select)

        self.folder_path_edit = QLineEdit()
        self.folder_path_edit.setText(self.settings.value("folder_path", "C:/"))
        self.select_folder_button = QPushButton()
        self.select_folder_button.setFont(QFont("Arial", 10))
        self.select_folder_button.clicked.connect(self.select_folder)
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.folder_path_edit)
        folder_layout.addWidget(self.select_folder_button)
        self.audio_folder_label = QLabel()
        form_layout.addRow(self.audio_folder_label, folder_layout)

        self.backend_select = QComboBox()
        self.backend_select.addItem("OpenAI Whisper", BACKEND_OPENAI)
        self.backend_select.addItem("Faster Whisper", BACKEND_FASTER)
        saved_backend = self.settings.value("backend", DEFAULT_BACKEND)
        backend_index = self.backend_select.findData(saved_backend)
        self.backend_select.setCurrentIndex(max(0, backend_index))
        self.backend_label = QLabel()
        form_layout.addRow(self.backend_label, self.backend_select)

        self.model_select = QComboBox()
        self.model_label = QLabel()
        form_layout.addRow(self.model_label, self.model_select)
        self.update_model_options()

        self.use_local_model_check = QCheckBox()
        form_layout.addRow("", self.use_local_model_check)
        self.local_model_path_edit = QLineEdit()
        self.local_model_browse_button = QPushButton()
        self.local_model_browse_button.setFont(QFont("Arial", 10))
        local_model_layout = QHBoxLayout()
        local_model_layout.addWidget(self.local_model_path_edit)
        local_model_layout.addWidget(self.local_model_browse_button)
        self.local_model_label = QLabel()
        form_layout.addRow(self.local_model_label, local_model_layout)
        self._active_backend_name = self.backend_select.currentData() or DEFAULT_BACKEND
        self.restore_local_model_settings(self._active_backend_name)

        self.faster_device_select = QComboBox()
        for device_mode in FASTER_DEVICE_MODES:
            self.faster_device_select.addItem(device_mode, device_mode)
        saved_device = self.settings.value("faster_device", "auto")
        device_index = self.faster_device_select.findData(saved_device)
        self.faster_device_select.setCurrentIndex(max(0, device_index))
        self.faster_device_label = QLabel()
        form_layout.addRow(self.faster_device_label, self.faster_device_select)

        self.faster_compute_select = QComboBox()
        self.faster_compute_label = QLabel()
        form_layout.addRow(self.faster_compute_label, self.faster_compute_select)
        self.update_faster_compute_options()

        self.language_input = QLineEdit()
        self.language_input.setText(
            self.settings.value("transcription_language", "auto")
        )
        self.language_label = QLabel()
        form_layout.addRow(self.language_label, self.language_input)

        output_formats_layout = QHBoxLayout()
        self.output_format_checks = {}
        saved_formats = self.settings.value("output_formats", "lrc")
        if isinstance(saved_formats, str):
            saved_formats = saved_formats.split(",")
        saved_formats = set(saved_formats or ("lrc",))
        for output_format in OUTPUT_FORMATS:
            checkbox = QCheckBox(output_format.upper())
            checkbox.setChecked(output_format in saved_formats)
            self.output_format_checks[output_format] = checkbox
            output_formats_layout.addWidget(checkbox)
        output_formats_layout.addStretch()
        self.output_formats_label = QLabel()
        form_layout.addRow(self.output_formats_label, output_formats_layout)
        layout.addLayout(form_layout)

        self.progress_label = QLabel()
        self.progress_label.setFont(QFont("Arial", 10))
        layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setFont(QFont("Consolas", 9))
        self.log_output.setMaximumHeight(150)
        self.log_label = QLabel()
        layout.addWidget(self.log_label)
        layout.addWidget(self.log_output)

        button_layout = QHBoxLayout()
        self.start_button = QPushButton()
        self.start_button.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.start_button.clicked.connect(self.start_processing)
        self.stop_button = QPushButton()
        self.stop_button.setFont(QFont("Arial", 12))
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_processing)
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        layout.addLayout(button_layout)

        self.backend_select.currentIndexChanged.connect(self.change_backend)
        self.model_select.currentTextChanged.connect(self.save_current_model)
        self.use_local_model_check.toggled.connect(self.local_model_selection_changed)
        self.local_model_path_edit.editingFinished.connect(
            self.save_local_model_settings
        )
        self.local_model_browse_button.clicked.connect(self.select_local_model)
        self.faster_device_select.currentIndexChanged.connect(
            self.change_faster_device
        )
        self.faster_compute_select.currentIndexChanged.connect(self.save_settings)
        self.folder_path_edit.editingFinished.connect(self.save_settings)
        self.language_input.editingFinished.connect(self.save_settings)
        for checkbox in self.output_format_checks.values():
            checkbox.toggled.connect(self.save_settings)

        geometry = self.settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        self.update_backend_controls_visibility()
        self.retranslate_ui()

    def change_display_language(self):
        self.locale_name = normalize_locale(self.display_language_select.currentData())
        self.settings.setValue("display_language", self.locale_name)
        if self.worker and self.worker.isRunning():
            self.worker.locale_name = self.locale_name
        self.retranslate_ui()

    def change_backend(self):
        self.save_local_model_settings(self._active_backend_name)
        self.settings.setValue("backend", self.backend_select.currentData())
        self.update_model_options()
        self._active_backend_name = self.backend_select.currentData() or DEFAULT_BACKEND
        self.restore_local_model_settings(self._active_backend_name)
        self.update_backend_controls_visibility()

    def local_model_settings_key(self, backend_name: str, value_name: str) -> str:
        return f"local_models/{backend_name}/{value_name}"

    def save_local_model_settings(self, backend_name: str | None = None):
        backend_name = backend_name or self._active_backend_name
        self.settings.setValue(
            self.local_model_settings_key(backend_name, "enabled"),
            self.use_local_model_check.isChecked(),
        )
        self.settings.setValue(
            self.local_model_settings_key(backend_name, "path"),
            self.local_model_path_edit.text(),
        )

    def restore_local_model_settings(self, backend_name: str):
        enabled = settings_bool(
            self.settings.value(
                self.local_model_settings_key(backend_name, "enabled"), False
            )
        )
        model_path = self.settings.value(
            self.local_model_settings_key(backend_name, "path"), ""
        )
        self.use_local_model_check.blockSignals(True)
        self.local_model_path_edit.blockSignals(True)
        self.use_local_model_check.setChecked(enabled)
        self.local_model_path_edit.setText(str(model_path or ""))
        self.local_model_path_edit.blockSignals(False)
        self.use_local_model_check.blockSignals(False)
        self.update_local_model_controls()

    def local_model_selection_changed(self):
        self.save_local_model_settings()
        self.update_local_model_controls()

    def update_local_model_controls(self, controls_enabled: bool | None = None):
        if controls_enabled is None:
            controls_enabled = self.use_local_model_check.isEnabled()
        use_local_model = self.use_local_model_check.isChecked()
        self.model_select.setEnabled(controls_enabled and not use_local_model)
        self.local_model_path_edit.setEnabled(controls_enabled and use_local_model)
        self.local_model_browse_button.setEnabled(controls_enabled and use_local_model)

    def select_local_model(self):
        backend_name = self.backend_select.currentData() or DEFAULT_BACKEND
        current_path = self.local_model_path_edit.text().strip()
        start_path = current_path if Path(current_path).exists() else str(BASE_PATH)
        if backend_name == BACKEND_OPENAI:
            selected_path, _selected_filter = QFileDialog.getOpenFileName(
                self,
                self.tr("dialog_select_openai_model"),
                start_path,
                "PyTorch checkpoints (*.pt);;All files (*)",
            )
        else:
            selected_path = QFileDialog.getExistingDirectory(
                self, self.tr("dialog_select_faster_model"), start_path
            )
        if selected_path:
            self.local_model_path_edit.setText(
                str(Path(selected_path).expanduser().resolve())
            )
            self.save_local_model_settings()

    def save_current_model(self):
        backend_name = self.backend_select.currentData() or DEFAULT_BACKEND
        if self.model_select.currentText():
            self.settings.setValue(
                f"models/{backend_name}", self.model_select.currentText()
            )

    def update_model_options(self):
        backend_name = self.backend_select.currentData() or DEFAULT_BACKEND
        previous_model = self.model_select.currentText()
        settings_key = f"models/{backend_name}"
        saved_model = (
            self.settings.value(settings_key)
            if self.settings.contains(settings_key)
            else None
        )
        self.model_select.blockSignals(True)
        self.model_select.clear()
        self.model_select.addItems(BACKEND_MODELS[backend_name])
        preferred_model = (
            saved_model
            if saved_model and saved_model in BACKEND_MODELS[backend_name]
            else previous_model
            if previous_model in BACKEND_MODELS[backend_name]
            else BACKEND_DEFAULT_MODELS[backend_name]
        )
        self.model_select.setCurrentText(preferred_model)
        self.model_select.blockSignals(False)

    def update_faster_compute_options(self):
        device_mode = self.faster_device_select.currentData() or "auto"
        saved_compute = self.settings.value("faster_compute", "auto")
        legal_compute_types = FASTER_COMPUTE_TYPES[device_mode]
        selected_compute = (
            saved_compute if saved_compute in legal_compute_types else legal_compute_types[0]
        )
        self.faster_compute_select.blockSignals(True)
        self.faster_compute_select.clear()
        self.faster_compute_select.addItems(legal_compute_types)
        self.faster_compute_select.setCurrentText(selected_compute)
        self.faster_compute_select.blockSignals(False)
        self.settings.setValue("faster_compute", selected_compute)

    def change_faster_device(self):
        self.settings.setValue(
            "faster_device", self.faster_device_select.currentData()
        )
        self.update_faster_compute_options()

    def update_backend_controls_visibility(self):
        is_faster = self.backend_select.currentData() == BACKEND_FASTER
        self.faster_device_label.setVisible(is_faster)
        self.faster_device_select.setVisible(is_faster)
        self.faster_compute_label.setVisible(is_faster)
        self.faster_compute_select.setVisible(is_faster)

    def save_settings(self):
        self.settings.setValue("folder_path", self.folder_path_edit.text())
        self.settings.setValue(
            "transcription_language", self.language_input.text()
        )
        selected_formats = [
            output_format
            for output_format, checkbox in self.output_format_checks.items()
            if checkbox.isChecked()
        ]
        self.settings.setValue("output_formats", ",".join(selected_formats))
        self.settings.setValue(
            "faster_device", self.faster_device_select.currentData()
        )
        self.settings.setValue(
            "faster_compute", self.faster_compute_select.currentText()
        )
        self.save_current_model()
        self.save_local_model_settings()

    def retranslate_ui(self):
        self.setWindowTitle(self.tr("window_title"))
        self.display_language_label.setText(self.tr("display_language"))
        self.audio_folder_label.setText(self.tr("audio_folder"))
        self.folder_path_edit.setPlaceholderText(self.tr("folder_placeholder"))
        self.select_folder_button.setText(self.tr("select_folder"))
        self.backend_label.setText(self.tr("backend"))
        self.model_label.setText(self.tr("model"))
        self.use_local_model_check.setText(self.tr("use_local_model"))
        self.local_model_label.setText(self.tr("local_model_path"))
        self.local_model_path_edit.setPlaceholderText(
            self.tr("local_model_placeholder")
        )
        self.local_model_browse_button.setText(self.tr("browse_local_model"))
        self.faster_device_label.setText(self.tr("faster_device_label"))
        self.faster_compute_label.setText(self.tr("faster_compute_label"))
        for index, device_mode in enumerate(FASTER_DEVICE_MODES):
            self.faster_device_select.setItemText(
                index, self.tr(f"device_{device_mode}")
            )
        self.language_label.setText(self.tr("language"))
        self.language_input.setPlaceholderText(self.tr("language_placeholder"))
        self.output_formats_label.setText(self.tr("output_formats"))
        self.log_label.setText(self.tr("log"))
        self.start_button.setText(self.tr("start"))
        self.stop_button.setText(self.tr("stop"))
        if self._status_key:
            self.progress_label.setText(self.tr(self._status_key, **self._status_values))

    def set_status(self, key: str, style: str = "", **values):
        self._status_key = key
        self._status_values = values
        self.progress_label.setText(self.tr(key, **values))
        self.progress_label.setStyleSheet(style)

    def select_folder(self):
        start_dir = self.folder_path_edit.text()
        if not Path(start_dir).is_dir():
            start_dir = str(BASE_PATH)
        folder = QFileDialog.getExistingDirectory(
            self, self.tr("dialog_select_folder"), start_dir
        )
        if folder:
            self.folder_path_edit.setText(folder)
            self.save_settings()

    def log_message(self, message: str):
        self.log_output.append(message)

    def start_processing(self):
        folder_str = self.folder_path_edit.text().strip()
        backend_name = self.backend_select.currentData()
        is_local_model = self.use_local_model_check.isChecked()
        model = (
            resolved_model_reference(self.local_model_path_edit.text(), True)
            if is_local_model and self.local_model_path_edit.text().strip()
            else self.model_select.currentText()
        )
        language = self.language_input.text().strip() or "auto"
        faster_device_mode = self.faster_device_select.currentData() or "auto"
        faster_compute_type = self.faster_compute_select.currentText() or "auto"
        output_formats = tuple(
            output_format
            for output_format, checkbox in self.output_format_checks.items()
            if checkbox.isChecked()
        )

        if not output_formats:
            QMessageBox.warning(self, self.tr("input_error"), self.tr("select_output_warning"))
            return
        if not folder_str:
            QMessageBox.warning(self, self.tr("input_error"), self.tr("select_folder_warning"))
            return
        folder_path = Path(folder_str)
        if not folder_path.is_dir():
            QMessageBox.warning(
                self, self.tr("input_error"), self.tr("invalid_folder", path=folder_str)
            )
            return
        if is_local_model:
            local_model_error = validate_local_model_path(
                backend_name, self.local_model_path_edit.text(), self.locale_name
            )
            if local_model_error:
                QMessageBox.warning(self, *local_model_error)
                return
        language_error = validate_transcription_language(
            model, language, self.locale_name, is_local_model
        )
        if language_error:
            QMessageBox.warning(self, *language_error)
            return
        dependency_error = check_backend_dependencies(backend_name, self.locale_name)
        if dependency_error:
            QMessageBox.critical(self, *dependency_error)
            return

        self.save_settings()

        self.log_output.clear()
        self.log_message(self.tr("log_base_path", path=BASE_PATH))
        self.log_message(self.tr("log_starting"))
        self.log_message(self.tr("log_folder", path=folder_path))
        self.log_message(
            self.tr("log_backend", backend=backend_display_name(backend_name))
        )
        self.log_message(self.tr("log_model", model=model))
        self.log_message(self.tr("log_language", language=language))
        self.log_message(
            self.tr("log_output_formats", formats=", ".join(fmt.upper() for fmt in output_formats))
        )

        self.set_controls_enabled(False)
        self.set_status("state_initializing")

        self.worker = Worker(
            folder_path,
            model,
            language,
            self.locale_name,
            output_formats=output_formats,
            backend_name=backend_name,
            faster_device_mode=faster_device_mode,
            faster_compute_type=faster_compute_type,
            is_local_model=is_local_model,
        )
        self.worker.progress.connect(self.update_progress)
        self.worker.error_occurred.connect(self.handle_error)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

    def stop_processing(self):
        if self.worker and self.worker.isRunning():
            self.log_message(self.tr("log_stopping"))
            self.worker.stop()
            self.stop_button.setEnabled(False)

    def update_progress(self, text, value):
        self._status_key = None
        self.progress_label.setText(text)
        self.progress_bar.setValue(value)
        self.log_message(text)

    def handle_error(self, error_message):
        self.log_message(self.tr("log_error_prefix", message=error_message))
        self.set_status("state_error", "color: red;")

    def worker_finished(self):
        worker = self.worker
        completion_status = worker.completion_status if worker else "failed"

        if completion_status == "cancelled":
            status_key, log_key, style = "state_stopped", "log_stopped", ""
        elif completion_status == "failed":
            status_key, log_key, style = "state_failed", "log_failed", "color: red;"
        elif completion_status == "completed_with_errors":
            status_key, log_key, style = (
                "state_finished_errors", "log_finished_errors", "color: darkorange;"
            )
            self.progress_bar.setValue(100)
        else:
            status_key, log_key, style = "state_finished", "log_finished", ""
            self.progress_bar.setValue(100)

        self.set_status(status_key, style)
        self.log_message(self.tr(log_key))
        self.set_controls_enabled(True)
        self.worker = None

        if self._close_when_worker_finishes:
            self.close()

    def set_controls_enabled(self, enabled: bool):
        self.start_button.setEnabled(enabled)
        self.select_folder_button.setEnabled(enabled)
        self.folder_path_edit.setEnabled(enabled)
        self.backend_select.setEnabled(enabled)
        self.model_select.setEnabled(enabled)
        self.use_local_model_check.setEnabled(enabled)
        self.update_local_model_controls(enabled)
        self.faster_device_select.setEnabled(enabled)
        self.faster_compute_select.setEnabled(enabled)
        self.language_input.setEnabled(enabled)
        for checkbox in self.output_format_checks.values():
            checkbox.setEnabled(enabled)
        self.stop_button.setEnabled(not enabled)
        # Display language remains available and also updates subsequent worker messages.
        self.display_language_select.setEnabled(True)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            if self._close_when_worker_finishes:
                event.ignore()
                return

            reply = QMessageBox.question(
                self,
                self.tr("confirm_exit"),
                self.tr("confirm_exit_text"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._close_when_worker_finishes = True
                self.stop_processing()
                self.set_status("state_stopping")
                self.log_message(self.tr("log_close_wait"))
            event.ignore()
        else:
            self.save_settings()
            self.settings.setValue("window_geometry", self.saveGeometry())
            self.settings.sync()
            event.accept()


def check_backend_availability(
    backend_name: str, locale_name: str
) -> tuple[str, str] | None:
    if backend_name == BACKEND_OPENAI:
        if whisper is None:
            return (
                translate(locale_name, "startup_error"),
                translate(locale_name, "whisper_missing"),
            )
        return None
    if backend_name == BACKEND_FASTER:
        if FasterWhisperModel is None:
            return (
                translate(locale_name, "startup_error"),
                translate(locale_name, "faster_whisper_missing"),
            )
        return None
    return (
        translate(locale_name, "startup_error"),
        f"Unsupported Whisper backend: {backend_name}",
    )


def check_backend_dependencies(
    backend_name: str, locale_name: str
) -> tuple[str, str] | None:
    availability_error = check_backend_availability(backend_name, locale_name)
    if availability_error:
        return availability_error
    if backend_name == BACKEND_OPENAI and shutil.which("ffmpeg") is None:
        return (
            translate(locale_name, "startup_error"),
            translate(locale_name, "startup_ffmpeg_missing"),
        )
    return None


def check_runtime_dependencies(
    locale_name: str, backend_name: str = DEFAULT_BACKEND
) -> tuple[str, str] | None:
    """Backward-compatible alias for callers that check before starting work."""
    return check_backend_dependencies(backend_name, locale_name)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = App()
    window.show()
    sys.exit(app.exec())
