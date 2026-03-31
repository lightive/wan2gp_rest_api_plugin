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
    negative_prompt: str | None = Field(None, description="Negative prompt – concepts to avoid.")
    alt_prompt: str | None = Field(None, description="Alternative prompt (model-specific).")
    resolution: str | None = Field(None, description="Output resolution, e.g. '1280x720', '1024x1024'.")
    seed: int | None = Field(None, description="Random seed. -1 for random.")
    num_inference_steps: int | None = Field(None, description="Number of denoising steps.")
    batch_size: int | None = Field(None, description="Number of outputs per task.")

    # -- Mode ---------------------------------------------------------------
    image_mode: int | None = Field(None, description="0 = video generation, 1 = image generation.")
    model_type: str | None = Field(None, description="Wan2GP model identifier, e.g. 'ltx2_22B_distilled_gguf_q4_k_m'.")
    model_filename: str | None = Field(None, description="HuggingFace URL or local path to the model file.")
    model_mode: int | None = Field(None, description="Model sub-mode (model-specific).")

    # -- Video --------------------------------------------------------------
    video_length: int | None = Field(None, description="Number of frames to generate.")
    video_prompt_type: str | None = Field(None, description="Video prompt mode (model-specific).")
    video_guide_outpainting: str | None = Field(None, description="Outpainting guide settings.")
    keep_frames_video_guide: str | None = Field(None, description="Frames to keep from video guide.")
    audio_scale: float | None = Field(None, description="Audio influence scale (audio-to-video models).")
    audio_prompt_type: str | None = Field(None, description="Audio prompt mode.")

    # -- Sliding window (long video) ----------------------------------------
    sliding_window_size: int | None = Field(None, description="Sliding window size in frames.")
    sliding_window_overlap: int | None = Field(None, description="Overlap frames between windows.")
    sliding_window_color_correction_strength: float | None = Field(None, description="Color correction between windows (0 = off).")
    sliding_window_overlap_noise: float | None = Field(None, description="Noise injected at window overlaps.")
    sliding_window_discard_last_frames: int | None = Field(None, description="Frames to discard at the end of each window.")

    # -- Image prompt -------------------------------------------------------
    image_prompt_type: str | None = Field(None, description="Image prompt mode (e.g. IP-Adapter type).")
    masking_strength: float | None = Field(None, description="Inpainting mask strength.")
    mask_expand: int | None = Field(None, description="Pixels to expand the mask by.")

    # -- LoRA ---------------------------------------------------------------
    activated_loras: list[Any] | None = Field(None, description="List of activated LoRA identifiers.")
    loras_multipliers: str | None = Field(None, description="Per-LoRA weight multipliers.")

    # -- Post-processing ----------------------------------------------------
    temporal_upsampling: str | None = Field(None, description="Frame interpolation method.")
    spatial_upsampling: str | None = Field(None, description="Spatial upscale method.")
    film_grain_intensity: float | None = Field(None, description="Film grain strength (0 = off).")
    film_grain_saturation: float | None = Field(None, description="Film grain color saturation.")

    # -- Advanced -----------------------------------------------------------
    RIFLEx_setting: int | None = Field(None, description="RIFLEx position-embedding override.")
    NAG_scale: float | None = Field(None, description="Normalized Attention Guidance scale.")
    NAG_tau: float | None = Field(None, description="NAG tau parameter.")
    NAG_alpha: float | None = Field(None, description="NAG alpha parameter.")
    prompt_enhancer: str | None = Field(None, description="Prompt enhancer model name (empty = off).")
    override_profile: int | None = Field(None, description="Override VRAM profile (-1 = auto).")
    override_attention: str | None = Field(None, description="Override attention mechanism.")

    # -- Self Refiner (iterative quality) -----------------------------------
    self_refiner_setting: int | None = Field(None, description="Self-refiner iterations (0 = off).")
    self_refiner_plan: list[Any] | None = Field(None, description="Self-refiner step plan.")
    self_refiner_f_uncertainty: float | None = Field(None, description="Self-refiner uncertainty factor.")
    self_refiner_certain_percentage: float | None = Field(None, description="Self-refiner certainty threshold.")

    # -- Repetition / batch -------------------------------------------------
    repeat_generation: int | None = Field(None, description="Repeat the generation N times.")
    multi_prompts_gen_type: int | None = Field(None, description="Multi-prompt generation strategy.")
    multi_images_gen_type: int | None = Field(None, description="Multi-image generation strategy.")

    # -- Output -------------------------------------------------------------
    output_filename: str | None = Field(None, description="Custom output filename (empty = auto).")
    mode: str | None = Field(None, description="Submission mode hint.")

    # -- Metadata (informational, not used by generation) -------------------
    settings_version: float | None = Field(None, description="Settings format version.")
    base_model_type: str | None = Field(None, description="Base model family identifier.")


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
    errors: list[ErrorDetail] = Field(default_factory=list)


class CancelResponse(BaseModel):
    """POST /jobs/{job_id}/cancel response."""
    job_id: str
    state: JobState = "cancelling"


class ErrorResponse(BaseModel):
    """Error response wrapper."""
    error: ErrorDetail


def serialize_wan2gp_error(error) -> dict:
    """Convert a Wan2GP GenerationError to a REST-friendly dict."""
    return {
        "message": getattr(error, "message", str(error)),
        "stage": getattr(error, "stage", None),
        "task_index": getattr(error, "task_index", None),
        "task_id": getattr(error, "task_id", None),
    }
