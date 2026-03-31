"""Thread-safe job state registry."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .schemas import JobState


@dataclass
class JobRecord:
    """A single job record managed by the REST API."""
    job_id: str
    created_at: datetime
    updated_at: datetime
    state: JobState
    source_type: str
    session_job: Any | None = None

    # Wan2GP progress snapshot
    phase: str | None = None
    raw_phase: str | None = None
    status: str | None = None
    progress: int = 0
    current_step: int | None = None
    total_steps: int | None = None

    # Results
    generated_files: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    # Metadata
    request_summary: dict = field(default_factory=dict)


_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
_EVICT_AGE_SECONDS = 3600  # Evict 1 hour after reaching terminal state


class JobStore:
    """Manages UUID → JobRecord mapping in a thread-safe manner."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, JobRecord] = {}

    # --- Internal helpers ---

    def _transition(self, job_id: str, **fields: Any) -> None:
        """Update record fields under lock.
        Ignores records already in a terminal state (prevents double-completion).
        """
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            # Ignore duplicate transitions for terminal states
            if record.state in _TERMINAL_STATES:
                return
            for k, v in fields.items():
                setattr(record, k, v)
            record.updated_at = datetime.now(timezone.utc)

    def _evict_stale(self) -> None:
        """Remove records that have been in a terminal state past the eviction age."""
        now = datetime.now(timezone.utc)
        to_remove: list[str] = []
        with self._lock:
            for jid, rec in self._jobs.items():
                if rec.state in _TERMINAL_STATES:
                    age = (now - rec.updated_at).total_seconds()
                    if age > _EVICT_AGE_SECONDS:
                        to_remove.append(jid)
            for jid in to_remove:
                self._jobs.pop(jid)

    # --- Public methods ---

    def create(self, source_type: str, request_summary: dict | None = None) -> JobRecord:
        """Create a new JobRecord and register it in the store."""
        self._evict_stale()
        now = datetime.now(timezone.utc)
        job_id = str(uuid.uuid4())
        record = JobRecord(
            job_id=job_id,
            created_at=now,
            updated_at=now,
            state="accepted",
            source_type=source_type,
            request_summary=request_summary or {},
        )
        with self._lock:
            self._jobs[job_id] = record
        return record

    def get(self, job_id: str) -> JobRecord | None:
        """Look up a record by job_id."""
        with self._lock:
            return self._jobs.get(job_id)

    def update_progress(
        self,
        job_id: str,
        *,
        phase: str | None = None,
        raw_phase: str | None = None,
        status: str | None = None,
        progress: int | None = None,
        current_step: int | None = None,
        total_steps: int | None = None,
    ) -> None:
        """Update progress fields."""
        fields: dict[str, Any] = {"state": "running"}
        if phase is not None:
            fields["phase"] = phase
        if raw_phase is not None:
            fields["raw_phase"] = raw_phase
        if status is not None:
            fields["status"] = status
        if progress is not None:
            fields["progress"] = progress
        if current_step is not None:
            fields["current_step"] = current_step
        if total_steps is not None:
            fields["total_steps"] = total_steps
        self._transition(job_id, **fields)

    def mark_running(self, job_id: str, session_job: Any) -> None:
        """Transition to running state and store the session_job reference."""
        self._transition(job_id, state="running", session_job=session_job)

    def mark_completed(self, job_id: str, generated_files: list[str]) -> None:
        """Transition to completed state."""
        self._transition(
            job_id,
            state="completed", progress=100,
            phase="completed", status="done",
            generated_files=generated_files,
        )

    def mark_failed(
        self, job_id: str, errors: list[dict],
        generated_files: list[str] | None = None,
    ) -> None:
        """Transition to failed state."""
        fields: dict[str, Any] = {
            "state": "failed", "phase": "error", "errors": errors,
        }
        if generated_files:
            fields["generated_files"] = generated_files
        self._transition(job_id, **fields)

    def add_error(self, job_id: str, error: dict) -> None:
        """Append an error record under lock."""
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            record.errors.append(error)

    def mark_cancelling(self, job_id: str) -> None:
        """Transition to cancelling state."""
        self._transition(job_id, state="cancelling")

    def mark_cancelled(self, job_id: str) -> None:
        """Transition to cancelled state."""
        self._transition(job_id, state="cancelled", phase="cancelled")
