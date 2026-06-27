from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.analysis.service import AnalysisService
from src.db.models import Indicator, MarketEvent, Price


def _chain(iterable, fallback):
    """Yield items from iterable, then yield fallback indefinitely."""
    for item in iterable:
        yield item
    while True:
        yield fallback


# ── Real data builders ──────────────────────────────────────────────


def _real_price_df(n: int = 150, start_date: date | None = None) -> pd.DataFrame:
    if start_date is None:
        start_date = date(2024, 1, 1)
    rng = np.random.default_rng(42)
    closes = 100.0 + np.cumsum(rng.normal(0, 1, n))
    opens = closes + rng.normal(0, 0.5, n)
    highs = np.maximum(closes, opens) + abs(rng.normal(0, 0.5, n))
    lows = np.minimum(closes, opens) - abs(rng.normal(0, 0.5, n))
    return pd.DataFrame(
        {
            "date": [start_date + timedelta(days=i) for i in range(n)],
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": np.random.default_rng(8).poisson(5_000_000, n),
        }
    )


def _real_indicator_df(n: int = 150, start_date: date | None = None) -> pd.DataFrame:
    if start_date is None:
        start_date = date(2024, 1, 1)
    rng = np.random.default_rng(9)
    closes = 100.0 + np.cumsum(rng.normal(0, 1, n))
    df = pd.DataFrame({"close": closes})
    df["rsi"] = np.clip(50 + rng.normal(0, 10, n), 0, 100)
    df["macd_line"] = rng.normal(0, 1, n)
    df["macd_signal"] = rng.normal(0, 0.8, n)
    df["macd_hist"] = df["macd_line"] - df["macd_signal"]
    df["sma_20"] = df["close"].rolling(20, min_periods=1).mean()
    df["sma_50"] = df["close"].rolling(50, min_periods=1).mean()
    df["sma_200"] = df["close"].rolling(200, min_periods=1).mean()
    df["bb_upper"] = df["sma_20"] + df["close"].rolling(20, min_periods=1).std() * 2
    df["bb_lower"] = df["sma_20"] - df["close"].rolling(20, min_periods=1).std() * 2
    df["bb_mid"] = df["sma_20"]
    df["volume_sma_20"] = np.full(n, 1_000_000.0)
    df["atr"] = np.abs(rng.normal(2, 0.5, n))
    df["date"] = [start_date + timedelta(days=i) for i in range(n)]
    return df


# ── Service fixtures ───────────────────────────────────────────────


@pytest.fixture
def service():
    return AnalysisService()


# ── DataFrame conversion tests ─────────────────────────────────────


class TestPriceDf:
    def test_converts_price_objects(self, service):
        prices = [MagicMock(date=date(2024, 1, 1), open=100.0, high=101.0, low=99.0, close=100.5, volume=1000)]
        df = service._price_df(prices)
        assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
        assert df["close"].iloc[0] == 100.5

    def test_empty_list(self, service):
        assert service._price_df([]).empty


class TestIndicatorDf:
    def test_converts_indicator_objects(self, service):
        rows = [
            MagicMock(
                date=date(2024, 1, 1),
                rsi=55.0,
                macd_line=0.5,
                macd_signal=0.3,
                macd_hist=0.2,
                sma_20=101.0,
                sma_50=100.0,
                sma_200=99.0,
                bb_upper=105.0,
                bb_lower=95.0,
                bb_mid=100.0,
                volume_sma_20=1_000_000.0,
                atr=2.0,
            )
        ]
        df = service._indicator_df(rows)
        assert df["rsi"].iloc[0] == 55.0

    def test_empty_list(self, service):
        assert service._indicator_df([]).empty


class TestDividendDf:
    def test_empty_list(self, service):
        assert service._dividend_df([]).empty


# ── _compute_ml tests (real DataFrames + mock models) ──────────────


class TestComputeMl:
    def test_returns_none_when_less_than_60_rows(self, service):
        df = pd.DataFrame({"close": [100] * 59, "date": [date(2024, 1, 1)] * 59})
        ind_df = pd.DataFrame({"rsi": [50] * 59})
        assert service._compute_ml(df, ind_df, "TEST") is None

    def test_returns_properly_structured_dict(self, service):
        df = _real_price_df(100)
        ind_df = _real_indicator_df(100)
        mock_prophet = MagicMock()
        mock_prophet.predict.return_value = {
            "target_price": 105.0,
            "current_price": 100.0,
            "price_change_pct": 5.0,
            "confidence": 0.7,
        }
        mock_ensemble = MagicMock()
        mock_ensemble.predict.return_value = {
            "confidence": 0.6,
            "xgb_action": "BUY",
            "lgb_action": "BUY",
            "cat_action": "HOLD",
            "model_votes": {"xgb": "BUY", "lgb": "BUY", "cat": "HOLD"},
        }
        with (
            patch.object(service, "_get_prophet", return_value=mock_prophet),
            patch.object(service, "_get_ensemble", return_value=mock_ensemble),
        ):
            result = service._compute_ml(df, ind_df, "TEST")
        assert result["ml_confidence"] == max(0.7, 0.6)
        assert result["xgb_action"] == "BUY"
        assert result["ensemble"]["cat_action"] == "HOLD"

    def test_returns_none_on_exception(self, service):
        df = pd.DataFrame({"close": [100] * 60, "date": [date(2024, 1, 1)] * 60})
        ind_df = pd.DataFrame({"rsi": [50] * 60})
        with patch.object(service, "_get_prophet", side_effect=ValueError("fail")):
            assert service._compute_ml(df, ind_df, "TEST") is None


# ── analyze_single with real analyzers (only DB mocked) ────────────


class TestAnalyzeSingle:
    @pytest.fixture
    def db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        return db

    @staticmethod
    def _price_mocks(n=100, start=date(2024, 1, 1)):
        return [
            MagicMock(
                date=start + timedelta(days=i),
                open=100.0 + i * 0.2,
                high=101.0 + i * 0.2,
                low=99.0 + i * 0.2,
                close=100.0 + i * 0.2,
                volume=1_000_000,
            )
            for i in range(n)
        ]

    @staticmethod
    def _indicator_mocks(n=100, start=date(2024, 1, 1)):
        return [
            MagicMock(
                date=start + timedelta(days=i),
                rsi=50.0 + (i % 30),
                macd_line=0.5,
                macd_signal=0.4,
                macd_hist=0.1,
                sma_20=101.0,
                sma_50=100.0,
                sma_200=99.0,
                bb_upper=105.0,
                bb_lower=95.0,
                bb_mid=100.0,
                volume_sma_20=1_000_000.0,
                atr=2.0,
            )
            for i in range(n)
        ]

    @pytest.mark.asyncio
    async def test_raises_on_insufficient_data(self, service, db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = self._price_mocks(49)
        db.execute.return_value = mock_result
        with pytest.raises(ValueError, match="Not enough price data for TEST"):
            await service.analyze_single(db, MagicMock(id=1), "TEST")

    @staticmethod
    def _setup_db_for_analyze(db, price_n=80, ind_n=80):
        price_mocks = TestAnalyzeSingle._price_mocks(price_n)
        ind_mocks = TestAnalyzeSingle._indicator_mocks(ind_n)
        div_mocks = []

        mock_prices = MagicMock()
        mock_prices.scalars.return_value.all.return_value = price_mocks
        mock_inds = MagicMock()
        mock_inds.scalars.return_value.all.return_value = ind_mocks
        mock_divs = MagicMock()
        mock_divs.scalars.return_value.all.return_value = div_mocks
        mock_fallback = MagicMock()
        mock_fallback.scalars.return_value.all.return_value = []
        mock_fallback.scalar_one_or_none.return_value = None
        mock_fallback.order_by.return_value = mock_fallback

        db.execute.side_effect = _chain([mock_prices, mock_inds, mock_divs], mock_fallback)

    @pytest.mark.asyncio
    async def test_runs_real_analyzers_on_real_data(self, service, db):
        self._setup_db_for_analyze(db)
        inst = MagicMock(id=1)
        with (
            patch.object(service, "_load_geo", AsyncMock(return_value={"score": 0.0})),
            patch.object(service, "_load_macro", AsyncMock(return_value={})),
            patch.object(
                service, "_load_sentiment", AsyncMock(return_value={"score": 0.0, "divergence": 0.0, "source": "none"})
            ),
            patch.object(service, "_compute_ml", return_value=None),
        ):
            result = await service.analyze_single(db, inst, "TEST", with_ml=False)
        assert result["ticker"] == "TEST"
        assert "action" in result
        assert "confidence" in result
        assert result["confidence"] >= 0.0
        assert result["action"] in ("BUY", "SELL", "HOLD", "CAUTIOUS_BUY", "NEUTRAL")

    @pytest.mark.asyncio
    async def test_ml_confidence_reflected_in_result(self, service, db):
        self._setup_db_for_analyze(db)
        inst = MagicMock(id=1)
        ml_result = {
            "target_price": 110.0,
            "signal_score": 0.5,
            "ml_confidence": 0.7,
            "xgb_action": "BUY",
            "ensemble": {},
        }
        with (
            patch.object(service, "_load_geo", AsyncMock(return_value={"score": 0.0})),
            patch.object(service, "_load_macro", AsyncMock(return_value={})),
            patch.object(
                service, "_load_sentiment", AsyncMock(return_value={"score": 0.0, "divergence": 0.0, "source": "none"})
            ),
            patch.object(service, "_compute_ml", return_value=ml_result),
        ):
            result = await service.analyze_single(db, inst, "TEST", with_ml=True)
        assert result["ticker"] == "TEST"
        assert result["components"]["ml"]["signal_score"] == 0.5


class TestAnalyzeAll:
    @staticmethod
    def _async_db(instruments, cached=None):
        db = MagicMock()
        db.execute = AsyncMock()

        mock_instruments = MagicMock()
        mock_instruments.scalars.return_value.all.return_value = instruments
        mock_any = MagicMock()
        mock_any.scalar_one_or_none.return_value = cached
        mock_any.scalars.return_value.all.return_value = []

        def side_effect(*a, **kw):
            q = a[0] if a else kw.get("statement", "")
            q_str = str(q)
            if "from instrument" in q_str.lower():
                return mock_instruments
            return mock_any

        db.execute.side_effect = side_effect
        return db

    @pytest.mark.asyncio
    async def test_processes_all_instruments(self, service):
        db = self._async_db([MagicMock(id=1, ticker="SBER"), MagicMock(id=2, ticker="GAZP")])
        mock_single = AsyncMock(return_value={"action": "BUY", "confidence": 0.8, "ticker": "SBER"})
        mock_save = AsyncMock()
        with (
            patch.object(service, "analyze_single", mock_single),
            patch.object(service.fusion, "save_signal", mock_save),
        ):
            results = await service.analyze_all(db, with_ml=False)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_filters_by_updated_ids(self, service):
        db = self._async_db([MagicMock(id=1, ticker="SBER")])
        with (
            patch.object(service, "analyze_single", AsyncMock(return_value={"action": "BUY"})),
            patch.object(service.fusion, "save_signal", AsyncMock()),
        ):
            results = await service.analyze_all(db, updated_ids={1}, with_ml=False)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_returns_cached_result(self, service):
        cached = MagicMock()
        cached.fused_json = {"action": "BUY", "confidence": 0.8}
        db = self._async_db([MagicMock(id=1, ticker="SBER")], cached=cached)
        with patch.object(service, "analyze_single") as mock_single:
            results = await service.analyze_all(db, with_ml=False)
        assert results == [{"action": "BUY", "confidence": 0.8}]
        mock_single.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_instruments_with_value_error(self, service):
        db = self._async_db([MagicMock(id=1, ticker="SBER"), MagicMock(id=2, ticker="GAZP")])
        with (
            patch.object(service, "analyze_single", AsyncMock(side_effect=[ValueError("no data"), {"action": "BUY"}])),
            patch.object(service.fusion, "save_signal", AsyncMock()),
        ):
            results = await service.analyze_all(db, with_ml=False)
        assert len(results) == 1


class TestAnalyzeWithAdvice:
    @pytest.mark.asyncio
    async def test_returns_fused_and_advice(self, service):
        fused = {"action": "BUY", "confidence": 0.8}
        with (
            patch.object(service, "analyze_single", AsyncMock(return_value=fused)) as mock_single,
            patch("src.analysis.service.llm") as mock_llm,
        ):
            mock_llm.advise = AsyncMock(return_value="Buy recommendation")
            result_fused, advice = await service.analyze_with_advice(AsyncMock(), MagicMock(id=1), "SBER")
        assert result_fused == fused
        assert advice == "Buy recommendation"
        mock_single.assert_called_once()


class TestAnalyzeAllSync:
    def test_processes_all_instruments(self, service):
        inst1, inst2 = MagicMock(id=1, ticker="SBER"), MagicMock(id=2, ticker="GAZP")
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [inst1, inst2]
        db.query.return_value.all.return_value = [inst1, inst2]
        db.query.return_value.filter.return_value.first.return_value = None

        with (
            patch.object(
                service,
                "_analyze_single_sync",
                side_effect=[
                    {"action": "BUY", "confidence": 0.8, "ticker": "SBER"},
                    {"action": "SELL", "confidence": 0.6, "ticker": "GAZP"},
                ],
            ),
            patch.object(service.fusion, "save_signal_sync", MagicMock()),
        ):
            results = service.analyze_all_sync(db)
        assert len(results) == 2
        assert results[0]["action"] == "BUY"
        assert results[1]["action"] == "SELL"

    def test_returns_cached_result(self, service):
        db = MagicMock()
        inst = MagicMock(id=1, ticker="SBER")
        db.query.return_value.filter.return_value.all.return_value = [inst]
        db.query.return_value.all.return_value = [inst]
        cached = MagicMock()
        cached.fused_json = {"action": "BUY", "confidence": 0.8}
        db.query.return_value.filter.return_value.first.return_value = cached
        with patch.object(service, "_analyze_single_sync") as mock_single:
            results = service.analyze_all_sync(db)
        assert results == [{"action": "BUY", "confidence": 0.8}]
        mock_single.assert_not_called()

    def test_skips_cached_non_dict_json(self, service):
        db = MagicMock()
        inst = MagicMock(id=1, ticker="SBER")
        db.query.return_value.all.return_value = [inst]
        db.query.return_value.filter.return_value.all.return_value = [inst]
        cached = MagicMock()
        cached.fused_json = "not a dict"
        db.query.return_value.filter.return_value.first.return_value = cached
        with (
            patch.object(
                service, "_analyze_single_sync", return_value={"action": "HOLD", "confidence": 0.5, "ticker": "SBER"}
            ),
            patch.object(service.fusion, "save_signal_sync", MagicMock()),
        ):
            results = service.analyze_all_sync(db)
        assert len(results) == 0

    def test_skips_instrument_on_value_error(self, service):
        db = MagicMock()
        inst = MagicMock(id=1, ticker="SBER")
        db.query.return_value.filter.return_value.all.return_value = [inst]
        db.query.return_value.all.return_value = [inst]
        db.query.return_value.filter.return_value.first.return_value = None
        with patch.object(service, "_analyze_single_sync", side_effect=ValueError("no data")):
            results = service.analyze_all_sync(db)
        assert results == []

    def test_catches_generic_exception(self, service):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [MagicMock(id=1, ticker="SBER")]
        db.query.return_value.filter.return_value.first.return_value = None
        db.query.return_value.order_by.return_value.all.side_effect = Exception("db error")
        with patch.object(service, "_analyze_single_sync") as mock_single:
            results = service.analyze_all_sync(db)
        assert results == []
        mock_single.assert_not_called()


class TestTrainModels:
    @staticmethod
    def _train_db(instruments, price_count=100, ind_count=10):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = instruments
        price_mock = MagicMock()
        price_mock.filter_by.return_value.order_by.return_value.all.return_value = [
            MagicMock() for _ in range(price_count)
        ]
        ind_mock = MagicMock()
        ind_mock.filter_by.return_value.order_by.return_value.all.return_value = [MagicMock() for _ in range(ind_count)]

        def query_side(model):
            if model is Price:
                return price_mock
            if model is Indicator:
                return ind_mock
            if model is MarketEvent:
                m = MagicMock()
                m.order_by.return_value.all.return_value = []
                return m
            m = MagicMock()
            m.filter_by.return_value.order_by.return_value.all.return_value = []
            return m

        db.query.side_effect = query_side
        return db

    def test_returns_results_dict(self, service):
        db = self._train_db([MagicMock(id=1, ticker="SBER")])
        mock_ensemble = MagicMock()
        mock_ensemble.train_all.return_value = {"lgb": True, "xgb": True, "cat": True}
        mock_prophet = MagicMock()
        mock_prophet.train.return_value = True
        with (
            patch.object(service, "_get_ensemble", return_value=mock_ensemble),
            patch.object(service, "_get_prophet", return_value=mock_prophet),
        ):
            results = service.train_models(db)
        assert results == {"SBER": True}

    def test_filters_by_ticker(self, service):
        db = self._train_db([MagicMock(id=1, ticker="SBER")])
        with (
            patch.object(service, "_get_ensemble", return_value=MagicMock(train_all=MagicMock(return_value={}))),
            patch.object(service, "_get_prophet", return_value=MagicMock(train=MagicMock(return_value=False))),
        ):
            assert len(service.train_models(db, ticker="SBER")) == 1

    def test_skips_instrument_with_insufficient_prices(self, service):
        db = self._train_db([MagicMock(id=1, ticker="SBER")], price_count=59)
        assert service.train_models(db) == {}

    def test_reports_partial_training(self, service):
        db = self._train_db([MagicMock(id=1, ticker="SBER")])
        mock_ensemble = MagicMock()
        mock_ensemble.train_all.return_value = {"lgb": True, "xgb": False, "cat": True}
        mock_prophet = MagicMock()
        mock_prophet.train.return_value = True
        with (
            patch.object(service, "_get_ensemble", return_value=mock_ensemble),
            patch.object(service, "_get_prophet", return_value=mock_prophet),
        ):
            assert service.train_models(db) == {"SBER": False}

    def test_multiple_instruments(self, service):
        db = self._train_db([MagicMock(id=1, ticker="SBER"), MagicMock(id=2, ticker="GAZP")])
        mock_ensemble = MagicMock()
        mock_ensemble.train_all.return_value = {"lgb": True, "xgb": True}
        mock_prophet = MagicMock()
        mock_prophet.train.return_value = True
        with (
            patch.object(service, "_get_ensemble", return_value=mock_ensemble),
            patch.object(service, "_get_prophet", return_value=mock_prophet),
        ):
            assert service.train_models(db) == {"SBER": True, "GAZP": True}
