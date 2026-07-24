from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.market.service import MarketService


@pytest.fixture
def db_result():
    return MagicMock()


@pytest.fixture
def mock_db(db_result):
    db = MagicMock()
    db.execute = AsyncMock(return_value=db_result)
    return db


@pytest.fixture
def service(mock_db):
    svc = MarketService(
        db=mock_db,
        analysis_service=MagicMock(),
        llm_router=MagicMock(),
        notification_service=MagicMock(),
    )
    svc._analysis = MagicMock()
    svc._analysis.fusion = MagicMock()
    return svc


class TestListInstruments:
    async def test_returns_empty_when_no_instruments(self, service, db_result):
        db_result.scalars.return_value.all.return_value = []
        result = await service.list_instruments()
        assert result == []

    async def test_returns_instruments_with_price(self, service, db_result):
        inst = MagicMock()
        inst.id = 1
        inst.ticker = "SBER"
        inst.full_name = "Сбер Банк"
        inst.sector = "Финансы"
        inst.instrument_type = "stock"
        db_result.scalars.return_value.all.return_value = [inst]

        price = MagicMock()
        price.close = 250.5
        price.date = date(2024, 6, 1)
        db_result.scalar_one_or_none.return_value = price

        result = await service.list_instruments()
        assert len(result) == 1
        assert result[0]["ticker"] == "SBER"
        assert result[0]["last_price"] == 250.5


class TestGetInstrument:
    async def test_raises_404_when_not_found(self, service, db_result):
        db_result.scalar_one_or_none.return_value = None
        with pytest.raises(HTTPException) as exc:
            await service.get_instrument("UNKNOWN")
        assert exc.value.status_code == 404

    async def test_returns_instrument_data(self, service, db_result):
        inst = MagicMock()
        inst.id = 1
        inst.ticker = "SBER"
        inst.full_name = "Сбер Банк"
        inst.isin = "RU0009029540"
        inst.sector = "Финансы"
        inst.instrument_type = "stock"
        inst.lot_size = 10
        inst.currency = "RUB"
        db_result.scalar_one_or_none.return_value = inst

        result = await service.get_instrument("SBER")
        assert result["ticker"] == "SBER"
        assert result["isin"] == "RU0009029540"
        assert result["lot_size"] == 10


class TestGetPrices:
    async def test_raises_404_when_not_found(self, service, db_result):
        db_result.scalar_one_or_none.return_value = None
        with pytest.raises(HTTPException) as exc:
            await service.get_prices("UNKNOWN")
        assert exc.value.status_code == 404

    async def test_returns_prices_within_date_range(self, service, db_result):
        inst = MagicMock()
        inst.id = 1
        db_result.scalar_one_or_none.return_value = inst

        p1 = MagicMock(date=date(2024, 5, 1), open=100.0, high=101.0, low=99.0, close=100.5, volume=1000)
        p2 = MagicMock(date=date(2024, 6, 1), open=101.0, high=102.0, low=100.0, close=101.5, volume=1500)
        db_result.scalars.return_value.all.return_value = [p1, p2]

        result = await service.get_prices("SBER", days=365)
        assert len(result) == 2
        assert result[0]["close"] == 100.5
        assert result[1]["volume"] == 1500


class TestGetIndicators:
    async def test_raises_404_when_not_found(self, service, db_result):
        db_result.scalar_one_or_none.return_value = None
        with pytest.raises(HTTPException) as exc:
            await service.get_indicators("UNKNOWN")
        assert exc.value.status_code == 404

    async def test_returns_indicator_dicts(self, service, db_result):
        inst = MagicMock()
        inst.id = 1
        db_result.scalar_one_or_none.return_value = inst

        ind = MagicMock()
        ind.date = date(2024, 6, 1)
        ind.rsi = 55.0
        ind.macd_line = 0.5
        ind.macd_signal = 0.3
        ind.macd_hist = 0.2
        ind.sma_20 = 100.0
        ind.sma_50 = 98.0
        ind.sma_200 = 95.0
        ind.bb_upper = 110.0
        ind.bb_lower = 90.0
        ind.bb_mid = 100.0
        ind.volume_sma_20 = 5000.0
        ind.atr = 2.5
        db_result.scalars.return_value.all.return_value = [ind]

        result = await service.get_indicators("SBER")
        assert len(result) == 1
        assert result[0]["rsi"] == 55.0
        assert result[0]["atr"] == 2.5


class TestGetSignal:
    async def test_returns_fused_signal(self, service, db_result):
        inst = MagicMock()
        inst.id = 1
        fused = {"action": "BUY", "confidence": 0.85}
        db_result.scalar_one_or_none.side_effect = [inst, None]
        svc = service
        svc._analysis.analyze_single = AsyncMock(return_value=fused)
        svc._analysis.fusion.save_signal = AsyncMock()

        result = await svc.get_signal("SBER")
        assert result["action"] == "BUY"

    async def test_uses_cached_signal_when_available(self, service, db_result):
        inst = MagicMock()
        inst.id = 1
        cached = MagicMock()
        cached.fused_json = {"action": "HOLD", "confidence": 0.6, "cached": True}
        db_result.scalar_one_or_none.side_effect = [inst, cached]

        result = await service.get_signal("SBER")
        assert result["cached"] is True
        service._analysis.analyze_single.assert_not_called()


class TestGetTradePlan:
    async def test_raises_400_when_not_enough_price_data(self, service, db_result):
        inst = MagicMock()
        inst.id = 1
        db_result.scalar_one_or_none.return_value = inst
        db_result.scalars.return_value.all.return_value = [MagicMock(close=100.0) for _ in range(5)]

        with pytest.raises(HTTPException) as exc:
            await service.get_trade_plan("SBER")
        assert exc.value.status_code == 400

    async def test_raises_400_when_no_indicator_data(self, service, db_result):
        inst = MagicMock()
        inst.id = 1
        db_result.scalar_one_or_none.return_value = inst
        prices = [MagicMock(date=date(2024, 6, 1), open=100.0, high=101.0, low=99.0, close=100.5, volume=1000) for _ in range(25)]
        db_result.scalars.return_value.all.side_effect = [prices, []]

        with pytest.raises(HTTPException) as exc:
            await service.get_trade_plan("SBER")
        assert exc.value.status_code == 400


class TestGetAdvice:
    async def test_returns_signal_and_advice(self, service, db_result):
        inst = MagicMock()
        inst.id = 1
        fused = {"action": "BUY"}
        db_result.scalar_one_or_none.side_effect = [inst, None]
        svc = service
        svc._analysis.analyze_single = AsyncMock(return_value=fused)
        svc._analysis.fusion.save_signal = AsyncMock()
        svc._llm.advise = AsyncMock(return_value="Consider buying at support")

        result = await svc.get_advice("SBER", user_id=42)
        assert result["signal"]["action"] == "BUY"
        assert "Consider buying" in result["advice"]
        assert result["user_id"] == 42


class TestGetNews:
    async def test_limits_and_formats_news(self, service, db_result):
        n = MagicMock()
        n.id = 1
        n.title = "Test News"
        n.summary = "A" * 500
        n.source_name = "TASS"
        n.url = "https://example.com"
        n.published_at = datetime(2024, 6, 1, 12, 0, 0)
        db_result.scalars.return_value.all.return_value = [n]

        result = await service.get_news(limit=5)
        assert len(result) == 1
        assert result[0]["title"] == "Test News"
        assert len(result[0]["summary"]) == 300

    async def test_returns_empty_when_no_news(self, service, db_result):
        db_result.scalars.return_value.all.return_value = []
        result = await service.get_news()
        assert result == []
