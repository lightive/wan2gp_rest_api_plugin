"""스레드 안전 Job 상태 레지스트리."""

from __future__ import annotations

import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .schemas import JobState


@dataclass
class JobRecord:
    """REST API에서 관리하는 단일 작업 레코드."""
    job_id: str
    created_at: datetime
    updated_at: datetime
    state: JobState
    source_type: str
    session_job: Any | None = None

    # Wan2GP 진행 상태 스냅샷
    phase: str | None = None
    raw_phase: str | None = None
    status: str | None = None
    progress: int = 0
    current_step: int | None = None
    total_steps: int | None = None

    # 결과
    generated_files: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    # 메타데이터
    request_summary: dict = field(default_factory=dict)
    temp_dir: str | None = None


_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
_EVICT_AGE_SECONDS = 3600  # 완료 후 1시간 경과 시 eviction


class JobStore:
    """UUID→JobRecord 매핑을 스레드 안전하게 관리한다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, JobRecord] = {}

    # --- 내부 헬퍼 ---

    def _transition(self, job_id: str, **fields: Any) -> None:
        """락을 잡고 레코드 필드를 업데이트하는 공통 메서드.
        터미널 상태인 레코드는 무시한다 (이중 완료 방지).
        """
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            # 이미 터미널 상태면 중복 전이 무시
            if record.state in _TERMINAL_STATES:
                return
            for k, v in fields.items():
                setattr(record, k, v)
            record.updated_at = datetime.now(timezone.utc)

    def _evict_stale(self) -> None:
        """터미널 상태에서 일정 시간 경과한 레코드를 제거하고 temp 디렉토리를 정리한다."""
        now = datetime.now(timezone.utc)
        to_remove: list[str] = []
        with self._lock:
            for jid, rec in self._jobs.items():
                if rec.state in _TERMINAL_STATES:
                    age = (now - rec.updated_at).total_seconds()
                    if age > _EVICT_AGE_SECONDS:
                        to_remove.append(jid)
            for jid in to_remove:
                rec = self._jobs.pop(jid)
                if rec.temp_dir:
                    shutil.rmtree(rec.temp_dir, ignore_errors=True)

    # --- 공개 메서드 ---

    def create(self, source_type: str, request_summary: dict | None = None) -> JobRecord:
        """새 JobRecord를 생성하고 store에 등록한다."""
        self._evict_stale()
        now = datetime.now(timezone.utc)
        job_id = str(uuid.uuid4())
        record = JobRecord(
            job_id=job_id,
            created_at=now,
            updated_at=now,
            state="accepted",
            source_type=source_type,
            request_summary=request_summary or {},
        )
        with self._lock:
            self._jobs[job_id] = record
        return record

    def get(self, job_id: str) -> JobRecord | None:
        """job_id로 레코드를 조회한다."""
        with self._lock:
            return self._jobs.get(job_id)

    def update_progress(
        self,
        job_id: str,
        *,
        phase: str | None = None,
        raw_phase: str | None = None,
        status: str | None = None,
        progress: int | None = None,
        current_step: int | None = None,
        total_steps: int | None = None,
    ) -> None:
        """진행 상태를 업데이트한다."""
        fields: dict[str, Any] = {"state": "running"}
        if phase is not None:
            fields["phase"] = phase
        if raw_phase is not None:
            fields["raw_phase"] = raw_phase
        if status is not None:
            fields["status"] = status
        if progress is not None:
            fields["progress"] = progress
        if current_step is not None:
            fields["current_step"] = current_step
        if total_steps is not None:
            fields["total_steps"] = total_steps
        self._transition(job_id, **fields)

    def mark_running(self, job_id: str, session_job: Any) -> None:
        """작업을 실행 상태로 전환하고 session_job 참조를 저장한다."""
        self._transition(job_id, state="running", session_job=session_job)

    def mark_completed(self, job_id: str, generated_files: list[str]) -> None:
        """작업을 완료 상태로 전환한다."""
        self._transition(
            job_id,
            state="completed", progress=100,
            phase="completed", status="done",
            generated_files=generated_files,
        )

    def mark_failed(
        self, job_id: str, errors: list[dict],
        generated_files: list[str] | None = None,
    ) -> None:
        """작업을 실패 상태로 전환한다."""
        fields: dict[str, Any] = {
            "state": "failed", "phase": "error", "errors": errors,
        }
        if generated_files:
            fields["generated_files"] = generated_files
        self._transition(job_id, **fields)

    def add_error(self, job_id: str, error: dict) -> None:
        """에러를 락 안에서 안전하게 추가한다."""
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            record.errors.append(error)

    def mark_cancelling(self, job_id: str) -> None:
        """작업을 취소 요청 상태로 전환한다."""
        self._transition(job_id, state="cancelling")

    def mark_cancelled(self, job_id: str) -> None:
        """작업을 취소 완료 상태로 전환한다."""
        self._transition(job_id, state="cancelled", phase="cancelled")
