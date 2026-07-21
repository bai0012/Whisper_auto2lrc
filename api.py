"""Local REST API for serial Whisper folder transcription jobs."""

from __future__ import annotations

import argparse
import threading
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from fastapi import FastAPI, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

import core


JobStatus = Literal[
    "queued",
    "running",
    "cancelling",
    "completed",
    "completed_with_errors",
    "failed",
    "cancelled",
]
TERMINAL_STATUSES = {"completed", "completed_with_errors", "failed", "cancelled"}


class QueueFullError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobOptions(BaseModel):
    """Serializable options retained in a job snapshot."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    folder_path: str = Field(min_length=1)
    backend: Literal[core.BACKEND_OPENAI, core.BACKEND_FASTER] = core.DEFAULT_BACKEND
    model: str = Field(default="base", min_length=1)
    language: str = "auto"
    formats: list[Literal["lrc", "srt", "vtt", "txt", "tsv", "json"]] = Field(
        default_factory=lambda: ["lrc"]
    )
    local_model_path: str | None = None
    faster_device: Literal["auto", "cpu", "cuda"] = "auto"
    faster_compute_type: str = "auto"
    locale: Literal["en", "zh_CN"] = "en"


class JobRequest(JobOptions):
    """Validated options for one recursive folder transcription job."""

    @model_validator(mode="after")
    def validate_options(self):
        folder = Path(self.folder_path).expanduser().resolve()
        if not folder.is_dir():
            raise ValueError(f"folder_path is not an existing directory: {folder}")
        self.folder_path = str(folder)
        self.formats = list(dict.fromkeys(self.formats))
        if not self.formats:
            raise ValueError("at least one output format is required")

        is_local = self.local_model_path is not None
        if is_local:
            local_error = core.validate_local_model(
                self.backend, self.local_model_path or ""
            )
            if local_error:
                raise ValueError(local_error)
            self.local_model_path = core.resolved_model_reference(
                self.local_model_path or "", True
            )
        elif self.model not in core.BACKEND_MODELS[self.backend]:
            raise ValueError(
                f"model '{self.model}' is not supported by backend '{self.backend}'"
            )

        effective_model = self.local_model_path if is_local else self.model
        language_error = core.validate_language(
            effective_model or self.model,
            self.language,
            is_local_model=is_local,
        )
        if language_error:
            raise ValueError(language_error)
        self.language = self.language.lower() or "auto"

        legal_compute_types = core.FASTER_COMPUTE_TYPES[self.faster_device]
        if (
            self.faster_compute_type != "auto"
            and self.faster_compute_type not in legal_compute_types
        ):
            raise ValueError(
                f"compute type '{self.faster_compute_type}' is not valid for "
                f"device '{self.faster_device}'"
            )
        return self


class JobResponse(BaseModel):
    """Stable public representation of a queued or completed job."""

    id: str
    request: JobOptions
    status: JobStatus
    progress: int = Field(ge=0, le=100)
    message: str
    errors: list[str]
    error_count: int = Field(ge=0)
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@dataclass
class JobRecord:
    id: str
    request: dict
    status: JobStatus = "queued"
    progress: int = 0
    message: str = "Queued"
    errors: list[str] = field(default_factory=list)
    error_count: int = 0
    created_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def snapshot(self) -> dict:
        return asdict(self)


RunnerFactory = Callable[..., core.TranscriptionRunner]


class JobManager:
    """Thread-safe, single-consumer queue that deliberately serializes GPU work."""

    def __init__(
        self,
        runner_factory: RunnerFactory = core.TranscriptionRunner,
        max_queue_size: int = 100,
        max_errors_per_job: int = 100,
        max_history: int = 1000,
    ):
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be at least 1")
        if max_errors_per_job < 1:
            raise ValueError("max_errors_per_job must be at least 1")
        if max_history <= max_queue_size:
            raise ValueError("max_history must be larger than max_queue_size")
        self._runner_factory = runner_factory
        self.max_queue_size = max_queue_size
        self.max_errors_per_job = max_errors_per_job
        self.max_history = max_history
        self._jobs: dict[str, JobRecord] = {}
        self._queue: deque[str] = deque()
        self._condition = threading.Condition()
        self._thread: threading.Thread | None = None
        self._active_job_id: str | None = None
        self._active_runner: core.TranscriptionRunner | None = None
        self._stopping = False

    def start(self) -> None:
        with self._condition:
            if self._thread and self._thread.is_alive():
                return
            self._stopping = False
            self._thread = threading.Thread(
                target=self._consume, name="whisper-job-queue", daemon=True
            )
            self._thread.start()

    def submit(self, request: JobRequest) -> dict:
        with self._condition:
            if self._stopping:
                raise RuntimeError("job manager is shutting down")
            if len(self._queue) >= self.max_queue_size:
                raise QueueFullError("job queue is full")
            self._prune_terminal_history()
            if len(self._jobs) >= self.max_history:
                raise QueueFullError("job history is full")
            job_id = uuid.uuid4().hex
            record = JobRecord(id=job_id, request=request.model_dump())
            self._jobs[job_id] = record
            self._queue.append(job_id)
            self._condition.notify()
            return record.snapshot()

    def list_jobs(self, limit: int = 100, offset: int = 0) -> list[dict]:
        with self._condition:
            records = sorted(
                self._jobs.values(), key=lambda item: item.created_at, reverse=True
            )
            return [record.snapshot() for record in records[offset : offset + limit]]

    def get(self, job_id: str) -> dict | None:
        with self._condition:
            record = self._jobs.get(job_id)
            return record.snapshot() if record else None

    def cancel(self, job_id: str) -> dict | None:
        with self._condition:
            record = self._jobs.get(job_id)
            if record is None:
                return None
            if record.status == "queued":
                try:
                    self._queue.remove(job_id)
                except ValueError:
                    pass
                record.status = "cancelled"
                record.message = "Cancelled before execution"
                record.finished_at = utc_now()
            elif record.status in {"running", "cancelling"}:
                record.status = "cancelling"
                record.message = "Cancellation requested"
                if self._active_job_id == job_id and self._active_runner:
                    self._active_runner.stop()
            return record.snapshot()

    def shutdown(self, timeout: float | None = None) -> None:
        with self._condition:
            self._stopping = True
            for job_id in tuple(self._queue):
                record = self._jobs[job_id]
                record.status = "cancelled"
                record.message = "Cancelled during server shutdown"
                record.finished_at = utc_now()
            self._queue.clear()
            if self._active_job_id:
                active_record = self._jobs[self._active_job_id]
                if active_record.status == "running":
                    active_record.status = "cancelling"
                    active_record.message = "Cancellation requested during shutdown"
            if self._active_runner:
                self._active_runner.stop()
            self._condition.notify_all()
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    def _consume(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._queue or self._stopping)
                if self._stopping and not self._queue:
                    return
                job_id = self._queue.popleft()
                record = self._jobs[job_id]
                if record.status != "queued":
                    continue
                record.status = "running"
                record.message = "Starting"
                record.started_at = utc_now()
                self._active_job_id = job_id
            self._run_job(job_id)
            with self._condition:
                self._active_job_id = None
                self._active_runner = None

    def _run_job(self, job_id: str) -> None:
        with self._condition:
            record = self._jobs[job_id]
            options = dict(record.request)
        is_local = options["local_model_path"] is not None
        model_name = options["local_model_path"] if is_local else options["model"]
        try:
            runner = self._runner_factory(
                folder_path=Path(options["folder_path"]),
                model_name=model_name,
                language=options["language"],
                output_formats=options["formats"],
                backend_name=options["backend"],
                faster_device_mode=options["faster_device"],
                faster_compute_type=options["faster_compute_type"],
                is_local_model=is_local,
                progress_callback=lambda message, progress: self._record_progress(
                    job_id, message, progress
                ),
                error_callback=lambda message: self._record_error(job_id, message),
                message_formatter=core.core_message_formatter(options["locale"]),
            )
            with self._condition:
                self._active_runner = runner
                cancelling = record.status == "cancelling" or self._stopping
            if cancelling:
                runner.stop()
            # Calling run() in this consumer thread preserves strict serialization.
            runner.run()
            completion_status = runner.completion_status
        except Exception as error:
            completion_status = "failed"
            self._record_error(job_id, str(error))

        with self._condition:
            record = self._jobs[job_id]
            if record.status == "cancelling" and completion_status != "cancelled":
                completion_status = "cancelled"
            if completion_status not in TERMINAL_STATUSES:
                completion_status = "failed"
                self._append_error(
                    record, "Worker returned an invalid completion status"
                )
            record.status = completion_status
            if completion_status.startswith("completed"):
                record.progress = 100
            messages = {
                "completed": "Completed",
                "completed_with_errors": "Completed with errors",
                "cancelled": "Cancelled",
                "failed": "Failed",
            }
            record.message = messages.get(completion_status, record.message)
            record.finished_at = utc_now()

    def _record_progress(self, job_id: str, message: str, progress: int) -> None:
        with self._condition:
            record = self._jobs[job_id]
            record.message = str(message)
            record.progress = max(record.progress, max(0, min(100, int(progress))))

    def _record_error(self, job_id: str, message: str) -> None:
        with self._condition:
            record = self._jobs[job_id]
            self._append_error(record, str(message))
            record.message = str(message)

    def _append_error(self, record: JobRecord, message: str) -> None:
        record.error_count += 1
        if len(record.errors) < self.max_errors_per_job:
            record.errors.append(message)

    def _prune_terminal_history(self) -> None:
        remove_count = max(0, len(self._jobs) - self.max_history + 1)
        if not remove_count:
            return
        terminal_records = sorted(
            (
                record
                for record in self._jobs.values()
                if record.status in TERMINAL_STATUSES
            ),
            key=lambda item: item.finished_at or item.created_at,
        )
        for record in terminal_records[:remove_count]:
            self._jobs.pop(record.id, None)


def create_app(job_manager: JobManager | None = None) -> FastAPI:
    manager = job_manager or JobManager()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        manager.start()
        try:
            yield
        finally:
            manager.shutdown()

    api_app = FastAPI(
        title="Whisper_auto2lrc Batch API", version="1.0.0", lifespan=lifespan
    )
    api_app.state.job_manager = manager

    @api_app.get("/health")
    def health():
        return {"status": "ok", "queue_mode": "serial"}

    @api_app.get("/v1/capabilities")
    def capabilities():
        return {
            "backends": {
                backend: {
                    "models": list(models),
                    "local_model": "file"
                    if backend == core.BACKEND_OPENAI
                    else "directory",
                }
                for backend, models in core.BACKEND_MODELS.items()
            },
            "formats": list(core.OUTPUT_FORMATS),
            "languages": ["auto", *sorted(core.SUPPORTED_LANGUAGE_CODES)],
            "faster_whisper": {
                "devices": list(core.FASTER_DEVICE_MODES),
                "compute_types": {
                    key: list(values)
                    for key, values in core.FASTER_COMPUTE_TYPES.items()
                },
            },
            "queue_mode": "serial",
        }

    @api_app.post(
        "/v1/jobs",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=JobResponse,
    )
    def submit_job(request: JobRequest, response: Response):
        try:
            record = manager.submit(request)
            response.headers["Location"] = f"/v1/jobs/{record['id']}"
            return record
        except QueueFullError as error:
            raise HTTPException(status_code=429, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @api_app.get("/v1/jobs", response_model=list[JobResponse])
    def list_jobs(
        limit: int = Query(default=100, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        return manager.list_jobs(limit=limit, offset=offset)

    @api_app.get("/v1/jobs/{job_id}", response_model=JobResponse)
    def get_job(job_id: str):
        record = manager.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return record

    @api_app.post("/v1/jobs/{job_id}/cancel", response_model=JobResponse)
    def cancel_job(job_id: str):
        existing = manager.get(job_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="job not found")
        if existing["status"] in TERMINAL_STATUSES:
            raise HTTPException(status_code=409, detail="job has already finished")
        record = manager.cancel(job_id)
        if record and record["status"] in TERMINAL_STATUSES - {"cancelled"}:
            raise HTTPException(status_code=409, detail="job has already finished")
        return record

    return api_app


app = create_app()


def main_entry() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main_entry()
