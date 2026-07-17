"""Tests for MOEXCollector mock mode."""

from unittest.mock import patch

import pytest

from src.collectors.moex import MOEXCollector


@pytest.mark.asyncio
async def test_mock_returns_securities():
    with patch("src.collectors.moex.MOCK_DATA_ENABLED", True):
        collector = MOEXCollector()
        data = await collector.get_securities()
        assert len(data) > 0
        assert data[0].get("SECID") == "SU26238RMFS5"


@pytest.mark.asyncio
async def test_mock_returns_coupons():
    with patch("src.collectors.moex.MOCK_DATA_ENABLED", True):
        collector = MOEXCollector()
        data = await collector.get_coupons("SU26238RMFS5")
        assert len(data) > 0
        assert data[0].get("COUPON_DATE") is not None


@pytest.mark.asyncio
async def test_mock_returns_history():
    with patch("src.collectors.moex.MOCK_DATA_ENABLED", True):
        collector = MOEXCollector()
        data = await collector.get_history("SU26238RMFS5", board="bond")
        assert len(data) > 0
        assert data[0].get("CLOSE") is not None


@pytest.mark.asyncio
async def test_mock_disabled_calls_real():
    with patch("src.collectors.moex.MOCK_DATA_ENABLED", False):
        with patch.object(MOEXCollector, "_fetch_json") as mock_fetch:
            mock_fetch.return_value = {"securities": {"columns": ["SECID"], "data": [["SU26238"]]}}
            collector = MOEXCollector()
            data = await collector.get_securities()
            mock_fetch.assert_called_once()
            assert len(data) == 1
