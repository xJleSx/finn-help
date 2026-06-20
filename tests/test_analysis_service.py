from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from src.db.models import Dividend, GeoRiskScore, Indicator, Instrument, News, Price, Signal


@pytest.fixture
def service():
    from src.analysis.service import AnalysisService
    return AnalysisService()


def _make_prices(n: int = 100, start_date: date | None = None) -> list[MagicMock]:
    if start_date is None:
        start_date = date(2024, 1, 1)
    prices = []
    for i in range(n):
        d = MagicMock()
        d.date = start_date + timedelta(days=i)
        d.open = 100.0 + i * 0.5
        d.high = 101.0 + i * 0.5
        d.low = 99.0 + i * 0.5
        d.close = 100.0 + i * 0.5
        d.volume = 1_000_000 + i * 100
        prices.append(d)
    return prices


def _make_indicators(n: int = 100, start_date: date | None = None) -> list[MagicMock]:
    if start_date is None:
        start_date = date(2024, 1, 1)
    rows = []
    for i in range(n):
        r = MagicMock()
        r.date = start_date + timedelta(days=i)
        r.rsi = 50.0 + i * 0.1
        r.macd_line = 0.5
        r.macd_signal = 0.4
        r.macd_hist = 0.1
        r.sma_20 = 101.0
        r.sma_50 = 100.0
        r.sma_200 = 99.0
        r.bb_upper = 105.0
        r.bb_lower = 95.0
        r.bb_mid = 100.0
        r.volume_sma_20 = 1_000_000.0
        r.atr = 2.0
        rows.append(r)
    return rows


def _make_dividends(n: int = 5) -> list[MagicMock]:
    divs = []
    for i in range(n):
        d = MagicMock()
        d.date = date(2024, 6, 1) + timedelta(days=30 * i)
        d.amount = 10.0 + i
        divs.append(d)
    return divs


def _async_db() -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock()
    db.execute.return_value = MagicMock()
    return db


class TestInit:
    def test_creates_analyzers(self, service):
        from src.analysis.service import TechnicalAnalyzer, FundamentalAnalyzer
        from src.analysis.volatility import VolatilityRegimeDetector
        from src.analysis.multi_timeframe import MultiTimeframeAnalyzer
        from src.signal.engine import SignalFusionEngine
        assert isinstance(service.analyzer, TechnicalAnalyzer)
        assert isinstance(service.fundamental, FundamentalAnalyzer)
        assert isinstance(service.fusion, SignalFusionEngine)
        assert isinstance(service.volatility, VolatilityRegimeDetector)
        assert isinstance(service.mtf, MultiTimeframeAnalyzer)
        assert service._prophet is None
        assert service._ensemble is None

    def test_prophet_property_uses_get_prophet(self, service):
        with (
            patch("src.analysis.ml.prophet_model.ProphetPredictor") as MockPP,
            patch.object(service, "_prophet_cache", {}, create=True),
        ):
            p = service.prophet
        MockPP.assert_called_once_with(ticker="")
        assert p is MockPP.return_value

    def test_ensemble_property_uses_get_ensemble(self, service):
        with (
            patch("src.analysis.ml.ensemble.EnsemblePredictor") as MockEP,
            patch.object(service, "_ensemble_cache", {}, create=True),
        ):
            e = service.ensemble
        MockEP.assert_called_once_with(ticker="")
        assert e is MockEP.return_value

    def test_get_prophet_caches_by_ticker(self, service):
        with patch("src.analysis.ml.prophet_model.ProphetPredictor") as MockPP:
            MockPP.side_effect = lambda ticker="": MagicMock(ticker=ticker)
            p1 = service._get_prophet("SBER")
            p2 = service._get_prophet("SBER")
            p3 = service._get_prophet("GAZP")
        assert p1 is p2
        assert p1 is not p3
        assert p1.ticker == "SBER"
        assert p3.ticker == "GAZP"
        assert MockPP.call_count == 2
        MockPP.assert_any_call(ticker="SBER")
        MockPP.assert_any_call(ticker="GAZP")

    def test_get_ensemble_caches_by_ticker(self, service):
        with patch("src.analysis.ml.ensemble.EnsemblePredictor") as MockEP:
            MockEP.side_effect = lambda ticker="": MagicMock(ticker=ticker)
            e1 = service._get_ensemble("SBER")
            e2 = service._get_ensemble("SBER")
            e3 = service._get_ensemble("GAZP")
        assert e1 is e2
        assert e1 is not e3
        assert e1.ticker == "SBER"
        assert e3.ticker == "GAZP"
        assert MockEP.call_count == 2
        MockEP.assert_any_call(ticker="SBER")
        MockEP.assert_any_call(ticker="GAZP")


class TestPriceDf:
    def test_converts_price_list(self, service):
        prices = _make_prices(10)
        df = service._price_df(prices)
        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
        assert len(df) == 10
        assert df["close"].iloc[0] == 100.0

    def test_empty_list(self, service):
        df = service._price_df([])
        assert df.empty


class TestIndicatorDf:
    def test_converts_indicator_list(self, service):
        rows = _make_indicators(10)
        df = service._indicator_df(rows)
        expected = ["date", "rsi", "macd_line", "macd_signal", "macd_hist", "sma_20", "sma_50", "sma_200", "bb_upper", "bb_lower", "bb_mid", "volume_sma_20", "atr"]
        assert list(df.columns) == expected
        assert len(df) == 10
        assert df["rsi"].iloc[0] == 50.0

    def test_empty_list(self, service):
        df = service._indicator_df([])
        assert df.empty


class TestDividendDf:
    def test_converts_dividend_list(self, service):
        divs = _make_dividends(5)
        df = service._dividend_df(divs)
        assert list(df.columns) == ["date", "amount"]
        assert len(df) == 5

    def test_empty_list(self, service):
        df = service._dividend_df([])
        assert df.empty


class TestComputeMl:
    def test_returns_none_when_less_than_60_rows(self, service):
        df = pd.DataFrame({"close": [100] * 59})
        ind_df = pd.DataFrame({"rsi": [50] * 59})
        assert service._compute_ml(df, ind_df, "TEST") is None

    def test_returns_merged_dict(self, service):
        df = pd.DataFrame({"close": [100] * 60, "date": [date(2024, 1, 1)] * 60})
        ind_df = pd.DataFrame({"rsi": [50] * 60})
        mock_prophet = MagicMock()
        mock_prophet.predict.return_value = {"target_price": 105.0, "current_price": 100.0, "price_change_pct": 5.0, "confidence": 0.7}
        mock_ensemble = MagicMock()
        mock_ensemble.predict.return_value = {"confidence": 0.6, "xgb_action": "BUY", "lgb_action": "BUY", "cat_action": "HOLD", "model_votes": {"xgb": "BUY", "lgb": "BUY", "cat": "HOLD"}}
        with patch.object(service, "_get_prophet", return_value=mock_prophet) as gp, patch.object(service, "_get_ensemble", return_value=mock_ensemble) as ge:
            result = service._compute_ml(df, ind_df, "TEST")
        gp.assert_called_once_with("TEST")
        ge.assert_called_once_with("TEST")
        assert result["target_price"] == 105.0
        assert result["ml_confidence"] == 0.7
        assert result["xgb_action"] == "BUY"
        assert result["ensemble"]["cat_action"] == "HOLD"
        assert result["ensemble"]["model_votes"]["xgb"] == "BUY"

    def test_ml_confidence_uses_max(self, service):
        df = pd.DataFrame({"close": [100] * 60, "date": [date(2024, 1, 1)] * 60})
        ind_df = pd.DataFrame({"rsi": [50] * 60})
        with (
            patch.object(service, "_get_prophet", return_value=MagicMock(predict=MagicMock(return_value={"confidence": 0.3}))),
            patch.object(service, "_get_ensemble", return_value=MagicMock(predict=MagicMock(return_value={"confidence": 0.9, "xgb_action": "BUY", "model_votes": {}}))),
        ):
            result = service._compute_ml(df, ind_df, "TEST")
        assert result["ml_confidence"] == 0.9

    def test_returns_none_on_exception(self, service):
        df = pd.DataFrame({"close": [100] * 60, "date": [date(2024, 1, 1)] * 60})
        ind_df = pd.DataFrame({"rsi": [50] * 60})
        with patch.object(service, "_get_prophet", side_effect=ValueError("fail")):
            assert service._compute_ml(df, ind_df, "TEST") is None


class TestLoadGeo:
    @pytest.mark.asyncio
    async def test_returns_score(self, service):
        db = _async_db()
        db.execute.return_value.scalar_one_or_none.return_value = MagicMock(score=7.5)
        assert await service._load_geo(db) == {"score": 7.5}

    @pytest.mark.asyncio
    async def test_returns_zero_when_none(self, service):
        db = _async_db()
        db.execute.return_value.scalar_one_or_none.return_value = None
        assert await service._load_geo(db) == {"score": 0.0}


class TestLoadMacro:
    @pytest.mark.asyncio
    async def test_returns_macro_data(self, service):
        db = _async_db()
        with patch("src.collectors.macro.MacroCollector") as MockMacro:
            MockMacro.latest_values_async = AsyncMock(return_value={"inflation": 7.5})
            result = await service._load_macro(db)
        assert result == {"inflation": 7.5}


class TestLoadSentiment:
    @pytest.mark.asyncio
    async def test_returns_scores_from_recent_news(self, service):
        db = _async_db()
        n1, n2 = MagicMock(), MagicMock()
        n1.sentiment_weighted, n1.sentiment_score = 0.5, 0.4
        n2.sentiment_weighted, n2.sentiment_score = -0.3, -0.2
        db.execute.return_value.scalars.return_value.all.return_value = [n1, n2]
        result = await service._load_sentiment(db)
        assert result["score"] == 0.1
        assert result["divergence"] == 0.32
        assert result["source"] == "rss"
        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_falls_back_when_no_news(self, service):
        db = _async_db()
        db.execute.return_value.scalars.return_value.all.return_value = []
        assert await service._load_sentiment(db) == {"score": 0.0, "divergence": 0.0, "source": "none"}

    @pytest.mark.asyncio
    async def test_divergence_capped_at_one(self, service):
        db = _async_db()
        n1, n2 = MagicMock(), MagicMock()
        n1.sentiment_weighted, n1.sentiment_score = 1.0, 1.0
        n2.sentiment_weighted, n2.sentiment_score = -1.0, -1.0
        db.execute.return_value.scalars.return_value.all.return_value = [n1, n2]
        result = await service._load_sentiment(db)
        assert result["divergence"] == 1.0

    @pytest.mark.asyncio
    async def test_single_news_zero_variance(self, service):
        db = _async_db()
        n1 = MagicMock()
        n1.sentiment_weighted, n1.sentiment_score = 0.5, 0.5
        db.execute.return_value.scalars.return_value.all.return_value = [n1]
        result = await service._load_sentiment(db)
        assert result["score"] == 0.5
        assert result["divergence"] == 0.0

    @pytest.mark.asyncio
    async def test_uses_sentiment_score_when_weighted_none(self, service):
        db = _async_db()
        n1 = MagicMock()
        n1.sentiment_weighted, n1.sentiment_score = None, 0.3
        db.execute.return_value.scalars.return_value.all.return_value = [n1]
        assert (await service._load_sentiment(db))["score"] == 0.3


class TestAnalyzeSingle:
    @pytest.mark.asyncio
    async def test_raises_on_insufficient_prices(self, service):
        db = _async_db()
        db.execute.return_value.scalars.return_value.all.return_value = _make_prices(49)
        with pytest.raises(ValueError, match="Not enough price data for TEST"):
            await service.analyze_single(db, MagicMock(id=1), "TEST")

    @pytest.mark.asyncio
    async def test_raises_on_insufficient_indicators(self, service):
        db = _async_db()
        db.execute.return_value.scalars.return_value.all.side_effect = [_make_prices(50), _make_indicators(1)]
        with pytest.raises(ValueError, match="Not enough indicator data for TEST"):
            await service.analyze_single(db, MagicMock(id=1), "TEST")

    @pytest.mark.asyncio
    async def test_fuses_all_components(self, service):
        db = _async_db()
        db.execute.return_value.scalars.return_value.all.side_effect = [_make_prices(50), _make_indicators(50), _make_dividends(3)]
        inst = MagicMock(id=1)
        mock_fuse = MagicMock(return_value={"action": "BUY", "confidence": 0.75, "ticker": "TEST", "reasons": [], "components": {}})
        with (
            patch.object(service.analyzer, "generate_signal", return_value={"action": "BUY", "confidence": 0.8, "score": 0.7, "reasons": []}),
            patch.object(service.fundamental, "analyze", return_value={"risk": 0.2, "anomalies": [], "signals": []}),
            patch.object(service.volatility, "detect", return_value={"regime": "NORMAL", "atr_ratio": 0.02, "hv": 0.2, "adjustment": 1.0}),
            patch.object(service.mtf, "compute_all", return_value={"daily": pd.DataFrame(), "weekly": pd.DataFrame()}),
            patch.object(service.mtf, "concordance", return_value={"concordance": 0.8, "signals": []}),
            patch.object(service.fusion, "fuse", mock_fuse),
            patch.object(service, "_load_geo", AsyncMock(return_value={"score": 3.0})),
            patch.object(service, "_load_macro", AsyncMock(return_value={"inflation": 7.5})),
            patch.object(service, "_load_sentiment", AsyncMock(return_value={"score": 0.2, "divergence": 0.1, "source": "rss"})),
            patch.object(service, "_compute_ml", return_value=None),
            patch("src.analysis.service.compute_risk_metrics", return_value={"sharpe": 1.5, "max_drawdown": 0.1}),
        ):
            result = await service.analyze_single(db, inst, "TEST", with_ml=True)
        assert result["action"] == "BUY"
        mock_fuse.assert_called_once()
        kw = mock_fuse.call_args[1]
        assert kw["ticker"] == "TEST"
        assert kw["technical"]["action"] == "BUY"
        assert kw["fundamental"]["risk"] == 0.2
        assert kw["geo"]["score"] == 3.0
        assert kw["volatility_regime"]["regime"] == "NORMAL"
        assert kw["risk_metrics"]["sharpe"] == 1.5
        assert kw["macro_context"]["inflation"] == 7.5
        assert kw["sentiment"]["score"] == 0.2
        assert kw["ml_prediction"] is None

    @pytest.mark.asyncio
    async def test_with_ml_false_skips_ml(self, service):
        db = _async_db()
        db.execute.return_value.scalars.return_value.all.side_effect = [_make_prices(50), _make_indicators(50), _make_dividends(3)]
        with (
            patch.object(service.analyzer, "generate_signal", return_value={"action": "HOLD", "confidence": 0.5, "score": 0.0, "reasons": []}),
            patch.object(service.fundamental, "analyze", return_value={"risk": 0.0}),
            patch.object(service.volatility, "detect", return_value={"regime": "NORMAL"}),
            patch.object(service.mtf, "compute_all", return_value={}),
            patch.object(service.fusion, "fuse", return_value={"action": "HOLD", "confidence": 0.5, "ticker": "TEST"}),
            patch.object(service, "_load_geo", AsyncMock(return_value={"score": 0.0})),
            patch.object(service, "_load_macro", AsyncMock(return_value={})),
            patch.object(service, "_load_sentiment", AsyncMock(return_value={"score": 0.0, "divergence": 0.0, "source": "none"})),
            patch("src.analysis.service.compute_risk_metrics", return_value={}),
        ):
            result = await service.analyze_single(db, MagicMock(id=1), "TEST", with_ml=False)
        assert result["action"] == "HOLD"

    @pytest.mark.asyncio
    async def test_mtf_none_concordance_when_no_data(self, service):
        db = _async_db()
        db.execute.return_value.scalars.return_value.all.side_effect = [_make_prices(50), _make_indicators(50), _make_dividends(3)]
        mock_fuse = MagicMock(return_value={"action": "HOLD", "confidence": 0.5, "ticker": "TEST"})
        with (
            patch.object(service.analyzer, "generate_signal", return_value={"action": "HOLD", "confidence": 0.5, "score": 0.0, "reasons": []}),
            patch.object(service.fundamental, "analyze", return_value={"risk": 0.0}),
            patch.object(service.volatility, "detect", return_value={"regime": "NORMAL"}),
            patch.object(service.mtf, "compute_all", return_value={}),
            patch.object(service.fusion, "fuse", mock_fuse),
            patch.object(service, "_load_geo", AsyncMock(return_value={"score": 0.0})),
            patch.object(service, "_load_macro", AsyncMock(return_value={})),
            patch.object(service, "_load_sentiment", AsyncMock(return_value={"score": 0.0, "divergence": 0.0, "source": "none"})),
            patch("src.analysis.service.compute_risk_metrics", return_value={}),
        ):
            await service.analyze_single(db, MagicMock(id=1), "TEST", with_ml=False)
        assert mock_fuse.call_args[1]["mtf"] is None


class TestAnalyzeAll:
    @pytest.mark.asyncio
    async def test_processes_all_instruments(self, service):
        db = _async_db()
        db.execute.return_value.scalars.return_value.all.return_value = [MagicMock(id=1, ticker="SBER"), MagicMock(id=2, ticker="GAZP")]
        db.execute.return_value.scalar_one_or_none.return_value = None
        mock_single = AsyncMock(return_value={"action": "BUY", "confidence": 0.8})
        mock_save = AsyncMock()
        with patch.object(service, "analyze_single", mock_single), patch.object(service.fusion, "save_signal", mock_save):
            results = await service.analyze_all(db, with_ml=True)
        assert len(results) == 2
        assert mock_single.call_count == 2
        assert mock_save.call_count == 2

    @pytest.mark.asyncio
    async def test_filters_by_updated_ids(self, service):
        db = _async_db()
        db.execute.return_value.scalars.return_value.all.return_value = [MagicMock(id=1, ticker="SBER")]
        db.execute.return_value.scalar_one_or_none.return_value = None
        with patch.object(service, "analyze_single", AsyncMock(return_value={"action": "BUY"})), patch.object(service.fusion, "save_signal", AsyncMock()):
            results = await service.analyze_all(db, updated_ids={1}, with_ml=True)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_returns_cached_result(self, service):
        db = _async_db()
        db.execute.return_value.scalars.return_value.all.return_value = [MagicMock(id=1, ticker="SBER")]
        cached = MagicMock()
        cached.fused_json = {"action": "BUY", "confidence": 0.8}
        db.execute.return_value.scalar_one_or_none.return_value = cached
        with patch.object(service, "analyze_single") as mock_single:
            results = await service.analyze_all(db, with_ml=True)
        assert len(results) == 1
        assert results[0] == {"action": "BUY", "confidence": 0.8}
        mock_single.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_instruments_with_value_error(self, service):
        db = _async_db()
        db.execute.return_value.scalars.return_value.all.return_value = [MagicMock(id=1, ticker="SBER"), MagicMock(id=2, ticker="GAZP")]
        db.execute.return_value.scalar_one_or_none.return_value = None
        with patch.object(service, "analyze_single", AsyncMock(side_effect=[ValueError("no data"), {"action": "BUY"}])), patch.object(service.fusion, "save_signal", AsyncMock()):
            results = await service.analyze_all(db, with_ml=True)
        assert len(results) == 1
        assert results[0]["action"] == "BUY"

    @pytest.mark.asyncio
    async def test_skips_cached_non_dict_json(self, service):
        db = _async_db()
        db.execute.return_value.scalars.return_value.all.return_value = [MagicMock(id=1, ticker="SBER")]
        cached = MagicMock()
        cached.fused_json = "not a dict"
        db.execute.return_value.scalar_one_or_none.return_value = cached
        results = await service.analyze_all(db, with_ml=True)
        assert len(results) == 0


class TestAnalyzeWithAdvice:
    @pytest.mark.asyncio
    async def test_returns_fused_and_advice(self, service):
        fused = {"action": "BUY", "confidence": 0.8}
        with (
            patch.object(service, "analyze_single", AsyncMock(return_value=fused)) as mock_single,
            patch("src.analysis.service.llm") as mock_llm,
        ):
            mock_llm.advise = AsyncMock(return_value="Buy recommendation")
            result_fused, advice = await service.analyze_with_advice(_async_db(), MagicMock(id=1), "SBER")
        assert result_fused == fused
        assert advice == "Buy recommendation"
        mock_single.assert_called_once()
        mock_llm.advise.assert_called_once_with(fused)

    @pytest.mark.asyncio
    async def test_passes_with_ml_false(self, service):
        with (
            patch.object(service, "analyze_single", AsyncMock(return_value={})) as mock_single,
            patch("src.analysis.service.llm") as mock_llm,
        ):
            mock_llm.advise = AsyncMock(return_value="Hold")
            await service.analyze_with_advice(_async_db(), MagicMock(id=1), "SBER", with_ml=False)
            mock_single.assert_called_once()


class TestAnalyzeAllSync:
    def _make_sync_db(self, instruments: list | None = None) -> MagicMock:
        """Sync db that returns instruments & bypasses cache with sufficient data for all queries."""
        db = MagicMock()
        insts = instruments or []

        inst_mock = MagicMock()
        inst_mock.filter.return_value.all.return_value = insts
        inst_mock.all.return_value = insts
        inst_mock.filter.return_value.first.return_value = None

        enough_prices = _make_prices(50)
        price_mock = MagicMock()
        price_mock.filter_by.return_value.order_by.return_value.all.return_value = enough_prices
        price_mock.order_by.return_value.all.return_value = enough_prices

        enough_inds = _make_indicators(10)
        ind_mock = MagicMock()
        ind_mock.filter_by.return_value.order_by.return_value.all.return_value = enough_inds
        ind_mock.order_by.return_value.all.return_value = enough_inds

        div_mock = MagicMock()
        div_mock.order_by.return_value.all.return_value = []

        geo_mock = MagicMock()
        geo_mock.order_by.return_value.first.return_value = None

        news_mock = MagicMock()
        news_mock.filter.return_value.all.return_value = []

        fallback = MagicMock()
        fallback.filter.return_value.first.return_value = None
        fallback.filter.return_value.all.return_value = []
        fallback.order_by.return_value.all.return_value = []
        fallback.order_by.return_value.first.return_value = None
        fallback.filter_by.return_value.order_by.return_value.all.return_value = []
        fallback.all.return_value = []

        def query_side(model):
            if model is Instrument:
                return inst_mock
            if model is Price:
                return price_mock
            if model is Indicator:
                return ind_mock
            if model is Dividend:
                return div_mock
            if model is GeoRiskScore:
                return geo_mock
            if model is News:
                return news_mock
            return fallback

        db.query.side_effect = query_side
        return db

    def test_processes_all_instruments(self, service):
        db = self._make_sync_db([MagicMock(id=1, ticker="SBER"), MagicMock(id=2, ticker="GAZP")])
        with (
            patch.object(service, "_compute_ml", return_value=None),
            patch("src.collectors.macro.MacroCollector") as MockMacro,
            patch("src.analysis.service.compute_risk_metrics", return_value={}),
            patch.object(service, "_price_df", return_value=pd.DataFrame({"close": [100] * 50, "date": [date(2024, 1, 1)] * 50})),
            patch.object(service, "_indicator_df", return_value=pd.DataFrame({"rsi": [50] * 50, "date": [date(2024, 1, 1)] * 50})),
            patch.object(service, "_dividend_df", return_value=pd.DataFrame()),
            patch.object(service.analyzer, "generate_signal", return_value={}),
            patch.object(service.fundamental, "analyze", return_value={}),
            patch.object(service.volatility, "detect", return_value={}),
            patch.object(service.mtf, "compute_all", return_value={}),
            patch.object(service.fusion, "fuse", return_value={"action": "BUY"}),
            patch.object(service.fusion, "save_signal_sync", MagicMock()),
        ):
            MockMacro.latest_values.return_value = {}
            results = service.analyze_all_sync(db)
        assert len(results) == 2

    def test_filters_by_updated_ids(self, service):
        db = self._make_sync_db([MagicMock(id=1, ticker="SBER")])
        with (
            patch.object(service, "_compute_ml", return_value=None),
            patch("src.collectors.macro.MacroCollector"),
            patch("src.analysis.service.compute_risk_metrics", return_value={}),
            patch.object(service, "_price_df", return_value=pd.DataFrame({"close": [100] * 50, "date": [date(2024, 1, 1)] * 50})),
            patch.object(service, "_indicator_df", return_value=pd.DataFrame({"rsi": [50] * 50, "date": [date(2024, 1, 1)] * 50})),
            patch.object(service, "_dividend_df", return_value=pd.DataFrame()),
            patch.object(service.analyzer, "generate_signal", return_value={}),
            patch.object(service.fundamental, "analyze", return_value={}),
            patch.object(service.volatility, "detect", return_value={}),
            patch.object(service.mtf, "compute_all", return_value={}),
            patch.object(service.fusion, "fuse", return_value={"action": "BUY"}),
            patch.object(service.fusion, "save_signal_sync", MagicMock()),
        ):
            results = service.analyze_all_sync(db, updated_ids={1})
        assert len(results) == 1

    def test_returns_cached_result(self, service):
        db = MagicMock()
        inst = MagicMock(id=1, ticker="SBER")
        db.query.return_value.filter.return_value.all.return_value = [inst]
        db.query.return_value.all.return_value = [inst]
        cached = MagicMock()
        cached.fused_json = {"action": "BUY", "confidence": 0.8}
        db.query.return_value.filter.return_value.first.return_value = cached
        results = service.analyze_all_sync(db)
        assert len(results) == 1
        assert results[0] == {"action": "BUY", "confidence": 0.8}

    def test_skips_instrument_with_fewer_than_50_prices(self, service):
        db = MagicMock()
        inst = MagicMock(id=1, ticker="SBER")
        db.query.return_value.filter.return_value.all.return_value = [inst]
        db.query.return_value.filter.return_value.first.return_value = None
        db.query.return_value.order_by.return_value.all.return_value = _make_prices(49)
        assert service.analyze_all_sync(db) == []

    def test_skips_instrument_with_fewer_than_2_indicators(self, service):
        db = MagicMock()
        inst = MagicMock(id=1, ticker="SBER")
        price_mock = MagicMock()
        price_mock.order_by.return_value.all.return_value = _make_prices(50)
        ind_mock = MagicMock()
        ind_mock.order_by.return_value.all.return_value = _make_indicators(1)
        fallback = MagicMock()
        fallback.order_by.return_value.all.return_value = []

        def query_side(model):
            if model is Price:
                return price_mock
            if model is Indicator:
                return ind_mock
            return fallback

        db.query.side_effect = query_side
        db.query.return_value.filter.return_value.first.return_value = None
        db.query.return_value.filter.return_value.all.return_value = [inst]
        assert service.analyze_all_sync(db) == []

    def test_catches_generic_exception(self, service):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [MagicMock(id=1, ticker="SBER")]
        db.query.return_value.filter.return_value.first.return_value = None
        db.query.return_value.order_by.return_value.all.side_effect = Exception("db error")
        assert service.analyze_all_sync(db) == []

    def test_non_dict_cached_json_falls_through(self, service):
        db = MagicMock()
        inst = MagicMock(id=1, ticker="SBER")
        inst_mock = MagicMock()
        inst_mock.filter.return_value.all.return_value = [inst]
        inst_mock.all.return_value = [inst]
        inst_mock.filter.return_value.first.return_value = MagicMock(fused_json="not a dict")
        price_mock = MagicMock()
        price_mock.order_by.return_value.all.return_value = _make_prices(50)
        price_mock.filter_by.return_value.order_by.return_value.all.return_value = _make_prices(50)
        ind_mock = MagicMock()
        ind_mock.order_by.return_value.all.return_value = _make_indicators(10)
        ind_mock.filter_by.return_value.order_by.return_value.all.return_value = _make_indicators(10)

        def query_side(model):
            if model is Instrument:
                return inst_mock
            if model is Price:
                return price_mock
            if model is Indicator:
                return ind_mock
            m = MagicMock()
            m.filter.return_value.first.return_value = None
            m.filter_by.return_value.order_by.return_value.all.return_value = []
            return m

        db.query.side_effect = query_side
        with (
            patch.object(service, "_compute_ml", return_value=None),
            patch("src.collectors.macro.MacroCollector"),
            patch("src.analysis.service.compute_risk_metrics", return_value={}),
            patch.object(service, "_price_df", return_value=pd.DataFrame({"close": [100] * 50, "date": [date(2024, 1, 1)] * 50})),
            patch.object(service, "_indicator_df", return_value=pd.DataFrame({"rsi": [50] * 50, "date": [date(2024, 1, 1)] * 50})),
            patch.object(service, "_dividend_df", return_value=pd.DataFrame()),
            patch.object(service.analyzer, "generate_signal", return_value={}),
            patch.object(service.fundamental, "analyze", return_value={}),
            patch.object(service.volatility, "detect", return_value={}),
            patch.object(service.mtf, "compute_all", return_value={}),
            patch.object(service.mtf, "concordance", return_value=None),
            patch.object(service.fusion, "fuse", return_value={"action": "BUY"}),
            patch.object(service.fusion, "save_signal_sync", MagicMock()),
        ):
            results = service.analyze_all_sync(db)
        assert len(results) == 1

    def test_computes_sentiment_from_news(self, service):
        db = MagicMock()
        inst = MagicMock(id=1, ticker="SBER")
        news1, news2 = MagicMock(), MagicMock()
        news1.sentiment_weighted, news1.sentiment_score = 0.5, 0.5
        news2.sentiment_weighted, news2.sentiment_score = -0.3, -0.3
        inst_mock = MagicMock()
        inst_mock.filter.return_value.all.return_value = [inst]
        inst_mock.all.return_value = [inst]
        inst_mock.filter.return_value.first.return_value = None
        price_mock = MagicMock()
        price_mock.order_by.return_value.all.return_value = _make_prices(50)
        price_mock.filter_by.return_value.order_by.return_value.all.return_value = _make_prices(50)
        ind_mock = MagicMock()
        ind_mock.order_by.return_value.all.return_value = _make_indicators(10)
        ind_mock.filter_by.return_value.order_by.return_value.all.return_value = _make_indicators(10)
        news_mock = MagicMock()
        news_mock.filter.return_value.all.return_value = [news1, news2]

        def query_side(model):
            if model is Instrument:
                return inst_mock
            if model is Price:
                return price_mock
            if model is Indicator:
                return ind_mock
            if model is News:
                return news_mock
            m = MagicMock()
            m.filter.return_value.first.return_value = None
            m.filter_by.return_value.order_by.return_value.all.return_value = []
            return m

        db.query.side_effect = query_side
        mock_fuse = MagicMock(return_value={"action": "BUY"})
        with (
            patch.object(service, "_compute_ml", return_value=None),
            patch("src.collectors.macro.MacroCollector"),
            patch("src.analysis.service.compute_risk_metrics", return_value={}),
            patch.object(service.analyzer, "generate_signal", return_value={}),
            patch.object(service.fundamental, "analyze", return_value={}),
            patch.object(service.volatility, "detect", return_value={}),
            patch.object(service.mtf, "compute_all", return_value={}),
            patch.object(service.mtf, "concordance", return_value=None),
            patch.object(service.fusion, "fuse", mock_fuse),
            patch.object(service.fusion, "save_signal_sync", MagicMock()),
        ):
            results = service.analyze_all_sync(db)
        assert len(results) == 1
        kw = mock_fuse.call_args[1]
        assert kw["sentiment"]["score"] == 0.1
        assert kw["sentiment"]["source"] == "rss"
        assert kw["sentiment"]["count"] == 2

    def test_uses_geo_row_when_exists(self, service):
        db = MagicMock()
        inst = MagicMock(id=1, ticker="SBER")
        geo_row = MagicMock(score=7.5)
        inst_mock = MagicMock()
        inst_mock.filter.return_value.all.return_value = [inst]
        inst_mock.all.return_value = [inst]
        inst_mock.filter.return_value.first.return_value = None
        price_mock = MagicMock()
        price_mock.order_by.return_value.all.return_value = _make_prices(50)
        price_mock.filter_by.return_value.order_by.return_value.all.return_value = _make_prices(50)
        ind_mock = MagicMock()
        ind_mock.order_by.return_value.all.return_value = _make_indicators(10)
        ind_mock.filter_by.return_value.order_by.return_value.all.return_value = _make_indicators(10)
        geo_mock = MagicMock()
        geo_mock.order_by.return_value.first.return_value = geo_row

        def query_side(model):
            if model is Instrument:
                return inst_mock
            if model is Price:
                return price_mock
            if model is Indicator:
                return ind_mock
            if model is GeoRiskScore:
                return geo_mock
            m = MagicMock()
            m.filter.return_value.first.return_value = None
            m.filter_by.return_value.order_by.return_value.all.return_value = []
            return m

        db.query.side_effect = query_side
        mock_fuse = MagicMock(return_value={"action": "BUY"})
        with (
            patch.object(service, "_compute_ml", return_value=None),
            patch("src.collectors.macro.MacroCollector"),
            patch("src.analysis.service.compute_risk_metrics", return_value={}),
            patch.object(service, "_price_df", return_value=pd.DataFrame({"close": [100] * 50, "date": [date(2024, 1, 1)] * 50})),
            patch.object(service, "_indicator_df", return_value=pd.DataFrame({"rsi": [50] * 50, "date": [date(2024, 1, 1)] * 50})),
            patch.object(service, "_dividend_df", return_value=pd.DataFrame()),
            patch.object(service.analyzer, "generate_signal", return_value={}),
            patch.object(service.fundamental, "analyze", return_value={}),
            patch.object(service.volatility, "detect", return_value={}),
            patch.object(service.mtf, "compute_all", return_value={}),
            patch.object(service.mtf, "concordance", return_value=None),
            patch.object(service.fusion, "fuse", mock_fuse),
            patch.object(service.fusion, "save_signal_sync", MagicMock()),
        ):
            results = service.analyze_all_sync(db)
        assert len(results) == 1
        kw = mock_fuse.call_args[1]
        assert kw["geo"]["score"] == 7.5


class TestTrainModels:
    def _make_train_db(self, instruments: list) -> MagicMock:
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = instruments
        price_mock = MagicMock()
        price_mock.filter_by.return_value.order_by.return_value.all.return_value = _make_prices(100)
        ind_mock = MagicMock()
        ind_mock.filter_by.return_value.order_by.return_value.all.return_value = _make_indicators(10)

        def query_side(model):
            if model is Price:
                return price_mock
            return ind_mock

        db.query.side_effect = query_side
        return db

    def test_returns_results_dict(self, service):
        db = self._make_train_db([MagicMock(id=1, ticker="SBER")])
        mock_ensemble = MagicMock()
        mock_ensemble.train_all.return_value = {"lgb": True, "xgb": True, "cat": True}
        with patch.object(service, "_get_ensemble", return_value=mock_ensemble):
            results = service.train_models(db)
        assert results == {"SBER": True}
        mock_ensemble.train_all.assert_called_once()

    def test_filters_by_ticker(self, service):
        db = self._make_train_db([MagicMock(id=1, ticker="SBER")])
        with patch.object(service, "_get_ensemble", return_value=MagicMock(train_all=MagicMock(return_value={}))):
            assert len(service.train_models(db, ticker="SBER")) == 1

    def test_skips_instrument_with_insufficient_prices(self, service):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [MagicMock(id=1, ticker="SBER")]
        db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = _make_prices(59)
        assert service.train_models(db) == {}

    def test_skips_instrument_with_insufficient_indicators(self, service):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [MagicMock(id=1, ticker="SBER")]
        price_mock = MagicMock()
        price_mock.filter_by.return_value.order_by.return_value.all.return_value = _make_prices(100)
        ind_mock = MagicMock()
        ind_mock.filter_by.return_value.order_by.return_value.all.return_value = _make_indicators(1)
        db.query.side_effect = lambda model: price_mock if model is Price else ind_mock
        assert service.train_models(db) == {}

    def test_reports_partial_training(self, service):
        db = self._make_train_db([MagicMock(id=1, ticker="SBER")])
        mock_ensemble = MagicMock()
        mock_ensemble.train_all.return_value = {"lgb": True, "xgb": False, "cat": True}
        with patch.object(service, "_get_ensemble", return_value=mock_ensemble):
            assert service.train_models(db) == {"SBER": False}

    def test_upcases_ticker_filter(self, service):
        db = self._make_train_db([MagicMock(id=1, ticker="SBER")])
        with patch.object(service, "_get_ensemble", return_value=MagicMock(train_all=MagicMock(return_value={}))):
            assert len(service.train_models(db, ticker="sber")) == 1

    def test_multiple_instruments(self, service):
        db = self._make_train_db([MagicMock(id=1, ticker="SBER"), MagicMock(id=2, ticker="GAZP")])
        mock_ensemble = MagicMock()
        mock_ensemble.train_all.return_value = {"lgb": True, "xgb": True}
        with patch.object(service, "_get_ensemble", return_value=mock_ensemble):
            assert service.train_models(db) == {"SBER": True, "GAZP": True}
