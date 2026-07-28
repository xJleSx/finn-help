from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from src.analysis.market.feature_drift import (
    DRIFT_THRESHOLD_DEFAULT,
    _collect_numeric_keys,
    _extract_vectors,
    auto_handle_drift,
    detect_drift,
    summary,
)


@pytest.fixture
def mock_session():
    with patch("src.analysis.market.feature_drift.get_session") as mock:
        session = MagicMock()
        mock.return_value = session
        yield session


def _make_cache_row(ticker, feature_type, date_val, value_json):
    row = MagicMock()
    row.ticker = ticker
    row.feature_type = feature_type
    row.date = date_val
    row.value_json = value_json
    return row


class TestCollectNumericKeys:
    def test_flat_dict(self):
        keys = _collect_numeric_keys({"a": 1.0, "b": 2, "c": "x"})
        assert "a" in keys
        assert "b" in keys
        assert "c" not in keys

    def test_nested_dict(self):
        keys = _collect_numeric_keys({"outer": {"inner": 1.5, "flag": True}})
        assert "outer.inner" in keys
        assert "outer.flag" not in keys

    def test_empty_dict(self):
        assert _collect_numeric_keys({}) == []


class TestExtractVectors:
    def test_extracts_numeric_values_by_key(self):
        entries = [
            {"value": {"a": 1.0, "b": 2.0}},
            {"value": {"a": 3.0, "b": 4.0}},
        ]
        result = _extract_vectors(entries, ["a", "b"])
        assert result["a"] == [1.0, 3.0]
        assert result["b"] == [2.0, 4.0]

    def test_skips_missing_keys(self):
        entries = [
            {"value": {"a": 1.0}},
            {"value": {"b": 2.0}},
        ]
        result = _extract_vectors(entries, ["a", "b"])
        assert result["a"] == [1.0]
        assert result["b"] == [2.0]

    def test_nested_key_extraction(self):
        entries = [
            {"value": {"x": {"y": 10.0}}},
            {"value": {"x": {"y": 20.0}}},
        ]
        result = _extract_vectors(entries, ["x.y"])
        assert result["x.y"] == [10.0, 20.0]

    def test_handles_none_values(self):
        entries = [
            {"value": {"a": None}},
        ]
        result = _extract_vectors(entries, ["a"])
        assert result.get("a", []) == []


class TestDetectDrift:
    def test_returns_empty_when_fewer_than_4_rows(self, mock_session):
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        result = detect_drift("technical")
        assert result == []

    def test_returns_empty_when_ticker_has_fewer_than_4_entries(self, mock_session):
        rows = [_make_cache_row("AAPL", "technical", date.today(), {"val": 1.0}) for _ in range(3)]
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows
        result = detect_drift("technical")
        assert result == []

    def test_detects_drift_when_ks_test_exceeds_threshold(self, mock_session):
        entries = []
        for i in range(40):
            day = date.today() - timedelta(days=i)
            entries.append(_make_cache_row("AAPL", "technical", day, {"price": float(1.0 if i < 20 else 5.0)}))
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = entries

        with patch("src.analysis.market.feature_drift.ks_2samp") as mock_ks:
            mock_ks.return_value = (0.8, 0.001)
            result = detect_drift("technical", threshold=0.1)
            assert len(result) >= 1
            assert result[0]["ticker"] == "AAPL"
            assert result[0]["drift_score"] > 0.1

    def test_respects_threshold(self, mock_session):
        entries = []
        for i in range(20):
            day = date.today() - timedelta(days=i)
            entries.append(_make_cache_row("AAPL", "technical", day, {"price": float(1.0 if i < 10 else 5.0)}))
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = entries

        with patch("src.analysis.market.feature_drift.ks_2samp") as mock_ks:
            mock_ks.return_value = (0.5, 0.5)
            result = detect_drift("technical", threshold=0.9)
            assert result == []

    def test_handles_exception_during_ks(self, mock_session):
        entries = []
        for i in range(20):
            day = date.today() - timedelta(days=i)
            entries.append(_make_cache_row("AAPL", "technical", day, {"price": float(i)}))
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = entries

        with patch("src.analysis.market.feature_drift.ks_2samp", side_effect=ValueError("test")):
            result = detect_drift("technical")
            assert result == []

    def test_skips_non_numeric_keys(self, mock_session):
        entries = []
        for i in range(20):
            day = date.today() - timedelta(days=i)
            entries.append(_make_cache_row("AAPL", "technical", day, {"name": "foo"}))
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = entries
        result = detect_drift("technical")
        assert result == []


class TestAutoHandleDrift:
    def test_invalidates_ticker_when_max_fields_drifted_exceeded(self, mock_session):
        entries = []
        for i in range(40):
            day = date.today() - timedelta(days=i)
            val = {"p1": 1.0, "p2": 1.0, "p3": 1.0, "p4": 1.0} if i < 20 else \
                  {"p1": 5.0, "p2": 5.0, "p3": 5.0, "p4": 5.0}
            entries.append(_make_cache_row("AAPL", "technical", day, val))
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = entries

        with (
            patch("src.analysis.market.feature_drift.ks_2samp") as mock_ks,
            patch("src.analysis.market.feature_drift.bump_version") as mock_bump,
            patch("src.analysis.market.feature_drift.invalidate") as mock_invalidate,
        ):
            mock_ks.return_value = (0.8, 0.001)
            result = auto_handle_drift("technical", threshold=0.1, max_fields_drifted=2)
            assert len(result) >= 1
            mock_bump.assert_called_once_with("technical")
            mock_invalidate.assert_called_once_with("AAPL", "technical")

    def test_no_invalidation_when_below_max_fields(self, mock_session):
        entries = []
        for i in range(40):
            day = date.today() - timedelta(days=i)
            val = {"p1": 1.0, "p2": 1.0} if i < 20 else {"p1": 5.0, "p2": 5.0}
            entries.append(_make_cache_row("AAPL", "technical", day, val))
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = entries

        with (
            patch("src.analysis.market.feature_drift.ks_2samp") as mock_ks,
            patch("src.analysis.market.feature_drift.bump_version") as mock_bump,
            patch("src.analysis.market.feature_drift.invalidate") as mock_invalidate,
        ):
            mock_ks.return_value = (0.8, 0.001)
            auto_handle_drift("technical", threshold=0.1, max_fields_drifted=3)
            mock_bump.assert_not_called()
            mock_invalidate.assert_not_called()


class TestSummary:
    def test_summary_returns_dict(self, mock_session):
        mock_session.query.return_value.group_by.return_value.all.return_value = [
            ("technical", 10),
            ("sentiment", 5),
        ]
        result = summary()
        assert result["feature_types"] == {"technical": 10, "sentiment": 5}
        assert result["drift_threshold"] == DRIFT_THRESHOLD_DEFAULT

    def test_summary_empty(self, mock_session):
        mock_session.query.return_value.group_by.return_value.all.return_value = []
        result = summary()
        assert result["feature_types"] == {}
