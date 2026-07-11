
import pytest


class TestTradingFlow:
    def test_signal_engine_imports(self):
        from src.signals.engine import SignalFusionEngine
        engine = SignalFusionEngine()
        assert engine is not None

    def test_risk_tracker(self):
        from src.trading.risk.guards import DrawdownStageManager, WeeklyLossTracker
        tracker = WeeklyLossTracker()
        tracker.record_trade(-500, __import__("datetime").date(2026, 7, 7))
        level = tracker.weekly_loss_level()
        assert level in ("normal", "reduce_50", "minimum_only", "full_halt")

        manager = DrawdownStageManager()
        manager.update([100000, 95000, 92000])
        dd = manager.current_drawdown()
        assert dd < 0
        stage = manager.stage()
        assert stage in ("normal", "caution", "warning", "critical", "emergency")

    def test_portfolio_metrics(self):
        import numpy as np

        from src.analysis.metrics import compute_sharpe, compute_sortino
        r = np.array([0.001, 0.002, -0.001, 0.003, -0.002])
        s = compute_sharpe(r)
        assert isinstance(s, float)
        so = compute_sortino(r)
        assert isinstance(so, float)

    def test_features_module(self):
        import numpy as np
        import pandas as pd

        from src.analysis.features import FeatureBuilder
        dates = pd.date_range("2026-01-01", periods=100, freq="D")
        df = pd.DataFrame({
            "open": np.random.randn(100) * 10 + 100,
            "high": np.random.randn(100) * 10 + 102,
            "low": np.random.randn(100) * 10 + 98,
            "close": np.random.randn(100) * 10 + 100,
            "volume": np.random.randint(100000, 1000000, 100),
        }, index=dates)
        builder = FeatureBuilder()
        features = builder.build(df)
        assert features is not None
        assert len(features.columns) > 0

    def test_regime_detection(self):
        from src.analysis.regime import classify_regime
        info = classify_regime(
            vol_percentile=0.5, adx=30, hurst=0.7, trend_dir=1
        )
        assert "label" in info
        assert "direction" in info
        assert "mean_reversion" in info

    def test_volatility_estimators(self):
        import numpy as np

        from src.analysis.volatility import parkinson_volatility
        highs = np.array([105, 110, 108, 112, 115])
        lows = np.array([95, 98, 96, 100, 102])
        vol = parkinson_volatility(highs, lows, period=5, annualize=False)
        assert vol is not None
        assert len(vol) > 0


class TestAlertFlow:
    def test_alert_scorer_imports(self):
        from src.alerts.scorer import classify_priority
        priority = classify_priority(anomaly_score=0.5, pred_return=0.02, in_portfolio=True)
        assert priority is not None

    def test_alert_engine(self):
        from src.alerts.engine import AlertEngine
        engine = AlertEngine()
        assert engine is not None

    @pytest.mark.skip(reason="Requires notification service with Telegram token")
    def test_notification_dispatch(self):
        pass
