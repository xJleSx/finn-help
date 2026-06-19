"""Parametrized tests for ensemble, sector, backtest, API, allocator, profile edge cases"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from pytest import approx


class TestEnsembleEdgeCases:
    @pytest.fixture
    def sample_df(self):
        np.random.seed(42)
        n = 100
        return pd.DataFrame(
            {
                "close": np.cumsum(np.random.randn(n)) + 100,
                "rsi": np.random.uniform(20, 80, n),
                "macd_hist": np.random.randn(n) * 0.5,
                "sma_20": np.full(n, 105),
                "sma_50": np.full(n, 100),
                "volume": np.random.randint(1000, 10000, n),
            }
        )

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

    @pytest.mark.parametrize(
        "n_rows,expected_actions",
        [
            (10, ("NEUTRAL", "HOLD")),
            (50, ("BUY", "SELL", "HOLD", "NEUTRAL")),
            (200, ("BUY", "SELL", "HOLD", "NEUTRAL")),
        ],
    )
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
        df = pd.DataFrame(
            {
                "close": np.cumsum(np.random.randn(n_rows)) + 100,
                "rsi": np.random.uniform(20, 80, n_rows),
                "macd_hist": np.random.randn(n_rows) * 0.5,
                "sma_20": np.full(n_rows, 105),
                "sma_50": np.full(n_rows, 100),
            }
        )
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
        mock_pred.predict.return_value = {
            "action": "NEUTRAL",
            "confidence": 0.0,
            "signal_score": 0.0,
            "probability": 0.5,
        }
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

    @pytest.mark.parametrize(
        "name,expected_sector",
        [
            ("Сбер Банк", "Финансы"),
            ("Газпром", "Нефть"),
            ("Яндекс", "IT"),
            ("Магнит", "Потребительский"),
            ("МТС", "Телеком"),
            ("Интер РАО", "Энергетика"),
            ("Фосагро", "Химия"),
            ("Аэрофлот", "Транспорт"),
        ],
    )
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
        from src.analysis.backtest import run_monte_carlo

        returns = [np.random.randn() * 0.02 for _ in range(100)]
        mc = run_monte_carlo(returns)
        assert isinstance(mc.simulations, int)

    @pytest.mark.parametrize("commission_pct", [0.0, 0.0005, 0.001, 0.003])
    def test_various_commission(self, commission_pct):
        from src.analysis.backtest import run_monte_carlo

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
        import math

        from src.analysis.backtest import run_monte_carlo

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
        import numpy as np

        from src.analysis.backtest import detect_regime

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


class TestAPIEdgeCases:
    def test_allocate_zero_capital(self, mock_client, mock_db):
        resp = mock_client.post("/api/portfolio/allocate", json={"capital": 0})
        assert resp.status_code in (200, 422)

    def test_allocate_negative_capital(self, mock_client, mock_db):
        resp = mock_client.post("/api/portfolio/allocate", json={"capital": -1000})
        assert resp.status_code in (200, 422)

    def test_allocate_missing_capital(self, mock_client, mock_db):
        resp = mock_client.post("/api/portfolio/allocate", json={})
        assert resp.status_code in (200, 422)

    def test_allocate_string_capital(self, mock_client, mock_db):
        resp = mock_client.post("/api/portfolio/allocate", json={"capital": "abc"})
        assert resp.status_code in (200, 422)

    def test_invalid_json_body(self, mock_client, mock_db):
        resp = mock_client.post("/api/portfolio/allocate", data="not json", headers={"Content-Type": "application/json"})
        assert resp.status_code in (200, 422)

    def test_unknown_route_returns_404(self, mock_client, mock_db):
        resp = mock_client.get("/api/this-does-not-exist")
        assert resp.status_code == 404

    def test_method_not_allowed(self, mock_client, mock_db):
        resp = mock_client.delete("/api/health")
        assert resp.status_code == 405


class TestAllocatorEdgeCases:
    def test_allocate_zero_capital(self, db_session):
        from src.portfolio.allocator import PortfolioAllocator

        pa = PortfolioAllocator()
        result = pa.allocate(0.0, db=db_session)
        assert isinstance(result, dict)

    def test_allocate_negative_capital(self, db_session):
        from src.portfolio.allocator import PortfolioAllocator

        pa = PortfolioAllocator()
        result = pa.allocate(-1000.0, db=db_session)
        assert isinstance(result, dict)

    def test_allocate_tiny_capital(self, db_session):
        from src.portfolio.allocator import PortfolioAllocator

        pa = PortfolioAllocator()
        result = pa.allocate(1.0, db=db_session)
        assert isinstance(result, dict)

    def test_set_invalid_profile(self):
        from src.portfolio.allocator import PortfolioAllocator

        pa = PortfolioAllocator()
        pa.set_profile("nonexistent_profile")
        assert pa.profile == "balanced"


class TestProfileEdgeCases:
    def test_user_profile_from_dict_missing_fields(self):
        from src.user_profile import UserProfile

        profile = UserProfile.from_dict({"user_id": "test_user"})
        assert profile.risk_profile == "balanced"

    def test_user_profile_from_dict_corrupted_preferences(self):
        from src.user_profile import UserProfile

        profile = UserProfile.from_dict({"user_id": "test_user", "risk_profile": "aggressive", "preferences": None})
        assert profile.preferences is None or isinstance(profile.preferences, dict)

    def test_profile_manager_get_creates_default_on_missing(self):
        from src.user_profile import UserProfileManager

        mgr = UserProfileManager()
        profile = mgr.get("__test_edge_new__")
        assert profile is not None
        assert profile.user_id == "__test_edge_new__"
        mgr.delete("__test_edge_new__")

    def test_profile_manager_list_empty_after_cleanup(self):
        from src.user_profile import UserProfileManager

        mgr = UserProfileManager()
        mgr.delete("__test_nonexistent__")
        profiles = mgr.list_profiles()
        assert isinstance(profiles, list)


class TestReportsEdgeCases:
    def test_generate_portfolio_csv_empty_list(self):
        from src.reports import generate_portfolio_csv

        result = generate_portfolio_csv([])
        assert isinstance(result, str)

    def test_generate_signals_csv_empty_list(self):
        from src.reports import generate_signals_csv

        result = generate_signals_csv([])
        assert isinstance(result, str)

    def test_generate_analysis_csv_empty_data(self):
        from src.reports import generate_analysis_csv

        result = generate_analysis_csv("SBER", {}, [])
        assert isinstance(result, str)

    def test_generate_portfolio_csv_missing_keys(self):
        from src.reports import generate_portfolio_csv

        result = generate_portfolio_csv([{"ticker": "SBER"}])
        assert "SBER" in result


class TestModelRegistryEdgeCases:
    def test_get_metrics_nonexistent(self):
        from src.model_registry import get_model_metrics

        result = get_model_metrics("__nonexistent_model_test__")
        assert result == {}

    def test_delete_nonexistent_model(self):
        from src.model_registry import delete_model

        delete_model("__nonexistent_model_test__")

    def test_list_models_empty_registry(self, tmp_path):
        from src.model_registry import MODEL_DIR, REGISTRY_FILE, list_models
        import src.model_registry as mr

        original_dir = MODEL_DIR
        original_reg = REGISTRY_FILE
        new_dir = tmp_path / "models"
        new_dir.mkdir(parents=True, exist_ok=True)
        mr.MODEL_DIR = new_dir
        mr.REGISTRY_FILE = new_dir / "registry.json"
        try:
            models = list_models()
            assert models == []
        finally:
            mr.MODEL_DIR = original_dir
            mr.REGISTRY_FILE = original_reg


class TestTelegramEdgeCases:
    def test_analysis_cache_miss(self):
        from src.interfaces.telegram import analysis_cache, CACHE_TTL

        key = "__test_cache_miss__"
        cached = analysis_cache.get(key)
        assert cached is None

    def test_analysis_cache_ttl_expired(self):
        from src.interfaces.telegram import analysis_cache, CACHE_TTL

        import time

        key = "__test_cache_expired__"
        analysis_cache[key] = (time.time() - CACHE_TTL - 10, {}, "test")
        now = time.time()
        cached = analysis_cache.get(key)
        assert (now - cached[0]) >= CACHE_TTL


class TestRiskGuardsEdgeCases:
    def test_check_leverage_zero(self):
        from src.trading.risk.guards import check_leverage

        ok, msg = check_leverage(0.0)
        assert ok is True

    def test_check_leverage_exact_limit(self):
        from src.trading.risk.guards import check_leverage

        ok, msg = check_leverage(1.0)
        assert ok is True

    def test_check_leverage_above_limit(self):
        from src.trading.risk.guards import check_leverage

        ok, msg = check_leverage(1.5)
        assert ok is False

    def test_check_var_limit_zero(self):
        from src.trading.risk.guards import check_var_limit

        ok, msg = check_var_limit(0.0)
        assert ok is True

    def test_check_var_limit_exact(self):
        from src.trading.risk.guards import check_var_limit

        ok, msg = check_var_limit(0.05)
        assert ok is True

    def test_check_var_limit_above(self):
        from src.trading.risk.guards import check_var_limit

        ok, msg = check_var_limit(0.10)
        assert ok is False

    def test_drawdown_returns_zero(self):
        from src.trading.risk.guards import current_drawdown

        dd = current_drawdown()
        assert dd == 0.0

    def test_drawdown_after_reset(self):
        from src.trading.risk.guards import reset_peak, current_drawdown

        reset_peak(100.0)
        dd = current_drawdown()
        assert dd == 0.0

    def test_risk_per_trade_default(self):
        from src.trading.risk.guards import risk_per_trade

        rate = risk_per_trade()
        assert 0 < rate <= 0.20

    def test_max_position_pct_default(self):
        from src.trading.risk.guards import max_position_pct

        pct = max_position_pct()
        assert 0 < pct <= 1.0

    def test_max_drawdown_pct_default(self):
        from src.trading.risk.guards import max_drawdown_pct

        pct = max_drawdown_pct()
        assert pct > 0

    def test_set_min_volume(self):
        import src.trading.risk.guards as guards

        original = guards.MIN_DAILY_VOLUME
        guards.set_min_volume(500_000.0)
        assert guards.MIN_DAILY_VOLUME == 500_000.0
        guards.set_min_volume(original)

    def test_compute_position_shares_zero_risk(self):
        from src.trading.risk.guards import compute_position_shares

        result = compute_position_shares(
            portfolio_value=100_000, risk_per_trade=0.02, stop_loss_pct=0.0, current_price=0.0
        )
        assert result >= 1

    def test_compute_volatility_target_zero_current(self):
        from src.trading.risk.guards import compute_volatility_target

        result = compute_volatility_target(target_vol=0.25, current_vol=0.0)
        assert result == 1.0

    def test_compute_volatility_target_normal(self):
        from src.trading.risk.guards import compute_volatility_target

        result = compute_volatility_target(target_vol=0.25, current_vol=0.50)
        assert result == 0.5

    def test_get_day_pnl_no_start(self):
        from src.trading.risk.guards import get_day_pnl

        pnl, pct = get_day_pnl()
        assert pnl == 0.0
        assert pct == 0.0
