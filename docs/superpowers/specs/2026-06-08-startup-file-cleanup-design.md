# Startup File Cleanup — Design

**Date:** 2026-06-08 · **Status:** Implemented (`cleanup.py`, wired in `plugin.py`/`callbacks.py`)

A one-time, safe cleanup pass that runs each time the plugin starts, before the HTTP server accepts requests.

## Problem

Two file categories accumulate over long-term operation:

- **Temp uploads** (`<plugin_dir>/_uploads/`): created by `POST /uploads` and base64 data-URI decoding. Today they are cleaned only on terminal job state. They leak when an upload group is never referenced, when the process restarts (the in-memory association map is lost), when the process is killed mid-generation, and the original upload group dir survives even after a successful job.
- **Generated outputs** (`<wan2gp_root>/outputs/`): `result.generated_files`, never deleted by the plugin — the dominant long-term consumer. This directory is **shared** with the user's manual Wan2GP UI generations, so the plugin must never delete files it did not create.

## Decisions

- Runs once at startup, before the server thread starts (so no jobs are in flight).
- Temp uploads: wipe all leftover content (always safe at startup).
- Outputs: **age-based** deletion, **ledger-scoped** (only files the plugin recorded as its own), default retention 30 days, on by default.
- Config via an auto-generated, Notepad-editable `cleanup_config.json` (no env vars).

## Architecture

### Config — `cleanup_config.json` (auto-created next to the plugin)

| Key | Default | Meaning |
|-----|---------|---------|
| `clean_uploads` | `true` | Wipe leftover `_uploads/` at startup |
| `clean_outputs` | `true` | Delete ledgered outputs past retention |
| `output_retention_days` | `30` | Age threshold; must be int ≥ 1, else falls back to 30 |
| `output_roots` | `[]` | Extra allowed roots; `<wan2gp_root>/outputs` is always included |

Missing file → created with defaults (best-effort write). Malformed/non-dict JSON or invalid values → safe defaults, file left untouched.

### `cleanup.py`

- `CleanupConfig.load_or_create(config_path, wan2gp_root)` → validated config; `allowed_roots = [<wan2gp_root>/outputs] + valid output_roots`.
- `Ledger(path = <plugin_dir>/_state/generated_ledger.jsonl)`
  - `record(paths)` — append `{path, ts}` per path; success-path only; skips empty/non-str; best-effort (append errors swallowed, never raised into the generation callback).
  - `prune(retention_days, allowed_roots) -> (deleted, freed)` — read (skip malformed lines), dedup by path keeping the newest valid timestamp, and for expired entries delete the file only if it is inside an allowed root and is a real file (not a dir); missing files are dropped, failures retained; survivors rewritten atomically (temp file + `os.replace`).
- `clean_uploads(upload_base) -> count` — remove every child; a symlink/junction (detected via `realpath` parent check) has only its link entry removed, never recursed through.
- `run_startup_cleanup(upload_base, ledger, config)` — best-effort orchestrator; honors the toggles; never raises; logs a one-line summary. `ledger` may be `None` (output cleanup disabled), in which case prune is skipped.

### Wiring

- `plugin.py` `post_ui_setup`: `ledger = Ledger(...) if config.clean_outputs else None`; `run_startup_cleanup(upload_manager.base_dir, ledger, config)` runs **before** `start_server`, wrapped so a failure can never block startup; the same `ledger` is injected into `JobCallbackAdapter`.
- `callbacks.py` `on_complete`: records to the ledger on **successful** completion only, guarded by `if self._ledger is not None` (so nothing is recorded — and the ledger never grows — when output cleanup is disabled). Failure and cancellation never record.

## Safety

- **Ledger-scoped**: the outputs dir is never scanned; only recorded, successful generations are eligible. Manual UI work and pre-feature outputs are never touched.
- **Root containment**: a ledgered path is deleted only if it resolves inside an allowed root and is a real file — a corrupted/tampered ledger cannot delete an arbitrary path.
- **Retention validation**: a non-int or `< 1` value falls back to 30, preventing a future-dated cutoff from wiping everything.
- **Atomic, resilient ledger**: temp-file + `os.replace`; malformed lines skipped; a valid record is never shadowed by a duplicate with an unparseable timestamp; the ledger self-compacts each prune.
- **Best-effort everywhere**: config write, `record`, and the whole orchestrator swallow errors and log — a read-only filesystem or any cleanup failure never blocks the plugin or server from starting.
- **Upload purge** is startup-safe (no jobs in flight) and cannot escape `_uploads/` through a symlink/junction. Uploaded files are ephemeral across restarts.

## Tests

`tests/test_cleanup.py` (config validation, ledger record/prune, containment, dir/symlink skip, dedup, malformed/atomic, upload purge, best-effort orchestrator) and `tests/test_callbacks_ledger.py` (success-only recording, `None` ledger no-op).
