from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.analysis.context import TickerContextBuilder


class TestTickerContextBuilder:
    def make_inst(self, id=1, ticker="SBER", full_name="Сбер Банк", sector="Финансы", instrument_type="stock", lot_size=10):
        inst = MagicMock()
        inst.id = id
        inst.ticker = ticker
        inst.full_name = full_name
        inst.sector = sector
        inst.instrument_type = instrument_type
        inst.lot_size = lot_size
        return inst

    def make_price(self, close, date=None, volume=1000):
        p = MagicMock()
        p.close = close
        p.date = date or datetime(2024, 1, 1)
        p.volume = volume
        return p

    def make_indicator(self, rsi=50, sma_20=100.0, sma_50=98.0, sma_200=95.0, bb_upper=110.0, bb_lower=90.0, macd_hist=0.5, atr=2.0, volume_sma_20=1000.0):
        ind = MagicMock()
        ind.rsi = rsi
        ind.sma_20 = sma_20
        ind.sma_50 = sma_50
        ind.sma_200 = sma_200
        ind.bb_upper = bb_upper
        ind.bb_lower = bb_lower
        ind.macd_hist = macd_hist
        ind.atr = atr
        ind.volume_sma_20 = volume_sma_20
        return ind

    def _setup_news_none(self, db):
        db.query.return_value.join.return_value.filter.return_value.order_by.return_value.limit.return_value.first.return_value = None
        db.query.return_value.join.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

    def _build(self, db, ticker="SBER"):
        with (
            patch("src.analysis.loader.data_loader.load_latest_report_sync", return_value=None),
            patch("src.analysis.loader.data_loader.load_bond_offering_sync", return_value=None),
            patch("src.collectors.news.NewsCollector.collect_for_ticker_sync"),
            patch("src.analysis.service.analysis_service") as mock_svc,
        ):
            mock_svc._analyze_single_sync.return_value = None
            return TickerContextBuilder().build(db, ticker)

    def test_build_unknown_ticker_returns_empty(self):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = None
        result = TickerContextBuilder().build(db, "UNKNOWN")
        assert result == ""

    def test_build_includes_instrument_info(self):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = self.make_inst()
        db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = []
        self._setup_news_none(db)
        result = self._build(db)
        assert "Сбер Банк" in result
        assert "Финансы" in result
        assert "10 шт" in result

    def test_build_price_statistics_for_multiple_periods(self):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = self.make_inst()
        closes = [100 + i for i in range(300)]
        db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [self.make_price(c) for c in closes]
        db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None
        self._setup_news_none(db)
        result = self._build(db)
        assert "Текущая цена: 399.00" in result
        assert "за всё время" in result
        assert "за 1 год" in result

    def test_build_rsi_label_overbought(self):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = self.make_inst()
        db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [self.make_price(100 + i) for i in range(30)]
        db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = self.make_indicator(rsi=75.0)
        self._setup_news_none(db)
        result = self._build(db)
        assert "перегрет" in result

    def test_build_rsi_label_oversold(self):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = self.make_inst()
        db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [self.make_price(100 + i) for i in range(30)]
        db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = self.make_indicator(rsi=25.0)
        self._setup_news_none(db)
        result = self._build(db)
        assert "перепродан" in result

    def test_build_bollinger_bands_position_upper(self):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = self.make_inst()
        db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [self.make_price(105) for _ in range(30)]
        db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = self.make_indicator(bb_upper=102.0, bb_lower=90.0)
        self._setup_news_none(db)
        result = self._build(db)
        assert "у верхней" in result

    def test_build_macd_bullish(self):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = self.make_inst()
        prices = [self.make_price(100 + i) for i in range(30)]
        prices[-1].close = 110.0
        db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = prices
        db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = self.make_indicator(macd_hist=1.5)
        self._setup_news_none(db)
        result = self._build(db)
        assert "бычья" in result

    def test_build_volume_above_average(self):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = self.make_inst()
        db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [self.make_price(100 + i, volume=2000) for i in range(30)]
        db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = self.make_indicator(volume_sma_20=1000.0)
        self._setup_news_none(db)
        result = self._build(db)
        assert "выше среднего" in result

    def test_build_dividends_included_when_price_positive(self):
        db = MagicMock()
        inst = self.make_inst()
        db.query.return_value.filter_by.return_value.first.return_value = inst
        prices = [self.make_price(100) for _ in range(30)]
        prices[-1].close = 200.0
        db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = prices
        db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None
        div = MagicMock()
        div.date = datetime(2024, 6, 1)
        div.amount = 15.0
        db.query.return_value.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = [div]
        self._setup_news_none(db)
        result = self._build(db)
        assert "15.0000" in result
        assert "7.50%" in result

    def test_build_news_sentiment_summary(self):
        db = MagicMock()
        inst = self.make_inst()
        db.query.return_value.filter_by.return_value.first.return_value = inst
        prices = [self.make_price(100) for _ in range(30)]
        prices[-1].close = 100.0
        db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = prices
        db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None
        now = datetime.now(timezone.utc)
        news = MagicMock()
        news.title = "Test news"
        news.sentiment_weighted = 0.5
        news.sentiment_score = 0.3
        news.created_at = now - timedelta(hours=1)
        db.query.return_value.join.return_value.filter.return_value.order_by.return_value.limit.return_value.first.return_value = news
        db.query.return_value.join.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [news]
        with (
            patch("src.analysis.loader.data_loader.load_latest_report_sync", return_value=None),
            patch("src.analysis.loader.data_loader.load_bond_offering_sync", return_value=None),
            patch("src.analysis.service.analysis_service") as mock_svc,
        ):
            mock_svc._analyze_single_sync.return_value = None
            result = TickerContextBuilder().build(db, "SBER")
        assert "Test news" in result
        assert "сентимент" in result
