"""Wan2GP REST API의 요청/응답 Pydantic 모델."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# --- 응답 모델 ---

JobState = Literal[
    "accepted", "queued", "running",
    "completed", "failed", "cancelling", "cancelled",
]


class JobCreatedResponse(BaseModel):
    """POST /jobs 응답."""
    job_id: str
    state: JobState = "accepted"


class ErrorDetail(BaseModel):
    """Wan2GP GenerationError를 REST 응답용으로 직렬화한 모델."""
    message: str
    stage: str | None = None
    task_index: int | None = None
    task_id: Any | None = None


class JobStatusResponse(BaseModel):
    """GET /jobs/{job_id} 응답."""
    job_id: str
    state: JobState
    phase: str | None = None
    raw_phase: str | None = None
    status: str | None = None
    progress: int = 0
    current_step: int | None = None
    total_steps: int | None = None
    generated_files: list[str] = Field(default_factory=list)
    errors: list[ErrorDetail] = Field(default_factory=list)


class CancelResponse(BaseModel):
    """POST /jobs/{job_id}/cancel 응답."""
    job_id: str
    state: JobState = "cancelling"


class ErrorResponse(BaseModel):
    """에러 응답 래퍼."""
    error: ErrorDetail


def serialize_wan2gp_error(error) -> dict:
    """Wan2GP GenerationError 객체를 REST 응답용 dict로 변환한다."""
    return {
        "message": getattr(error, "message", str(error)),
        "stage": getattr(error, "stage", None),
        "task_index": getattr(error, "task_index", None),
        "task_id": getattr(error, "task_id", None),
    }
