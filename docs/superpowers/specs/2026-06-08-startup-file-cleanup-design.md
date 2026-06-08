# Startup File Cleanup — Design Spec

**Date:** 2026-06-08
**Status:** Approved (design); cross-checked with Codex in 3 passes
**Scope:** Add a one-time, safe file-cleanup pass that runs each time the plugin starts.

## Problem

Over months/years of continuous operation the plugin leaks disk space through two
distinct file categories:

### 1. Plugin-owned temp uploads — `<plugin_dir>/_uploads/`
Created by `POST /uploads` and by base64 data-URI decoding. Cleaned today only via
`UploadManager.cleanup_job(job_id)`, which is invoked from `JobCallbackAdapter.on_complete`
and the submission/validation failure paths. Confirmed leaks (audited + Codex-confirmed):

- **L1 — Orphaned upload groups:** `POST /uploads` creates `_uploads/<group_id>/`. If no
  job ever references the group, `cleanup_job` is never called → leaks forever.
- **L2 — Restart orphans:** `UploadManager._job_groups` is in-memory only. After a restart
  the map is empty, so any leftover `_uploads/<id>/` dirs are orphaned permanently.
- **L3 — Crash mid-generation:** if the process dies before `on_complete` fires, the upload
  dir is never cleaned.
- **L4 — Original upload group survives every job:** `_prepare_settings` re-encodes upload
  paths as data-URIs, then `resolve_data_uris` saves *copies* under the `job_id` dir.
  `cleanup_job` removes the `job_id` dir but leaves the original `_uploads/<group_id>/`
  intact. Result: one leaked group dir per job that used an uploaded file.
- **L5 — Cancel-before-submit:** a cancel that lands before submission can skip cleanup.

### 2. Wan2GP generated outputs — `<wan2gp_root>/outputs/`
`result.generated_files` (e.g. `...\outputs\2026-04-01-13h55m56s_output.jpg`) are never
deleted by the plugin (**L6**). This is the dominant long-term disk consumer. Critically,
this directory is **shared** with the user's manual Wan2GP UI generations — the plugin must
never delete files it did not itself create.

## Goals / Non-Goals

**Goals**
- One safe cleanup pass per plugin startup (before the HTTP server accepts requests).
- Fully reclaim leftover `_uploads/` (fixes L1–L5).
- Delete only the plugin's *own* generated outputs older than a retention window (addresses
  L6) without ever touching the user's manual UI generations.
- Windows-friendly, easy-to-edit configuration.
- Never block plugin/server startup if cleanup fails.

**Non-Goals**
- No periodic/background cleanup (startup-only by request).
- No deletion of manual Wan2GP UI outputs.
- No deletion of outputs created before this feature existed (no ledger record → not touched).
- No size-budget/LRU or keep-last-N policy (age-based was chosen).

## Decisions (from brainstorming)

| Decision | Choice |
|----------|--------|
| When | Once, at plugin startup, **before** the uvicorn server thread starts |
| `_uploads/` policy | Always wipe all leftover content (safe — no jobs in flight at startup) |
| Output retention policy | **Age-based**: delete outputs older than N days |
| Output scope | **Ledger-scoped** — only files the plugin recorded as its own generations |
| Default retention | 30 days |
| Output cleanup default | **On** |
| Configuration | Auto-generated `cleanup_config.json` (Notepad-editable). No env vars. |

## Architecture

### Configuration — `cleanup_config.json`
Location: `<plugin_dir>/cleanup_config.json`. Auto-created with defaults on first run if
missing. Edited with any text editor; changes apply on next Pinokio/plugin restart.

```json
{
  "_comment": "Wan2GP REST startup cleanup. Edit values, restart to apply.",
  "clean_uploads": true,
  "clean_outputs": true,
  "output_retention_days": 30,
  "output_roots": []
}
```

- `clean_uploads` (bool, default `true`) — wipe leftover `_uploads/`.
- `clean_outputs` (bool, default `true`) — prune ledgered outputs past retention.
- `output_retention_days` (int, default `30`) — must be an integer `>= 1`. Any invalid
  value (negative, `0`, float, string, null, bool) → fall back to `30` and log a warning.
  (To disable output cleanup, set `clean_outputs: false`, not a sentinel day count.)
- `output_roots` (list of str, default empty) — additional allowed roots for deletion
  containment (see Safety). When empty, the default root `<wan2gp_root>/outputs` is used.

Missing or malformed JSON → safe defaults are used and a warning is logged. A malformed
file is **not** overwritten (avoid clobbering a user's broken-but-recoverable edit); a
missing file **is** created with defaults.

### New module — `cleanup.py`
Single responsibility: perform the one-time startup cleanup. Public surface:

- `CleanupConfig`
  - `load_or_create(path, wan2gp_root) -> CleanupConfig` — read/auto-create JSON, validate
    fields, resolve allowed output roots (config `output_roots` ∪ `<wan2gp_root>/outputs`).
  - Fields: `clean_uploads: bool`, `clean_outputs: bool`, `retention_days: int`,
    `allowed_roots: list[Path]`.

- `Ledger` (file: `<plugin_dir>/_state/generated_ledger.jsonl`)
  - `record(paths: list[str]) -> None` — append one `{"path": ..., "ts": ISO8601}` JSON line
    per path. Thread-safe (internal lock). Called **only on successful** job completion.
    Empty `paths` is a no-op (ledger untouched).
  - `prune(retention_days: int, allowed_roots: list[Path]) -> tuple[int, int]` — returns
    `(deleted_count, freed_bytes)`. Algorithm:
    1. Read all lines; **skip malformed lines** (don't abort the whole prune).
    2. **Dedup by path, latest `ts` wins** (a re-used path keeps only its newest record).
    3. For each entry older than `now - retention_days`: delete the file **only if** it
       passes the deletion guard (see Safety); accumulate freed bytes; drop the entry.
    4. Rewrite surviving entries **atomically**: write to a temp file in the same dir, then
       `os.replace` over the ledger. A crash mid-write leaves the old ledger intact.

- `clean_uploads(upload_base: Path) -> int` — returns count of removed children. Removes
  every child of `_uploads/` (gated by config). Per-child handling to prevent escape:
  - symlink/junction → `unlink()` the link only (never recurse through it);
  - real directory → `shutil.rmtree(child, ignore_errors=True)`;
  - file → `unlink()`.

- `run_startup_cleanup(plugin_dir, upload_manager, ledger, config) -> None` — orchestrator.
  Each step wrapped in its own `try/except`; logs a one-line summary; **never raises**.
  Summary log: `[Wan2GP REST] cleanup: temp <N> items, outputs <M> files (<X> MB freed)`.

### Wiring (surgical edits)
- `plugin.py` `post_ui_setup`: after creating `store`, `upload_manager`, and `Ledger`, and
  **before** `start_server`, call `CleanupConfig.load_or_create(...)` then
  `run_startup_cleanup(...)`. The `Ledger` is injected into `JobCallbackAdapter`.
- `callbacks.py` `JobCallbackAdapter`: accept a `ledger` dependency; in `on_complete`,
  **only on `result.success`**, call `ledger.record(result.generated_files)`. Failure and
  cancellation paths do **not** record (avoid deleting partial/inspectable artifacts).
- `.gitignore`: add `_state/` and `cleanup_config.json`.
- `README.md`: document the cleanup behavior, the config file, that `_uploads/` is
  ephemeral across restarts, and the output-root containment guarantee.

## Safety

- **Ledger-only output deletion.** The `outputs/` directory is never scanned. Only paths the
  plugin recorded as its own successful generations are eligible — manual UI work is never
  touched, and pre-feature outputs (no record) are never touched.
- **Success-only ledger.** Partial/failed/cancelled artifacts are never recorded, so they
  are never deleted by a later startup (users can still inspect them).
- **Deletion guard (root containment).** Before deleting any ledgered path, require that it
  (a) resolves inside one of `allowed_roots` (`is_relative_to`) and (b) `is_file()` (never a
  directory). Anything failing the guard is skipped and **retained**, with a warning. This
  neutralizes a corrupted/tampered ledger that could otherwise target an arbitrary absolute
  path, and defends against any `generated_files` entry that is actually an input/external
  reference.
- **Retention validation.** `output_retention_days` is clamped to a safe default unless it is
  an integer `>= 1`, preventing a future-dated cutoff (`-1`/`0`) from wiping the whole ledger.
- **Atomic, resilient ledger rewrite.** Temp-file + `os.replace`; malformed lines skipped
  individually. The ledger self-compacts on each startup (deleted + deduped entries dropped),
  bounding growth.
- **`_uploads/` purge is startup-safe.** It runs before the server starts, so no job is in
  flight and the localhost plugin is the sole writer of `_uploads/`. Per-child handling
  prevents symlink/junction escape outside the upload base. Documented assumption: uploaded
  files are **ephemeral across restarts** — an upload not submitted before a restart is gone.
- **Best-effort.** Any cleanup failure is caught and logged; the plugin and HTTP server
  start normally regardless.

## Testing — `tests/test_cleanup.py`

**Config**
- Missing file → created with defaults.
- Malformed JSON → safe defaults used, file not overwritten.
- Toggles respected (`clean_uploads`/`clean_outputs` false → corresponding step skipped).
- `output_retention_days` = negative / `0` / float / string / null / bool → falls back to 30.

**Ledger**
- `record` appends one line per path; `record([])` leaves the ledger unchanged.
- `prune` deletes files older than N days, keeps newer ones.
- `prune` drops entries whose file is missing (no error).
- Dedup by path, latest `ts` wins (older record cannot delete a newer same-path file).
- Atomic rewrite leaves surviving entries; a malformed line is skipped, not fatal.
- Ledger entry **outside** `allowed_roots` → skipped and retained, not deleted.
- Ledger entry pointing to a **directory** → not deleted as a file.
- Relative / unusual Windows paths and case-only-different duplicates handled safely
  (Windows case-insensitive FS).

**Uploads**
- Purge removes leftover subdirs and stray top-level files under `_uploads/`.
- `clean_uploads: false` → nothing removed.
- A symlink/junction child does not let deletion escape the upload base.

**Orchestration**
- `run_startup_cleanup` never raises on bad input (unreadable ledger, missing dirs, bad
  config) and always returns after logging.

## Files Touched

- **New:** `cleanup.py`, `tests/test_cleanup.py`
- **Edit:** `plugin.py` (wire ledger + cleanup), `callbacks.py` (record on success),
  `.gitignore` (`_state/`, `cleanup_config.json`), `README.md` (document behavior/config)

## Cross-Check Record (Codex)

- **Pass 1 (leak inventory):** confirmed L1–L4, surfaced L4 (per-job original group leak) and
  L5 (cancel path) that the initial audit missed.
- **Pass 2 (design safety):** drove success-only ledger, dedup latest-wins, and atomic
  rewrite + malformed-line skipping.
- **Pass 3 (final review):** `APPROVE-WITH-CHANGES` → added retention-value validation,
  root-containment deletion guard, symlink-escape handling in upload purge, ephemeral-upload
  documentation, and the expanded edge-case test matrix.
