import io
import json
import subprocess
import sys

import pytest

import cli
import core
from version import __version__


class Runner:
    status = "completed"
    kwargs = None

    def __init__(self, **kwargs):
        type(self).kwargs = kwargs
        self.completion_status = self.status
        self.stopped = False

    def run(self):
        self.kwargs["progress_callback"]("工作中", 100)
        return self.completion_status

    def stop(self):
        self.stopped = True


class FakeSignal:
    SIGINT = 2
    SIGTERM = 15

    def __init__(self):
        self.originals = {
            self.SIGINT: object(),
            self.SIGTERM: object(),
        }
        self.handlers = dict(self.originals)

    def signal(self, signum, handler):
        previous = self.handlers.get(signum)
        self.handlers[signum] = handler
        return previous


class TtyStringIO(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture(autouse=True)
def reset_runner_state():
    Runner.status = "completed"
    Runner.kwargs = None


def invoke(tmp_path, monkeypatch, *extra, mode="text"):
    monkeypatch.setattr(core, "validate_backend_runtime", lambda _backend: None)
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        ["transcribe", str(tmp_path), "--output-mode", mode, *extra],
        runner_factory=Runner,
        stdout=out,
        stderr=err,
    )
    return code, out.getvalue(), err.getvalue()


def test_import_has_no_ui_or_web_dependencies():
    code = (
        "import cli,sys; assert not {'PyQt6','fastapi','uvicorn'} & sys.modules.keys()"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_dynamic_default_and_explicit_formats(tmp_path, monkeypatch):
    code, out, _ = invoke(
        tmp_path, monkeypatch, "--backend", "faster-whisper", "-f", "srt", "-f", "srt"
    )
    assert code == 0 and out == ""
    assert (
        Runner.kwargs["model_name"] == core.BACKEND_DEFAULT_MODELS[core.BACKEND_FASTER]
    )
    assert Runner.kwargs["output_formats"] == ("srt",)

    code, _, _ = invoke(tmp_path, monkeypatch)
    assert code == 0
    assert Runner.kwargs["output_formats"] == ("lrc",)


def test_full_faster_local_model_mapping(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "validate_backend_runtime", lambda _backend: None)
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    stderr = io.StringIO()

    code = cli.main(
        [
            "transcribe",
            str(tmp_path),
            "--backend",
            "faster-whisper",
            "--local-model",
            str(model_dir),
            "--language",
            "en",
            "--device",
            "cpu",
            "--compute-type",
            "int8",
            "--locale",
            "zh_CN",
            "-f",
            "srt",
            "-f",
            "json",
        ],
        runner_factory=Runner,
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert code == 0
    assert Runner.kwargs["model_name"] == str(model_dir.resolve())
    assert Runner.kwargs["is_local_model"] is True
    assert Runner.kwargs["faster_device_mode"] == "cpu"
    assert Runner.kwargs["faster_compute_type"] == "int8"
    assert Runner.kwargs["output_formats"] == ("srt", "json")
    assert Runner.kwargs["message_formatter"]("cancelled") == "处理已取消。"


def test_model_and_local_model_are_mutually_exclusive(tmp_path):
    assert (
        cli.main(["transcribe", str(tmp_path), "--model", "base", "--local-model", "x"])
        == 2
    )


def test_missing_command_and_blank_values_are_argument_errors(tmp_path):
    assert cli.main([]) == 2
    for option in ("--model", "--language"):
        raw = io.BytesIO()
        assert (
            cli.main(
                [
                    "transcribe",
                    str(tmp_path),
                    option,
                    "   ",
                    "--output-mode",
                    "json",
                ],
                stdout=raw,
                stderr=io.StringIO(),
            )
            == 2
        )
        assert json.loads(raw.getvalue().splitlines()[-1])["status"] == (
            "invalid_arguments"
        )


def test_openai_rejects_faster_options(tmp_path, monkeypatch):
    code, _, error = invoke(tmp_path, monkeypatch, "--device", "cpu")
    assert code == 2
    assert "Faster Whisper" in error


def test_json_is_utf8_json_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "validate_backend_runtime", lambda _backend: None)
    raw = io.BytesIO()
    code = cli.main(
        ["transcribe", str(tmp_path), "--output-mode", "json"],
        runner_factory=Runner,
        stdout=raw,
        stderr=io.StringIO(),
    )
    events = [json.loads(line) for line in raw.getvalue().decode("utf-8").splitlines()]
    assert code == 0
    assert events[0]["message"] == "工作中"
    assert events[-1]["type"] == "result"


def test_plain_text_uses_stderr_without_carriage_returns(tmp_path, monkeypatch):
    code, output, error = invoke(tmp_path, monkeypatch)
    assert code == 0
    assert output == ""
    assert "[100%] 工作中\n" in error
    assert "\r" not in error


def test_status_exit_codes(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "validate_backend_runtime", lambda _backend: None)
    for status, expected in (
        ("completed", 0),
        ("completed_with_errors", 1),
        ("failed", 3),
    ):
        Runner.status = status
        assert (
            cli.main(
                ["transcribe", str(tmp_path)],
                runner_factory=Runner,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
            == expected
        )


def test_capabilities_json_uses_core(monkeypatch):
    expected = {"backends": {}, "formats": [], "faster_whisper": {"devices": []}}
    monkeypatch.setattr(core, "capabilities", lambda: expected)
    output = io.BytesIO()
    assert cli.main(["capabilities", "--json"], stdout=output) == 0
    assert json.loads(output.getvalue().decode("utf-8")) == expected


def test_capabilities_text_uses_core(monkeypatch):
    expected = {
        "backends": {"fake": {"default_model": "tiny"}},
        "formats": ["lrc"],
        "faster_whisper": {"devices": ["cpu"]},
    }
    monkeypatch.setattr(core, "capabilities", lambda: expected)
    output = io.StringIO()
    assert cli.main(["capabilities"], stdout=output) == 0
    assert "fake (default model: tiny)" in output.getvalue()
    assert "Formats: lrc" in output.getvalue()
    assert "Devices: cpu" in output.getvalue()


def test_first_signal_overrides_failed_runner(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "validate_backend_runtime", lambda _backend: None)
    signals = FakeSignal()

    class SignalledRunner(Runner):
        def run(self):
            signals.handlers[signals.SIGINT](signals.SIGINT, None)
            self.completion_status = "failed"

    raw = io.BytesIO()
    code = cli.main(
        ["transcribe", str(tmp_path), "--output-mode", "json"],
        runner_factory=SignalledRunner,
        stdout=raw,
        stderr=io.StringIO(),
        signal_module=signals,
    )
    assert code == 130
    assert json.loads(raw.getvalue().splitlines()[-1])["status"] == "cancelled"


def test_signal_handlers_are_restored_after_normal_completion(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "validate_backend_runtime", lambda _backend: None)
    signals = FakeSignal()
    assert (
        cli.main(
            ["transcribe", str(tmp_path)],
            runner_factory=Runner,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            signal_module=signals,
        )
        == 0
    )
    assert signals.handlers == signals.originals


def test_empty_language_is_json_argument_error(tmp_path):
    raw = io.BytesIO()
    code = cli.main(
        ["transcribe", str(tmp_path), "--language", "", "--output-mode", "json"],
        stdout=raw,
        stderr=io.StringIO(),
    )
    assert code == 2
    events = [json.loads(line) for line in raw.getvalue().splitlines()]
    assert events[-1]["status"] == "invalid_arguments"


def test_quiet_hides_progress_but_keeps_errors_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "validate_backend_runtime", lambda _backend: None)

    class ErrorRunner(Runner):
        status = "completed_with_errors"

        def run(self):
            self.kwargs["progress_callback"]("hidden", 50)
            self.kwargs["error_callback"]("visible")
            return self.completion_status

    stderr = io.StringIO()
    code = cli.main(
        ["transcribe", str(tmp_path), "--output-mode", "quiet"],
        runner_factory=ErrorRunner,
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert code == 1
    assert "hidden" not in stderr.getvalue()
    assert "visible" in stderr.getvalue()
    assert "completed_with_errors" in stderr.getvalue()


def test_tty_progress_finishes_line_before_error(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "validate_backend_runtime", lambda _backend: None)

    class ErrorRunner(Runner):
        status = "completed_with_errors"

        def run(self):
            self.kwargs["progress_callback"]("long progress message", 50)
            self.kwargs["progress_callback"]("short", 60)
            self.kwargs["error_callback"]("failure")
            return self.completion_status

    stderr = TtyStringIO()
    code = cli.main(
        ["transcribe", str(tmp_path), "--no-color"],
        runner_factory=ErrorRunner,
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert code == 1
    assert "\nERROR: failure\n" in stderr.getvalue()
    assert "\x1b" not in stderr.getvalue()


def test_chinese_validation_and_runtime_errors(tmp_path, monkeypatch):
    missing = tmp_path / "missing.pt"
    code, _, error = invoke(
        tmp_path,
        monkeypatch,
        "--locale",
        "zh_CN",
        "--local-model",
        str(missing),
    )
    assert code == 2
    assert "本地模型必须是权重文件" in error

    monkeypatch.setattr(
        core,
        "validate_backend_runtime",
        lambda _backend: core.BACKEND_RUNTIME_ERRORS["ffmpeg_missing"],
    )
    stderr = io.StringIO()
    code = cli.main(
        ["transcribe", str(tmp_path), "--locale", "zh_CN"],
        runner_factory=Runner,
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert code == 3
    assert "未找到 FFmpeg" in stderr.getvalue()


def test_faster_compute_type_validation(tmp_path, monkeypatch):
    code, _, _ = invoke(
        tmp_path,
        monkeypatch,
        "--backend",
        "faster-whisper",
        "--device",
        "cpu",
    )
    assert code == 0
    assert Runner.kwargs["faster_compute_type"] == "auto"

    code, _, error = invoke(
        tmp_path,
        monkeypatch,
        "--backend",
        "faster-whisper",
        "--device",
        "cpu",
        "--compute-type",
        "float16",
    )
    assert code == 2
    assert "Unsupported compute type" in error


def test_sigterm_and_constructor_failure_preserve_cancellation(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "validate_backend_runtime", lambda _backend: None)
    signals = FakeSignal()

    class ConstructorFailure:
        def __init__(self, **_kwargs):
            signals.handlers[signals.SIGTERM](signals.SIGTERM, None)
            raise RuntimeError("constructor failed after signal")

    raw = io.BytesIO()
    code = cli.main(
        ["transcribe", str(tmp_path), "--output-mode", "json"],
        runner_factory=ConstructorFailure,
        stdout=raw,
        stderr=io.StringIO(),
        signal_module=signals,
    )
    events = [json.loads(line) for line in raw.getvalue().splitlines()]
    assert code == 143
    assert events[-1]["status"] == "cancelled"
    assert signals.handlers == signals.originals


def test_second_signal_forces_exit_without_json_result(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "validate_backend_runtime", lambda _backend: None)
    signals = FakeSignal()

    class DoubleSignalRunner(Runner):
        def run(self):
            handler = signals.handlers[signals.SIGINT]
            handler(signals.SIGINT, None)
            handler(signals.SIGINT, None)

    raw = io.BytesIO()
    code = cli.main(
        ["transcribe", str(tmp_path), "--output-mode", "json"],
        runner_factory=DoubleSignalRunner,
        stdout=raw,
        stderr=io.StringIO(),
        signal_module=signals,
    )
    assert code == 130
    assert not any(
        json.loads(line)["type"] == "result" for line in raw.getvalue().splitlines()
    )
    assert signals.handlers == signals.originals


def test_second_sigterm_forces_143_and_restores_handlers(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "validate_backend_runtime", lambda _backend: None)
    signals = FakeSignal()

    class DoubleSignalRunner(Runner):
        def run(self):
            handler = signals.handlers[signals.SIGTERM]
            handler(signals.SIGTERM, None)
            handler(signals.SIGTERM, None)

    raw = io.BytesIO()
    code = cli.main(
        ["transcribe", str(tmp_path), "--output-mode", "json"],
        runner_factory=DoubleSignalRunner,
        stdout=raw,
        stderr=io.StringIO(),
        signal_module=signals,
    )
    assert code == 143
    assert raw.getvalue() == b""
    assert signals.handlers == signals.originals


def test_signal_during_runtime_validation_wins(tmp_path, monkeypatch):
    signals = FakeSignal()

    def validate(_backend):
        signals.handlers[signals.SIGINT](signals.SIGINT, None)
        return core.BACKEND_RUNTIME_ERRORS["ffmpeg_missing"]

    monkeypatch.setattr(core, "validate_backend_runtime", validate)
    raw = io.BytesIO()
    code = cli.main(
        ["transcribe", str(tmp_path), "--output-mode", "json"],
        runner_factory=Runner,
        stdout=raw,
        stderr=io.StringIO(),
        signal_module=signals,
    )
    events = [json.loads(line) for line in raw.getvalue().splitlines()]
    assert code == 130
    assert events == [
        {
            "type": "result",
            "status": "cancelled",
            "progress": 0,
            "error_count": 0,
        }
    ]
    assert signals.handlers == signals.originals


def test_internal_adapter_exception_returns_software_error(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "validate_backend_runtime", lambda _backend: None)
    signals = FakeSignal()

    class BrokenRunner:
        def __init__(self, **_kwargs):
            raise RuntimeError("adapter broke")

    raw = io.BytesIO()
    code = cli.main(
        ["transcribe", str(tmp_path), "--output-mode", "json"],
        runner_factory=BrokenRunner,
        stdout=raw,
        stderr=io.StringIO(),
        signal_module=signals,
    )
    events = [json.loads(line) for line in raw.getvalue().splitlines()]
    assert code == 70
    assert events[-1]["status"] == "failed"
    assert events[-1]["error_count"] == 1
    assert signals.handlers == signals.originals


def test_unknown_runner_status_is_internal_error(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "validate_backend_runtime", lambda _backend: None)

    class UnknownRunner(Runner):
        status = "unknown"

    raw = io.BytesIO()
    code = cli.main(
        ["transcribe", str(tmp_path), "--output-mode", "json"],
        runner_factory=UnknownRunner,
        stdout=raw,
        stderr=io.StringIO(),
    )
    events = [json.loads(line) for line in raw.getvalue().splitlines()]
    assert code == 70
    assert events[-2]["type"] == "error"
    assert events[-1]["status"] == "failed"


def test_json_bypasses_non_utf8_text_wrapper(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "validate_backend_runtime", lambda _backend: None)
    raw = io.BytesIO()
    wrapper = io.TextIOWrapper(raw, encoding="ascii")
    code = cli.main(
        ["transcribe", str(tmp_path), "--output-mode", "json"],
        runner_factory=Runner,
        stdout=wrapper,
        stderr=io.StringIO(),
    )
    wrapper.flush()
    events = [json.loads(line) for line in raw.getvalue().decode("utf-8").splitlines()]
    assert code == 0
    assert events[0]["message"] == "工作中"


def test_broken_json_output_returns_70_without_escaping(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "validate_backend_runtime", lambda _backend: None)

    class BrokenOutput:
        def write(self, _value):
            raise OSError("closed")

        def flush(self):
            raise OSError("closed")

    stderr = io.StringIO()
    code = cli.main(
        ["transcribe", str(tmp_path), "--output-mode", "json"],
        runner_factory=Runner,
        stdout=BrokenOutput(),
        stderr=stderr,
    )
    assert code == 70
    assert "output failure" in stderr.getvalue()


def test_version_flag_uses_single_version_source():
    result = subprocess.run(
        [sys.executable, "cli.py", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == __version__
