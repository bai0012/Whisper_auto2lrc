import threading
import time
import weakref
from types import SimpleNamespace

import core
import main


def test_model_cache_hits_same_name_and_replaces_on_switch():
    cache = main.ModelCache()
    calls = []

    def loader(name):
        calls.append(name)
        return object()

    first, first_hit = cache.get_or_load("base", loader)
    again, second_hit = cache.get_or_load("base", loader)
    switched, switch_hit = cache.get_or_load("small", loader)

    assert first is again
    assert switched is not first
    assert (first_hit, second_hit, switch_hit) == (False, True, False)
    assert calls == ["base", "small"]
    assert cache._model_name == "small"


def test_failed_load_does_not_pollute_cache():
    cache = main.ModelCache()

    def fail(_name):
        raise RuntimeError("load failed")

    try:
        cache.get_or_load("base", fail)
    except RuntimeError:
        pass

    loaded = object()
    model, cache_hit = cache.get_or_load("base", lambda _name: loaded)
    assert model is loaded
    assert cache_hit is False
    assert cache._model_name == "base"


def test_failed_model_switch_releases_previous_model():
    cache = main.ModelCache()
    original = object()
    cache.get_or_load("base", lambda _name: original)

    def fail(_name):
        raise RuntimeError("load failed")

    try:
        cache.get_or_load("small", fail)
    except RuntimeError:
        pass

    assert cache._model_name is None
    assert cache._model is None


def test_model_is_released_before_replacement_loader_runs():
    cache = main.ModelCache()

    class Model:
        pass

    first, _cache_hit = cache.get_or_load("base", lambda _name: Model())
    first_reference = weakref.ref(first)
    del first

    def load_replacement(_name):
        assert first_reference() is None
        return Model()

    cache.get_or_load("small", load_replacement)


def test_concurrent_requests_for_same_model_only_load_once():
    cache = main.ModelCache()
    calls = []
    results = []
    start = threading.Barrier(3)

    def loader(name):
        calls.append(name)
        time.sleep(0.05)
        return object()

    def request_model():
        start.wait()
        results.append(cache.get_or_load("base", loader))

    threads = [threading.Thread(target=request_model) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=1)

    assert all(not thread.is_alive() for thread in threads)
    assert calls == ["base"]
    assert results[0][0] is results[1][0]
    assert sorted(cache_hit for _model, cache_hit in results) == [False, True]


def test_worker_reports_loaded_then_cached_model(tmp_path, monkeypatch):
    calls = []
    model = SimpleNamespace(transcribe=lambda *_args, **_kwargs: {"segments": []})
    monkeypatch.setattr(
        core,
        "whisper",
        SimpleNamespace(load_model=lambda name: calls.append(name) or model),
    )
    (tmp_path / "song.mp3").touch()

    first_messages = []
    first = main.Worker(tmp_path, "base", "auto", "en")
    first.progress.connect(lambda text, _value: first_messages.append(text))
    first.run()

    second_messages = []
    second = main.Worker(tmp_path, "base", "auto", "en")
    second.progress.connect(lambda text, _value: second_messages.append(text))
    second.run()

    assert calls == ["base"]
    assert any("loaded and cached" in message for message in first_messages)
    assert any("Using cached" in message for message in second_messages)


def test_worker_model_load_failure_is_failed_and_uncached(tmp_path, monkeypatch):
    monkeypatch.setattr(
        main,
        "whisper",
        SimpleNamespace(
            load_model=lambda _name: (_ for _ in ()).throw(RuntimeError("bad"))
        ),
    )
    (tmp_path / "song.mp3").touch()
    errors = []
    worker = main.Worker(tmp_path, "base", "auto", "en")
    worker.error_occurred.connect(errors.append)
    worker.run()

    assert worker.completion_status == "failed"
    assert "Failed to load" in errors[0]
    assert main.WHISPER_MODEL_CACHE._model is None
