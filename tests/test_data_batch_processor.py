from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.data.batch_processor import NewsBatchProcessor


@pytest.fixture
def mock_engines():
    return {
        "filter_engine": MagicMock(),
        "classifier": MagicMock(),
        "deduplicator": MagicMock(),
        "sector_mapper": MagicMock(),
        "impact_engine": MagicMock(),
        "company_aggregator": MagicMock(),
        "geo_engine": MagicMock(),
        "event_detector": MagicMock(),
    }


@pytest.fixture
def processor(mock_engines):
    return NewsBatchProcessor(**mock_engines)


@pytest.fixture
def mock_article():
    a = MagicMock()
    a.id = 1
    a.title = "Oil prices surge on sanctions"
    a.summary = "Oil prices increased significantly"
    a.source_name = "Reuters"