"""FastAPI application, routes, and uvicorn background thread."""

from __future__ import annotations

import threading
import uuid
from typing import TYPE_CHECKING, Any

import uvicorn
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile

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
    UploadedFile,
    UploadResponse,
)
from .uploads import UploadManager

if TYPE_CHECKING:
    from .callbacks import JobCallbackAdapter
    from .job_store import JobStore

# --- Module-level references (injected by plugin.py) ---
_store: JobStore | None = None
_session: Any = None  # WanGPSession
_callback_adapter: JobCallbackAdapter | None = None
_upload_manager: UploadManager | None = None
_submit_lock = threading.Lock()

app = FastAPI(title="Wan2GP REST API", version="1.0.0")


def configure(
    store: JobStore,
    session: Any,
    callback_adapter: JobCallbackAdapter,
    upload_manager: UploadManager | None = None,
) -> None:
    """Inject dependencies during plugin initialization."""
    global _store, _session, _callback_adapter, _upload_manager
    _store = store
    _session = session
    _callback_adapter = callback_adapter
    _upload_manager = upload_manager or UploadManager()


def _require_session() -> None:
    """FastAPI dependency that verifies all services are initialized."""
    if _session is None or _store is None or _upload_manager is None:
        raise HTTPException(503, detail="Wan2GP session not initialized")


def _prepare_settings(task: TaskSettings, job_id: str) -> dict:
    """Convert a TaskSettings model to a Wan2GP settings dict.

    Any base64 data-URI values in recognised attachment keys
    (e.g. ``image_start``) are decoded and saved to disk so that
    Wan2GP receives ordinary file paths.
    """
    settings = task.model_dump(exclude_none=True)
    _upload_manager.resolve_data_uris(settings, job_id)
    return settings


def _submit_and_track(job_id: str, submit_fn) -> None:
    """Submit a job and wire up callback-based completion tracking.

    _submit_lock serializes submissions so that active_job_id is always
    correct for the duration of the submit call and subsequent callbacks.
    Wan2GP processes one job at a time, so serialization is expected.
    """
    with _submit_lock:
        _callback_adapter.set_active_job(job_id)
        try:
            session_job = submit_fn()
        except Exception as exc:
            _store.mark_failed(job_id, [{"message": str(exc), "stage": "submission"}])
            _upload_manager.cleanup_job(job_id)
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
        "Use `image_mode: 1` for image generation and `image_mode: 0` for video generation."
    ),
    dependencies=[Depends(_require_session)],
)
def create_job(body: SingleTaskRequest):
    """Submit a single generation task."""
    record = _store.create("task", request_summary={"task_keys": list(body.task.model_fields_set)})
    try:
        settings = _prepare_settings(body.task, record.job_id)
    except ValueError as exc:
        _store.mark_failed(record.job_id, [{"message": str(exc), "stage": "validation"}])
        _upload_manager.cleanup_job(record.job_id)
        raise HTTPException(422, detail=str(exc))
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
    record = _store.create("manifest", request_summary={"task_count": len(body.tasks)})
    try:
        tasks_list = [_prepare_settings(t, record.job_id) for t in body.tasks]
    except ValueError as exc:
        _store.mark_failed(record.job_id, [{"message": str(exc), "stage": "validation"}])
        _upload_manager.cleanup_job(record.job_id)
        raise HTTPException(422, detail=str(exc))
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
    outcome, session_job = _store.try_cancel(job_id)
    if outcome == "not_found":
        raise HTTPException(404, detail=f"Job {job_id} not found")
    if outcome == "rejected":
        raise HTTPException(409, detail=f"Job {job_id} cannot be cancelled")
    if session_job is not None:
        try:
            session_job.cancel()
        except Exception:
            pass
    return CancelResponse(job_id=job_id, state="cancelling")


@app.post(
    "/uploads",
    response_model=UploadResponse,
    status_code=201,
    summary="Upload media files",
    description=(
        "Upload one or more image/video/audio files. "
        "Returns absolute server-side paths that can be used in task settings "
        "(e.g. ``image_start``, ``image_end``, ``video_source``)."
    ),
    dependencies=[Depends(_require_session)],
)
async def upload_files(files: list[UploadFile] = File(..., description="Media files to upload.")):
    """Accept multipart file uploads and return on-disk paths."""
    group_id = uuid.uuid4().hex[:16]
    results: list[UploadedFile] = []
    for f in files:
        data = await f.read()
        if not data:
            continue
        path = _upload_manager.save_file(group_id, f.filename or "upload.bin", data)
        results.append(UploadedFile(filename=f.filename or "upload.bin", path=path))
    if not results:
        raise HTTPException(400, detail="No valid files uploaded")
    return UploadResponse(job_id=group_id, files=results)


# --- Server startup ---

def start_server(host: str = "127.0.0.1", port: int = 8000) -> threading.Thread:
    """Start uvicorn as a background daemon thread."""
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="wan2gp-rest-api")
    thread.start()
    print(f"[Wan2GP REST] Server started on http://{host}:{port}")
    return thread
