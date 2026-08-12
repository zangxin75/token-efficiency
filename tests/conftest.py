"""pytest 共享 fixture。"""

import tempfile
from pathlib import Path
from typing import Iterator

import pytest

from tokeneff.meter.store import UsageStore
from tokeneff.meter.types import UsageRecord


@pytest.fixture
def tmp_db() -> Iterator[UsageStore]:
    """临时 UsageStore（隔离的 SQLite 文件）。"""
    tmpdir = Path(tempfile.mkdtemp())
    store = UsageStore(tmpdir / "test.db")
    import asyncio
    asyncio.get_event_loop_policy().new_event_loop()
    asyncio.run(store.init())
    yield store
    asyncio.run(store.close())


@pytest.fixture
def sample_records() -> list[UsageRecord]:
    """样例记录。"""
    return [
        UsageRecord("2026-08-12T10:00:00", "deepseek-v4-flash", "byok",
                    1000, 500, 0.001, 0.001, 0.0, "USD", 100),
        UsageRecord("2026-08-12T11:00:00", "deepseek-v4-flash", "byok",
                    2000, 1000, 0.002, 0.002, 0.0, "USD", 200),
        UsageRecord("2026-08-12T12:00:00", "gpt-4o", "byok",
                    500, 200, 0.01, 0.01, 0.0, "USD", 50),
    ]
