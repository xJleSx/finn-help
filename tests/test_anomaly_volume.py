from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.analysis.anomaly.volume_anomaly import VolumeAnomalyDetector


def _make_volume_features_df():
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    data = {"day": dates, "count": rng.integers(1, 30, 30)}
    for w in (3, 7, 14, 30):
        data[f"vol_ma_{w}d"] = rng.random(30) * 20
        data[f"vol_std_{w}d"] = rng.random(30) * 5
    data["vol_zscore_7d"] = rng.random(30) * 3 - 1.5
    df = pd.DataFrame(data).set_index("day")
    df.index.name = "day"
    return df


@pytest.fixture
def mock_volume_features():
    df = _make_volume_features_df()
    with patch(
        "src.analysis.anomaly.volume_anomaly.rolling_volume_features",
        return_value=df,
    ):
        yield


class TestVolumeAnomalyDetectorInit:
    def test_init_default_ticker(self):
        d = VolumeAnomalyDetector()
        assert d.ticker == ""
        assert d._model is None
        assert not d._trained

    def test_init_custom_ticker(self):
        d = VolumeAnomalyDetector("AAPL")
        assert d.ticker == "AAPL"

    def test_trained_property_default(self):
        d = VolumeAnomalyDetector()
        assert not d.trained


class TestVolumeAnomalyDetectorTrain:
    def test_train_no_ticker(self):
        d = VolumeAnomalyDetector()
        result = d.train(MagicMock())
        assert not result["trained"]
        assert result["reason"] == "no ticker"

    def test_train_empty_data(self):
        with patch(
            "src.analysis.anomaly.volume_anomaly.rolling_volume_features",
            return_value=pd.DataFrame(),
        ):
            d = VolumeAnomalyDetector("TEST")
            result = d.train(MagicMock())
            assert not result["trained"]
            assert result["reason"] == "insufficient data"

    def test_train_success(self, mock_volume_features):
        d = VolumeAnomalyDetector("TEST")
        result = d.train(MagicMock())
        assert result["trained"]
        assert result["samples"] == 30
        assert result["features"] > 0
        assert d._model is not None
        assert d.trained

    def test_train_stores_feature_columns(self, mock_volume_features):
        d = VolumeAnomalyDetector("TEST")
        d.train(MagicMock())
        assert len(d._feature_cols) > 0
        assert "count" not in d._feature_cols
        assert "vol_ma_3d" in d._feature_cols

    def test_train_with_ticker_param_overrides_instance(self):
        d = VolumeAnomalyDetector("DEFAULT")
        df = _make_volume_features_df()
        mock_db = MagicMock()
        with patch(
            "src.analysis.anomaly.volume_anomaly.rolling_volume_features",
            return_value=df,
        ) as mock_rvf:
            result = d.train(mock_db, ticker="OVERRIDE")
            mock_rvf.assert_called_with(mock_db, "OVERRIDE")
            assert result["trained"]

    def test_train_too_few_samples_returns_insufficient(self):
        df = _make_volume_features_df().iloc[:2]
        with patch(
            "src.analysis.anomaly.volume_anomaly.rolling_volume_features",
            return_value=df,
        ):
            d = VolumeAnomalyDetector("TEST")
            result = d.train(MagicMock())
            assert not result["trained"]
            assert result["reason"] == "insufficient data"


class TestVolumeAnomalyDetectorPredict:
    def test_predict_no_model_returns_zero(self):
        d = VolumeAnomalyDetector("TEST")
        score = d.predict({"vol_ma_7d": 10.0})
        assert score == 0.0

    def test_predict_with_model(self, mock_volume_features):
        d = VolumeAnomalyDetector("TEST")
        d.train(MagicMock())
        features = {c: 0.0 for c in d._feature_cols}
        score = d.predict(features)
        assert 0.0 <= score <= 1.0

    def test_predict_returns_clipped_score(self, mock_volume_features):
        d = VolumeAnomalyDetector("TEST")
        d.train(MagicMock())
        features = {c: 999.0 for c in d._feature_cols}
        score = d.predict(features)
        assert 0.0 <= score <= 1.0

    def test_predict_missing_feature_defaults_to_zero(self, mock_volume_features):
        d = VolumeAnomalyDetector("TEST")
        d.train(MagicMock())
        score = d.predict({})
        assert 0.0 <= score <= 1.0


class TestVolumeAnomalyDetectorPredictArticle:
    def test_predict_article_uses_db_and_article(self):
        d = VolumeAnomalyDetector("TEST")
        d._model = MagicMock()
        d._model.score_samples.return_value = np.array([-0.5])
        d._trained = True
        d._feature_cols = ["vol_ma_3d", "vol_ma_7d"]

        mock_article = MagicMock()
        mock_article.published_at = datetime(2024, 6, 15, tzinfo=timezone.utc)

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar.return_value = 5

        score = d.predict_article(mock_db, mock_article)
        assert 0.0 <= score <= 1.0

    def test_predict_article_no_published_at(self):
        d = VolumeAnomalyDetector("TEST")
        d._model = MagicMock()
        d._model.score_samples.return_value = np.array([-0.5])
        d._trained = True
        d._feature_cols = ["vol_ma_3d"]

        mock_article = MagicMock()
        mock_article.published_at = None

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar.return_value = 0

        score = d.predict_article(mock_db, mock_article)
        assert 0.0 <= score <= 1.0


class TestVolumeAnomalyDetectorAsync:
    @pytest.mark.asyncio
    async def test_async_train(self, mock_volume_features):
        d = VolumeAnomalyDetector("TEST")
        with patch("src.analysis.anomaly.volume_anomaly.get_executor") as mock_get_exec:
            from concurrent.futures import ThreadPoolExecutor
            real_exec = ThreadPoolExecutor(max_workers=1)
            mock_get_exec.return_value = real_exec

            try:
                result = await d.async_train()
                assert result["trained"]
            finally:
                real_exec.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_async_predict_article(self):
        d = VolumeAnomalyDetector("TEST")
        d._model = MagicMock()
        d._model.score_samples.return_value = np.array([-0.5])
        d._trained = True
        d._feature_cols = ["vol_ma_3d"]

        with patch("src.analysis.anomaly.volume_anomaly.get_executor") as mock_get_exec:
            from concurrent.futures import ThreadPoolExecutor
            real_exec = ThreadPoolExecutor(max_workers=1)
            mock_get_exec.return_value = real_exec

            mock_article = MagicMock()
            mock_article.published_at = datetime(2024, 6, 15, tzinfo=timezone.utc)

            try:
                score = await d.async_predict_article(mock_article)
                assert 0.0 <= score <= 1.0
            finally:
                real_exec.shutdown(wait=False)


class TestVolumeAnomalyDetectorBuildSingleDayFeatures:
    def test_build_single_day_features_queries_db(self):
        d = VolumeAnomalyDetector("TEST")
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar.return_value = 5

        features = d._build_single_day_features(
            mock_db,
            datetime(2024, 6, 15, tzinfo=timezone.utc),
        )
        assert "vol_ma_3d" in features
        assert "vol_ma_7d" in features
        assert "vol_ma_14d" in features
        assert "vol_ma_30d" in features
        assert features["vol_ma_3d"] == 5.0
        assert features["vol_std_3d"] == 0.0
        assert features["vol_zscore_7d"] == 0.0

    def test_build_single_day_features_handles_null(self):
        d = VolumeAnomalyDetector("TEST")
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar.return_value = None

        features = d._build_single_day_features(
            mock_db,
            datetime(2024, 6, 15, tzinfo=timezone.utc),
        )
        assert features["vol_ma_3d"] == 0.0

    def test_build_single_day_features_with_custom_windows(self):
        d = VolumeAnomalyDetector("TEST")
        with patch("src.analysis.anomaly.volume_anomaly.settings") as mock_settings:
            mock_settings.ml_anomaly_window_sizes = "5,10"
            mock_db = MagicMock()
            mock_db.execute.return_value.scalar.return_value = 3

            features = d._build_single_day_features(
                mock_db,
                datetime(2024, 6, 15, tzinfo=timezone.utc),
            )
            assert "vol_ma_5d" in features
            assert "vol_ma_10d" in features
            assert "vol_ma_3d" not in features
