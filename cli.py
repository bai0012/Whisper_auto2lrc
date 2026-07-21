"""Command-line adapter for the framework-free transcription core."""

from __future__ import annotations

import argparse
import json
import locale as system_locale
import os
import signal
import sys
import threading
from pathlib import Path

import core
from version import __version__

EXIT_CODES = {"completed": 0, "completed_with_errors": 1, "failed": 3}

CLI_MESSAGES = {
    "en": {
        "invalid_folder": "Folder is not an existing directory: {path}",
        "empty_language": "--language cannot be empty",
        "empty_model": "--model cannot be empty",
        "unsupported_model": "Unsupported model for {backend}: {model}",
        "faster_options": "--device and --compute-type are Faster Whisper options",
        "unsupported_compute": "Unsupported compute type for {device}: {compute_type}",
        "local_model_required": "Please select a local model path.",
        "openai_local_model": "The OpenAI Whisper local model must be a checkpoint file:\n{path}",
        "faster_local_model": "The Faster Whisper local model must be a CTranslate2 model directory:\n{path}",
        "unsupported_language": "Unsupported transcription language code: {language}",
        "english_only": "Model '{model}' only supports English; language '{language}' is not valid.",
        "whisper_missing": "Could not import 'whisper'. Install openai-whisper.",
        "ffmpeg_missing": "FFmpeg was not found in the system PATH.",
        "faster_whisper_missing": "Could not import 'faster_whisper'. Install faster-whisper.",
        "invalid_status": "Runner returned an invalid completion status: {status}",
    },
    "zh_CN": {
        "invalid_folder": "文件夹不存在或不是目录：{path}",
        "empty_language": "--language 不能为空",
        "empty_model": "--model 不能为空",
        "unsupported_model": "后端 {backend} 不支持模型：{model}",
        "faster_options": "--device 和 --compute-type 仅适用于 Faster Whisper",
        "unsupported_compute": "设备 {device} 不支持计算精度：{compute_type}",
        "local_model_required": "请选择本地模型路径。",
        "openai_local_model": "OpenAI Whisper 本地模型必须是权重文件：\n{path}",
        "faster_local_model": "Faster Whisper 本地模型必须是 CTranslate2 模型目录：\n{path}",
        "unsupported_language": "不支持的转录语言代码：{language}",
        "english_only": "模型“{model}”仅支持英语，不能使用语言“{language}”。",
        "whisper_missing": "无法导入“whisper”，请安装 openai-whisper。",
        "ffmpeg_missing": "系统 PATH 中未找到 FFmpeg。",
        "faster_whisper_missing": "无法导入“faster_whisper”，请安装 faster-whisper。",
        "invalid_status": "核心返回了无效的完成状态：{status}",
    },
}


class ForcedTermination(BaseException):
    def __init__(self, signum: int):
        self.signum = signum


class OutputError(RuntimeError):
    """Raised when a reporter cannot honor its output protocol."""


class Reporter:
    def __init__(self, mode, locale_name, stdout, stderr, no_color=False):
        self.mode, self.locale = mode, locale_name
        self.stdout, self.stderr = stdout, stderr
        self.error_count = 0
        self.progress_value = 0
        self.tty = getattr(stderr, "isatty", lambda: False)()
        self.color = bool(not no_color and "NO_COLOR" not in os.environ and self.tty)
        self._progress_line_active = False
        self._progress_width = 0

    def _json(self, event):
        payload = (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
        target = getattr(self.stdout, "buffer", self.stdout)
        try:
            target.write(payload)
        except TypeError:
            try:
                target.write(payload.decode("utf-8"))
            except Exception as error:
                raise OutputError(str(error)) from error
        except Exception as error:
            raise OutputError(str(error)) from error
        try:
            target.flush()
        except Exception as error:
            raise OutputError(str(error)) from error

    def _print(self, *values, **options):
        try:
            print(*values, file=self.stderr, **options)
        except Exception as error:
            raise OutputError(str(error)) from error

    def progress(self, message, value):
        self.progress_value = max(self.progress_value, max(0, min(100, int(value))))
        if self.mode == "json":
            self._json(
                {
                    "type": "progress",
                    "progress": self.progress_value,
                    "message": str(message),
                }
            )
        elif self.mode == "text":
            line = f"[{self.progress_value:3d}%] {message}"
            if self.tty:
                width = max(self._progress_width, len(line))
                self._print(
                    f"\r{line:<{width}}",
                    end="",
                    flush=True,
                )
                self._progress_width = width
                self._progress_line_active = True
            else:
                self._print(line, flush=True)

    def _finish_progress_line(self):
        if self._progress_line_active:
            self._print(flush=True)
            self._progress_line_active = False
            self._progress_width = 0

    def error(self, message):
        self.error_count += 1
        if self.mode == "json":
            self._json(
                {
                    "type": "error",
                    "progress": self.progress_value,
                    "message": str(message),
                }
            )
        else:
            self._finish_progress_line()
            prefix = "错误：" if self.locale == "zh_CN" else "ERROR:"
            if self.color:
                prefix = f"\033[31m{prefix}\033[0m"
            self._print(f"{prefix} {message}", flush=True)

    def result(self, status):
        event = {
            "type": "result",
            "status": status,
            "progress": self.progress_value,
            "error_count": self.error_count,
        }
        if self.mode == "json":
            self._json(event)
        else:
            self._finish_progress_line()
            labels = {
                "zh_CN": {
                    "completed": "完成",
                    "invalid_arguments": "参数无效",
                    "failed": "失败",
                    "cancelled": "已取消",
                },
                "en": {
                    "completed": "Completed",
                    "invalid_arguments": "Invalid arguments",
                    "failed": "Failed",
                    "cancelled": "Cancelled",
                },
            }
            label = labels[self.locale].get(status, status.replace("_", " ").title())
            self._print(
                f"{label}: status={status} progress={self.progress_value} errors={self.error_count}",
                flush=True,
            )


def build_parser():
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Recursively transcribe a folder with a shared Whisper core.",
        epilog=(
            "Examples:\n"
            "  python cli.py transcribe ./audio -f lrc -f srt\n"
            "  python cli.py transcribe ./audio --backend faster-whisper --device cpu\n"
            "  python cli.py capabilities --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=__version__, help="show version and exit"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    transcribe = commands.add_parser(
        "transcribe", help="transcribe all supported media in a folder"
    )
    transcribe.add_argument("folder", help="folder to scan recursively")
    transcribe.add_argument(
        "--backend",
        choices=tuple(core.BACKEND_MODELS),
        default=core.DEFAULT_BACKEND,
        help=f"transcription backend (default: {core.DEFAULT_BACKEND})",
    )
    models = transcribe.add_mutually_exclusive_group()
    models.add_argument(
        "--model", help="built-in model name (backend default if omitted)"
    )
    models.add_argument(
        "--local-model", metavar="PATH", help="local checkpoint file or model directory"
    )
    transcribe.add_argument(
        "-l",
        "--language",
        default="auto",
        help="Whisper language code or auto (default: auto)",
    )
    transcribe.add_argument(
        "-f",
        "--format",
        dest="formats",
        action="append",
        choices=core.OUTPUT_FORMATS,
        default=None,
        help="output format; repeat for multiple formats (default: lrc)",
    )
    transcribe.add_argument(
        "--locale",
        choices=("auto", "en", "zh_CN"),
        default="auto",
        help="CLI message language (default: auto)",
    )
    transcribe.add_argument(
        "--device",
        choices=core.FASTER_DEVICE_MODES,
        default="auto",
        help="Faster Whisper device (default: auto)",
    )
    transcribe.add_argument(
        "--compute-type", default="auto", help="Faster Whisper compute type"
    )
    transcribe.add_argument(
        "--output-mode",
        choices=("text", "quiet", "json"),
        default="text",
        help="terminal output protocol (default: text)",
    )
    transcribe.add_argument(
        "--no-color", action="store_true", help="disable ANSI colors"
    )
    capability = commands.add_parser(
        "capabilities", help="show supported backends, models, and formats"
    )
    capability.add_argument(
        "--json", action="store_true", help="write strict UTF-8 JSON"
    )
    return parser


def _locale(value):
    if value != "auto":
        return value
    detected = system_locale.getlocale()[0] or ""
    return "zh_CN" if detected.lower().replace("-", "_").startswith("zh") else "en"


def _message(locale_name, key, **values):
    return CLI_MESSAGES[locale_name][key].format(**values)


def _localized_runtime_error(locale_name, error):
    runtime_keys = {
        core.BACKEND_RUNTIME_ERRORS["whisper_missing"]: "whisper_missing",
        core.BACKEND_RUNTIME_ERRORS["ffmpeg_missing"]: "ffmpeg_missing",
        core.BACKEND_RUNTIME_ERRORS["faster_whisper_missing"]: (
            "faster_whisper_missing"
        ),
    }
    key = runtime_keys.get(error)
    return _message(locale_name, key) if key else error


def _localized_local_model_error(locale_name, backend, model):
    error = core.validate_local_model(backend, model)
    if error is None or locale_name == "en":
        return error
    if not model.strip():
        return _message(locale_name, "local_model_required")
    resolved = Path(model).expanduser().resolve()
    key = (
        "openai_local_model" if backend == core.BACKEND_OPENAI else "faster_local_model"
    )
    return _message(locale_name, key, path=resolved)


def _localized_language_error(locale_name, model, language, is_local):
    error = core.validate_language(model, language, is_local)
    if error is None or locale_name == "en":
        return error
    normalized = language.strip().lower()
    if normalized not in core.SUPPORTED_LANGUAGE_CODES:
        return _message(locale_name, "unsupported_language", language=normalized)
    return _message(locale_name, "english_only", model=model, language=normalized)


def _semantic_error(reporter, message):
    reporter.error(message)
    reporter.result("invalid_arguments")
    return 2


def run_capabilities(args, stdout):
    data = core.capabilities()
    if args.json:
        payload = (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")
        target = getattr(stdout, "buffer", stdout)
        try:
            target.write(payload)
        except TypeError:
            target.write(payload.decode("utf-8"))
        target.flush()
    else:
        print("Backends:", file=stdout)
        for name, details in data["backends"].items():
            print(f"  {name} (default model: {details['default_model']})", file=stdout)
        print(f"Formats: {', '.join(data['formats'])}", file=stdout)
        print(f"Devices: {', '.join(data['faster_whisper']['devices'])}", file=stdout)
    return 0


def _safe_fatal(stderr, error):
    try:
        print(f"ERROR: {error}", file=stderr, flush=True)
    except Exception:
        pass


def _cancel_exit_code(signum, signal_module):
    if signum is None:
        signum = signal_module.SIGINT
    return 130 if signum == signal_module.SIGINT else 128 + int(signum)


def _finish_cancelled(reporter, signum, signal_module):
    reporter.result("cancelled")
    return _cancel_exit_code(signum, signal_module)


def _prepare_transcription(args, reporter, locale_name, stop_event):
    if stop_event.is_set():
        return None
    if not args.folder.strip():
        return _semantic_error(
            reporter, _message(locale_name, "invalid_folder", path=args.folder)
        )
    folder = Path(args.folder).expanduser().resolve()
    if stop_event.is_set():
        return None
    folder_is_dir = folder.is_dir()
    if stop_event.is_set():
        return None
    if not folder_is_dir:
        return _semantic_error(
            reporter, _message(locale_name, "invalid_folder", path=folder)
        )
    if not args.language.strip():
        return _semantic_error(reporter, _message(locale_name, "empty_language"))
    if args.model is not None and not args.model.strip():
        return _semantic_error(reporter, _message(locale_name, "empty_model"))
    is_local = args.local_model is not None
    model = (
        args.local_model
        if is_local
        else (
            args.model
            if args.model is not None
            else core.BACKEND_DEFAULT_MODELS[args.backend]
        )
    )
    if is_local:
        error = _localized_local_model_error(locale_name, args.backend, model)
        if stop_event.is_set():
            return None
        if error:
            return _semantic_error(reporter, error)
        model = core.resolved_model_reference(model, True)
    elif model not in core.BACKEND_MODELS[args.backend]:
        return _semantic_error(
            reporter,
            _message(
                locale_name,
                "unsupported_model",
                backend=args.backend,
                model=model,
            ),
        )
    language_error = _localized_language_error(
        locale_name, model, args.language, is_local
    )
    if stop_event.is_set():
        return None
    if language_error:
        return _semantic_error(reporter, language_error)
    if args.backend == core.BACKEND_OPENAI and (
        args.device != "auto" or args.compute_type != "auto"
    ):
        return _semantic_error(reporter, _message(locale_name, "faster_options"))
    allowed = core.FASTER_COMPUTE_TYPES.get(args.device, ())
    if args.compute_type != "auto" and args.compute_type not in allowed:
        return _semantic_error(
            reporter,
            _message(
                locale_name,
                "unsupported_compute",
                device=args.device,
                compute_type=args.compute_type,
            ),
        )
    dependency_error = core.validate_backend_runtime(args.backend)
    if stop_event.is_set():
        return None
    if dependency_error:
        reporter.error(_localized_runtime_error(locale_name, dependency_error))
        reporter.result("failed")
        return 3
    formats = tuple(dict.fromkeys(args.formats or ["lrc"]))
    return {
        "folder": folder,
        "model": model,
        "is_local": is_local,
        "formats": formats,
    }


def run_transcribe(args, runner_factory, stdout, stderr, signal_module=signal):
    locale_name = _locale(args.locale)
    reporter = Reporter(args.output_mode, locale_name, stdout, stderr, args.no_color)
    first_signal = {"value": None}
    runner_holder = {"value": None}
    stop_event = threading.Event()

    def handle_signal(signum, _frame):
        if first_signal["value"] is not None:
            if signum == getattr(signal_module, "SIGINT", 2):
                raise KeyboardInterrupt
            raise ForcedTermination(signum)
        first_signal["value"] = signum
        stop_event.set()
        if runner_holder["value"] is not None:
            runner_holder["value"].stop()

    previous = {}
    try:
        watched = [signal_module.SIGINT]
        if hasattr(signal_module, "SIGTERM"):
            watched.append(signal_module.SIGTERM)
        for watched_signal in watched:
            previous[watched_signal] = signal_module.signal(
                watched_signal, handle_signal
            )

        prepared = _prepare_transcription(args, reporter, locale_name, stop_event)
        if prepared is None:
            return _finish_cancelled(reporter, first_signal["value"], signal_module)
        if isinstance(prepared, int):
            return prepared

        runner = runner_factory(
            folder_path=prepared["folder"],
            model_name=prepared["model"],
            language=args.language,
            output_formats=prepared["formats"],
            backend_name=args.backend,
            faster_device_mode=args.device,
            faster_compute_type=args.compute_type,
            is_local_model=prepared["is_local"],
            progress_callback=reporter.progress,
            error_callback=reporter.error,
            message_formatter=core.core_message_formatter(locale_name),
        )
        runner_holder["value"] = runner
        if stop_event.is_set():
            runner.stop()
        run_status = runner.run()
        status = (
            "cancelled"
            if first_signal["value"] is not None
            else getattr(runner, "completion_status", run_status)
        )
        if status == "cancelled":
            return _finish_cancelled(reporter, first_signal["value"], signal_module)
        if status not in EXIT_CODES:
            reporter.error(_message(locale_name, "invalid_status", status=status))
            reporter.result("failed")
            return 70
        reporter.result(status)
        return EXIT_CODES[status]
    except OutputError as error:
        _safe_fatal(stderr, f"output failure: {error}")
        return 70
    except KeyboardInterrupt:
        return 130
    except ForcedTermination as error:
        return 128 + error.signum
    except Exception as error:
        try:
            reporter.error(str(error))
            if first_signal["value"] is not None:
                return _finish_cancelled(reporter, first_signal["value"], signal_module)
            reporter.result("failed")
            return 70
        except OutputError as output_error:
            _safe_fatal(stderr, f"output failure: {output_error}")
            return 70
    finally:
        for sig, handler in previous.items():
            signal_module.signal(sig, handler)


def main(
    argv=None, *, runner_factory=None, stdout=None, stderr=None, signal_module=signal
):
    stdout, stderr = stdout or sys.stdout, stderr or sys.stderr
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)
    if args.command == "capabilities":
        try:
            return run_capabilities(args, stdout)
        except Exception as error:
            _safe_fatal(stderr, error)
            return 70
    return run_transcribe(
        args, runner_factory or core.TranscriptionRunner, stdout, stderr, signal_module
    )


if __name__ == "__main__":
    raise SystemExit(main())
