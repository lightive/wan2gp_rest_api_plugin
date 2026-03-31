"""FastAPI application, routes, and uvicorn background thread."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException

from .schemas import (
    BatchTaskRequest,
    CancelResponse,
    ErrorDetail,
    JobCreatedResponse,
    JobListResponse,
    JobStatusResponse,
    JobSummary,
    SingleTaskRequest,
    TaskSettings,
)

if TYPE_CHECKING:
    from .callbacks import JobCallbackAdapter
    from .job_store import JobStore

# --- Module-level references (injected by plugin.py) ---
_store: JobStore | None = None
_session: Any = None  # WanGPSession
_callback_adapter: JobCallbackAdapter | None = None
_submit_lock = threading.Lock()

app = FastAPI(title="Wan2GP REST API", version="1.0.0")


def configure(store: JobStore, session: Any, callback_adapter: JobCallbackAdapter) -> None:
    """Inject dependencies during plugin initialization."""
    global _store, _session, _callback_adapter
    _store = store
    _session = session
    _callback_adapter = callback_adapter


def _require_session() -> None:
    """FastAPI dependency that verifies the session is initialized."""
    if _session is None or _store is None:
        raise HTTPException(503, detail="Wan2GP session not initialized")


def _prepare_settings(task: TaskSettings) -> dict:
    """Convert a TaskSettings model to a Wan2GP settings dict.

    Maps REST API field names to Wan2GP internal names:
      gen_mode -> image_mode
    """
    settings = task.model_dump(exclude_none=True)
    if "gen_mode" in settings:
        settings["image_mode"] = settings.pop("gen_mode")
    return settings


def _submit_and_track(job_id: str, submit_fn) -> None:
    """Submit a job and wire up callback-based completion tracking.

    _submit_lock serializes submissions so that active_job_id is always
    correct for the duration of the submit call and subsequent callbacks.
    Wan2GP processes one job at a time, so serialization is expected.
    """
    with _submit_lock:
        _callback_adapter.active_job_id = job_id
        try:
            session_job = submit_fn()
        except Exception as exc:
            _store.mark_failed(job_id, [{"message": str(exc), "stage": "submission"}])
            return
        _store.mark_running(job_id, session_job)


# --- Endpoints ---

@app.post(
    "/jobs",
    response_model=JobCreatedResponse,
    status_code=202,
    summary="Create a generation job",
    description=(
        "Submit a single generation task. "
        "Task settings follow the Wan2GP 'Export Settings' JSON format. "
        "Use `gen_mode: 1` for image generation and `gen_mode: 0` for video generation."
    ),
    dependencies=[Depends(_require_session)],
)
def create_job(body: SingleTaskRequest):
    """Submit a single generation task."""
    settings = _prepare_settings(body.task)
    record = _store.create("task", request_summary={"task_keys": list(settings.keys())})
    _submit_and_track(record.job_id, lambda: _session.submit_task(settings))
    return JobCreatedResponse(job_id=record.job_id, state="accepted")


@app.post(
    "/jobs/batch",
    response_model=JobCreatedResponse,
    status_code=202,
    summary="Create a batch generation job",
    description="Submit multiple tasks in a single request. Each task uses the same settings format as the single-task endpoint.",
    dependencies=[Depends(_require_session)],
)
def create_job_batch(body: BatchTaskRequest):
    """Submit a batch of generation tasks."""
    tasks_list = [_prepare_settings(t) for t in body.tasks]
    record = _store.create("manifest", request_summary={"task_count": len(tasks_list)})
    _submit_and_track(record.job_id, lambda: _session.submit_manifest(tasks_list))
    return JobCreatedResponse(job_id=record.job_id, state="accepted")


@app.get(
    "/jobs",
    response_model=JobListResponse,
    summary="List all jobs",
    dependencies=[Depends(_require_session)],
)
def list_jobs():
    """Return all jobs ordered by creation time (newest first)."""
    records = _store.list_all()
    return JobListResponse(
        jobs=[
            JobSummary(
                job_id=r.job_id,
                state=r.state,
                progress=r.progress,
                created_at=r.created_at.isoformat(),
                source_type=r.source_type,
            )
            for r in records
        ],
        total=len(records),
    )


@app.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job status",
    dependencies=[Depends(_require_session)],
)
def get_job_status(job_id: str):
    """Retrieve the current status and progress of a generation job."""
    record = _store.get(job_id)
    if record is None:
        raise HTTPException(404, detail=f"Job {job_id} not found")
    return JobStatusResponse(
        job_id=record.job_id,
        state=record.state,
        phase=record.phase,
        raw_phase=record.raw_phase,
        status=record.status,
        progress=record.progress,
        current_step=record.current_step,
        total_steps=record.total_steps,
        generated_files=record.generated_files,
        errors=[
            ErrorDetail(
                message=e.get("message", ""),
                stage=e.get("stage"),
                task_index=e.get("task_index"),
                task_id=e.get("task_id"),
            )
            for e in record.errors
        ],
    )


@app.post(
    "/jobs/{job_id}/cancel",
    response_model=CancelResponse,
    summary="Cancel a job",
    dependencies=[Depends(_require_session)],
)
def cancel_job(job_id: str):
    """Request cancellation of a running or queued job."""
    record = _store.get(job_id)
    if record is None:
        raise HTTPException(404, detail=f"Job {job_id} not found")
    if record.state not in ("accepted", "queued", "running"):
        raise HTTPException(409, detail=f"Job {job_id} is in state '{record.state}' and cannot be cancelled")
    _store.mark_cancelling(job_id)
    if record.session_job is not None:
        try:
            record.session_job.cancel()
        except Exception:
            pass
    return CancelResponse(job_id=record.job_id, state="cancelling")


# --- Server startup ---

def start_server(host: str = "127.0.0.1", port: int = 8000) -> threading.Thread:
    """Start uvicorn as a background daemon thread."""
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="wan2gp-rest-api")
    thread.start()
    print(f"[Wan2GP REST] Server started on http://{host}:{port}")
    return thread
