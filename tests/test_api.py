import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import api


class FakeSignal:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback

    def emit(self, *args):
        if self.callback:
            self.callback(*args)


class FakeWorker:
    running_count = 0
    max_running_count = 0
    lock = threading.Lock()

    def __init__(self, **options):
        self.options = options
        self.progress = FakeSignal()
        self.error_occurred = FakeSignal()
        self.completion_status = "running"
        self.stopped = False

    def stop(self):
        self.stopped = True

    def run(self):
        with self.lock:
            type(self).running_count += 1
            type(self).max_running_count = max(
                type(self).max_running_count, type(self).running_count
            )
        self.progress.emit("Processing", 50)
        time.sleep(0.02)
        self.completion_status = "cancelled" if self.stopped else "completed"
        with self.lock:
            type(self).running_count -= 1


def wait_for_status(manager, job_id, statuses, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = manager.get(job_id)
        if record["status"] in statuses:
            return record
        time.sleep(0.005)
    raise AssertionError(f"job did not reach {statuses}: {manager.get(job_id)}")


def make_request(folder: Path, **changes):
    values = {"folder_path": str(folder), "model": "base", "formats": ["lrc"]}
    values.update(changes)
    return api.JobRequest(**values)


def test_request_validates_folder_model_language_formats_and_faster_options(tmp_path):
    request = make_request(tmp_path, formats=["lrc", "lrc", "srt"])
    assert request.formats == ["lrc", "srt"]

    invalid_cases = [
        {"folder_path": str(tmp_path / "missing")},
        {"folder_path": str(tmp_path), "model": "not-a-model"},
        {"folder_path": str(tmp_path), "language": "not-a-language"},
        {"folder_path": str(tmp_path), "formats": []},
        {
            "folder_path": str(tmp_path),
            "backend": "faster-whisper",
            "faster_device": "cpu",
            "faster_compute_type": "float16",
        },
    ]
    for values in invalid_cases:
        with pytest.raises(ValidationError):
            api.JobRequest(**values)


def test_request_validates_backend_specific_local_model(tmp_path):
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"model")
    directory = tmp_path / "ct2-model"
    directory.mkdir()

    openai_request = make_request(tmp_path, local_model_path=str(checkpoint))
    faster_request = make_request(
        tmp_path, backend="faster-whisper", local_model_path=str(directory)
    )
    assert openai_request.local_model_path == str(checkpoint.resolve())
    assert faster_request.local_model_path == str(directory.resolve())

    with pytest.raises(ValidationError):
        make_request(tmp_path, backend="faster-whisper", local_model_path=str(checkpoint))


def test_job_manager_runs_jobs_serially_and_maps_worker_options(tmp_path):
    FakeWorker.max_running_count = 0
    created = []

    def factory(**options):
        worker = FakeWorker(**options)
        created.append(worker)
        return worker

    manager = api.JobManager(factory)
    manager.start()
    try:
        first = manager.submit(make_request(tmp_path, formats=["lrc", "srt"]))
        second = manager.submit(make_request(tmp_path, backend="faster-whisper"))
        first_done = wait_for_status(manager, first["id"], {"completed"})
        second_done = wait_for_status(manager, second["id"], {"completed"})
    finally:
        manager.shutdown()

    assert FakeWorker.max_running_count == 1
    assert first_done["progress"] == 100
    assert second_done["finished_at"] is not None
    assert created[0].options["output_formats"] == ["lrc", "srt"]
    assert created[1].options["backend_name"] == "faster-whisper"


def test_job_manager_records_worker_errors_and_completion_status(tmp_path):
    class ErrorWorker(FakeWorker):
        def run(self):
            self.progress.emit("Writing outputs", 75)
            self.error_occurred.emit("one file failed")
            self.completion_status = "completed_with_errors"

    manager = api.JobManager(ErrorWorker)
    manager.start()
    try:
        submitted = manager.submit(make_request(tmp_path))
        record = wait_for_status(manager, submitted["id"], {"completed_with_errors"})
    finally:
        manager.shutdown()

    assert record["progress"] == 100
    assert record["message"] == "Completed with errors"
    assert record["errors"] == ["one file failed"]
    assert record["error_count"] == 1


def test_job_manager_caps_stored_errors_and_shutdown_is_safe(tmp_path):
    entered = threading.Event()

    class ShutdownWorker(FakeWorker):
        def run(self):
            entered.set()
            while not self.stopped:
                time.sleep(0.005)
            for index in range(5):
                self.error_occurred.emit(f"error {index}")
            self.completion_status = "cancelled"

    manager = api.JobManager(ShutdownWorker, max_errors_per_job=2)
    manager.start()
    active = manager.submit(make_request(tmp_path))
    assert entered.wait(1)
    queued = manager.submit(make_request(tmp_path))

    manager.shutdown()

    active_record = manager.get(active["id"])
    queued_record = manager.get(queued["id"])
    assert active_record["status"] == "cancelled"
    assert active_record["error_count"] == 5
    assert active_record["errors"] == ["error 0", "error 1"]
    assert queued_record["status"] == "cancelled"


def test_shutdown_during_worker_construction_preserves_cancellation(tmp_path):
    constructor_entered = threading.Event()
    release_constructor = threading.Event()
    created = []

    def blocking_factory(**options):
        constructor_entered.set()
        assert release_constructor.wait(1)
        worker = FakeWorker(**options)
        created.append(worker)
        return worker

    manager = api.JobManager(blocking_factory)
    manager.start()
    submitted = manager.submit(make_request(tmp_path))
    assert constructor_entered.wait(1)

    shutdown_thread = threading.Thread(target=manager.shutdown)
    shutdown_thread.start()
    assert wait_for_status(manager, submitted["id"], {"cancelling"})
    release_constructor.set()
    shutdown_thread.join(2)

    assert shutdown_thread.is_alive() is False
    assert created[0].stopped is True
    assert manager.get(submitted["id"])["status"] == "cancelled"


def test_job_history_is_bounded_and_list_is_paginated(tmp_path):
    manager = api.JobManager(FakeWorker, max_queue_size=1, max_history=3)
    manager.start()
    submitted_ids = []
    try:
        for _index in range(5):
            record = manager.submit(make_request(tmp_path))
            submitted_ids.append(record["id"])
            wait_for_status(manager, record["id"], {"completed"})

        assert len(manager.list_jobs(limit=10)) == 3
        assert manager.get(submitted_ids[0]) is None
        assert len(manager.list_jobs(limit=1, offset=1)) == 1
    finally:
        manager.shutdown()


def test_job_manager_cancels_queued_and_running_jobs(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    class BlockingWorker(FakeWorker):
        def run(self):
            entered.set()
            release.wait(1)
            self.completion_status = "cancelled" if self.stopped else "completed"

    manager = api.JobManager(BlockingWorker)
    manager.start()
    first = manager.submit(make_request(tmp_path))
    assert entered.wait(1)
    second = manager.submit(make_request(tmp_path))
    assert manager.cancel(second["id"])["status"] == "cancelled"
    assert manager.cancel(first["id"])["status"] == "cancelling"
    release.set()
    try:
        assert wait_for_status(manager, first["id"], {"cancelled"})["status"] == "cancelled"
    finally:
        manager.shutdown()


def test_queue_limit_rejects_submission(tmp_path):
    manager = api.JobManager(FakeWorker, max_queue_size=1)
    manager.submit(make_request(tmp_path))
    with pytest.raises(api.QueueFullError):
        manager.submit(make_request(tmp_path))
    manager.shutdown()


def test_api_endpoints_and_errors(tmp_path):
    manager = api.JobManager(FakeWorker)
    app = api.create_app(manager)
    with TestClient(app) as client:
        assert client.get("/health").json() == {
            "status": "ok",
            "queue_mode": "serial",
        }
        capabilities = client.get("/v1/capabilities").json()
        assert "openai-whisper" in capabilities["backends"]
        assert "lrc" in capabilities["formats"]

        response = client.post(
            "/v1/jobs",
            json={"folder_path": str(tmp_path), "formats": ["lrc", "vtt"]},
        )
        assert response.status_code == 202
        job_id = response.json()["id"]
        assert response.headers["location"] == f"/v1/jobs/{job_id}"
        assert client.get(f"/v1/jobs/{job_id}").status_code == 200
        assert any(item["id"] == job_id for item in client.get("/v1/jobs").json())
        assert len(client.get("/v1/jobs?limit=1&offset=0").json()) == 1
        wait_for_status(manager, job_id, {"completed"})
        assert client.post(f"/v1/jobs/{job_id}/cancel").status_code == 409
        assert client.get("/v1/jobs/missing").status_code == 404
        assert client.post("/v1/jobs/missing/cancel").status_code == 404


def test_api_returns_422_for_invalid_request_and_429_for_full_queue(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    class BlockingWorker(FakeWorker):
        def run(self):
            entered.set()
            release.wait(1)
            self.completion_status = "completed"

    manager = api.JobManager(BlockingWorker, max_queue_size=1)
    app = api.create_app(manager)
    with TestClient(app) as client:
        assert client.post("/v1/jobs", json={"folder_path": "missing"}).status_code == 422
        assert client.post("/v1/jobs", json={"folder_path": str(tmp_path)}).status_code == 202
        assert entered.wait(1)
        assert client.post("/v1/jobs", json={"folder_path": str(tmp_path)}).status_code == 202
        assert client.post("/v1/jobs", json={"folder_path": str(tmp_path)}).status_code == 429
        release.set()
