"""Wan2GP callback → JobStore state update adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .schemas import serialize_wan2gp_error

if TYPE_CHECKING:
    from .job_store import JobStore


class JobCallbackAdapter:
    """Routes Wan2GP session callbacks to JobStore state updates.

    When processing multiple jobs through a single shared session,
    set active_job_id so callbacks update the correct JobRecord.
    """

    def __init__(self, store: JobStore) -> None:
        self._store = store
        self.active_job_id: str | None = None

    def on_progress(self, progress) -> None:
        """Wan2GP ProgressUpdate → JobStore progress update."""
        job_id = self.active_job_id
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
        """
        job_id = self.active_job_id
        if job_id is None:
            return
        if result.success:
            self._store.mark_completed(job_id, list(result.generated_files))
        else:
            errors = [serialize_wan2gp_error(e) for e in result.errors]
            self._store.mark_failed(
                job_id, errors,
                generated_files=list(result.generated_files),
            )

    def on_error(self, error) -> None:
        """Wan2GP GenerationError → JobStore error append (thread-safe)."""
        job_id = self.active_job_id
        if job_id is None:
            return
        self._store.add_error(job_id, serialize_wan2gp_error(error))

    def on_preview(self, preview) -> None:
        """Preview images are ignored."""
        pass

    def on_stream(self, line) -> None:
        """stdout/stderr streams are ignored."""
        pass
