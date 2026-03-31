"""FastAPI 앱 정의, 라우트, uvicorn 백그라운드 스레드 기동."""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

import uvicorn
from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile

from .schemas import (
    CancelResponse,
    ErrorDetail,
    JobCreatedResponse,
    JobStatusResponse,
)

if TYPE_CHECKING:
    from .callbacks import JobCallbackAdapter
    from .job_store import JobStore

# --- 모듈 레벨 참조 (plugin.py에서 주입) ---
_store: JobStore | None = None
_session: Any = None  # WanGPSession
_callback_adapter: JobCallbackAdapter | None = None
_submit_lock = threading.Lock()

app = FastAPI(title="Wan2GP REST API", version="1.0.0")


def configure(store: JobStore, session: Any, callback_adapter: JobCallbackAdapter) -> None:
    """플러그인 초기화 시 의존성을 주입한다."""
    global _store, _session, _callback_adapter
    _store = store
    _session = session
    _callback_adapter = callback_adapter


def _ensure_initialized() -> None:
    """세션과 스토어가 초기화되었는지 확인한다."""
    if _session is None or _store is None:
        raise HTTPException(503, detail="Wan2GP session not initialized")


def _submit_and_track(job_id: str, submit_fn) -> None:
    """작업을 제출하고 콜백 기반 완료 처리를 설정한다.

    _submit_lock은 active_job_id 설정에만 사용한다.
    submit_fn()이 느릴 수 있으므로 락 밖에서 실행한다.
    완료 처리는 callbacks.py의 on_complete()가 담당한다.
    """
    with _submit_lock:
        _callback_adapter.active_job_id = job_id
    try:
        session_job = submit_fn()
    except Exception as exc:
        _store.mark_failed(job_id, [{"message": str(exc), "stage": "submission"}])
        return
    _store.mark_running(job_id, session_job)


# --- 엔드포인트 ---

@app.post("/jobs", response_model=JobCreatedResponse, status_code=202)
async def create_job(body: dict[str, Any] | None = Body(default=None)):
    """작업을 생성한다. JSON body로 task 또는 tasks(manifest)를 받는다."""
    _ensure_initialized()
    if body is None:
        raise HTTPException(400, detail="Request body is required")

    if "task" in body:
        settings = body["task"]
        record = _store.create("task", request_summary={"task_keys": list(settings.keys())})
        _submit_and_track(record.job_id, lambda: _session.submit_task(settings))
        return JobCreatedResponse(job_id=record.job_id, state="accepted")

    if "tasks" in body:
        tasks_list = body["tasks"]
        if not isinstance(tasks_list, list) or len(tasks_list) == 0:
            raise HTTPException(400, detail="'tasks' must be a non-empty list")
        record = _store.create("manifest", request_summary={"task_count": len(tasks_list)})
        _submit_and_track(record.job_id, lambda: _session.submit_manifest(tasks_list))
        return JobCreatedResponse(job_id=record.job_id, state="accepted")

    raise HTTPException(400, detail="Request must contain 'task' or 'tasks' field")


@app.post("/jobs/upload", response_model=JobCreatedResponse, status_code=202)
async def create_job_multipart(
    settings_file: UploadFile = File(...),
    media_files: list[UploadFile] = File(default=[]),
    mode: str = Form(default="task"),
):
    """multipart/form-data로 settings 파일과 미디어 파일을 업로드하여 작업을 생성한다."""
    _ensure_initialized()

    filename = settings_file.filename or "upload"
    content = await settings_file.read()
    tmp_dir = tempfile.mkdtemp(prefix="wan2gp_job_")

    # 미디어 파일 저장
    for mf in media_files:
        media_path = Path(tmp_dir) / (mf.filename or "media")
        media_content = await mf.read()
        media_path.write_bytes(media_content)

    # .zip 파일은 파일 경로로 제출
    if filename.endswith(".zip"):
        settings_path = Path(tmp_dir) / filename
        settings_path.write_bytes(content)
        record = _store.create("zip_file", request_summary={"filename": filename})
        record.temp_dir = tmp_dir
        _submit_and_track(record.job_id, lambda: _session.submit(settings_path))
        return JobCreatedResponse(job_id=record.job_id, state="accepted")

    # .json 파일은 파싱 후 데이터로 제출
    try:
        settings_data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(400, detail="settings_file must be valid JSON")

    if isinstance(settings_data, list):
        record = _store.create("manifest", request_summary={"task_count": len(settings_data)})
        record.temp_dir = tmp_dir
        _submit_and_track(record.job_id, lambda: _session.submit_manifest(settings_data))
    elif isinstance(settings_data, dict):
        record = _store.create("task", request_summary={"task_keys": list(settings_data.keys())})
        record.temp_dir = tmp_dir
        _submit_and_track(record.job_id, lambda: _session.submit_task(settings_data))
    else:
        raise HTTPException(400, detail="settings_file must contain a JSON object or array")

    return JobCreatedResponse(job_id=record.job_id, state="accepted")


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """작업 상태를 조회한다."""
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


@app.post("/jobs/{job_id}/cancel", response_model=CancelResponse)
async def cancel_job(job_id: str):
    """실행 중인 작업을 취소한다."""
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


# --- 서버 기동 ---

def start_server(host: str = "127.0.0.1", port: int = 8000) -> threading.Thread:
    """uvicorn을 백그라운드 데몬 스레드로 기동한다."""
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="wan2gp-rest-api")
    thread.start()
    print(f"[Wan2GP REST] Server started on http://{host}:{port}")
    return thread
