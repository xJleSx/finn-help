from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from src.scheduler.tasks import _delete_today_signals, _process_in_batches


@pytest.mark.asyncio
async def test_delete_today_signals():
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    with patch("src.scheduler.tasks.date") as mock_date:
        mock_date.today.return_value = date(2026, 7, 17)
        await _delete_today_signals(mock_db)
        assert mock_db.execute.called
        assert mock_db.commit.called


@pytest.mark.asyncio
async def test_process_in_batches_single_batch():
    async def processor(item: int) -> int:
        return item * 2

    results = await _process_in_batches([1, 2, 3], processor, batch_size=5)
    assert results == [2, 4, 6]


@pytest.mark.asyncio
async def test_process_in_batches_multiple():
    async def processor(item: int) -> int:
        return item + 1

    results = await _process_in_batches([1, 2, 3, 4, 5, 6], processor, batch_size=3)
    assert results == [2, 3, 4, 5, 6, 7]


@pytest.mark.asyncio
async def test_process_in_batches_empty():
    results = await _process_in_batches([], lambda x: x)
    assert results == []


@pytest.mark.asyncio
async def test_process_in_batches_with_errors():
    async def processor(item: int) -> int:
        if item == 2:
            raise ValueError("error")
        return item

    results = await _process_in_batches([1, 2, 3], processor, batch_size=2)
    assert results[0] == 1
    assert results[1] is None
    assert results[2] == 3
