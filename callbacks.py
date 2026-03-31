"""Wan2GP callback → JobStore state update adapter."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from .schemas import serialize_wan2gp_error

if TYPE_CHECKING:
    from .job_store import JobStore


class JobCallbackAdapter:
    """Routes Wan2GP session callbacks to JobStore state updates.

    Wan2GP fires callbacks on a single shared session.  ``set_active_job``
    must be called (under the external ``_submit_lock``) before each
    ``submit_*`` call so that callbacks update the correct JobRecord.

    Thread-safety: ``_job_lock`` serialises every read/write of
    ``_active_job_id`` so that a late callback arriving after a new
    submission cannot silently corrupt the wrong job.  ``on_complete``
    atomically clears the id, preventing any subsequent stale callback
    from routing to an already-finished job.
    """

    def __init__(self, store: JobStore) -> None:
        self._store = store
        self._job_lock = threading.Lock()
        self._active_job_id: str | None = None

    def set_active_job(self, job_id: str) -> None:
        """Set the job id that subsequent callbacks will update."""
        with self._job_lock:
            self._active_job_id = job_id

    def _get_active_job_id(self) -> str | None:
        with self._job_lock:
            return self._active_job_id

    def on_progress(self, progress) -> None:
        """Wan2GP ProgressUpdate → JobStore progress update."""
        job_id = self._get_active_job_id()
        if job_id is None:
            return
        self._store.update_progress(
            job_id,
            phase=progress.phase,
            raw_phase=getattr(progress, "raw_phase", None),
            status=getattr(progress, "status", None),
            progress=progress.progress,
            current_step=getattr(progress, "current_step", None),
            total_steps=getattr(progress, "total_steps", None),
        )

    def on_complete(self, result) -> None:
        """Wan2GP GenerationResult → JobStore completion/failure handling.

        This callback is the sole path for completion handling.
        Cancellation is detected by checking for stage="cancelled" errors,
        which Wan2GP emits when a job is cooperatively cancelled.

        Atomically clears ``_active_job_id`` so no further stale callbacks
        can affect this (or any) job after completion.
        """
        with self._job_lock:
            job_id = self._active_job_id
            self._active_job_id = None
        if job_id is None:
            return
        if result.success:
            self._store.mark_completed(job_id, list(result.generated_files))
            return

        is_cancelled = any(
            getattr(e, "stage", None) == "cancelled" for e in result.errors
        )
        if is_cancelled:
            self._store.mark_cancelled(job_id)
        else:
            errors = [serialize_wan2gp_error(e) for e in result.errors]
            self._store.mark_failed(
                job_id, errors,
                generated_files=list(result.generated_files),
            )

    def on_error(self, error) -> None:
        """Wan2GP GenerationError → JobStore error append (thread-safe)."""
        job_id = self._get_active_job_id()
        if job_id is None:
            return
        self._store.add_error(job_id, serialize_wan2gp_error(error))

    def on_preview(self, preview) -> None:
        """Preview images are ignored."""
        pass

    def on_stream(self, line) -> None:
        """stdout/stderr streams are ignored."""
        pass
