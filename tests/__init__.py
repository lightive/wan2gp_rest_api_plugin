from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def now() -> datetime:
    return datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def store_cls():
    from job_store import JobStore
    return JobStore
