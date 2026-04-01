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

### Core Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `model_type` | str | **Required.** Model ID (e.g. `"flux2_klein_9b"`, `"ltx2_22B_distilled_gguf_q4_k_m"`, `"wan21_t2v_1_3B"`) |
| `model_filename` | str | HuggingFace URL or local path to model weights |
| `base_model_type` | str | Base model type for distillation/quantized variants |
| `prompt` | str | **Required.** Text prompt describing the desired output |
| `negative_prompt` | str | Negative prompt — concepts to avoid |
| `alt_prompt` | str | Alternate prompt for guidance switching |
| `image_mode` | int | `0` = video generation, `1` = image generation |
| `model_mode` | str | Specific model mode if the model supports multiple (e.g. `"t2v"`, `"i2v"`) |
| `resolution` | str | Output resolution, e.g. `"1280x720"`, `"1024x1024"` |
| `video_length` | int | Number of frames to generate (video only) |
| `duration_seconds` | float | Approximate video duration in seconds (alternative to video_length) |
| `pause_seconds` | float | Pause duration between generated clips |
| `batch_size` | int | Number of outputs per task |
| `repeat_generation` | int | How many times to repeat the generation with the same settings |
| `seed` | int | Random seed. `-1` for random |
| `override_profile` | int | VRAM profile override (`-1` = auto) |
| `override_attention` | str | Attention mode override |

### Inference & Sampling

| Parameter | Type | Description |
|-----------|------|-------------|
| `num_inference_steps` | int | Number of denoising steps |
| `guidance_scale` | float | CFG (Classifier Free Guidance) scale |
| `guidance2_scale` | float | Secondary guidance scale (dual-CFG models) |
| `guidance3_scale` | float | Tertiary guidance scale (dual-CFG models) |
| `alt_guidance_scale` | float | Guidance scale for alternate prompt |
| `alt_scale` | float | Alternate scale for guidance |
| `audio_guidance_scale` | float | Audio guidance scale |
| `embedded_guidance_scale` | float | Embedded guidance scale |
| `flow_shift` | float | Flow shift for flow-matching models |
| `sample_solver` | str | Sampler/solver selection |
| `guidance_phases` | str | Guidance phase configuration |
| `model_switch_phase` | int | Phase at which to switch models |
| `switch_threshold` | float | Threshold for model switching |
| `switch_threshold2` | float | Secondary threshold for model switching |
| `temperature` | float | Sampling temperature for autoregressive models |
| `top_p` | float | Top-p (nucleus) sampling threshold |
| `top_k` | int | Top-k sampling limit |

### Frame Rate & Multi-Prompt

| Parameter | Type | Description |
|-----------|------|-------------|
| `force_fps` | str | Force output FPS (e.g. `"24"`, `"30"`, `"23.976"`) |
| `multi_prompts_gen_type` | int | Multi-prompt mode: `0` = each line = new video, `1` = each line = new sliding window, `2` = multi-line single prompt |
| `multi_images_gen_type` | int | Multi-image mode — how to handle multiple reference images |

### LoRA

| Parameter | Type | Description |
|-----------|------|-------------|
| `activated_loras` | array of str | List of LoRA identifiers/paths to activate (e.g. `["lora_name_1", "/path/to/lora.safetensors"]`) |
| `loras_multipliers` | str | LoRA weights as JSON string, e.g. `{"lora_name_1": 0.8, "lora_name_2": 1.0}` |

### Media Attachments (Input)

Upload files via `POST /uploads` first, then use the returned paths in these fields. Alternatively, use base64 data-URIs.

| Parameter | Type | Description |
|-----------|------|-------------|
| `image_start` | str/path | Start image (first frame) for image-to-video. Use with `image_prompt_type: "S"` or `"SE"` |
| `image_end` | str/path | End image (last frame) for image-to-video interpolation. Use with `image_prompt_type: "E"` or `"SE"` |
| `image_refs` | list | Reference images to influence style/subject (background refs, style refs) |
| `image_refs_relative_size` | float | Relative size scaling for reference images |
| `remove_background_images_ref` | bool | Whether to remove background from reference images |
| `image_guide` | str/path | Guidance/control image for image-guided generation |
| `image_mask` | str/path | Input mask for inpainting/outpainting |
| `video_source` | str/path | Source video for video-to-video transformation |
| `keep_frames_video_source` | list of str | Frame indices or ranges to keep from source video |
| `keep_frames_video_guide` | list of str | Frame indices or ranges to keep from guide video |
| `input_video_strength` | float | Strength of influence from input video (0.0–1.0) |
| `video_guide` | str/path | Control/guide video for video-guided generation |
| `denoising_strength` | float | Denoising strength for img2img/vid2vid (0.0–1.0) |
| `masking_strength` | float | Mask strength for inpainting |
| `mask_expand` | int | Mask expansion pixels for inpainting |
| `video_mask` | str/path | Video mask for temporal inpainting |
| `video_guide_outpainting` | str | Outpainting mode for video guide (e.g. `"Left"`, `"Right"`, `"Top"`, `"Bottom"`) |
| `speakers_locations` | str | Speaker face locations for lip-sync |
| `frames_positions` | str | Frame placement/positioning configuration |

### Prompt Type Flags

| Parameter | Type | Description |
|-----------|------|-------------|
| `image_prompt_type` | str | **Critical for attachments.** Image attachment flags: `"S"` = start image, `"E"` = end image, `"SE"` = both start+end, `"VL"` = video length from reference. Empty `""` = none |
| `video_prompt_type` | str | Video prompt mode flags (varies by model). May include `"V"` = video guide, `"K"` = keyframes, `"F"` = frames, `"G"` = generation, `"L"` = continuation |
| `audio_prompt_type` | str | Audio prompt mode flags |

### Audio

| Parameter | Type | Description |
|-----------|------|-------------|
| `audio_guide` | str/path | Audio file to guide generation |
| `audio_guide2` | str/path | Secondary audio guide |
| `audio_source` | str/path | Source audio for lip-sync or audio-driven generation |

### Sliding Window (Long Videos)

| Parameter | Type | Description |
|-----------|------|-------------|
| `sliding_window_size` | int | Frames per sliding window |
| `sliding_window_overlap` | int | Overlap frames between adjacent windows |
| `sliding_window_color_correction_strength` | float | Color correction between windows (`0` = off) |
| `sliding_window_overlap_noise` | float | Noise added at window overlap boundaries |
| `sliding_window_discard_last_frames` | int | Frames to discard from end of each window |
| `min_frames_if_references` | int | Minimum output frames when reference images are used |

### Skip Steps Cache (TeaCache / MagCache)

| Parameter | Type | Description |
|-----------|------|-------------|
| `skip_steps_cache_type` | str | Cache type: `"tea"` for TeaCache, `"mag"` for MagCache, `""` to disable |
| `skip_steps_multiplier` | int | Step skip multiplier for cache acceleration |
| `skip_steps_start_step_perc` | float | Percentage of steps at which to start caching |

### Advanced Guidance (NAG, CFG Star, APG)

| Parameter | Type | Description |
|-----------|------|-------------|
| `NAG_scale` | float | Normalized Adversarial Guidance scale |
| `NAG_tau` | float | NAG tau (smoothing parameter) |
| `NAG_alpha` | float | NAG alpha (guidance blend) |
| `perturbation_switch` | int | Perturbation toggle (`0` = off, `1` = on) |
| `perturbation_layers` | list of int | Model layers to apply perturbation |
| `perturbation_start_perc` | float | Perturbation start percentage of denoising |
| `perturbation_end_perc` | float | Perturbation end percentage of denoising |
| `apg_switch` | int | Adaptive Progressive Guidance toggle (`0` = off, `1` = on) |
| `cfg_star_switch` | int | CFG Star mode toggle (`0` = off, `1` = on) |
| `cfg_zero_step` | int | Number of initial CFG=0 (guidance-free) steps |

### Upsampling & Post-Processing

| Parameter | Type | Description |
|-----------|------|-------------|
| `temporal_upsampling` | str | Frame interpolation: `"x2"` or `"x4"` RIFE upsampling, `""` = none |
| `spatial_upsampling` | str | Spatial upscale: `"1.5x"`, `"2x"` Lanczos, or model-based, `""` = none |
| `film_grain_intensity` | float | Film grain overlay intensity (`0` = off) |
| `film_grain_saturation` | float | Film grain color saturation |
| `RIFLEx_setting` | int | RIFLEx extrapolation position embedding override |
| `output_filename` | str | Custom output filename prefix (empty = auto-generated) |

### MMAudio (Audio Generation)

| Parameter | Type | Description |
|-----------|------|-------------|
| `MMAudio_setting` | int | MMAudio mode: `0` = off, `1` = generate, `2` = generate + mux, `3` = generate + sync |
| `MMAudio_prompt` | str | Prompt for audio generation |
| `MMAudio_neg_prompt` | str | Negative prompt for audio generation |

### Motion

| Parameter | Type | Description |
|-----------|------|-------------|
| `motion_amplitude` | float | Motion intensity/amplitude control |

### Custom Settings

| Parameter | Type | Description |
|-----------|------|-------------|
| `custom_settings` | str | JSON string of custom model-specific settings. Structure: `[{"name":"param","value":1.0,"type":"float"}, ...]` |

### Self-Refiner

| Parameter | Type | Description |
|-----------|------|-------------|
| `self_refiner_setting` | int | Self-refiner iterations (`0` = off) |
| `self_refiner_plan` | str | Self-refiner plan string (per-step guidance) |
| `self_refiner_f_uncertainty` | float | Uncertainty factor for self-refiner |
| `self_refiner_certain_percentage` | float | Certainty percentage threshold for self-refiner |

---

<details>
<summary><b>Quick Reference: Minimal JSON for common scenarios</b></summary>

**Text-to-Image:**
```json
{
  "task": {
    "image_mode": 1,
    "prompt": "A beautiful sunset",
    "resolution": "1024x1024",
    "num_inference_steps": 20,
    "model_type": "flux2_klein_9b"
  }
}
```

**Text-to-Video:**
```json
{
  "task": {
    "image_mode": 0,
    "prompt": "Ocean waves crashing on rocks",
    "resolution": "1280x720",
    "video_length": 121,
    "num_inference_steps": 20,
    "model_type": "ltx2_22B_distilled_gguf_q4_k_m"
  }
}
```

**Image-to-Video (Start Frame):**
```json
{
  "task": {
    "image_mode": 0,
    "image_prompt_type": "S",
    "image_start": "/path/to/start_image.png",
    "prompt": "The character walks forward",
    "resolution": "1280x720",
    "video_length": 121,
    "num_inference_steps": 20,
    "model_type": "ltx2_22B_distilled_gguf_q4_k_m"
  }
}
```

**Image-to-Video (Start + End Frame Interpolation):**
```json
{
  "task": {
    "image_mode": 0,
    "image_prompt_type": "SE",
    "image_start": "/path/to/start.png",
    "image_end": "/path/to/end.png",
    "prompt": "Smooth transition",
    "resolution": "1280x720",
    "video_length": 121,
    "num_inference_steps": 20,
    "model_type": "ltx2_22B_distilled_gguf_q4_k_m"
  }
}
```

**With LoRA:**
```json
{
  "task": {
    "image_mode": 1,
    "prompt": "A portrait in anime style",
    "resolution": "1024x1024",
    "num_inference_steps": 20,
    "model_type": "flux2_klein_9b",
    "activated_loras": ["anime_v5"],
    "loras_multipliers": "{\"anime_v5\": 0.8}"
  }
}
```

**With MMAudio:**
```json
{
  "task": {
    "image_mode": 0,
    "prompt": "Rain falling on a city street",
    "resolution": "1280x720",
    "video_length": 121,
    "num_inference_steps": 20,
    "model_type": "ltx2_22B_distilled_gguf_q4_k_m",
    "MMAudio_setting": 3,
    "MMAudio_prompt": "rain sounds, droplets, city ambience"
  }
}
```

</details>

## Attaching Media Files

Wan2GP accepts files for attachment keys such as `image_start`, `image_end`, `image_refs`, `video_source`, etc. There are two ways to provide these:

### Option A: Multipart Upload (Recommended)

Upload files first via `POST /uploads`, then use the returned paths in task settings. The plugin automatically handles file path resolution — you can paste the returned path directly into your job request.

```bash
# 1. Upload
curl -X POST http://127.0.0.1:7989/uploads \
  -F "files=@start_frame.png"

# Response: {"job_id": "abc123", "files": [{"filename": "start_frame.png", "path": "/absolute/path/to/start_frame.png"}]}

# 2. Use the returned path directly in a job
curl -X POST http://127.0.0.1:7989/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "task": {
      "image_mode": 0,
      "image_prompt_type": "S",
      "prompt": "A sunrise over mountains",
      "image_start": "/absolute/path/to/start_frame.png",
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

### Video with LoRA

```bash
curl -X POST http://127.0.0.1:7989/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "task": {
      "image_mode": 0,
      "prompt": "A cyberpunk city at night",
      "resolution": "1280x720",
      "video_length": 121,
      "num_inference_steps": 20,
      "model_type": "ltx2_22B_distilled_gguf_q4_k_m",
      "activated_loras": ["cyberpunk_v2"],
      "loras_multipliers": "{\"cyberpunk_v2\": 0.7}"
    }
  }'
```

### Video with MMAudio (Auto-Generate Audio)

```bash
curl -X POST http://127.0.0.1:7989/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "task": {
      "image_mode": 0,
      "prompt": "Rain falling on a city street at night",
      "resolution": "1280x720",
      "video_length": 121,
      "num_inference_steps": 20,
      "model_type": "ltx2_22B_distilled_gguf_q4_k_m",
      "MMAudio_setting": 3,
      "MMAudio_prompt": "heavy rain, thunder, city traffic ambience",
      "MMAudio_neg_prompt": "music, speech, silence"
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
    "H:\\pinokio\\api\\wan.git\\app\\outputs\\2026-04-01-13h55m56s_output.jpg"
  ],
  "download_links": [
    {
      "filename": "2026-04-01-13h55m56s_output.jpg",
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

## Error Handling

| HTTP Status | When |
|-------------|------|
| `503` | Wan2GP session not initialized |
| `400` | Invalid request body |
| `422` | Task validation failed (e.g. missing required fields, unsupported attachment for model) |
| `404` | Job not found |
| `409` | Cannot cancel a terminal job (already completed, failed, or cancelled) |

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
