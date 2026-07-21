from types import SimpleNamespace

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QMessageBox

import main


def test_default_transcription_language_is_auto(qapp):
    window = main.App("en")
    assert window.backend_select.currentData() == main.BACKEND_OPENAI
    assert window.model_select.currentText() == "base"
    assert window.language_input.text() == "auto"
    selected = {
        output_format
        for output_format, checkbox in window.output_format_checks.items()
        if checkbox.isChecked()
    }
    assert selected == {"lrc"}
    window.close()


def test_backend_switch_updates_models_and_preserves_common_choice(qapp):
    window = main.App("en")
    window.model_select.setCurrentText("small")
    window.backend_select.setCurrentIndex(
        window.backend_select.findData(main.BACKEND_FASTER)
    )
    assert window.model_select.currentText() == "small"
    assert "distil-large-v3" in [
        window.model_select.itemText(index)
        for index in range(window.model_select.count())
    ]

    window.model_select.setCurrentText("distil-large-v3")
    window.backend_select.setCurrentIndex(
        window.backend_select.findData(main.BACKEND_OPENAI)
    )
    assert window.model_select.currentText() == "small"
    assert "distil-large-v3" not in [
        window.model_select.itemText(index)
        for index in range(window.model_select.count())
    ]
    window.close()


def test_local_model_controls_and_backend_specific_settings(
    qapp, isolate_qsettings, tmp_path
):
    openai_model = tmp_path / "openai.pt"
    faster_model = tmp_path / "faster"
    window = main.App("en", settings=isolate_qsettings)

    window.use_local_model_check.setChecked(True)
    window.local_model_path_edit.setText(str(openai_model))
    window.save_local_model_settings()
    assert window.model_select.isEnabled() is False
    assert window.local_model_path_edit.isEnabled() is True

    window.backend_select.setCurrentIndex(
        window.backend_select.findData(main.BACKEND_FASTER)
    )
    assert window.use_local_model_check.isChecked() is False
    assert window.local_model_path_edit.text() == ""
    window.use_local_model_check.setChecked(True)
    window.local_model_path_edit.setText(str(faster_model))
    window.save_local_model_settings()

    window.backend_select.setCurrentIndex(
        window.backend_select.findData(main.BACKEND_OPENAI)
    )
    assert window.use_local_model_check.isChecked() is True
    assert window.local_model_path_edit.text() == str(openai_model)
    window.close()

    restored = main.App("en", settings=isolate_qsettings)
    assert restored.use_local_model_check.isChecked() is True
    assert restored.local_model_path_edit.text() == str(openai_model)
    restored.backend_select.setCurrentIndex(
        restored.backend_select.findData(main.BACKEND_FASTER)
    )
    assert restored.use_local_model_check.isChecked() is True
    assert restored.local_model_path_edit.text() == str(faster_model)
    restored.close()


def test_local_model_browse_uses_file_for_openai_and_directory_for_faster(
    qapp, isolate_qsettings, tmp_path, monkeypatch
):
    checkpoint = tmp_path / "custom.pt"
    model_dir = tmp_path / "ctranslate2-model"
    calls = []
    window = main.App("en", settings=isolate_qsettings)
    window.use_local_model_check.setChecked(True)
    monkeypatch.setattr(
        main.QFileDialog,
        "getOpenFileName",
        lambda *_args: (str(checkpoint), "PyTorch checkpoints (*.pt)"),
    )
    monkeypatch.setattr(
        main.QFileDialog,
        "getExistingDirectory",
        lambda *_args: calls.append("directory") or str(model_dir),
    )

    window.select_local_model()
    assert window.local_model_path_edit.text() == str(checkpoint.resolve())

    window.backend_select.setCurrentIndex(
        window.backend_select.findData(main.BACKEND_FASTER)
    )
    window.use_local_model_check.setChecked(True)
    window.select_local_model()
    assert calls == ["directory"]
    assert window.local_model_path_edit.text() == str(model_dir.resolve())
    window.close()


def test_ui_rejects_wrong_local_model_path_type(qapp, tmp_path, monkeypatch):
    window = main.App("en")
    window.folder_path_edit.setText(str(tmp_path))
    window.use_local_model_check.setChecked(True)
    window.local_model_path_edit.setText(str(tmp_path / "missing.pt"))
    warnings = []
    monkeypatch.setattr(
        main.QMessageBox,
        "warning",
        lambda _parent, title, text: warnings.append((title, text)),
    )

    window.start_processing()
    assert "checkpoint file" in warnings[-1][1]

    checkpoint = tmp_path / "not-a-directory.pt"
    checkpoint.touch()
    window.backend_select.setCurrentIndex(
        window.backend_select.findData(main.BACKEND_FASTER)
    )
    window.use_local_model_check.setChecked(True)
    window.local_model_path_edit.setText(str(checkpoint))
    window.start_processing()
    assert "CTranslate2 model directory" in warnings[-1][1]
    assert window.worker is None
    window.close()


def test_faster_device_selection_exposes_only_legal_compute_types(qapp):
    window = main.App("en")
    window.backend_select.setCurrentIndex(
        window.backend_select.findData(main.BACKEND_FASTER)
    )
    assert window.faster_device_select.isHidden() is False
    assert [
        window.faster_compute_select.itemText(index)
        for index in range(window.faster_compute_select.count())
    ] == ["auto"]

    window.faster_device_select.setCurrentIndex(
        window.faster_device_select.findData("cpu")
    )
    assert [
        window.faster_compute_select.itemText(index)
        for index in range(window.faster_compute_select.count())
    ] == ["int8", "float32"]

    window.faster_device_select.setCurrentIndex(
        window.faster_device_select.findData("cuda")
    )
    assert [
        window.faster_compute_select.itemText(index)
        for index in range(window.faster_compute_select.count())
    ] == ["float16", "int8_float16", "int8"]
    window.close()


def test_settings_persist_backend_specific_models_and_user_choices(
    qapp, isolate_qsettings, tmp_path
):
    window = main.App("en", settings=isolate_qsettings)
    window.folder_path_edit.setText(str(tmp_path))
    window.model_select.setCurrentText("small")
    window.backend_select.setCurrentIndex(
        window.backend_select.findData(main.BACKEND_FASTER)
    )
    window.model_select.setCurrentText("distil-large-v3")
    window.faster_device_select.setCurrentIndex(
        window.faster_device_select.findData("cuda")
    )
    window.faster_compute_select.setCurrentText("int8_float16")
    window.language_input.setText("zh")
    window.output_format_checks["lrc"].setChecked(False)
    window.output_format_checks["srt"].setChecked(True)
    window.resize(812, 623)
    window.close()

    restored = main.App("en", settings=isolate_qsettings)
    assert restored.folder_path_edit.text() == str(tmp_path)
    assert restored.backend_select.currentData() == main.BACKEND_FASTER
    assert restored.model_select.currentText() == "distil-large-v3"
    assert restored.faster_device_select.currentData() == "cuda"
    assert restored.faster_compute_select.currentText() == "int8_float16"
    assert restored.language_input.text() == "zh"
    assert restored.output_format_checks["lrc"].isChecked() is False
    assert restored.output_format_checks["srt"].isChecked() is True

    restored.backend_select.setCurrentIndex(
        restored.backend_select.findData(main.BACKEND_OPENAI)
    )
    assert restored.model_select.currentText() == "small"
    restored.close()


def test_ui_rejects_invalid_and_english_only_model_languages(
    qapp, tmp_path, monkeypatch
):
    window = main.App("zh_CN")
    window.folder_path_edit.setText(str(tmp_path))
    warnings = []
    monkeypatch.setattr(
        main.QMessageBox,
        "warning",
        lambda _parent, title, text: warnings.append((title, text)),
    )

    window.language_input.setText("not-a-language")
    window.start_processing()
    assert "不支持" in warnings[-1][1]

    window.model_select.setCurrentText("base.en")
    window.language_input.setText("zh")
    window.start_processing()
    assert "仅支持英语" in warnings[-1][1]

    window.backend_select.setCurrentIndex(
        window.backend_select.findData(main.BACKEND_FASTER)
    )
    window.model_select.setCurrentText("distil-large-v3.5")
    window.start_processing()
    assert "仅支持英语" in warnings[-1][1]
    assert window.worker is None
    window.close()


def test_ui_can_switch_between_english_and_chinese(qapp):
    window = main.App("en")
    assert window.start_button.text() == "Start Processing"
    assert "Audio Subtitle" in window.windowTitle()

    window.display_language_select.setCurrentIndex(
        window.display_language_select.findData("zh_CN")
    )
    assert window.start_button.text() == "开始处理"
    assert window.audio_folder_label.text() == "音频文件夹："
    assert window.progress_label.text().startswith("状态：")

    window.display_language_select.setCurrentIndex(
        window.display_language_select.findData("en")
    )
    assert window.start_button.text() == "Start Processing"
    window.close()


def test_saved_display_language_is_restored_on_normal_startup(
    qapp, isolate_qsettings
):
    isolate_qsettings.setValue("display_language", "zh_CN")
    window = main.App(settings=isolate_qsettings)

    assert window.locale_name == "zh_CN"
    assert window.start_button.text() == "开始处理"
    window.close()


def test_language_switch_does_not_reset_dynamic_running_status(qapp):
    window = main.App("en")
    window.update_progress("Processing: song.mp3", 25)
    window.display_language_select.setCurrentIndex(
        window.display_language_select.findData("zh_CN")
    )
    assert window.progress_label.text() == "Processing: song.mp3"
    window.close()


def test_close_running_worker_requests_stop_and_waits(qapp, monkeypatch):
    window = main.App("en")

    class FakeWorker:
        stopped = False

        def isRunning(self):
            return True

        def stop(self):
            self.stopped = True

    fake_worker = FakeWorker()
    window.worker = fake_worker
    monkeypatch.setattr(
        main.QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    event = QCloseEvent()
    window.closeEvent(event)

    assert fake_worker.stopped is True
    assert window._close_when_worker_finishes is True
    assert event.isAccepted() is False
    assert "waiting" in window.progress_label.text().lower()
    window.worker = None
    window.close()


def test_language_switch_updates_running_worker_locale(qapp):
    window = main.App("en")
    window.worker = SimpleNamespace(isRunning=lambda: True, locale_name="en")
    window.display_language_select.setCurrentIndex(
        window.display_language_select.findData("zh_CN")
    )
    assert window.worker.locale_name == "zh_CN"
    window.worker = None
    window.close()


def test_output_formats_label_is_localized(qapp):
    window = main.App("en")
    assert window.output_formats_label.text() == "Output Formats:"
    window.display_language_select.setCurrentIndex(
        window.display_language_select.findData("zh_CN")
    )
    assert window.output_formats_label.text() == "输出格式："
    window.close()


def test_start_requires_at_least_one_output_format(qapp, monkeypatch):
    window = main.App("zh_CN")
    for checkbox in window.output_format_checks.values():
        checkbox.setChecked(False)
    warnings = []
    monkeypatch.setattr(
        main.QMessageBox,
        "warning",
        lambda _parent, title, text: warnings.append((title, text)),
    )

    window.start_processing()

    assert warnings == [("输入错误", "请至少选择一种输出格式。")]
    assert window.worker is None
    window.close()
