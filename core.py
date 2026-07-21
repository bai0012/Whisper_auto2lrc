"""Qt-free transcription core shared by the desktop UI and REST API."""

from __future__ import annotations

import csv
import gc
import io
import json
import os
import sys
import tempfile
import threading
import traceback
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Callable

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


AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".mkv", ".mp4"}
OUTPUT_FORMATS = ("lrc", "srt", "vtt", "txt", "tsv", "json")
BACKEND_OPENAI = "openai-whisper"
BACKEND_FASTER = "faster-whisper"
DEFAULT_BACKEND = BACKEND_OPENAI
BACKEND_MODELS = {
    BACKEND_OPENAI: (
        "tiny",
        "tiny.en",
        "base",
        "base.en",
        "small",
        "small.en",
        "medium",
        "medium.en",
        "large-v1",
        "large-v2",
        "large-v3",
        "large",
        "large-v3-turbo",
        "turbo",
    ),
    BACKEND_FASTER: (
        "tiny",
        "tiny.en",
        "base",
        "base.en",
        "small",
        "small.en",
        "distil-small.en",
        "medium",
        "medium.en",
        "distil-medium.en",
        "large-v1",
        "large-v2",
        "large-v3",
        "large",
        "distil-large-v2",
        "distil-large-v3",
        "distil-large-v3.5",
        "large-v3-turbo",
        "turbo",
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
    "af",
    "am",
    "ar",
    "as",
    "az",
    "ba",
    "be",
    "bg",
    "bn",
    "bo",
    "br",
    "bs",
    "ca",
    "cs",
    "cy",
    "da",
    "de",
    "el",
    "en",
    "es",
    "et",
    "eu",
    "fa",
    "fi",
    "fo",
    "fr",
    "gl",
    "gu",
    "ha",
    "haw",
    "he",
    "hi",
    "hr",
    "ht",
    "hu",
    "hy",
    "id",
    "is",
    "it",
    "ja",
    "jw",
    "ka",
    "kk",
    "km",
    "kn",
    "ko",
    "la",
    "lb",
    "ln",
    "lo",
    "lt",
    "lv",
    "mg",
    "mi",
    "mk",
    "ml",
    "mn",
    "mr",
    "ms",
    "mt",
    "my",
    "ne",
    "nl",
    "nn",
    "no",
    "oc",
    "pa",
    "pl",
    "ps",
    "pt",
    "ro",
    "ru",
    "sa",
    "sd",
    "si",
    "sk",
    "sl",
    "sn",
    "so",
    "sq",
    "sr",
    "su",
    "sv",
    "sw",
    "ta",
    "te",
    "tg",
    "th",
    "tk",
    "tl",
    "tr",
    "tt",
    "uk",
    "ur",
    "uz",
    "vi",
    "yi",
    "yo",
    "yue",
    "zh",
}


def resolved_model_reference(model_name: str, is_local_model: bool) -> str:
    return (
        str(Path(model_name).expanduser().resolve()) if is_local_model else model_name
    )


def validate_language(
    model_name: str, language: str, is_local_model: bool = False
) -> str | None:
    normalized = language.strip().lower()
    if not normalized or normalized == "auto":
        return None
    if normalized not in SUPPORTED_LANGUAGE_CODES:
        return f"Unsupported transcription language code: {normalized}"
    if not is_local_model and model_name in ENGLISH_ONLY_MODELS and normalized != "en":
        return f"Model '{model_name}' only supports English; language '{normalized}' is not valid."
    return None


def validate_local_model(backend_name: str, model_path: str) -> str | None:
    path = Path(model_path).expanduser().resolve()
    if not model_path.strip():
        return "Please select a local model path."
    if backend_name == BACKEND_OPENAI and not path.is_file():
        return f"The OpenAI Whisper local model must be a checkpoint file:\n{path}"
    if backend_name == BACKEND_FASTER and not path.is_dir():
        return f"The Faster Whisper local model must be a CTranslate2 model directory:\n{path}"
    return None


def format_lrc_time(seconds: float) -> str:
    value = Decimal(str(seconds))
    if value < 0:
        raise ValueError("non-negative timestamp expected")
    centiseconds = int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))
    minutes, remainder = divmod(centiseconds, 6_000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f"{minutes:02d}:{whole_seconds:02d}.{fraction:02d}"


def normalize_segment_text(raw_text) -> str:
    return " ".join(str(raw_text).split()) if raw_text else ""


def timestamped_segments(result: dict):
    for segment in result.get("segments", []):
        text = normalize_segment_text(segment.get("text"))
        if text:
            yield segment, text


def generate_lrc_content(result: dict) -> str:
    lines = [
        f"[{format_lrc_time(s['start'])}]{text}"
        for s, text in timestamped_segments(result)
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def format_subtitle_time(seconds: float, separator: str = ",") -> str:
    value = Decimal(str(seconds))
    if value < 0:
        raise ValueError("non-negative timestamp expected")
    milliseconds = int((value * 1_000).to_integral_value(rounding=ROUND_HALF_UP))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, fraction = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{fraction:03d}"


def generate_srt_content(result: dict) -> str:
    blocks = []
    for index, (segment, text) in enumerate(timestamped_segments(result), 1):
        start = format_subtitle_time(segment["start"], ",")
        end = format_subtitle_time(segment["end"], ",")
        blocks.append(f"{index}\n{start} --> {end}\n{text.replace('-->', '->')}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def generate_vtt_content(result: dict) -> str:
    blocks = []
    for segment, text in timestamped_segments(result):
        start = format_subtitle_time(segment["start"], ".")
        end = format_subtitle_time(segment["end"], ".")
        blocks.append(f"{start} --> {end}\n{text.replace('-->', '->')}")
    return "WEBVTT\n\n" + "\n\n".join(blocks) + ("\n" if blocks else "")


def generate_txt_content(result: dict) -> str:
    lines = [text for _segment, text in timestamped_segments(result)]
    return "\n".join(lines) + ("\n" if lines else "")


def generate_tsv_content(result: dict) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(("start", "end", "text"))
    for segment, text in timestamped_segments(result):
        start = int(
            (Decimal(str(segment["start"])) * 1_000).to_integral_value(ROUND_HALF_UP)
        )
        end = int(
            (Decimal(str(segment["end"])) * 1_000).to_integral_value(ROUND_HALF_UP)
        )
        writer.writerow((start, end, text))
    return output.getvalue()


def generate_output_content(output_format: str, result: dict) -> str:
    generators = {
        "lrc": generate_lrc_content,
        "srt": generate_srt_content,
        "vtt": generate_vtt_content,
        "txt": generate_txt_content,
        "tsv": generate_tsv_content,
        "json": lambda value: json.dumps(value, ensure_ascii=False, indent=2) + "\n",
    }
    try:
        return generators[output_format](result)
    except KeyError as error:
        raise ValueError(f"unsupported output format: {output_format}") from error


def write_text_atomically(target_path: Path, content: str) -> None:
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


def discover_audio_tasks(
    folder_path: Path,
    output_formats,
    stop_requested: Callable[[], bool] | None = None,
) -> tuple[list, list]:
    candidates = []
    for path in folder_path.rglob("*"):
        if stop_requested is not None and stop_requested():
            break
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
            candidates.append(path)
    candidates.sort(key=lambda path: (str(path).casefold(), str(path)))
    by_base = {}
    for audio_file in candidates:
        base = audio_file.with_suffix("")
        if any(
            not audio_file.with_suffix(f".{fmt}").exists() for fmt in output_formats
        ):
            by_base.setdefault(base, []).append(audio_file)
    tasks, conflicts = [], []
    for base, sources in sorted(
        by_base.items(), key=lambda item: (str(item[0]).casefold(), str(item[0]))
    ):
        if len(sources) > 1:
            conflicts.append((base, tuple(sources)))
        else:
            audio_file = sources[0]
            missing = tuple(
                fmt
                for fmt in output_formats
                if not audio_file.with_suffix(f".{fmt}").exists()
            )
            tasks.append((audio_file, missing))
    return tasks, conflicts


def faster_whisper_runtime(
    device_mode: str = "auto", compute_type: str = "auto"
) -> tuple[str, str]:
    if device_mode not in FASTER_DEVICE_MODES:
        raise ValueError(f"unsupported Faster Whisper device: {device_mode}")
    if device_mode != "auto":
        legal = FASTER_COMPUTE_TYPES[device_mode]
        resolved = legal[0] if compute_type == "auto" else compute_type
        if resolved not in legal:
            raise ValueError(
                f"compute type '{resolved}' is not valid for {device_mode}"
            )
        return device_mode, resolved
    try:
        has_cuda = bool(
            ctranslate2 is not None
            and getattr(ctranslate2, "get_cuda_device_count", lambda: 0)() > 0
        )
    except Exception:
        has_cuda = False
    return ("cuda", "float16") if has_cuda else ("cpu", "int8")


def release_unused_model_memory() -> None:
    gc.collect()
    torch_module = sys.modules.get("torch")
    try:
        if torch_module is not None and torch_module.cuda.is_available():
            torch_module.cuda.empty_cache()
    except Exception:
        pass


class OpenAIWhisperBackend:
    name = BACKEND_OPENAI

    def cache_key(self, model_name: str, is_local_model: bool = False):
        return self.name, resolved_model_reference(model_name, is_local_model)

    def load_model(self, model_name: str, is_local_model: bool = False):
        if whisper is None:
            raise RuntimeError("Could not import 'whisper'.")
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
        self.device, self.compute_type = "cpu", "int8"

    def cache_key(self, model_name: str, is_local_model: bool = False):
        return (
            self.name,
            resolved_model_reference(model_name, is_local_model),
            self.device,
            self.compute_type,
        )

    def load_model(self, model_name: str, is_local_model: bool = False):
        if FasterWhisperModel is None:
            raise RuntimeError("Could not import 'faster_whisper'.")
        options = {"device": self.device, "compute_type": self.compute_type}
        if is_local_model:
            options["local_files_only"] = True
        return FasterWhisperModel(
            resolved_model_reference(model_name, is_local_model), **options
        )

    def transcribe(self, model, audio_file: Path, language: str | None) -> dict:
        segments, info = model.transcribe(str(audio_file), language=language)
        normalized, text_parts = [], []
        for segment in segments:
            text = str(segment.text)
            text_parts.append(text)
            normalized.append(
                {"start": float(segment.start), "end": float(segment.end), "text": text}
            )
        return {
            "text": "".join(text_parts).strip(),
            "segments": normalized,
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
    def __init__(self):
        self._lock = threading.Lock()
        self._model_name = None
        self._model = None

    def get_or_load(self, model_name, loader):
        with self._lock:
            if self._model_name == model_name and self._model is not None:
                return self._model, True
            previous_model = self._model
            self._model_name = self._model = None
            del previous_model
            release_unused_model_memory()
            try:
                model = loader(model_name)
            except Exception:
                release_unused_model_memory()
                raise
            self._model_name, self._model = model_name, model
            return model, False

    def clear(self):
        with self._lock:
            previous_model = self._model
            self._model_name = self._model = None
            del previous_model
            release_unused_model_memory()


WHISPER_MODEL_CACHE = ModelCache()


CORE_MESSAGES = {
    "en": {
        "cancelled": "Processing cancelled.",
        "no_unambiguous": "No unambiguous audio files found; conflicts were skipped.",
        "no_new_files": "No new audio files found to process.",
        "found_files": "Found {count} files to process...",
        "processing": "Processing: {name} ({current}/{total})",
        "loading_model": "Loading {backend} model: {model}...",
        "using_cached_model": "Using cached {backend} model: {model}.",
        "model_loaded": "{backend} model '{model}' loaded and cached.",
        "model_load_failed": "Failed to load {backend} model '{model}': {error}",
        "faster_device": "Faster Whisper runtime: {device} / {compute_type}.",
        "faster_cpu_fallback": "CUDA model loading failed ({error}). Auto mode is retrying once with CPU / int8.",
        "conflict": "Multiple media files map to the same output name; all were skipped:\nOutput base: {target}\nSources:\n{sources}",
        "empty_result": "Whisper produced no timestamped text for {name}.",
        "target_appeared": "Skipped existing output for {source}: {target}",
        "processing_error": "Error processing {name}: {error}\n{traceback}",
        "worker_error": "An unexpected error occurred in worker setup: {error}\n{traceback}",
    },
    "zh_CN": {
        "cancelled": "处理已取消。",
        "no_unambiguous": "未找到无冲突的音频文件；冲突文件已跳过。",
        "no_new_files": "没有需要处理的新音频文件。",
        "found_files": "找到 {count} 个待处理文件...",
        "processing": "正在处理：{name}（{current}/{total}）",
        "loading_model": "正在加载 {backend} 模型：{model}...",
        "using_cached_model": "正在使用已缓存的 {backend} 模型：{model}。",
        "model_loaded": "{backend} 模型“{model}”已加载并缓存。",
        "model_load_failed": "无法加载 {backend} 模型“{model}”：{error}",
        "faster_device": "Faster Whisper 运行配置：{device} / {compute_type}。",
        "faster_cpu_fallback": "CUDA 模型加载失败（{error}）。自动模式将使用 CPU / int8 重试一次。",
        "conflict": "多个媒体文件对应同一个输出名称，已全部跳过：\n输出基础名称：{target}\n来源：\n{sources}",
        "empty_result": "Whisper 没有为 {name} 生成带时间戳的文本。",
        "target_appeared": "已跳过 {source} 的现有输出：{target}",
        "processing_error": "处理 {name} 时出错：{error}\n{traceback}",
        "worker_error": "工作线程初始化时发生意外错误：{error}\n{traceback}",
    },
}


def core_message_formatter(locale_name: str = "en") -> Callable[..., str]:
    locale = "zh_CN" if locale_name.lower().replace("-", "_").startswith("zh") else "en"

    def format_message(key: str, **values) -> str:
        return CORE_MESSAGES[locale][key].format(**values)

    return format_message


class TranscriptionRunner:
    """Synchronous, framework-free folder transcription runner."""

    def __init__(
        self,
        folder_path: Path,
        model_name: str,
        language: str,
        output_formats=None,
        backend_name: str = DEFAULT_BACKEND,
        faster_device_mode: str = "auto",
        faster_compute_type: str = "auto",
        is_local_model: bool = False,
        progress_callback: Callable[[str, int], None] | None = None,
        error_callback: Callable[[str], None] | None = None,
        message_formatter: Callable[..., str] | None = None,
    ):
        self.folder_path = Path(folder_path)
        self.model_name = model_name
        self.is_local_model = is_local_model
        self.backend_name = backend_name
        self.backend = create_backend(
            backend_name, faster_device_mode, faster_compute_type
        )
        normalized = language.strip().lower() if language else ""
        self.language = normalized if normalized and normalized != "auto" else None
        selected = output_formats if output_formats is not None else ("lrc",)
        self.output_formats = tuple(fmt for fmt in OUTPUT_FORMATS if fmt in selected)
        self.progress_callback = progress_callback or (lambda _message, _value: None)
        self.error_callback = error_callback or (lambda _message: None)
        self.message_formatter = message_formatter or self._default_message
        self._stop_event = threading.Event()
        self._last_progress = 0
        self.completion_status = "running"
        self.had_errors = False
        self.whisper_model = None

    @staticmethod
    def _default_message(key: str, **values) -> str:
        return CORE_MESSAGES["en"][key].format(**values)

    def message(self, key: str, **values) -> str:
        return self.message_formatter(key, **values)

    def emit_progress(self, message: str, value: int) -> None:
        value = max(self._last_progress, min(100, max(0, int(value))))
        self._last_progress = value
        self.progress_callback(message, value)

    def report_error(self, message: str) -> None:
        self.had_errors = True
        self.error_callback(message)

    def stop(self) -> None:
        self._stop_event.set()

    def _load_model(self):
        label = backend_display_name(self.backend_name)
        if isinstance(self.backend, FasterWhisperBackend):
            self.emit_progress(
                self.message(
                    "faster_device",
                    device=self.backend.device,
                    compute_type=self.backend.compute_type,
                ),
                0,
            )
        self.emit_progress(
            self.message("loading_model", backend=label, model=self.model_name), 0
        )
        try:
            return WHISPER_MODEL_CACHE.get_or_load(
                self.backend.cache_key(self.model_name, self.is_local_model),
                lambda _key: self.backend.load_model(
                    self.model_name, self.is_local_model
                ),
            )
        except Exception as error:
            if (
                not isinstance(self.backend, FasterWhisperBackend)
                or not self.backend.can_fallback_to_cpu
            ):
                raise
            self.emit_progress(self.message("faster_cpu_fallback", error=error), 0)
            self.backend.fallback_to_cpu()
            self.emit_progress(
                self.message(
                    "faster_device",
                    device=self.backend.device,
                    compute_type=self.backend.compute_type,
                ),
                0,
            )
            return WHISPER_MODEL_CACHE.get_or_load(
                self.backend.cache_key(self.model_name, self.is_local_model),
                lambda _key: self.backend.load_model(
                    self.model_name, self.is_local_model
                ),
            )

    def run(self) -> str:
        try:
            if not self.folder_path.is_dir():
                self.report_error(
                    f"Audio folder is not an existing directory: {self.folder_path}"
                )
                self.completion_status = "failed"
                return self.completion_status
            if not self.output_formats:
                self.report_error("At least one output format is required.")
                self.completion_status = "failed"
                return self.completion_status
            language_error = validate_language(
                self.model_name, self.language or "auto", self.is_local_model
            )
            if language_error:
                self.report_error(language_error)
                self.completion_status = "failed"
                return self.completion_status
            if self._stop_event.is_set():
                self.emit_progress(self.message("cancelled"), 0)
                self.completion_status = "cancelled"
                return self.completion_status
            tasks, conflicts = discover_audio_tasks(
                self.folder_path, self.output_formats, self._stop_event.is_set
            )
            if self._stop_event.is_set():
                self.emit_progress(self.message("cancelled"), 0)
                self.completion_status = "cancelled"
                return self.completion_status
            for output_base, sources in conflicts:
                source_list = "\n".join(f"- {source}" for source in sources)
                self.report_error(
                    self.message("conflict", target=output_base, sources=source_list)
                )
            total = len(tasks)
            if total == 0:
                self.emit_progress(
                    self.message(
                        "no_unambiguous" if self.had_errors else "no_new_files"
                    ),
                    100,
                )
                self.completion_status = (
                    "completed_with_errors" if self.had_errors else "completed"
                )
                return self.completion_status
            label = backend_display_name(self.backend_name)
            try:
                self.whisper_model, cache_hit = self._load_model()
            except Exception as error:
                self.report_error(
                    self.message(
                        "model_load_failed",
                        backend=label,
                        model=self.model_name,
                        error=error,
                    )
                )
                self.completion_status = "failed"
                return self.completion_status
            self.emit_progress(
                self.message(
                    "using_cached_model" if cache_hit else "model_loaded",
                    backend=label,
                    model=self.model_name,
                ),
                0,
            )
            self.emit_progress(self.message("found_files", count=total), 0)
            for index, (audio_file, missing_formats) in enumerate(tasks):
                if self._stop_event.is_set():
                    self.emit_progress(
                        self.message("cancelled"), int(index / total * 100)
                    )
                    break
                progress_text = self.message(
                    "processing", name=audio_file.name, current=index + 1, total=total
                )
                self.emit_progress(progress_text, int(index / total * 100))
                try:
                    result = self.backend.transcribe(
                        self.whisper_model, audio_file, self.language
                    )
                    if not any(timestamped_segments(result)):
                        self.report_error(
                            self.message("empty_result", name=audio_file.name)
                        )
                    else:
                        for output_format in missing_formats:
                            target = audio_file.with_suffix(f".{output_format}")
                            try:
                                if not write_text_exclusively(
                                    target,
                                    generate_output_content(output_format, result),
                                ):
                                    self.report_error(
                                        self.message(
                                            "target_appeared",
                                            source=audio_file,
                                            target=target,
                                        )
                                    )
                            except Exception as error:
                                self.report_error(
                                    self.message(
                                        "processing_error",
                                        name=f"{audio_file.name} -> {output_format.upper()}",
                                        error=error,
                                        traceback=traceback.format_exc(),
                                    )
                                )
                except Exception as error:
                    self.report_error(
                        self.message(
                            "processing_error",
                            name=audio_file.name,
                            error=error,
                            traceback=traceback.format_exc(),
                        )
                    )
                finally:
                    # Every visited task advances exactly once, including empty/error cases.
                    self.emit_progress(progress_text, int((index + 1) / total * 100))
            if self._stop_event.is_set():
                self.completion_status = "cancelled"
            elif self.had_errors:
                self.completion_status = "completed_with_errors"
            else:
                self.completion_status = "completed"
            return self.completion_status
        except Exception as error:
            self.report_error(
                self.message(
                    "worker_error", error=error, traceback=traceback.format_exc()
                )
            )
            self.completion_status = "failed"
            return self.completion_status
