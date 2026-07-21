from types import SimpleNamespace

import core
import main


class FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, path, **options):
        self.calls.append((path, options))
        return {"segments": [{"start": 0.5, "text": "lyrics"}]}


def install_fake_whisper(monkeypatch, model):
    monkeypatch.setattr(
        core, "whisper", SimpleNamespace(load_model=lambda _name: model)
    )
    monkeypatch.setattr(core.shutil, "which", lambda _name: "/usr/bin/ffmpeg")


def test_worker_honors_stop_requested_before_thread_starts(tmp_path, monkeypatch):
    (tmp_path / "song.mp3").touch()
    model = FakeModel()
    install_fake_whisper(monkeypatch, model)
    worker = main.Worker(tmp_path, "base", "auto")

    worker.stop()
    worker.run()

    assert worker.completion_status == "cancelled"
    assert model.calls == []


def test_worker_skips_conflicting_sources_and_reports_them(tmp_path, monkeypatch):
    model = FakeModel()
    install_fake_whisper(monkeypatch, model)
    (tmp_path / "song.mp3").touch()
    (tmp_path / "song.wav").touch()

    errors = []
    worker = main.Worker(tmp_path, "base", "auto", "en")
    worker.error_occurred.connect(errors.append)
    worker.run()

    assert worker.completion_status == "completed_with_errors"
    assert model.calls == []
    assert not (tmp_path / "song.lrc").exists()
    assert "song.mp3" in errors[0] and "song.wav" in errors[0]


def test_worker_skips_media_with_existing_lrc(tmp_path, monkeypatch):
    model = FakeModel()
    install_fake_whisper(monkeypatch, model)
    (tmp_path / "song.mp3").touch()
    target = tmp_path / "song.lrc"
    target.write_text("existing", encoding="utf-8")

    worker = main.Worker(tmp_path, "base", "auto", "en")
    worker.run()

    assert worker.completion_status == "completed"
    assert model.calls == []
    assert target.read_text(encoding="utf-8") == "existing"


def test_worker_processes_unique_file_with_auto_language(tmp_path, monkeypatch):
    model = FakeModel()
    install_fake_whisper(monkeypatch, model)
    source = tmp_path / "unique.mp3"
    source.touch()

    worker = main.Worker(tmp_path, "base", "", "en")
    worker.run()

    assert worker.completion_status == "completed"
    assert model.calls[0][1]["language"] is None
    assert (tmp_path / "unique.lrc").read_text(encoding="utf-8") == "[00:00.50]lyrics\n"


def test_worker_uses_chinese_messages(tmp_path, monkeypatch):
    model = FakeModel()
    install_fake_whisper(monkeypatch, model)
    (tmp_path / "song.mp3").touch()
    messages = []
    worker = main.Worker(tmp_path, "base", "auto", "zh_CN")
    worker.progress.connect(lambda text, _value: messages.append(text))
    worker.run()
    assert any("正在加载" in message for message in messages)
    assert any("正在处理" in message for message in messages)


def test_worker_transcribes_once_and_writes_all_selected_formats(tmp_path, monkeypatch):
    model = FakeModel()
    model.transcribe = lambda path, **options: (
        model.calls.append((path, options))
        or {
            "text": "lyrics",
            "segments": [{"start": 0.5, "end": 1.75, "text": "lyrics"}],
        }
    )
    install_fake_whisper(monkeypatch, model)
    source = tmp_path / "song.mp3"
    source.touch()

    worker = main.Worker(
        tmp_path,
        "base",
        "auto",
        "en",
        output_formats=("lrc", "srt", "vtt", "txt", "tsv", "json"),
    )
    worker.run()

    assert worker.completion_status == "completed"
    assert len(model.calls) == 1
    assert (tmp_path / "song.lrc").read_text(encoding="utf-8") == "[00:00.50]lyrics\n"
    assert "00:00:00,500 --> 00:00:01,750" in (tmp_path / "song.srt").read_text(
        encoding="utf-8"
    )
    assert (tmp_path / "song.vtt").read_text(encoding="utf-8").startswith("WEBVTT\n\n")
    assert (tmp_path / "song.txt").read_text(encoding="utf-8") == "lyrics\n"
    assert (
        (tmp_path / "song.tsv")
        .read_text(encoding="utf-8")
        .startswith("start\tend\ttext\n")
    )
    assert '"text": "lyrics"' in (tmp_path / "song.json").read_text(encoding="utf-8")


def test_worker_only_creates_missing_selected_formats(tmp_path, monkeypatch):
    model = FakeModel()
    model.transcribe = lambda path, **options: (
        model.calls.append((path, options))
        or {"segments": [{"start": 0.5, "end": 1.0, "text": "new"}]}
    )
    install_fake_whisper(monkeypatch, model)
    (tmp_path / "song.mp3").touch()
    existing = tmp_path / "song.lrc"
    existing.write_text("keep me", encoding="utf-8")

    worker = main.Worker(tmp_path, "base", "auto", "en", output_formats=("lrc", "srt"))
    worker.run()

    assert len(model.calls) == 1
    assert existing.read_text(encoding="utf-8") == "keep me"
    assert (tmp_path / "song.srt").exists()


def test_worker_reports_output_that_appears_and_writes_remaining_format(
    tmp_path, monkeypatch
):
    source = tmp_path / "song.mp3"
    source.touch()

    class TargetAppearingModel(FakeModel):
        def transcribe(self, path, **options):
            self.calls.append((path, options))
            (tmp_path / "song.lrc").write_text("created elsewhere", encoding="utf-8")
            return {"segments": [{"start": 0.5, "end": 1.0, "text": "lyrics"}]}

    model = TargetAppearingModel()
    install_fake_whisper(monkeypatch, model)
    errors = []
    worker = main.Worker(tmp_path, "base", "auto", "en", output_formats=("lrc", "srt"))
    worker.error_occurred.connect(errors.append)
    worker.run()

    assert worker.completion_status == "completed_with_errors"
    assert (tmp_path / "song.lrc").read_text(encoding="utf-8") == "created elsewhere"
    assert (tmp_path / "song.srt").exists()
    assert "song.lrc" in errors[0]


def test_worker_skips_same_stem_conflict_for_non_lrc_output(tmp_path, monkeypatch):
    model = FakeModel()
    install_fake_whisper(monkeypatch, model)
    (tmp_path / "song.mp3").touch()
    (tmp_path / "song.wav").touch()

    errors = []
    worker = main.Worker(tmp_path, "base", "auto", "en", output_formats=("srt", "vtt"))
    worker.error_occurred.connect(errors.append)
    worker.run()

    assert worker.completion_status == "completed_with_errors"
    assert model.calls == []
    assert not (tmp_path / "song.srt").exists()
    assert "song.mp3" in errors[0] and "song.wav" in errors[0]


def test_worker_empty_result_creates_no_selected_outputs(tmp_path, monkeypatch):
    model = FakeModel()
    model.transcribe = lambda path, **options: (
        model.calls.append((path, options)) or {"text": "", "segments": []}
    )
    install_fake_whisper(monkeypatch, model)
    (tmp_path / "song.mp3").touch()

    worker = main.Worker(
        tmp_path, "base", "auto", "en", output_formats=("lrc", "srt", "json")
    )
    worker.run()

    assert worker.completion_status == "completed_with_errors"
    assert len(model.calls) == 1
    assert not (tmp_path / "song.lrc").exists()
    assert not (tmp_path / "song.srt").exists()
    assert not (tmp_path / "song.json").exists()


def test_worker_does_not_load_model_when_all_selected_outputs_exist(
    tmp_path, monkeypatch
):
    load_calls = []
    monkeypatch.setattr(
        main,
        "whisper",
        SimpleNamespace(load_model=lambda name: load_calls.append(name)),
    )
    (tmp_path / "song.mp3").touch()
    (tmp_path / "song.lrc").write_text("existing", encoding="utf-8")
    (tmp_path / "song.srt").write_text("existing", encoding="utf-8")

    worker = main.Worker(tmp_path, "base", "auto", "en", output_formats=("lrc", "srt"))
    worker.run()

    assert worker.completion_status == "completed"
    assert load_calls == []


def test_media_suffix_directory_is_not_treated_as_audio(tmp_path, monkeypatch):
    load_calls = []
    monkeypatch.setattr(
        main,
        "whisper",
        SimpleNamespace(load_model=lambda name: load_calls.append(name)),
    )
    (tmp_path / "not-a-file.mp3").mkdir()

    tasks, conflicts = main.discover_audio_tasks(tmp_path, ("lrc",))
    worker = main.Worker(tmp_path, "base", "auto", "en")
    worker.run()

    assert tasks == []
    assert conflicts == []
    assert worker.completion_status == "completed"
    assert load_calls == []
