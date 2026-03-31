"""Wan2GP 콜백 → JobStore 상태 업데이트 어댑터."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .schemas import serialize_wan2gp_error

if TYPE_CHECKING:
    from .job_store import JobStore


class JobCallbackAdapter:
    """Wan2GP 세션 콜백을 JobStore 상태 업데이트로 라우팅한다.

    하나의 공유 세션에서 여러 작업을 처리할 때,
    active_job_id를 설정하여 콜백이 올바른 JobRecord를 업데이트하도록 한다.
    """

    def __init__(self, store: JobStore) -> None:
        self._store = store
        self.active_job_id: str | None = None

    def on_progress(self, progress) -> None:
        """Wan2GP ProgressUpdate → JobStore 진행 상태 업데이트."""
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
        """Wan2GP GenerationResult → JobStore 완료/실패 처리.

        이 콜백이 완료 처리의 유일한 경로이다.
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
        """Wan2GP GenerationError → JobStore 에러 추가 (락 안에서)."""
        job_id = self.active_job_id
        if job_id is None:
            return
        self._store.add_error(job_id, serialize_wan2gp_error(error))

    def on_preview(self, preview) -> None:
        """프리뷰 이미지는 무시한다."""
        pass

    def on_stream(self, line) -> None:
        """stdout/stderr 스트림은 무시한다."""
        pass
