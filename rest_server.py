"""FastAPI application, routes, and uvicorn background thread."""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from .schemas import (
    BatchTaskRequest,
    CancelResponse,
    ErrorDetail,
    JobCreatedResponse,
    JobStatusResponse,
    SingleTaskRequest,
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


def _ensure_initialized() -> None:
    """Verify that the session and store are initialized."""
    if _session is None or _store is None:
        raise HTTPException(503, detail="Wan2GP session not initialized")


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
        "Submit a single task or a batch of tasks. "
        "Task settings follow the Wan2GP 'Export Settings' JSON format. "
        "Use `image_mode: 1` for image generation and `image_mode: 0` for video generation."
    ),
)
def create_job_single(body: SingleTaskRequest):
    """Submit a single generation task."""
    _ensure_initialized()
    settings = body.task.model_dump(exclude_none=True)
    record = _store.create("task", request_summary={"task_keys": list(settings.keys())})
    _submit_and_track(record.job_id, lambda: _session.submit_task(settings))
    return JobCreatedResponse(job_id=record.job_id, state="accepted")


@app.post(
    "/jobs/batch",
    response_model=JobCreatedResponse,
    status_code=202,
    summary="Create a batch generation job",
    description="Submit multiple tasks in a single request. Each task uses the same settings format as the single-task endpoint.",
)
def create_job_batch(body: BatchTaskRequest):
    """Submit a batch of generation tasks."""
    _ensure_initialized()
    tasks_list = [t.model_dump(exclude_none=True) for t in body.tasks]
    record = _store.create("manifest", request_summary={"task_count": len(tasks_list)})
    _submit_and_track(record.job_id, lambda: _session.submit_manifest(tasks_list))
    return JobCreatedResponse(job_id=record.job_id, state="accepted")


@app.post(
    "/jobs/upload",
    response_model=JobCreatedResponse,
    status_code=202,
    summary="Create a job via file upload",
    description="Upload a settings JSON or ZIP file with optional media attachments.",
)
async def create_job_multipart(
    settings_file: UploadFile = File(..., description="A .json or .zip settings file exported from Wan2GP."),
    media_files: list[UploadFile] = File(default=[], description="Optional media files (images, videos) referenced by the settings."),
    mode: str = Form(default="task", description="Submission mode: 'task' or 'manifest'."),
):
    """Create a generation job from uploaded files."""
    _ensure_initialized()

    filename = settings_file.filename or "upload"
    content = await settings_file.read()
    tmp_dir = tempfile.mkdtemp(prefix="wan2gp_job_")

    # Save media files
    for mf in media_files:
        media_path = Path(tmp_dir) / (mf.filename or "media")
        media_content = await mf.read()
        media_path.write_bytes(media_content)

    # .zip files are submitted by path
    if filename.endswith(".zip"):
        settings_path = Path(tmp_dir) / filename
        settings_path.write_bytes(content)
        record = _store.create("zip_file", request_summary={"filename": filename})
        record.temp_dir = tmp_dir
        await asyncio.to_thread(_submit_and_track, record.job_id, lambda: _session.submit(settings_path))
        return JobCreatedResponse(job_id=record.job_id, state="accepted")

    # .json files are parsed and submitted as data
    try:
        settings_data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(400, detail="settings_file must be valid JSON")

    if isinstance(settings_data, list):
        record = _store.create("manifest", request_summary={"task_count": len(settings_data)})
        record.temp_dir = tmp_dir
        await asyncio.to_thread(_submit_and_track, record.job_id, lambda: _session.submit_manifest(settings_data))
    elif isinstance(settings_data, dict):
        record = _store.create("task", request_summary={"task_keys": list(settings_data.keys())})
        record.temp_dir = tmp_dir
        await asyncio.to_thread(_submit_and_track, record.job_id, lambda: _session.submit_task(settings_data))
    else:
        raise HTTPException(400, detail="settings_file must contain a JSON object or array")

    return JobCreatedResponse(job_id=record.job_id, state="accepted")


@app.get("/jobs/{job_id}", response_model=JobStatusResponse, summary="Get job status")
def get_job_status(job_id: str):
    """Retrieve the current status and progress of a generation job."""
    _ensure_initialized()
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


@app.post("/jobs/{job_id}/cancel", response_model=CancelResponse, summary="Cancel a job")
def cancel_job(job_id: str):
    """Request cancellation of a running or queued job."""
    _ensure_initialized()
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
