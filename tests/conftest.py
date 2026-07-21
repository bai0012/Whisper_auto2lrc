import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

import main


@pytest.fixture(scope="session")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture(autouse=True)
def clear_model_cache():
    main.WHISPER_MODEL_CACHE.clear()
    yield
    main.WHISPER_MODEL_CACHE.clear()


@pytest.fixture(autouse=True)
def isolate_qsettings(tmp_path, monkeypatch):
    settings = QSettings(
        str(tmp_path / "settings.ini"), QSettings.Format.IniFormat
    )
    monkeypatch.setattr(main, "create_settings", lambda: settings)
    yield settings
    settings.clear()
    settings.sync()
