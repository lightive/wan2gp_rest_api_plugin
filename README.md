# Wan2GP REST API Plugin

A [Wan2GP](https://github.com/deepbeepmeep/Wan2GP) plugin that exposes image and video generation via a local REST API. Submit jobs, track progress, and retrieve results from any HTTP client.

## Getting Started

1. **Install Wan2GP** — One-click installation with [Pinokio](https://pinokio.co/), or follow the [manual setup](https://github.com/deepbeepmeep/Wan2GP).
2. **Open Wan2GP Web UI** — In your browser, navigate to `http://127.0.0.1:42003`.
3. **Install the plugin** — In Wan2GP, go to the **Plugins** tab, paste the URL below, and click install:
   ```
   https://github.com/lightive/wan2gp_rest_api_plugin
   ```
4. **Enable & restart** — Check **"Wan2GP REST API"**, click **Save Settings**, then restart Wan2GP.
5. **Ready** — The API is live at `http://127.0.0.1:7989`. Open `/docs` for interactive Swagger UI.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/jobs` | Submit a single generation task |
| `POST` | `/jobs/batch` | Submit multiple tasks at once |
| `GET` | `/jobs` | List all jobs (newest first) |
| `GET` | `/jobs/{job_id}` | Poll job status and progress |
| `POST` | `/jobs/{job_id}/cancel` | Cancel a running job |
| `GET` | `/jobs/{job_id}/download/{index}` | Download a generated file by index |
| `POST` | `/uploads` | Upload media files (returns server-side paths) |

**Response** (`202 Accepted`):
```json
{"job_id": "550e8400-...", "state": "accepted"}
```

**Job state flow:** `accepted` → `queued` → `running` → `completed` | `failed` | `cancelling` → `cancelled`

## Task Settings

Settings follow the Wan2GP **Export Settings** JSON format. Use the Export Settings button in the Wan2GP UI to discover all available fields for a given model. **Any unlisted field is still accepted and forwarded to Wan2GP.**

| Parameter | Type | Description |
|-----------|------|-------------|
| `image_mode` | int | `0` = video, `1` = image |
| `prompt` | str | Text prompt |
| `negative_prompt` | str | Concepts to avoid |
| `resolution` | str | e.g. `"1280x720"`, `"1024x1024"` |
| `num_inference_steps` | int | Denoising steps (more = higher quality) |
| `seed` | int | Random seed (`-1` = random) |
| `model_type` | str | Model ID (e.g. `"flux2_klein_9b"`, `"ltx2_22B_distilled_gguf_q4_k_m"`) |
| `model_filename` | str | HuggingFace URL or local path to model weights |
| `video_length` | int | Number of frames (video only) |
| `batch_size` | int | Outputs per task |

<details>
<summary><b>Video &amp; Sliding Window</b></summary>

| Parameter | Type | Description |
|-----------|------|-------------|
| `video_prompt_type` | str | Video prompt mode |
| `image_prompt_type` | str | Image prompt mode — `"S"` for start image, `"E"` for end image, `"SE"` for both, `""` for none |
| `audio_scale` | float | Audio influence scale |
| `sliding_window_size` | int | Window size in frames |
| `sliding_window_overlap` | int | Overlap frames between windows |
| `sliding_window_color_correction_strength` | float | Color correction (`0` = off) |
| `sliding_window_overlap_noise` | float | Noise at window overlaps |
| `sliding_window_discard_last_frames` | int | Frames to discard per window |

</details>

<details>
<summary><b>LoRA, Post-Processing &amp; Advanced</b></summary>

| Parameter | Type | Description |
|-----------|------|-------------|
| `activated_loras` | array | LoRA identifiers |
| `loras_multipliers` | str | Per-LoRA weights |
| `temporal_upsampling` | str | Frame interpolation |
| `spatial_upsampling` | str | Spatial upscale |
| `film_grain_intensity` | float | Film grain (`0` = off) |
| `NAG_scale` | float | Normalized Attention Guidance scale |
| `NAG_tau` | float | NAG tau |
| `NAG_alpha` | float | NAG alpha |
| `RIFLEx_setting` | int | RIFLEx override |
| `prompt_enhancer` | str | Prompt enhancer (empty = off) |
| `override_profile` | int | VRAM profile (`-1` = auto) |
| `self_refiner_setting` | int | Self-refiner iterations (`0` = off) |
| `output_filename` | str | Custom filename (empty = auto) |

</details>

## Attaching Media Files

Wan2GP accepts files for attachment keys such as `image_start`, `image_end`, `image_refs`, `video_source`, etc. There are two ways to provide these:

### Option A: Multipart Upload (Recommended)

Upload files first via `POST /uploads`, then use the returned paths in task settings. The plugin automatically handles file path resolution — you can paste the returned path directly into your job request.

```bash
# 1. Upload
curl -X POST http://127.0.0.1:7989/uploads \
  -F "files=@start_frame.png"

# Response: {"job_id": "abc123", "files": [{"filename": "start_frame.png", "path": "H:\\pinokio\\api\\wan.git\\app\\plugins\\wan2gp_rest_api_plugin\\_uploads\\abc123\\start_frame.png"}]}

# 2. Use the returned path directly in a job
curl -X POST http://127.0.0.1:7989/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "task": {
      "image_mode": 0,
      "image_prompt_type": "S",
      "prompt": "A sunrise over mountains",
      "image_start": "H:\\pinokio\\api\\wan.git\\app\\plugins\\wan2gp_rest_api_plugin\\_uploads\\abc123\\start_frame.png",
      "resolution": "1280x720",
      "video_length": 81
    }
  }'
```

> **Note:** Upload paths are automatically re-encoded and saved under the job directory internally, so they remain available throughout the entire generation pipeline. No manual path manipulation is needed.

### Option B: Inline Base64 Data-URI

Embed images directly in the task JSON as `data:<mime>;base64,<data>` values. They are decoded and saved to disk automatically.

```bash
curl -X POST http://127.0.0.1:7989/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "task": {
      "image_mode": 0,
      "prompt": "A sunrise over mountains",
      "image_start": "data:image/png;base64,iVBORw0KGgo...",
      "resolution": "1280x720",
      "video_length": 81
    }
  }'
```

Supported attachment keys: `image_start`, `image_end`, `image_refs`, `image_guide`, `image_mask`, `video_guide`, `video_mask`, `video_source`, `audio_guide`, `audio_guide2`, `audio_source`, `custom_guide`.

## Full Examples

### Image Generation (Flux 2 Klein, 1024x1024)

```bash
curl -X POST http://127.0.0.1:7989/jobs \
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

### Video Generation (LTX-2, 1280x720, 241 frames)

```bash
curl -X POST http://127.0.0.1:7989/jobs \
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

### Video Generation from Start Image

To generate video from a reference image, upload the image first and include `image_prompt_type: "S"` along with the uploaded path:

```bash
# 1. Upload the start image
curl -X POST http://127.0.0.1:7989/uploads \
  -F "files=@reference.png"

# 2. Extract the path from the response, then submit the job
curl -X POST http://127.0.0.1:7989/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "task": {
      "image_mode": 0,
      "image_prompt_type": "S",
      "image_start": "/path/from/upload/response.png",
      "prompt": "The garden comes alive with blooming flowers",
      "resolution": "1280x720",
      "video_length": 241,
      "num_inference_steps": 8,
      "seed": -1,
      "batch_size": 1,
      "model_type": "ltx2_22B_distilled_gguf_q4_k_m",
      "model_filename": "https://huggingface.co/DeepBeepMeep/LTX-2/resolve/main/ltx-2.3-22b-distilled-Q4_K_M_light.gguf",
      "base_model_type": "ltx2_22B",
      "sliding_window_size": 481,
      "sliding_window_overlap": 17
    }
  }'
```

> **Important:** The `image_prompt_type` field controls how attachment images are processed:
> - `"S"` — Use `image_start` (start image / first frame)
> - `"E"` — Use `image_end` (end image / last frame)
> - `"SE"` — Use both `image_start` and `image_end`
> - `""` — No attachment image (text-to-video only)
>
> Models that don't support start images will return a validation error.

### Video Generation with Start and End Images (Image-to-Video Interpolation)

```bash
curl -X POST http://127.0.0.1:7989/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "task": {
      "image_mode": 0,
      "image_prompt_type": "SE",
      "image_start": "/path/to/start.png",
      "image_end": "/path/to/end.png",
      "prompt": "A smooth transition from morning to sunset",
      "resolution": "1280x720",
      "video_length": 121,
      "num_inference_steps": 8,
      "model_type": "ltx2_22B_distilled_gguf_q4_k_m",
      "model_filename": "https://huggingface.co/DeepBeepMeep/LTX-2/resolve/main/ltx-2.3-22b-distilled-Q4_K_M_light.gguf"
    }
  }'
```

### Python Client

```python
import time
import requests

BASE_URL = "http://127.0.0.1:7989"

# Submit
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

# Poll
while True:
    status = requests.get(f"{BASE_URL}/jobs/{job_id}").json()
    print(f"[{status['state']}] {status['progress']}%")
    if status["state"] in ("completed", "failed", "cancelled"):
        break
    time.sleep(2)

# Result
if status["state"] == "completed":
    print("Generated files:", status["generated_files"])
    # Download links are also available
    for link in status["download_links"]:
        print(f"  {link['filename']}: {link['download_url']}")
else:
    print("Errors:", status["errors"])
```

## Job Status Response

When polling `GET /jobs/{job_id}`, the response includes both local file paths and downloadable URLs:

```json
{
  "job_id": "481065ae-0213-4bf7-bfde-70c1905b5ba1",
  "state": "completed",
  "phase": "completed",
  "raw_phase": "VAE Decoding",
  "status": "done",
  "progress": 100,
  "current_step": 4,
  "total_steps": 4,
  "generated_files": [
    "H:\\pinokio\\api\\wan.git\\app\\outputs\\2026-04-01-13h55m56s_seed132212039_output.jpg"
  ],
  "download_links": [
    {
      "filename": "2026-04-01-13h55m56s_seed132212039_output.jpg",
      "download_url": "http://127.0.0.1:7989/jobs/481065ae-0213-4bf7-bfde-70c1905b5ba1/download/0"
    }
  ],
  "errors": []
}
```

## Downloading Generated Files

Use the `download_url` from the job status response, or construct the URL manually:

```bash
# Download by index (0-based)
curl -O http://127.0.0.1:7989/jobs/{job_id}/download/0
```

Supported media types for download: images (`.jpg`, `.png`, `.webp`) and videos (`.mp4`, `.webm`).

## Error Handling

| HTTP Status | When |
|-------------|------|
| `503` | Wan2GP session not initialized |
| `400` | Invalid request body |
| `422` | Task validation failed |
| `404` | Job not found |
| `409` | Cannot cancel a terminal job |

Generation failures set `state: "failed"` with details in the `errors` array.

## Development

Install development dependencies:

```bash
make install          # pip install -e ".[dev]"
```

Run the test suite:

```bash
make test             # pytest tests/ -v --tb=short
```

Lint and type check:

```bash
make lint             # ruff check .
make format           # ruff format .
make typecheck        # mypy .
make check            # lint + typecheck + test
```

### Project Structure

```
plugin.py            ─ Wan2GP plugin entry point (RestApiPlugin)
rest_server.py       ─ FastAPI app, routes, and uvicorn startup
schemas.py           ─ Pydantic request/response models
job_store.py         ─ Thread-safe in-memory job state registry
uploads.py           ─ Upload manager & base64 data-URI resolution
callbacks.py         ─ Wan2GP callback ─> JobStore state adapter
tests/               ─ Unit tests for standalone modules
postman_collections/ ─ Postman collection for testing the API
```

## References

- [Wan2GP Python API Documentation](https://github.com/deepbeepmeep/Wan2GP/blob/main/docs/API.md) — Session, settings format, callbacks, and event streaming
- [Wan2GP Plugin System Documentation](https://github.com/deepbeepmeep/Wan2GP/blob/main/docs/PLUGINS.md) — Plugin lifecycle, UI injection, and distribution

## License

See the [Wan2GP repository](https://github.com/deepbeepmeep/Wan2GP) for license details.
