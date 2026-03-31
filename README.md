# Wan2GP REST API Plugin

A plugin for [Wan2GP](https://github.com/deepbeepmeep/Wan2GP) that exposes image and video generation capabilities through a local REST API. Any HTTP client can submit generation jobs, poll for progress, and retrieve results programmatically.

## Features

- **Async job submission** - Submit tasks and get a `job_id` immediately (non-blocking)
- **Real-time progress tracking** - Poll job status including phase, step count, and percentage
- **Batch generation** - Submit multiple tasks in a single request
- **File upload support** - Upload settings JSON or ZIP files with media attachments
- **Job cancellation** - Cancel running jobs at any time
- **Swagger UI** - Interactive API docs available at `/docs`

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

## API Reference

### Create a Job

```
POST /jobs
```

**Single task:**
```json
{
  "task": {
    "prompt": "A cinematic mountain sunrise",
    "resolution": "1280x704",
    "num_inference_steps": 8,
    "video_length": 97
  }
}
```

**Batch tasks:**
```json
{
  "tasks": [
    {"prompt": "Shot 1", "resolution": "1280x704"},
    {"prompt": "Shot 2", "resolution": "1280x704"}
  ]
}
```

**Response:** `202 Accepted`
```json
{"job_id": "uuid", "state": "accepted"}
```

### Upload Files to Create a Job

```
POST /jobs/upload
Content-Type: multipart/form-data
```

| Field | Type | Description |
|-------|------|-------------|
| `settings_file` | File (required) | A `.json` or `.zip` file containing generation settings |
| `media_files[]` | File(s) (optional) | Reference images or other media inputs |
| `mode` | String (optional) | Submission mode (default: `"task"`) |

### Get Job Status

```
GET /jobs/{job_id}
```

**Response:**
```json
{
  "job_id": "uuid",
  "state": "running",
  "phase": "inference",
  "progress": 54,
  "current_step": 4,
  "total_steps": 8,
  "generated_files": [],
  "errors": []
}
```

**Job states:** `accepted` → `queued` → `running` → `completed` | `failed` | `cancelling` → `cancelled`

### Cancel a Job

```
POST /jobs/{job_id}/cancel
```

**Response:**
```json
{"job_id": "uuid", "state": "cancelling"}
```

## Quick Start

1. Start Wan2GP with the plugin enabled.
2. Open the interactive API docs at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).
3. Submit a test job:
   ```bash
   curl -X POST http://127.0.0.1:8000/jobs \
     -H "Content-Type: application/json" \
     -d '{"task": {"prompt": "A cinematic sunset over the ocean"}}'
   ```
4. Check the job status:
   ```bash
   curl http://127.0.0.1:8000/jobs/{job_id}
   ```
5. When `state` is `"completed"`, the `generated_files` array contains output file paths.

## Client Integration Example

You can integrate with the REST API from any language. Here is a minimal Python example:

```python
import time
import requests

BASE_URL = "http://127.0.0.1:8000"

# Submit a job
resp = requests.post(f"{BASE_URL}/jobs", json={
    "task": {
        "prompt": "A cinematic scene",
        "resolution": "1280x704",
        "num_inference_steps": 8,
    }
})
job_id = resp.json()["job_id"]

# Poll until completion
while True:
    status = requests.get(f"{BASE_URL}/jobs/{job_id}").json()
    print(f"State: {status['state']}  Progress: {status['progress']}%")
    if status["state"] in ("completed", "failed", "cancelled"):
        break
    time.sleep(2)

# Check results
if status["state"] == "completed":
    print("Generated files:", status["generated_files"])
else:
    print("Errors:", status["errors"])
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Server not ready | Returns `503 Service Unavailable` |
| Invalid request body | Returns `400 Bad Request` with details |
| Job not found | Returns `404 Not Found` |
| Cancel a completed job | Returns `409 Conflict` |
| Generation failure | Job state becomes `failed` with error details in the `errors` array |

## Project Structure

```
wan2gp_rest_api_plugin/
├── __init__.py          # Package marker
├── plugin.py            # Plugin entry point (lifecycle management)
├── rest_server.py       # FastAPI app, routes, and uvicorn server
├── job_store.py         # Thread-safe job state registry
├── callbacks.py         # Wan2GP callback → job store adapter
├── schemas.py           # Pydantic request/response models
└── requirements.txt     # Python dependencies
```

## Requirements

- [Wan2GP](https://github.com/deepbeepmeep/Wan2GP)
- Python 3.10+
- Dependencies are auto-installed: `fastapi`, `uvicorn`, `pydantic`, `python-multipart`

## License

This project is provided as-is for use with Wan2GP. See the [Wan2GP repository](https://github.com/deepbeepmeep/Wan2GP) for license details.
