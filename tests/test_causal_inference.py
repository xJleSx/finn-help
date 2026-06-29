from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.analysis.inference.causal import (
    CausalImpactAnalyzer,
    GrangerCausality,
    InstrumentCausalGraph,
)


@pytest.fixture
def mock_db():
    return MagicMock()


def _make_mock_price(date, close):
    p = MagicMock()
    p.date = date
    p.close = close
    return p


def _make_mock_instrument(ticker="SBER", sector="Finance"):
    inst = MagicMock()
    inst.id = 1
    inst.ticker = ticker
    inst.sector = sector
    return inst


def _query_side_effect(**model_mocks):
    """Return a side_effect for db_session.query that dispatches by model name."""

    def side_effect(model):
        name = model.__name__ if hasattr(model, "__name__") else str(model)
        for key, mock_obj in model_mocks.items():
            if key == name:
                return mock_obj
        return MagicMock()

    return side_effect


class TestGrangerCausality:
    def test_statsmodels_not_available(self, mock_db):
        with patch("src.analysis.inference.causal._HAS_STATSMODELS", False):
            gc = GrangerCausality()
            result = gc.test_news_sentiment_impact("SBER", mock_db)
            assert result == {"available": False}

    def test_instrument_not_found(self, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("src.analysis.inference.causal._HAS_STATSMODELS", True):
            gc = GrangerCausality()
            result = gc.test_news_sentiment_impact("UNKNOWN", mock_db)
            assert result["error"] == "Instrument not found"

    def test_not_enough_price_data(self, mock_db):
        mock_inst = _make_mock_instrument()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_inst
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            _make_mock_price(datetime.now().date() - timedelta(days=i), 100.0) for i in range(3)
        ]
        with patch("src.analysis.inference.causal._HAS_STATSMODELS", True):
            gc = GrangerCausality(max_lag=10)
            result = gc.test_news_sentiment_impact("SBER", mock_db)
            assert result["error"] == "Not enough price data"

    def test_returns_expected_structure(self, mock_db):
        mock_inst = _make_mock_instrument()

        # Instrument query mock
        inst_query = MagicMock()
        inst_query.filter.return_value.first.return_value = mock_inst

        # Price query mock
        today = datetime.now().date()
        prices = [
            _make_mock_price(today - timedelta(days=30 - i), 100.0 + i * 0.5)
            for i in range(31)
        ]
        price_query = MagicMock()
        price_query.filter.return_value.order_by.return_value.all.return_value = prices

        # News query mock
        mock_news = []
        for i in range(20):
            n = MagicMock()
            n.published_at = datetime.now(timezone.utc) - timedelta(days=i * 2)
            n.sentiment_score = 0.5 if i % 2 == 0 else -0.3
            mock_news.append(n)
        news_query = MagicMock()
        news_query.join.return_value.filter.return_value.order_by.return_value.all.return_value = mock_news

        mock_db.query.side_effect = _query_side_effect(
            Instrument=inst_query, Price=price_query, News=news_query
        )

        mock_granger = {
            lag: [{"ssr_chi2test": (3.0, 0.08 if lag != 2 else 0.003)}]
            for lag in range(1, 11)
        }

        with (
            patch("src.analysis.inference.causal._HAS_STATSMODELS", True),
            patch(
                "src.analysis.inference.causal.grangercausalitytests",
                create=True,
                return_value=mock_granger,
            ),
        ):
            gc = GrangerCausality(max_lag=10)
            result = gc.test_news_sentiment_impact("SBER", mock_db)

        assert result["ticker"] == "SBER"
        assert result["lags_tested"] == 10
        assert result["best_lag"] == 2
        assert result["best_pvalue"] == 0.003
        assert result["causal_direction"] == "sentiment -> returns"
        assert result["significant"] is True

    def test_not_significant(self, mock_db):
        mock_inst = _make_mock_instrument()

        inst_query = MagicMock()
        inst_query.filter.return_value.first.return_value = mock_inst

        today = datetime.now().date()
        prices = [
            _make_mock_price(today - timedelta(days=30 - i), 100.0 + i * 0.5)
            for i in range(31)
        ]
        price_query = MagicMock()
        price_query.filter.return_value.order_by.return_value.all.return_value = prices

        mock_news = []
        for i in range(20):
            n = MagicMock()
            n.published_at = datetime.now(timezone.utc) - timedelta(days=i * 2)
            n.sentiment_score = 0.5 if i % 2 == 0 else -0.3
            mock_news.append(n)
        news_query = MagicMock()
        news_query.join.return_value.filter.return_value.order_by.return_value.all.return_value = mock_news

        mock_db.query.side_effect = _query_side_effect(
            Instrument=inst_query, Price=price_query, News=news_query
        )

        mock_granger = {
            lag: [{"ssr_chi2test": (0.5, 0.5)}] for lag in range(1, 11)
        }

        with (
            patch("src.analysis.inference.causal._HAS_STATSMODELS", True),
            patch(
                "src.analysis.inference.causal.grangercausalitytests",
                create=True,
                return_value=mock_granger,
            ),
        ):
            gc = GrangerCausality(max_lag=10)
            result = gc.test_news_sentiment_impact("SBER", mock_db)

        assert result["significant"] is False
        assert result["best_pvalue"] == 0.5


class TestCausalImpactAnalyzer:
    def test_estimate_impact_returns_expected_structure(self, mock_db):
        mock_inst = _make_mock_instrument()
        inst_query = MagicMock()
        inst_query.filter.return_value.first.return_value = mock_inst

        today = datetime.now().date()
        before_prices = [
            _make_mock_price(today - timedelta(days=35 - i), 100.0 + i * 0.2)
            for i in range(30)
        ]
        after_prices = [
            _make_mock_price(today + timedelta(days=1 + i), 106.0 + i * 0.1)
            for i in range(30)
        ]

        price_query = MagicMock()
        price_query.filter.return_value.order_by.return_value.all.side_effect = [
            before_prices,
            after_prices,
        ]

        peer_query = MagicMock()
        peer_query.filter.return_value.all.return_value = []

        mock_db.query.side_effect = _query_side_effect(
            Instrument=inst_query,
            Price=price_query,
        )

        analyzer = CausalImpactAnalyzer()
        result = analyzer.estimate_impact("SBER", datetime.now(), mock_db, window_days=30)

        assert result["ticker"] == "SBER"
        assert "event_date" in result
        assert "observed_effect" in result
        assert "predicted_counterfactual" in result
        assert "impact" in result
        assert "p_value_approximate" in result
        assert isinstance(result["observed_effect"], float)
        assert isinstance(result["p_value_approximate"], float)

    def test_estimate_impact_with_peers(self, mock_db):
        mock_inst = _make_mock_instrument()
        peer_inst = _make_mock_instrument(ticker="GAZP", sector="Finance")
        peer_inst.id = 2

        # Instrument query: first .filter().first() → mock_inst, second .filter().all() → peers
        inst_filter = MagicMock()
        inst_filter.first.return_value = mock_inst
        inst_filter.all.return_value = [peer_inst]
        inst_query = MagicMock()
        inst_query.filter.return_value = inst_filter

        today = datetime.now().date()
        before_prices = [
            _make_mock_price(today - timedelta(days=35 - i), 100.0 + i * 0.2)
            for i in range(30)
        ]
        after_prices = [
            _make_mock_price(today + timedelta(days=1 + i), 106.0 + i * 0.1)
            for i in range(30)
        ]
        peer_before = [
            _make_mock_price(today - timedelta(days=35 - i), 200.0 + i * 0.3)
            for i in range(30)
        ]
        peer_after = [
            _make_mock_price(today + timedelta(days=1 + i), 205.0 + i * 0.2)
            for i in range(30)
        ]

        price_query = MagicMock()
        price_query.filter.return_value.order_by.return_value.all.side_effect = [
            before_prices,
            after_prices,
            peer_before,
            peer_after,
        ]

        mock_db.query.side_effect = _query_side_effect(
            Instrument=inst_query,
            Price=price_query,
        )

        analyzer = CausalImpactAnalyzer()
        result = analyzer.estimate_impact("SBER", datetime.now(), mock_db, window_days=30)

        assert result["ticker"] == "SBER"
        assert "impact" in result
        assert isinstance(result["impact"], float)

    def test_analyze_news_event_no_published_at(self, mock_db):
        article = MagicMock()
        article.published_at = None

        analyzer = CausalImpactAnalyzer()
        result = analyzer.analyze_news_event(article, mock_db)
        assert result["error"] == "Article has no published_at"

    def test_analyze_news_event_returns_structure(self, mock_db):
        article = MagicMock()
        article.id = 42
        article.title = "Test news"
        article.published_at = datetime.now(timezone.utc)

        mock_inst = _make_mock_instrument()

        # Instrument query for linked instruments
        inst_query = MagicMock()
        # .join().filter().all() → linked instruments
        inst_query.join.return_value.filter.return_value.all.return_value = [mock_inst]
        # .filter().first() → for estimate_impact
        inst_filter = MagicMock()
        inst_filter.first.return_value = mock_inst
        inst_query.filter.return_value = inst_filter

        today = datetime.now().date()
        before_prices = [
            _make_mock_price(today - timedelta(days=35 - i), 100.0 + i * 0.2)
            for i in range(30)
        ]
        after_prices = [
            _make_mock_price(today + timedelta(days=1 + i), 106.0 + i * 0.1)
            for i in range(30)
        ]

        price_query = MagicMock()
        price_query.filter.return_value.order_by.return_value.all.side_effect = [
            before_prices,
            after_prices,
        ]

        peer_query = MagicMock()
        peer_query.filter.return_value.all.return_value = []

        mock_db.query.side_effect = _query_side_effect(
            Instrument=inst_query,
            Price=price_query,
        )

        analyzer = CausalImpactAnalyzer()
        result = analyzer.analyze_news_event(article, mock_db)

        assert result["news_id"] == 42
        assert result["title"] == "Test news"
        assert "published_at" in result
        assert "impacts" in result
        assert len(result["impacts"]) == 1
        assert result["impacts"][0]["ticker"] == "SBER"


class TestInstrumentCausalGraph:
    def test_statsmodels_not_available(self, mock_db):
        with patch("src.analysis.inference.causal._HAS_STATSMODELS", False):
            graph = InstrumentCausalGraph()
            result = graph.estimate_peer_impact("SBER", "GAZP", mock_db)
            assert result == {"available": False}

    def test_estimate_peer_impact_structure(self, mock_db):
        src = _make_mock_instrument(ticker="GAZP")
        tgt = _make_mock_instrument(ticker="SBER")
        src.id = 1
        tgt.id = 2

        inst_query = MagicMock()
        inst_query.filter.return_value.first.side_effect = [src, tgt]

        today = datetime.now().date()
        src_prices = [
            _make_mock_price(today - timedelta(days=40 - i), 100.0 + i * 0.3)
            for i in range(35)
        ]
        tgt_prices = [
            _make_mock_price(today - timedelta(days=40 - i), 200.0 + i * 0.5)
            for i in range(35)
        ]

        price_query = MagicMock()
        price_query.filter.return_value.order_by.return_value.all.side_effect = [
            src_prices,
            tgt_prices,
        ]

        mock_db.query.side_effect = _query_side_effect(
            Instrument=inst_query,
            Price=price_query,
        )

        mock_granger = {
            lag: [{"ssr_chi2test": (2.0, 0.05 if lag != 3 else 0.01)}]
            for lag in range(1, 11)
        }

        with (
            patch("src.analysis.inference.causal._HAS_STATSMODELS", True),
            patch(
                "src.analysis.inference.causal.grangercausalitytests",
                create=True,
                return_value=mock_granger,
            ),
        ):
            graph = InstrumentCausalGraph(max_lag=10)
            result = graph.estimate_peer_impact("GAZP", "SBER", mock_db)

        assert result["source"] == "GAZP"
        assert result["target"] == "SBER"
        assert "best_lag" in result
        assert "best_pvalue" in result
        assert result["best_pvalue"] == 0.01
        assert "causal_direction" in result
        assert "significant" in result

    def test_find_influencers_no_statsmodels(self, mock_db):
        with patch("src.analysis.inference.causal._HAS_STATSMODELS", False):
            graph = InstrumentCausalGraph()
            result = graph.find_influencers("SBER", mock_db)
            assert result == []

    def test_find_influencers_returns_top_n(self, mock_db):
        mock_inst = _make_mock_instrument(ticker="SBER", sector="Finance")

        inst_query = MagicMock()
        inst_query.filter.return_value.first.return_value = mock_inst

        peers = [
            _make_mock_instrument(ticker=f"PEER{i}", sector="Finance")
            for i in range(5)
        ]
        for i, p in enumerate(peers):
            p.id = 10 + i

        # For peer listing query (after instrument is found)
        inst_query.filter.return_value.all.return_value = peers

        mock_db.query.side_effect = _query_side_effect(
            Instrument=inst_query,
        )

        with patch("src.analysis.inference.causal._HAS_STATSMODELS", True):
            graph = InstrumentCausalGraph(max_lag=10)

            with patch.object(graph, "estimate_peer_impact") as mock_epi:
                # p-values increase with index so PEER0 has the lowest (best)
                mock_epi.side_effect = [
                    {
                        "source": f"PEER{i}",
                        "target": "SBER",
                        "best_lag": 2,
                        "best_pvalue": round(0.01 * (i + 1), 6),
                        "causal_direction": f"PEER{i} -> SBER",
                        "significant": i == 0,
                    }
                    for i in range(5)
                ]

                result = graph.find_influencers("SBER", mock_db, top_n=3)

        assert len(result) == 3
        assert result[0]["source"] == "PEER0"
        assert result[0]["best_pvalue"] < result[1]["best_pvalue"]
        assert result[1]["best_pvalue"] < result[2]["best_pvalue"]
