# Wan2GP REST API Plugin

A [Wan2GP](https://github.com/deepbeepmeep/Wan2GP) plugin that exposes image and video generation via a local REST API. Submit jobs, track progress, and retrieve results from any HTTP client.

## Getting Started

1. **Install Wan2GP** — One-click installation with [Pinokio](https://pinokio.co/), or follow the [manual setup](https://github.com/deepbeepmeep/Wan2GP).
2. **Install the plugin** — In Wan2GP, go to the **Plugins** tab, paste the URL below, and click install:
   ```
   https://github.com/lightive/wan2gp_rest_api_plugin
   ```
3. **Enable & restart** — Check **"Wan2GP REST API"**, click **Save Settings**, then restart Wan2GP.
4. **Ready** — The API is live at `http://127.0.0.1:8000`. Open `/docs` for interactive Swagger UI.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/jobs` | Submit a single generation task |
| `POST` | `/jobs/batch` | Submit multiple tasks at once |
| `GET` | `/jobs` | List all jobs (newest first) |
| `GET` | `/jobs/{job_id}` | Poll job status and progress |
| `POST` | `/jobs/{job_id}/cancel` | Cancel a running job |

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

## Full Examples

### Image Generation (Flux 2 Klein, 1024x1024)

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

### Video Generation (LTX-2, 1280x720, 241 frames)

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
print(status["generated_files"] if status["state"] == "completed" else status["errors"])
```

## Error Handling

| HTTP Status | When |
|-------------|------|
| `503` | Wan2GP session not initialized |
| `400` | Invalid request body |
| `404` | Job not found |
| `409` | Cannot cancel a terminal job |

Generation failures set `state: "failed"` with details in the `errors` array.

## References

- [Wan2GP Python API Documentation](https://github.com/deepbeepmeep/Wan2GP/blob/main/docs/API.md) — Session, settings format, callbacks, and event streaming
- [Wan2GP Plugin System Documentation](https://github.com/deepbeepmeep/Wan2GP/blob/main/docs/PLUGINS.md) — Plugin lifecycle, UI injection, and distribution

## License

See the [Wan2GP repository](https://github.com/deepbeepmeep/Wan2GP) for license details.
