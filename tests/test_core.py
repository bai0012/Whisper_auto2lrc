import subprocess
import sys

import core


def test_capabilities_are_complete_json_data_and_fresh():
    first = core.capabilities()
    second = core.capabilities()

    assert first == second
    assert first is not second
    assert first["backends"][core.BACKEND_OPENAI]["default_model"] == "base"
    assert first["backends"][core.BACKEND_OPENAI]["local_model"] == "file"
    assert first["backends"][core.BACKEND_FASTER]["local_model"] == "directory"
    assert first["formats"] == list(core.OUTPUT_FORMATS)
    assert first["languages"][0] == "auto"
    assert first["faster_whisper"]["devices"] == ["auto", "cpu", "cuda"]
    first["backends"][core.BACKEND_OPENAI]["models"].append("mutated")
    assert "mutated" not in second["backends"][core.BACKEND_OPENAI]["models"]


def test_validate_backend_runtime_checks_only_selected_backend(monkeypatch):
    monkeypatch.setattr(core, "whisper", object())
    monkeypatch.setattr(core, "FasterWhisperModel", object())
    monkeypatch.setattr(core.shutil, "which", lambda _name: None)

    assert "FFmpeg" in core.validate_backend_runtime(core.BACKEND_OPENAI)
    assert core.validate_backend_runtime(core.BACKEND_FASTER) is None

    monkeypatch.setattr(core, "whisper", None)
    monkeypatch.setattr(core, "FasterWhisperModel", None)
    assert "openai-whisper" in core.validate_backend_runtime(core.BACKEND_OPENAI)
    assert "faster-whisper" in core.validate_backend_runtime(core.BACKEND_FASTER)
    assert "unsupported" in core.validate_backend_runtime("other").lower()


def test_core_and_api_import_without_qt_modules():
    code = (
        "import sys; import core, api; "
        "assert not any(name.startswith('PyQt') for name in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_runner_progress_is_monotonic_and_advances_for_empty_and_error(
    tmp_path, monkeypatch
):
    for name in ("a.mp3", "b.mp3", "c.mp3"):
        (tmp_path / name).touch()

    class Backend:
        def cache_key(self, *_args):
            return ("fake",)

        def load_model(self, *_args):
            return object()

        def transcribe(self, _model, path, _language):
            if path.name == "a.mp3":
                return {"segments": []}
            if path.name == "b.mp3":
                raise RuntimeError("broken")
            return {"segments": [{"start": 0, "end": 1, "text": "ok"}]}

    monkeypatch.setattr(core, "create_backend", lambda *_args, **_kwargs: Backend())
    monkeypatch.setattr(core, "validate_backend_runtime", lambda _backend: None)
    progress = []
    errors = []
    runner = core.TranscriptionRunner(
        tmp_path,
        "base",
        "auto",
        progress_callback=lambda _message, value: progress.append(value),
        error_callback=errors.append,
    )

    assert runner.run() == "completed_with_errors"
    assert progress == sorted(progress)
    assert progress[-1] == 100
    assert len(errors) == 2
    assert (tmp_path / "c.lrc").exists()


def test_runner_validates_folder_and_output_formats(tmp_path):
    errors = []
    missing = core.TranscriptionRunner(
        tmp_path / "missing", "base", "auto", error_callback=errors.append
    )
    assert missing.run() == "failed"
    no_formats = core.TranscriptionRunner(
        tmp_path, "base", "auto", output_formats=(), error_callback=errors.append
    )
    assert no_formats.run() == "failed"


def test_runner_checks_runtime_after_scan_before_model_load(tmp_path, monkeypatch):
    (tmp_path / "song.mp3").touch()
    load_calls = []

    class Backend:
        def cache_key(self, *_args):
            return ("fake",)

        def load_model(self, *_args):
            load_calls.append(True)

    monkeypatch.setattr(core, "create_backend", lambda *_args, **_kwargs: Backend())
    monkeypatch.setattr(
        core, "validate_backend_runtime", lambda _backend: "missing dependency"
    )
    errors = []
    runner = core.TranscriptionRunner(
        tmp_path, "base", "auto", error_callback=errors.append
    )

    assert runner.run() == "failed"
    assert load_calls == []
    assert "missing dependency" in errors[0]


def test_discovery_stops_early_when_cancellation_is_requested(tmp_path):
    for index in range(20):
        (tmp_path / f"{index:02}.mp3").touch()
    checks = 0

    def stop_requested():
        nonlocal checks
        checks += 1
        return checks >= 3

    tasks, conflicts = core.discover_audio_tasks(
        tmp_path, ("lrc",), stop_requested=stop_requested
    )

    assert checks == 3
    assert len(tasks) < 20
    assert conflicts == []
