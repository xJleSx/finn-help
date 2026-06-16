"""Parametrized tests for ensemble, sector, backtest edge cases"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from pytest import approx


class TestEnsembleEdgeCases:
    @pytest.fixture
    def sample_df(self):
        np.random.seed(42)
        n = 100
        return pd.DataFrame({
            "close": np.cumsum(np.random.randn(n)) + 100,
            "rsi": np.random.uniform(20, 80, n),
            "macd_hist": np.random.randn(n) * 0.5,
            "sma_20": np.full(n, 105),
            "sma_50": np.full(n, 100),
            "volume": np.random.randint(1000, 10000, n),
        })

    def test_empty_df(self):
        from src.analysis.ml.ensemble import EnsemblePredictor
        ep = EnsemblePredictor()
        ep._xgb = MagicMock()
        ep._xgb.predict.return_value = {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0, "probability": 0.5}
        ep._lgb = MagicMock()
        ep._lgb.predict.return_value = {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0, "probability": 0.5}
        ep._cat = MagicMock()
        ep._cat.predict.return_value = {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0, "probability": 0.5}
        result = ep.predict(pd.DataFrame())
        assert result["action"] == "NEUTRAL"

    def test_single_row(self):
        from src.analysis.ml.ensemble import EnsemblePredictor
        ep = EnsemblePredictor()
        ep._xgb = MagicMock()
        ep._xgb.predict.return_value = {"action": "BUY", "confidence": 0.7, "signal_score": 0.3, "probability": 0.65}
        ep._lgb = MagicMock()
        ep._lgb.predict.return_value = {"action": "BUY", "confidence": 0.6, "signal_score": 0.2, "probability": 0.6}
        ep._cat = MagicMock()
        ep._cat.predict.return_value = {"action": "HOLD", "confidence": 0.5, "signal_score": 0.0, "probability": 0.5}
        df = pd.DataFrame({"close": [100], "rsi": [50], "macd_hist": [0], "sma_20": [100], "sma_50": [100]})
        result = ep.predict(df)
        assert result["action"] in ("BUY", "SELL", "HOLD", "NEUTRAL")

    @pytest.mark.parametrize("n_rows,expected_actions", [
        (10, ("NEUTRAL", "HOLD")),
        (50, ("BUY", "SELL", "HOLD", "NEUTRAL")),
        (200, ("BUY", "SELL", "HOLD", "NEUTRAL")),
    ])
    def test_various_sizes(self, n_rows, expected_actions):
        from src.analysis.ml.ensemble import EnsemblePredictor
        ep = EnsemblePredictor()
        ep._xgb = MagicMock()
        ep._xgb.predict.return_value = {"action": "BUY", "confidence": 0.7, "signal_score": 0.3, "probability": 0.65}
        ep._lgb = MagicMock()
        ep._lgb.predict.return_value = {"action": "HOLD", "confidence": 0.5, "signal_score": 0.0, "probability": 0.5}
        ep._cat = MagicMock()
        ep._cat.predict.return_value = {"action": "HOLD", "confidence": 0.5, "signal_score": 0.0, "probability": 0.5}
        np.random.seed(42)
        df = pd.DataFrame({
            "close": np.cumsum(np.random.randn(n_rows)) + 100,
            "rsi": np.random.uniform(20, 80, n_rows),
            "macd_hist": np.random.randn(n_rows) * 0.5,
            "sma_20": np.full(n_rows, 105),
            "sma_50": np.full(n_rows, 100),
        })
        result = ep.predict(df)
        assert result["action"] in expected_actions
        assert 0 <= result["confidence"] <= 1
        assert -1 <= result["signal_score"] <= 1

    @pytest.mark.parametrize("missing_col", ["rsi", "macd_hist", "close"])
    def test_missing_columns(self, missing_col, sample_df):
        from src.analysis.ml.ensemble import EnsemblePredictor
        ep = EnsemblePredictor()
        ep._xgb = MagicMock()
        ep._xgb.predict.return_value = {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0, "probability": 0.5}
        ep._lgb = MagicMock()
        ep._lgb.predict.return_value = {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0, "probability": 0.5}
        ep._cat = MagicMock()
        ep._cat.predict.return_value = {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0, "probability": 0.5}
        df = sample_df.drop(columns=[missing_col])
        result = ep.predict(df)
        assert result["action"] in ("BUY", "SELL", "HOLD", "NEUTRAL")

    def test_all_models_fail(self, sample_df):
        from src.analysis.ml.ensemble import EnsemblePredictor
        ep = EnsemblePredictor()
        mock_pred = MagicMock()
        mock_pred.predict.return_value = {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0, "probability": 0.5}
        ep._xgb = mock_pred
        ep._lgb = mock_pred
        ep._cat = mock_pred
        result = ep.predict(sample_df)
        assert result["action"] == "NEUTRAL"


class TestSectorAnalyzer:
    @pytest.fixture
    def analyzer(self):
        from src.analysis.sector import SectorAnalyzer
        return SectorAnalyzer()

    @pytest.mark.parametrize("name,expected_sector", [
        ("Сбер Банк", "Финансы"),
        ("Газпром", "Нефть"),
        ("Яндекс", "IT"),
        ("Магнит", "Потребительский"),
        ("МТС", "Телеком"),
        ("Интер РАО", "Энергетика"),
        ("Фосагро", "Химия"),
        ("Аэрофлот", "Транспорт"),
    ])
    def test_sector_for(self, analyzer, name, expected_sector):
        assert analyzer.sector_for(name, "") == expected_sector

    def test_unknown_sector(self, analyzer):
        assert analyzer.sector_for("Unknown Company Inc", "XXX") == "Прочее"

    def test_sector_performance_empty_db(self, analyzer):
        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = []
        result = analyzer.compute_sector_performance(mock_db)
        assert result == {}

    def test_sector_performance_with_data(self, analyzer):
        mock_db = MagicMock()
        mock_inst = MagicMock()
        mock_inst.id = 1
        mock_inst.ticker = "SBER"
        mock_inst.full_name = "Сбер Банк"
        mock_db.query.return_value.all.return_value = [mock_inst]

        mock_price = MagicMock()
        mock_price.close = 250.0
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_price
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_price]

        result = analyzer.compute_sector_performance(mock_db)
        assert isinstance(result, dict)

    @pytest.mark.parametrize("days", [7, 30, 90, 365])
    def test_sector_performance_various_days(self, analyzer, days):
        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = []
        result = analyzer.compute_sector_performance(mock_db, days=days)
        assert result == {}


class TestBacktestEdgeCases:
    @pytest.mark.parametrize("slippage_bps", [0, 5, 10, 20])
    def test_various_slippage(self, slippage_bps):
        from src.analysis.backtest import BacktestConfig, run_monte_carlo
        config = BacktestConfig(slippage_bps=slippage_bps)
        returns = [np.random.randn() * 0.02 for _ in range(100)]
        mc = run_monte_carlo(returns)
        assert isinstance(mc.simulations, int)

    @pytest.mark.parametrize("commission_pct", [0.0, 0.0005, 0.001, 0.003])
    def test_various_commission(self, commission_pct):
        from src.analysis.backtest import BacktestConfig, run_monte_carlo
        config = BacktestConfig(commission_pct=commission_pct)
        returns = [np.random.randn() * 0.02 for _ in range(100)]
        mc = run_monte_carlo(returns)
        assert isinstance(mc.simulations, int)

    @pytest.mark.parametrize("initial_capital", [10000, 100000, 1000000])
    def test_various_capital(self, initial_capital):
        from src.analysis.backtest import BacktestConfig
        config = BacktestConfig(capital=initial_capital)
        assert config.capital == initial_capital

    def test_constant_prices(self):
        from src.analysis.backtest import BacktestResult
        prices = [100] * 50
        result = BacktestResult(capital=100000)
        for i in range(1, len(prices)):
            result.add_snapshot(str(i), 0.0, 0.0)
        assert result.portfolio_return == approx(0.0, abs=0.01)
        assert result.portfolio_sharpe == approx(0.0, abs=0.01)

    def test_uptrend_prices(self):
        from src.analysis.backtest import BacktestResult
        prices = [100 + i for i in range(100)]
        result = BacktestResult(capital=100000)
        for i in range(1, len(prices)):
            ret = (prices[i] - prices[i - 1]) / prices[i - 1]
            result.add_snapshot(str(i), ret, 0.0)
        assert result.portfolio_return > 0

    def test_downtrend_prices(self):
        from src.analysis.backtest import BacktestResult
        prices = [100 - i for i in range(100)]
        result = BacktestResult(capital=100000)
        for i in range(1, len(prices)):
            ret = (prices[i] - prices[i - 1]) / prices[i - 1]
            result.add_snapshot(str(i), ret, 0.0)
        assert result.portfolio_return < 0

    def test_very_short_series(self):
        from src.analysis.backtest import BacktestResult
        result = BacktestResult(capital=100000)
        assert result.portfolio_return == 0.0
        assert result.portfolio_sharpe == 0.0

    def test_extreme_volatility(self):
        from src.analysis.backtest import BacktestResult, run_monte_carlo
        import math
        returns = [0.1 * math.sin(i) for i in range(100)]
        mc = run_monte_carlo(returns)
        assert isinstance(mc.simulations, int) and mc.simulations > 0

    def test_apply_costs(self):
        from src.analysis.backtest import BacktestConfig, apply_costs
        config = BacktestConfig()
        net, slippage, commission = apply_costs(0.01, True, 0.5, config)
        assert net < 0.01
        assert slippage >= 0
        assert commission >= 0

    def test_detect_regime(self):
        from src.analysis.backtest import detect_regime
        import numpy as np
        returns = np.array([0.01] * 30)
        regime = detect_regime(returns)
        assert regime.regime == "BULL"
        returns = np.array([-0.01] * 30)
        regime = detect_regime(returns)
        assert regime.regime == "BEAR"
        returns = np.random.randn(30) * 0.001
        regime = detect_regime(returns)
        assert regime.regime in ("SIDEWAYS", "BULL", "BEAR", "HIGH_VOL", "UNKNOWN")

    def test_monte_carlo_empty(self):
        from src.analysis.backtest import run_monte_carlo
        mc = run_monte_carlo([], n_simulations=100)
        assert mc.simulations == 0

    def test_monte_carlo_few(self):
        from src.analysis.backtest import run_monte_carlo
        mc = run_monte_carlo([0.01, 0.02, -0.01], n_simulations=100)
        assert mc.simulations == 0

    def test_monte_carlo_normal(self):
        from src.analysis.backtest import run_monte_carlo
        returns = [np.random.randn() * 0.02 for _ in range(100)]
        mc = run_monte_carlo(returns, n_simulations=500, periods=252)
        assert mc.simulations == 500
        assert isinstance(mc.mean_return, float)
        assert isinstance(mc.var_95, float)
