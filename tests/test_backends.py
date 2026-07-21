from pathlib import Path
from types import SimpleNamespace

import core
import main


def test_backend_model_lists_include_backend_specific_models():
    assert "turbo" in main.BACKEND_MODELS[main.BACKEND_OPENAI]
    assert "large-v3-turbo" in main.BACKEND_MODELS[main.BACKEND_OPENAI]
    assert "distil-large-v3" not in main.BACKEND_MODELS[main.BACKEND_OPENAI]
    assert "distil-large-v3" in main.BACKEND_MODELS[main.BACKEND_FASTER]
    assert "distil-large-v3.5" in main.BACKEND_MODELS[main.BACKEND_FASTER]
    assert "large-v3-turbo" in main.BACKEND_MODELS[main.BACKEND_FASTER]


def test_faster_runtime_uses_cuda_float16_when_cuda_is_available(monkeypatch):
    monkeypatch.setattr(
        core, "ctranslate2", SimpleNamespace(get_cuda_device_count=lambda: 1)
    )
    assert main.faster_whisper_runtime() == ("cuda", "float16")


def test_faster_runtime_uses_cpu_int8_without_cuda(monkeypatch):
    monkeypatch.setattr(
        core, "ctranslate2", SimpleNamespace(get_cuda_device_count=lambda: 0)
    )
    assert main.faster_whisper_runtime() == ("cpu", "int8")


def test_faster_runtime_falls_back_to_cpu_if_cuda_probe_fails(monkeypatch):
    monkeypatch.setattr(
        core,
        "ctranslate2",
        SimpleNamespace(
            get_cuda_device_count=lambda: (_ for _ in ()).throw(
                RuntimeError("probe failed")
            )
        ),
    )
    assert main.faster_whisper_runtime() == ("cpu", "int8")


def test_faster_adapter_loads_with_runtime_and_consumes_segments(monkeypatch):
    load_calls = []

    class FakeWhisperModel:
        def __init__(self, model_name, **options):
            load_calls.append((model_name, options))

        def transcribe(self, path, language):
            def generated_segments():
                yield SimpleNamespace(start=0.25, end=1.5, text=" hello")
                yield SimpleNamespace(start=1.5, end=2.0, text=" world")

            return generated_segments(), SimpleNamespace(language="en")

    monkeypatch.setattr(core, "FasterWhisperModel", FakeWhisperModel)
    monkeypatch.setattr(
        core, "ctranslate2", SimpleNamespace(get_cuda_device_count=lambda: 0)
    )
    backend = main.FasterWhisperBackend()
    model = backend.load_model("distil-large-v3")
    result = backend.transcribe(model, Path("song.mp3"), None)

    assert load_calls == [
        ("distil-large-v3", {"device": "cpu", "compute_type": "int8"})
    ]
    assert result == {
        "text": "hello world",
        "segments": [
            {"start": 0.25, "end": 1.5, "text": " hello"},
            {"start": 1.5, "end": 2.0, "text": " world"},
        ],
        "language": "en",
    }


def test_openai_adapter_preserves_result_and_auto_language(monkeypatch):
    calls = []
    expected = {"text": "hello", "segments": []}
    model = SimpleNamespace(
        transcribe=lambda path, **options: calls.append((path, options)) or expected
    )
    monkeypatch.setattr(
        core, "whisper", SimpleNamespace(load_model=lambda _name: model)
    )
    backend = main.OpenAIWhisperBackend()

    assert (
        backend.transcribe(backend.load_model("base"), Path("song.mp3"), None)
        is expected
    )
    assert calls == [("song.mp3", {"language": None, "verbose": False})]


def test_openai_adapter_loads_resolved_local_checkpoint(tmp_path, monkeypatch):
    checkpoint = tmp_path / "model.pt"
    checkpoint.touch()
    calls = []
    monkeypatch.setattr(
        core, "whisper", SimpleNamespace(load_model=lambda value: calls.append(value))
    )

    main.OpenAIWhisperBackend().load_model(str(checkpoint), is_local_model=True)

    assert calls == [str(checkpoint.resolve())]


def test_faster_adapter_disables_download_for_local_ctranslate2_dir(
    tmp_path, monkeypatch
):
    model_dir = tmp_path / "faster-model"
    model_dir.mkdir()
    calls = []

    class FakeWhisperModel:
        def __init__(self, model_name, **options):
            calls.append((model_name, options))

    monkeypatch.setattr(core, "FasterWhisperModel", FakeWhisperModel)
    monkeypatch.setattr(
        core, "ctranslate2", SimpleNamespace(get_cuda_device_count=lambda: 0)
    )

    main.FasterWhisperBackend().load_model(str(model_dir), is_local_model=True)

    assert calls == [
        (
            str(model_dir.resolve()),
            {
                "device": "cpu",
                "compute_type": "int8",
                "local_files_only": True,
            },
        )
    ]


def test_cache_key_isolated_by_backend_and_faster_runtime(monkeypatch):
    monkeypatch.setattr(
        core, "ctranslate2", SimpleNamespace(get_cuda_device_count=lambda: 0)
    )
    openai_key = main.OpenAIWhisperBackend().cache_key("base")
    faster_key = main.FasterWhisperBackend().cache_key("base")

    assert openai_key == (main.BACKEND_OPENAI, "base")
    assert faster_key == (main.BACKEND_FASTER, "base", "cpu", "int8")
    assert openai_key != faster_key


def test_local_model_cache_key_uses_resolved_path(tmp_path, monkeypatch):
    monkeypatch.setattr(
        core, "ctranslate2", SimpleNamespace(get_cuda_device_count=lambda: 0)
    )
    model_dir = tmp_path / "models" / "local"
    relative_path = model_dir.parent / ".." / "models" / "local"

    key = main.FasterWhisperBackend().cache_key(str(relative_path), is_local_model=True)

    assert key == (
        main.BACKEND_FASTER,
        str(model_dir.resolve()),
        "cpu",
        "int8",
    )


def test_local_model_language_is_not_assumed_english_only():
    assert (
        main.validate_transcription_language(
            "distil-custom.en", "zh", "en", is_local_model=True
        )
        is None
    )


def test_dependency_checks_are_backend_specific(monkeypatch):
    monkeypatch.setattr(core, "whisper", object())
    monkeypatch.setattr(core, "FasterWhisperModel", object())
    monkeypatch.setattr(main.shutil, "which", lambda _name: None)

    assert main.check_backend_dependencies(main.BACKEND_OPENAI, "en") is not None
    assert main.check_backend_dependencies(main.BACKEND_FASTER, "en") is None

    monkeypatch.setattr(core, "whisper", None)
    monkeypatch.setattr(core, "FasterWhisperModel", None)
    assert (
        "openai-whisper"
        in main.check_backend_dependencies(main.BACKEND_OPENAI, "en")[1]
    )
    assert (
        "faster-whisper"
        in main.check_backend_dependencies(main.BACKEND_FASTER, "en")[1]
    )


def test_worker_uses_faster_backend_and_writes_normalized_output(tmp_path, monkeypatch):
    calls = []

    class FakeWhisperModel:
        def __init__(self, model_name, **options):
            calls.append(("load", model_name, options))

        def transcribe(self, path, language):
            calls.append(("transcribe", path, language))
            return iter(
                [SimpleNamespace(start=1.0, end=2.25, text=" faster result")]
            ), SimpleNamespace(language="en")

    monkeypatch.setattr(core, "FasterWhisperModel", FakeWhisperModel)
    monkeypatch.setattr(
        core, "ctranslate2", SimpleNamespace(get_cuda_device_count=lambda: 0)
    )
    source = tmp_path / "song.mp3"
    source.touch()

    worker = main.Worker(
        tmp_path,
        "base",
        "auto",
        "en",
        output_formats=("lrc", "json"),
        backend_name=main.BACKEND_FASTER,
    )
    worker.run()

    assert worker.completion_status == "completed"
    assert calls[0] == ("load", "base", {"device": "cpu", "compute_type": "int8"})
    assert calls[1] == ("transcribe", str(source), None)
    assert (tmp_path / "song.lrc").read_text(encoding="utf-8") == (
        "[00:01.00]faster result\n"
    )
    assert '"language": "en"' in (tmp_path / "song.json").read_text(encoding="utf-8")


def test_auto_cuda_load_failure_retries_cpu_and_caches_actual_runtime(
    tmp_path, monkeypatch
):
    load_calls = []

    class FakeWhisperModel:
        def __init__(self, model_name, **options):
            load_calls.append((model_name, options))
            if options["device"] == "cuda":
                raise RuntimeError("CUDA libraries missing")

        def transcribe(self, path, language):
            return iter(
                [SimpleNamespace(start=0.0, end=1.0, text=" fallback")]
            ), SimpleNamespace(language="en")

    monkeypatch.setattr(core, "FasterWhisperModel", FakeWhisperModel)
    monkeypatch.setattr(
        core, "ctranslate2", SimpleNamespace(get_cuda_device_count=lambda: 1)
    )
    (tmp_path / "song.mp3").touch()
    messages = []
    worker = main.Worker(
        tmp_path,
        "base",
        "auto",
        "zh_CN",
        backend_name=main.BACKEND_FASTER,
        faster_device_mode="auto",
        faster_compute_type="auto",
    )
    worker.progress.connect(lambda message, _value: messages.append(message))
    worker.run()

    assert worker.completion_status == "completed"
    assert load_calls == [
        ("base", {"device": "cuda", "compute_type": "float16"}),
        ("base", {"device": "cpu", "compute_type": "int8"}),
    ]
    assert any("CPU / int8" in message and "重试" in message for message in messages)
    assert main.WHISPER_MODEL_CACHE._model_name == (
        main.BACKEND_FASTER,
        "base",
        "cpu",
        "int8",
    )


def test_explicit_cuda_load_failure_does_not_fallback(tmp_path, monkeypatch):
    load_calls = []

    class FailingWhisperModel:
        def __init__(self, model_name, **options):
            load_calls.append((model_name, options))
            raise RuntimeError("CUDA failed")

    monkeypatch.setattr(core, "FasterWhisperModel", FailingWhisperModel)
    (tmp_path / "song.mp3").touch()
    errors = []
    worker = main.Worker(
        tmp_path,
        "base",
        "auto",
        "en",
        backend_name=main.BACKEND_FASTER,
        faster_device_mode="cuda",
        faster_compute_type="int8_float16",
    )
    worker.error_occurred.connect(errors.append)
    worker.run()

    assert worker.completion_status == "failed"
    assert load_calls == [("base", {"device": "cuda", "compute_type": "int8_float16"})]
    assert "Failed to load" in errors[0]
