# Wan2GP REST API Plugin

A plugin for [Wan2GP](https://github.com/deepbeepmeep/Wan2GP) that exposes image and video generation capabilities through a local REST API. Any HTTP client can submit generation jobs, poll for progress, and retrieve results programmatically.

## Features

- **Async job submission** — Submit tasks and get a `job_id` immediately (non-blocking)
- **Real-time progress tracking** — Poll job status including phase, step count, and percentage
- **Batch generation** — Submit multiple tasks in a single request via `/jobs/batch`
- **File upload support** — Upload exported settings JSON or ZIP files with media attachments
- **Job cancellation** — Cancel running jobs at any time
- **Swagger UI** — Interactive API docs with full parameter schemas at `/docs`

## Installation

1. Clone or copy this repository into the Wan2GP `plugins/` directory:
   ```bash
   cd /path/to/Wan2GP/plugins
   git clone https://github.com/lightive/wan2gp_rest_api_plugin.git
   ```
2. Launch Wan2GP and navigate to the **Plugins** tab.
3. Enable **"Wan2GP REST API"** and click **Save Settings**.
4. Restart Wan2GP. Dependencies (`requirements.txt`) are installed automatically on activation.

The REST API server starts on `http://127.0.0.1:8000` by default.

## Quick Start

1. Start Wan2GP with the plugin enabled.
2. Open the interactive API docs at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).
3. Submit a test image generation job:
   ```bash
   curl -X POST http://127.0.0.1:8000/jobs \
     -H "Content-Type: application/json" \
     -d '{
       "task": {
         "prompt": "A glass greenhouse filled with tropical plants",
         "resolution": "1024x1024",
         "image_mode": 1,
         "num_inference_steps": 4,
         "model_type": "flux2_klein_9b"
       }
     }'
   ```
4. Check the job status (replace `{job_id}` with the returned ID):
   ```bash
   curl http://127.0.0.1:8000/jobs/{job_id}
   ```
5. When `state` is `"completed"`, the `generated_files` array contains output file paths.

## API Reference

### POST /jobs — Create a single generation job

Submit a single task. The `task` object accepts all [Wan2GP settings parameters](#task-settings-parameters).

**Request:**
```json
{
  "task": {
    "prompt": "A cinematic mountain sunrise",
    "resolution": "1280x720",
    "image_mode": 0,
    "video_length": 241,
    "num_inference_steps": 8,
    "model_type": "ltx2_22B_distilled_gguf_q4_k_m",
    "seed": -1
  }
}
```

**Response:** `202 Accepted`
```json
{"job_id": "550e8400-e29b-41d4-a716-446655440000", "state": "accepted"}
```

### POST /jobs/batch — Create a batch generation job

Submit multiple tasks in a single request. Each item in `tasks` uses the same settings format.

**Request:**
```json
{
  "tasks": [
    {
      "prompt": "A quiet library at sunrise",
      "resolution": "1024x1024",
      "image_mode": 1,
      "num_inference_steps": 4,
      "model_type": "flux2_klein_9b"
    },
    {
      "prompt": "A rainy alley with neon signs",
      "resolution": "1024x1024",
      "image_mode": 1,
      "num_inference_steps": 4,
      "model_type": "flux2_klein_9b"
    }
  ]
}
```

### POST /jobs/upload — Create a job via file upload

Upload a settings file exported from the Wan2GP UI (JSON or ZIP) with optional media attachments.

```
Content-Type: multipart/form-data
```

| Field | Type | Description |
|-------|------|-------------|
| `settings_file` | File (required) | A `.json` or `.zip` settings file exported from Wan2GP |
| `media_files[]` | File(s) (optional) | Reference images or other media inputs |
| `mode` | String (optional) | Submission mode (default: `"task"`) |

**Example with curl:**
```bash
curl -X POST http://127.0.0.1:8000/jobs/upload \
  -F "settings_file=@my_settings.json" \
  -F "media_files[]=@reference.png"
```

### GET /jobs/{job_id} — Get job status

Retrieve the current status and progress of a generation job.

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "state": "running",
  "phase": "inference",
  "raw_phase": "Denoising",
  "status": "Prompt 1/1 | Denoising | 7.2s",
  "progress": 54,
  "current_step": 4,
  "total_steps": 8,
  "generated_files": [],
  "errors": []
}
```

**Job state flow:** `accepted` → `queued` → `running` → `completed` | `failed` | `cancelling` → `cancelled`

| Phase | Description |
|-------|-------------|
| `loading_model` | Loading the model into memory |
| `encoding_text` | Encoding text prompt |
| `inference` | Running denoising steps |
| `decoding` | Decoding latents to pixels |
| `downloading_output` | Saving output files |
| `completed` | Generation finished |
| `cancelled` | Job was cancelled |

### POST /jobs/{job_id}/cancel — Cancel a job

Request cancellation of a running or queued job.

**Response:**
```json
{"job_id": "550e8400-e29b-41d4-a716-446655440000", "state": "cancelling"}
```

---

## Task Settings Parameters

Task settings follow the Wan2GP "Export Settings" JSON format. You can discover every available field for a given model by using the **Export Settings** button in the Wan2GP UI.

The most commonly used parameters are listed below. **Any unlisted field is still accepted and forwarded to Wan2GP as-is.**

### Core Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `prompt` | string | Text prompt describing the desired output |
| `negative_prompt` | string | Negative prompt — concepts to avoid |
| `alt_prompt` | string | Alternative prompt (model-specific) |
| `resolution` | string | Output resolution, e.g. `"1280x720"`, `"1024x1024"` |
| `seed` | integer | Random seed. `-1` for random |
| `num_inference_steps` | integer | Number of denoising steps (more = higher quality, slower) |
| `batch_size` | integer | Number of outputs per task |

### Mode Selection

| Parameter | Type | Description |
|-----------|------|-------------|
| `image_mode` | integer | **`0`** = video generation, **`1`** = image generation |
| `model_type` | string | Wan2GP model identifier (e.g. `"ltx2_22B_distilled_gguf_q4_k_m"`, `"flux2_klein_9b"`) |
| `model_filename` | string | HuggingFace URL or local path to the model weights |
| `model_mode` | integer | Model sub-mode (model-specific) |
| `base_model_type` | string | Base model family (e.g. `"ltx2_22B"`) |

### Video Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `video_length` | integer | Number of frames to generate |
| `video_prompt_type` | string | Video prompt mode (model-specific) |
| `video_guide_outpainting` | string | Outpainting guide settings |
| `keep_frames_video_guide` | string | Frames to keep from video guide |
| `audio_scale` | float | Audio influence scale (audio-to-video models) |
| `audio_prompt_type` | string | Audio prompt mode |

### Sliding Window (Long Video)

For generating videos longer than the model's native context, the sliding window parameters control how segments are stitched together.

| Parameter | Type | Description |
|-----------|------|-------------|
| `sliding_window_size` | integer | Window size in frames |
| `sliding_window_overlap` | integer | Overlap frames between windows |
| `sliding_window_color_correction_strength` | float | Color correction between windows (`0` = off) |
| `sliding_window_overlap_noise` | float | Noise injected at window overlaps |
| `sliding_window_discard_last_frames` | integer | Frames to discard at the end of each window |

### Image Prompt / Inpainting

| Parameter | Type | Description |
|-----------|------|-------------|
| `image_prompt_type` | string | Image prompt mode (e.g. IP-Adapter type) |
| `masking_strength` | float | Inpainting mask strength |
| `mask_expand` | integer | Pixels to expand the mask by |

### LoRA

| Parameter | Type | Description |
|-----------|------|-------------|
| `activated_loras` | array | List of activated LoRA identifiers |
| `loras_multipliers` | string | Per-LoRA weight multipliers |

### Post-Processing

| Parameter | Type | Description |
|-----------|------|-------------|
| `temporal_upsampling` | string | Frame interpolation method |
| `spatial_upsampling` | string | Spatial upscale method |
| `film_grain_intensity` | float | Film grain strength (`0` = off) |
| `film_grain_saturation` | float | Film grain color saturation |

### Advanced

| Parameter | Type | Description |
|-----------|------|-------------|
| `RIFLEx_setting` | integer | RIFLEx position-embedding override |
| `NAG_scale` | float | Normalized Attention Guidance scale |
| `NAG_tau` | float | NAG tau parameter |
| `NAG_alpha` | float | NAG alpha parameter |
| `prompt_enhancer` | string | Prompt enhancer model name (empty = off) |
| `override_profile` | integer | Override VRAM profile (`-1` = auto) |
| `override_attention` | string | Override attention mechanism |

### Self Refiner

| Parameter | Type | Description |
|-----------|------|-------------|
| `self_refiner_setting` | integer | Self-refiner iterations (`0` = off) |
| `self_refiner_plan` | array | Self-refiner step plan |
| `self_refiner_f_uncertainty` | float | Self-refiner uncertainty factor |
| `self_refiner_certain_percentage` | float | Self-refiner certainty threshold |

### Output

| Parameter | Type | Description |
|-----------|------|-------------|
| `output_filename` | string | Custom output filename (empty = auto-generated) |
| `repeat_generation` | integer | Repeat the generation N times |
| `multi_prompts_gen_type` | integer | Multi-prompt generation strategy |
| `multi_images_gen_type` | integer | Multi-image generation strategy |

---

## Full Examples

### Image Generation

Generate a 1024x1024 image using Flux 2 Klein:

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "task": {
      "image_mode": 1,
      "prompt": "A glass greenhouse filled with lush tropical plants, misty air, and dappled light",
      "resolution": "1024x1024",
      "num_inference_steps": 4,
      "seed": -1,
      "batch_size": 1,
      "model_type": "flux2_klein_9b",
      "model_filename": "https://huggingface.co/DeepBeepMeep/Flux2/resolve/main/flux-2-klein-9b_quanto_bf16_int8.safetensors",
      "NAG_scale": 1,
      "NAG_tau": 3.5,
      "NAG_alpha": 0.5
    }
  }'
```

### Video Generation

Generate a 1280x720 video (241 frames) using LTX-2:

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "task": {
      "image_mode": 0,
      "prompt": "A warm sunny backyard, cinematic camera movement with natural lighting",
      "resolution": "1280x720",
      "video_length": 241,
      "num_inference_steps": 8,
      "seed": -1,
      "batch_size": 1,
      "model_type": "ltx2_22B_distilled_gguf_q4_k_m",
      "model_filename": "https://huggingface.co/DeepBeepMeep/LTX-2/resolve/main/ltx-2.3-22b-distilled-Q4_K_M_light.gguf",
      "base_model_type": "ltx2_22B",
      "audio_scale": 1,
      "sliding_window_size": 481,
      "sliding_window_overlap": 17
    }
  }'
```

### Python Client

```python
import time
import requests

BASE_URL = "http://127.0.0.1:8000"

# --- Image generation ---
resp = requests.post(f"{BASE_URL}/jobs", json={
    "task": {
        "image_mode": 1,
        "prompt": "A glass greenhouse filled with tropical plants",
        "resolution": "1024x1024",
        "num_inference_steps": 4,
        "model_type": "flux2_klein_9b",
    }
})
job_id = resp.json()["job_id"]
print(f"Job submitted: {job_id}")

# --- Poll until completion ---
while True:
    status = requests.get(f"{BASE_URL}/jobs/{job_id}").json()
    print(f"  [{status['state']}] {status['phase'] or ''} {status['progress']}%")
    if status["state"] in ("completed", "failed", "cancelled"):
        break
    time.sleep(2)

if status["state"] == "completed":
    print("Generated files:", status["generated_files"])
else:
    print("Errors:", status["errors"])
```

## Error Handling

| Scenario | HTTP Status | Detail |
|----------|-------------|--------|
| Server not ready | `503` | Wan2GP session not initialized |
| Missing or invalid request body | `400` | Validation error with field details |
| Job not found | `404` | Job {job_id} not found |
| Cancel a terminal job | `409` | Job is in state '{state}' and cannot be cancelled |
| Generation failure | — | Job state becomes `failed` with error details in `errors` |

## Project Structure

```
wan2gp_rest_api_plugin/
├── __init__.py          # Package marker
├── plugin.py            # Plugin entry point (lifecycle management)
├── rest_server.py       # FastAPI app, routes, and uvicorn server
├── job_store.py         # Thread-safe job state registry
├── callbacks.py         # Wan2GP callback → job store adapter
├── schemas.py           # Pydantic request/response models + TaskSettings
└── requirements.txt     # Python dependencies
```

## Requirements

- [Wan2GP](https://github.com/deepbeepmeep/Wan2GP)
- Python 3.10+
- Dependencies are auto-installed: `fastapi`, `uvicorn`, `pydantic`, `python-multipart`

## License

This project is provided as-is for use with Wan2GP. See the [Wan2GP repository](https://github.com/deepbeepmeep/Wan2GP) for license details.
