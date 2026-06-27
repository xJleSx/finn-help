from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from src.analysis.ml.ensemble import EnsemblePredictor
from src.analysis.ml.walk_forward import adjust_confidence_by_oos, walk_forward_validate


def _make_df(n: int = 200) -> pd.DataFrame:
    dates = [date.today() - timedelta(days=i) for i in range(n, 0, -1)]
    close = np.sin(np.linspace(0, 6, n)) * 50 + 200 + np.random.default_rng(0).normal(0, 1, n)
    close = close + np.linspace(0, 10, n)
    df = pd.DataFrame(
        {
            "date": dates,
            "close": close,
            "open": close + np.random.default_rng(1).normal(0, 2, n),
            "high": close + abs(np.random.default_rng(2).normal(0, 3, n)),
            "low": close - abs(np.random.default_rng(3).normal(0, 3, n)),
            "volume": np.random.default_rng(4).poisson(5_000_000, n),
        }
    )
    df["rsi"] = 50 + np.random.default_rng(5).normal(0, 10, n)
    df["macd_hist"] = np.random.default_rng(6).normal(0, 1, n)
    df["sma_20"] = df["close"].rolling(20).mean()
    df["sma_50"] = df["close"].rolling(50).mean()
    df["sma_200"] = df["close"].rolling(200).mean() if n >= 200 else df["close"].rolling(n).mean()
    df["bb_upper"] = df["sma_20"] + df["close"].rolling(20).std() * 2
    df["bb_lower"] = df["sma_20"] - df["close"].rolling(20).std() * 2
    df["atr"] = np.random.default_rng(7).uniform(1, 5, n)
    df["volume_sma_20"] = df["volume"].rolling(20).mean()
    return df


class TestXGBoostModel:
    @pytest.fixture
    def model(self):
        from src.analysis.ml.xgboost_model import XGBoostClassifier

        return XGBoostClassifier()

    def test_predict_returns_expected_keys(self, model):
        df = _make_df(100)
        result = model.predict(df)
        assert isinstance(result, dict)
        assert "action" in result
        assert "confidence" in result
        assert "signal_score" in result
        assert result["action"] in ("BUY", "SELL", "HOLD", "NEUTRAL")

    def test_predict_with_too_few_rows_returns_fallback(self, model):
        df = _make_df(10)
        result = model.predict(df)
        assert result["action"] == "NEUTRAL"
        assert result["confidence"] == 0.0

    def test_predict_with_noisy_data(self, model):
        df = _make_df(200)
        result = model.predict(df)
        assert 0.0 <= result["confidence"] <= 1.0
        if result["action"] != "NEUTRAL":
            assert -1.0 <= result["signal_score"] <= 1.0
            assert "probability" in result


class TestLightGBMModel:
    @pytest.fixture
    def model(self):
        from src.analysis.ml.lightgbm_model import LightGBMClassifier

        return LightGBMClassifier()

    def test_predict_returns_expected_keys(self, model):
        df = _make_df(100)
        result = model.predict(df)
        assert isinstance(result, dict)
        assert "action" in result
        assert result["action"] in ("BUY", "SELL", "HOLD", "NEUTRAL")

    def test_predict_short_data(self, model):
        df = _make_df(5)
        result = model.predict(df)
        assert result["action"] == "NEUTRAL"


class TestCatBoostModel:
    @pytest.fixture
    def model(self):
        pytest.importorskip("catboost")
        from src.analysis.ml.catboost_model import CatBoostClassifierModel

        return CatBoostClassifierModel()

    def test_predict_returns_expected_keys(self, model):
        df = _make_df(100)
        result = model.predict(df)
        assert isinstance(result, dict)
        assert "action" in result
        assert result["action"] in ("BUY", "SELL", "HOLD", "NEUTRAL")

    def test_predict_short_data(self, model):
        df = _make_df(5)
        result = model.predict(df)
        assert result["action"] == "NEUTRAL"


class TestEnsemble:
    @pytest.fixture
    def ensemble(self):
        return EnsemblePredictor()

    def test_predict_returns_all_keys(self, ensemble):
        df = _make_df(100)
        result = ensemble.predict(df)
        assert isinstance(result, dict)
        assert "action" in result
        assert "confidence" in result
        assert "signal_score" in result
        assert result["action"] in ("BUY", "SELL", "HOLD", "NEUTRAL")
        if result["action"] != "NEUTRAL":
            assert "probability" in result
            assert "model_votes" in result
            assert "walk_forward" in result

    def test_predict_short_data(self, ensemble):
        df = _make_df(5)
        result = ensemble.predict(df)
        assert result["action"] in ("NEUTRAL", "HOLD")

    def test_ensemble_returns_consistent_type(self, ensemble):
        for n in [50, 100, 200]:
            df = _make_df(n)
            result = ensemble.predict(df)
            assert isinstance(result["confidence"], float)
            assert result["confidence"] >= 0.0


class TestWalkForward:
    def test_walk_forward_validate_returns_metrics(self):
        rng = np.random.default_rng(42)
        x = rng.normal(0, 1, (150, 5))
        y = (rng.normal(0, 1, 150) > 0).astype(int)

        from xgboost import XGBClassifier

        model = XGBClassifier(n_estimators=10, max_depth=2)

        result = walk_forward_validate(model, x, y, n_splits=2, min_train_size=50)
        assert "oos_accuracy" in result
        assert "oos_precision" in result
        assert "oos_recall" in result
        assert "folds_completed" in result
        assert 0 <= result["oos_accuracy"] <= 1

    def test_adjust_confidence_default(self):
        result = adjust_confidence_by_oos(0.5, {"oos_accuracy": 0.6, "folds_completed": 3})
        assert 0.0 <= result <= 1.0

    def test_adjust_confidence_no_folds(self):
        result = adjust_confidence_by_oos(0.5, {"oos_accuracy": 0.0, "folds_completed": 0})
        assert result == pytest.approx(0.0)


class TestProphet:
    @pytest.fixture
    def prophet(self):
        from src.analysis.ml.prophet_model import ProphetPredictor

        return ProphetPredictor()

    def test_predict_returns_keys(self, prophet):
        df = _make_df(200)
        result = prophet.predict(df)
        assert isinstance(result, dict)
        assert "target_price" in result
        assert "current_price" in result
        assert "price_change_pct" in result
        assert "confidence" in result

    def test_predict_short_data(self, prophet):
        df = _make_df(10)
        result = prophet.predict(df)
        assert "target_price" in result

    def test_predict_flat_price(self, prophet):
        df = _make_df(100)
        df["close"] = 100.0
        result = prophet.predict(df)
        assert result["current_price"] == 100.0

    def test_predict_empty_df(self, prophet):
        df = pd.DataFrame()
        result = prophet.predict(df)
        assert result["target_price"] is None


class TestEdgeCases:
    def test_xgboost_empty_features(self):
        from src.analysis.ml.xgboost_model import XGBoostClassifier

        model = XGBoostClassifier()
        df = pd.DataFrame({"close": [100] * 10})
        result = model.predict(df)
        assert result["action"] == "NEUTRAL"

    def test_xgboost_nan_close(self):
        from src.analysis.ml.xgboost_model import XGBoostClassifier

        model = XGBoostClassifier()
        df = _make_df(100)
        df["close"] = float("nan")
        result = model.predict(df)
        assert result["action"] in ("BUY", "SELL", "HOLD", "NEUTRAL")

    def test_ensemble_missing_columns(self):
        ensemble = EnsemblePredictor()
        df = pd.DataFrame({"close": [100] * 50})
        result = ensemble.predict(df)
        assert isinstance(result, dict)
        assert "action" in result

    def test_prophet_zero_price(self):
        from src.analysis.ml.prophet_model import ProphetPredictor

        prophet = ProphetPredictor()
        df = _make_df(100)
        df["close"] = 0.0
        result = prophet.predict(df)
        assert isinstance(result, dict)
        assert "target_price" in result

    def test_walk_forward_minimal_data(self):
        rng = np.random.default_rng(42)
        x = rng.normal(0, 1, (30, 5))
        y = (rng.normal(0, 1, 30) > 0).astype(int)

        from xgboost import XGBClassifier

        model = XGBClassifier(n_estimators=5, max_depth=2)

        result = walk_forward_validate(model, x, y, n_splits=2, min_train_size=25)
        assert "folds_completed" in result
        assert 0 <= result["oos_accuracy"] <= 1
