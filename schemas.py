"""Wan2GP REST API request/response Pydantic models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Task settings – mirrors Wan2GP's "Export Settings" JSON format.
# All fields are optional because different models require different subsets.
# Extra fields are forwarded to Wan2GP as-is (`extra = "allow"`).
# ---------------------------------------------------------------------------

class TaskSettings(BaseModel):
    """Generation settings passed directly to the Wan2GP session.

    Use the Wan2GP UI "Export Settings" button to discover every available
    field for a given model.  The fields listed below are the most commonly
    used ones; any unlisted field is still accepted and forwarded.
    """

    model_config = ConfigDict(extra="allow")

    # -- Core ---------------------------------------------------------------
    prompt: str | None = Field(None, description="Text prompt describing the desired output.")
    negative_prompt: str | None = Field(None, description="Negative prompt — concepts to avoid.")
    resolution: str | None = Field(None, description="Output resolution, e.g. '1280x720', '1024x1024'.")
    seed: int | None = Field(None, description="Random seed. -1 for random.")
    num_inference_steps: int | None = Field(None, description="Number of denoising steps.")
    batch_size: int | None = Field(None, description="Number of outputs per task.")

    # -- Mode ---------------------------------------------------------------
    image_mode: Literal[0, 1] | None = Field(None, description="0 = video generation, 1 = image generation.")
    model_type: str | None = Field(None, description="Wan2GP model identifier, e.g. 'ltx2_22B_distilled_gguf_q4_k_m'.")
    model_filename: str | None = Field(None, description="HuggingFace URL or local path to the model file.")

    # -- Video --------------------------------------------------------------
    video_length: int | None = Field(None, description="Number of frames to generate.")


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class SingleTaskRequest(BaseModel):
    """Submit a single generation task."""
    task: TaskSettings


class BatchTaskRequest(BaseModel):
    """Submit multiple generation tasks."""
    tasks: list[TaskSettings] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

JobState = Literal[
    "accepted", "queued", "running",
    "completed", "failed", "cancelling", "cancelled",
]


class JobCreatedResponse(BaseModel):
    """POST /jobs response."""
    job_id: str
    state: JobState = "accepted"


class ErrorDetail(BaseModel):
    """Serialized Wan2GP GenerationError."""
    message: str
    stage: str | None = None
    task_index: int | None = None
    task_id: Any | None = None


class DownloadLink(BaseModel):
    """A downloadable link for a generated file."""
    filename: str = Field(..., description="Output filename.")
    download_url: str = Field(..., description="URL to download the file via the REST API.")


class JobStatusResponse(BaseModel):
    """GET /jobs/{job_id} response."""
    job_id: str
    state: JobState
    phase: str | None = None
    raw_phase: str | None = None
    status: str | None = None
    progress: int = 0
    current_step: int | None = None
    total_steps: int | None = None
    generated_files: list[str] = Field(default_factory=list)
    download_links: list[DownloadLink] = Field(default_factory=list)
    errors: list[ErrorDetail] = Field(default_factory=list)


class JobSummary(BaseModel):
    """Compact job info for list responses."""
    job_id: str
    state: JobState
    progress: int = 0
    created_at: str
    source_type: str


class JobListResponse(BaseModel):
    """GET /jobs response."""
    jobs: list[JobSummary]
    total: int


class CancelResponse(BaseModel):
    """POST /jobs/{job_id}/cancel response."""
    job_id: str
    state: JobState = "cancelling"


class UploadedFile(BaseModel):
    """A single uploaded file descriptor."""
    filename: str = Field(..., description="Original filename.")
    path: str = Field(..., description="Absolute server-side path. Use this value in task settings (e.g. image_start).")


class UploadResponse(BaseModel):
    """POST /uploads response."""
    job_id: str = Field(..., description="Upload group ID — pass to the task or use for cleanup.")
    files: list[UploadedFile]


def serialize_wan2gp_error(error) -> dict:
    """Convert a Wan2GP GenerationError to a REST-friendly dict."""
    return {
        "message": getattr(error, "message", str(error)),
        "stage": getattr(error, "stage", None),
        "task_index": getattr(error, "task_index", None),
        "task_id": getattr(error, "task_id", None),
    }
