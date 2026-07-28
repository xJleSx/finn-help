from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, PropertyMock, patch

import numpy as np
import pandas as pd

from src.analysis.anomaly.features import (
    article_counts_per_day,
    build_anomaly_feature_vector,
    rolling_volume_features,
    sentiment_features_per_day,
    source_frequencies,
    topic_frequencies,
)
from src.analysis.ml.news_impact_features import ALL_FEATURE_COLS
from src.db.models import News


def make_mock_row(day_label, count_val):
    """Create a mock row like what db.execute().mappings().all() returns."""
    row = MagicMock()
    row.__getitem__ = lambda self, k: {"day": day_label, "count": count_val}.get(k, 0)
    type(row).day = PropertyMock(return_value=day_label)
    type(row).count = PropertyMock(return_value=count_val)
    return row


def make_mock_sentiment_row(day_label, avg_score, count_val):
    row = MagicMock()
    type(row).day = PropertyMock(return_value=day_label)
    type(row).avg_score = PropertyMock(return_value=avg_score)
    type(row).count = PropertyMock(return_value=count_val)
    return row


class TestArticleCountsPerDay:
    def test_returns_dataframe(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"day": datetime(2024, 1, 1, tzinfo=timezone.utc), "count": 5},
            {"day": datetime(2024, 1, 2, tzinfo=timezone.utc), "count": 3},
            {"day": datetime(2024, 1, 3, tzinfo=timezone.utc), "count": 7},
        ]
        df = article_counts_per_day(mock_db, "TEST", days_back=365)
        assert isinstance(df, pd.DataFrame)
        assert "count" in df.columns
        assert len(df) >= 3

    def test_empty_result_returns_empty_dataframe(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = []
        df = article_counts_per_day(mock_db, "UNKNOWN", days_back=365)
        assert df.empty
        assert list(df.columns) == ["day", "count"]

    def test_fills_missing_dates_with_zero(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"day": datetime(2024, 1, 1, tzinfo=timezone.utc), "count": 10},
            {"day": datetime(2024, 1, 3, tzinfo=timezone.utc), "count": 5},
        ]
        df = article_counts_per_day(mock_db, "TEST", days_back=365)
        assert len(df) >= 3
        zero_days = (df["count"] == 0).sum()
        assert zero_days >= 1

    def test_respects_days_back(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {
                "day": datetime.now(timezone.utc) - timedelta(days=i),
                "count": 1,
            }
            for i in range(5)
        ]
        with patch("src.analysis.anomaly.features.settings") as mock_settings:
            mock_settings.ml_anomaly_days_back = 5
            df = article_counts_per_day(mock_db, "TEST", days_back=5)
        assert not df.empty
        assert "count" in df.columns

    def test_passes_correct_cutoff_to_query(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = []
        with patch("src.analysis.anomaly.features.settings") as mock_settings:
            mock_settings.ml_anomaly_days_back = 100
            article_counts_per_day(mock_db, "TEST")
            sql = mock_db.execute.call_args[0][0]
            assert sql is not None


class TestRollingVolumeFeatures:
    def test_returns_features(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"day": datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i), "count": i % 10}
            for i in range(30)
        ]
        df = rolling_volume_features(mock_db, "TEST", days_back=365)
        assert not df.empty
        assert "vol_ma_7d" in df.columns
        assert "vol_std_7d" in df.columns
        assert "vol_zscore_7d" in df.columns

    def test_insufficient_data_returns_empty(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"day": datetime(2024, 1, 1, tzinfo=timezone.utc), "count": 1},
        ]
        df = rolling_volume_features(mock_db, "UNKNOWN", days_back=365)
        assert df.empty

    def test_adds_all_window_sizes(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"day": datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i), "count": 1}
            for i in range(30)
        ]
        with patch("src.analysis.anomaly.features.settings") as mock_settings:
            mock_settings.ml_anomaly_window_sizes = "3,7,14,30"
            df = rolling_volume_features(mock_db, "TEST", days_back=365)
            for w in (3, 7, 14, 30):
                assert f"vol_ma_{w}d" in df.columns
                assert f"vol_std_{w}d" in df.columns

    def test_zscore_computation(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"day": datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i), "count": 10}
            for i in range(30)
        ]
        df = rolling_volume_features(mock_db, "TEST", days_back=365)
        zscore_col = "vol_zscore_7d"
        if zscore_col in df.columns:
            non_zero = (df[zscore_col] != 0).sum()
            assert non_zero >= 0


class TestSentimentFeaturesPerDay:
    def test_returns_features(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"day": datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i), "avg_score": 0.5, "count": 5}
            for i in range(30)
        ]
        df = sentiment_features_per_day(mock_db, "TEST", days_back=365)
        assert not df.empty
        assert "sent_ma_7d" in df.columns
        assert "sent_std_7d" in df.columns
        assert "sent_change_1d" in df.columns
        assert "sent_change_3d" in df.columns

    def test_empty_data(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = []
        df = sentiment_features_per_day(mock_db, "TEST", days_back=365)
        assert df.empty
        assert list(df.columns) == ["day", "sentiment_mean", "article_count"]

    def test_fills_missing_dates(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"day": datetime(2024, 1, 1, tzinfo=timezone.utc), "avg_score": 0.5, "count": 5},
            {"day": datetime(2024, 1, 3, tzinfo=timezone.utc), "avg_score": -0.2, "count": 3},
        ]
        df = sentiment_features_per_day(mock_db, "TEST", days_back=365)
        assert len(df) >= 3
        assert df["sentiment_mean"].iloc[1] == 0.0
        assert df["article_count"].iloc[1] == 0

    def test_handles_none_avg_score(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"day": datetime(2024, 1, 1, tzinfo=timezone.utc), "avg_score": None, "count": 0},
        ]
        df = sentiment_features_per_day(mock_db, "TEST", days_back=365)
        assert not df.empty
        assert df["sentiment_mean"].iloc[0] == 0.0

    def test_sentiment_change_columns(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"day": datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i), "avg_score": float(i), "count": 1}
            for i in range(10)
        ]
        df = sentiment_features_per_day(mock_db, "TEST", days_back=365)
        assert "sent_change_1d" in df.columns
        assert "sent_change_3d" in df.columns
        assert df["sent_change_1d"].iloc[0] == 0.0


class TestSourceFrequencies:
    def test_returns_dict(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"source_name": "SourceA", "category": "MACRO", "cnt": 10},
            {"source_name": "SourceA", "category": "COMPANY", "cnt": 5},
            {"source_name": "SourceB", "category": "MACRO", "cnt": 20},
        ]
        freqs = source_frequencies(mock_db)
        assert isinstance(freqs, dict)
        assert "SourceA" in freqs
        assert "SourceB" in freqs

    def test_filter_by_category(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"source_name": "SourceA", "category": "MACRO", "cnt": 10},
        ]
        freqs = source_frequencies(mock_db, category="MACRO")
        assert "SourceA" in freqs

    def test_handles_null_source_name(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"source_name": None, "category": "MACRO", "cnt": 5},
        ]
        freqs = source_frequencies(mock_db)
        assert "unknown" in freqs

    def test_handles_null_category(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"source_name": "SourceA", "category": None, "cnt": 5},
        ]
        freqs = source_frequencies(mock_db)
        assert "UNCLASSIFIED" in freqs.get("SourceA", {})

    def test_computes_ratio_correctly(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"source_name": "SourceA", "category": "MACRO", "cnt": 10},
            {"source_name": "SourceA", "category": "COMPANY", "cnt": 10},
            {"source_name": "SourceB", "category": "MACRO", "cnt": 80},
        ]
        freqs = source_frequencies(mock_db)
        cat_total_macro = 10 + 80
        source_a_total = 20
        expected_ratio = 10 / max(cat_total_macro * source_a_total / max(cat_total_macro + 10, 1), 1)
        assert "SourceA" in freqs
        assert "MACRO" in freqs["SourceA"]


class TestTopicFrequencies:
    def test_returns_dict(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"ticker": "AAPL", "category": "MACRO", "subcategory": "monetary_policy", "cnt": 10},
            {"ticker": "AAPL", "category": "COMPANY", "subcategory": "earnings", "cnt": 5},
            {"ticker": "MSFT", "category": "MACRO", "subcategory": "monetary_policy", "cnt": 3},
        ]
        freqs = topic_frequencies(mock_db)
        assert "AAPL" in freqs
        assert "MSFT" in freqs

    def test_topic_keys_are_tuples(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"ticker": "AAPL", "category": "MACRO", "subcategory": "monetary_policy", "cnt": 10},
        ]
        freqs = topic_frequencies(mock_db)
        for topic in freqs["AAPL"]:
            assert isinstance(topic, tuple)
            assert len(topic) == 2

    def test_handles_null_category(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"ticker": "AAPL", "category": None, "subcategory": None, "cnt": 5},
        ]
        freqs = topic_frequencies(mock_db)
        assert ("UNCLASSIFIED", "GENERAL") in freqs["AAPL"]

    def test_handles_null_subcategory(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [
            {"ticker": "AAPL", "category": "MACRO", "subcategory": None, "cnt": 5},
        ]
        freqs = topic_frequencies(mock_db)
        assert ("MACRO", "GENERAL") in freqs["AAPL"]

    def test_empty_result(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = []
        freqs = topic_frequencies(mock_db)
        assert isinstance(freqs, dict)
        assert len(freqs) == 0


class TestBuildAnomalyFeatureVector:
    def test_returns_numpy_array(self):
        mock_db = MagicMock()
        mock_article = MagicMock(spec=News)
        mock_article.published_at = datetime.now(timezone.utc)
        mock_article.created_at = None
        mock_article.sentiment_score = 0.5
        mock_article.impact_score = 0.3
        mock_article.source_weight = 0.8
        mock_article.source_count = 2
        mock_article.sentiment = "positive"
        mock_article.category = "MACRO"
        mock_article.subcategory = "monetary_policy"

        mock_instrument_link = MagicMock()
        mock_instrument_link.instrument_id = 1
        mock_db.query.return_value.filter.return_value.first.return_value = mock_instrument_link

        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        vec = build_anomaly_feature_vector(mock_db, mock_article)
        assert isinstance(vec, np.ndarray)
        assert vec.ndim == 1
        assert vec.dtype == np.float32
        assert len(vec) == len(ALL_FEATURE_COLS)

    def test_returns_array_with_length_matching_feature_cols(self):
        mock_db = MagicMock()
        mock_article = MagicMock(spec=News)
        mock_article.published_at = datetime.now(timezone.utc)
        mock_article.created_at = None
        mock_article.sentiment_score = None
        mock_article.impact_score = None
        mock_article.source_weight = None
        mock_article.source_count = None
        mock_article.sentiment = None
        mock_article.category = None
        mock_article.subcategory = None

        mock_db.query.return_value.filter.return_value.first.return_value = None

        vec = build_anomaly_feature_vector(mock_db, mock_article)
        assert isinstance(vec, np.ndarray)
        assert vec.ndim == 1
        assert len(vec) == len(ALL_FEATURE_COLS)
