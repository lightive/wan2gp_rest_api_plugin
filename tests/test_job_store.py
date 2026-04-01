from datetime import datetime, timezone

import pytest

from job_store import JobStore


def test_create_returns_accepted_state():
    store = JobStore()
    record = store.create("task", request_summary={"task_keys": ["prompt"]})
    assert record.job_id is not None
    assert record.state == "accepted"
    assert record.source_type == "task"


def test_get_snapshot_is_independent():
    store = JobStore()
    record = store.create("task")
    record.state = "running"  # modify the snapshot, not the store
    original = store.get(record.job_id)
    assert original.state == "accepted"  # store still has original state


def test_update_progress():
    store = JobStore()
    rec = store.create("task")
    store.update_progress(
        rec.job_id,
        phase="sampling",
        progress=50,
        current_step=10,
        total_steps=20,
    )
    updated = store.get(rec.job_id)
    assert updated.state == "running"
    assert updated.progress == 50
    assert updated.current_step == 10
    assert updated.total_steps == 20


def test_mark_completed_then_fails_ignored():
    store = JobStore()
    rec = store.create("task")
    store.mark_completed(rec.job_id, ["output_001.png"])
    # Second completion should be a no-op (terminal state guard)
    store.mark_completed(rec.job_id, ["output_002.png"])
    record = store.get(rec.job_id)
    assert record.state == "completed"
    assert record.generated_files == ["output_001.png"]


def test_try_cancel_not_found():
    store = JobStore()
    outcome, _ = store.try_cancel("nonexistent")
    assert outcome == "not_found"


def test_try_cancel_then_mark_cancelled():
    store = JobStore()
    rec = store.create("task")
    # Set a fake session_job
    with store._lock:
        store._jobs[rec.job_id].session_job = MagicMock()
    outcome, sess_job = store.try_cancel(rec.job_id)
    assert outcome == "ok"
    assert sess_job is not None
    store.mark_cancelled(rec.job_id)
    result = store.get(rec.job_id)
    assert result.state == "cancelled"


def test_try_cancel_rejected_for_completed():
    store = JobStore()
    rec = store.create("task")
    store.mark_completed(rec.job_id, [])
    outcome, _ = store.try_cancel(rec.job_id)
    assert outcome == "rejected"


def test_list_all_ordering_newest_first():
    store = JobStore()
    rec_a = store.create("task")
    rec_b = store.create("task")
    records = store.list_all()
    assert records[0].job_id == rec_b.job_id  # newest first
    assert records[1].job_id == rec_a.job_id


def test_evict_stale_after_one_hour(monkeypatch):
    store = JobStore()
    rec = store.create("task")
    store.mark_completed(rec.job_id, [])
    # Pretend time jumped 2 hours ahead
    future = datetime(2024, 1, 1, 15, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("job_store.datetime", MagicMock(wraps=datetime))
    from job_store import datetime as dt_cls

    class FrozenDatetime:
        @classmethod
        def now(cls, tz=None):
            return future

        @classmethod
        def __getattr__(cls, name):
            return getattr(datetime, name)

    monkeypatch.setattr("job_store.datetime", FrozenDatetime)
    store._evict_stale()
    assert store.get(rec.job_id) is None
