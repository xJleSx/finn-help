from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from sqlalchemy.orm import Session

from src.analysis.fundamental.sector_medians import OutlierDetector, SectorMedianCalculator

# ── helpers ──────────────────────────────────────────────────────────────────


def named_row(**kwargs):
    return type("Row", (), kwargs)()


# ── SectorMedianCalculator tests ────────────────────────────────────────────


class TestComputeRollingMedians:
    def test_empty_sector(self):
        db = MagicMock(spec=Session)
        db.query.return_value.join.return_value.filter.return_value.all.return_value = []
        calc = SectorMedianCalculator(db)
        result = calc.compute_rolling_medians("Empty", "pe_ratio")
        assert result["current_median"] is None
        assert result["rolling_history"] == []
        assert result["trend"] == "stable"

    def test_unknown_metric_raises(self):
        db = MagicMock(spec=Session)
        calc = SectorMedianCalculator(db)
        with pytest.raises(ValueError, match="Unknown metric"):
            calc.compute_rolling_medians("Tech", "not_a_metric")

    def test_single_ticker(self):
        db = MagicMock(spec=Session)
        today = date.today()
        db.query.return_value.join.return_value.filter.return_value.all.return_value = [
            named_row(ticker="TICK", value=15.0, date=today),
        ]
        calc = SectorMedianCalculator(db)
        result = calc.compute_rolling_medians("Tech", "pe_ratio")
        assert result["current_median"] == 15.0
        assert result["trend"] == "stable"

    def test_includes_monthly_history(self):
        db = MagicMock(spec=Session)
        today = date.today()
        rows = []
        for i in range(24):
            dt = today - timedelta(days=30 * i)
            rows.append(named_row(ticker="TICK", value=10.0 + i * 0.5, date=dt))
            rows.append(named_row(ticker="TICK2", value=12.0 + i * 0.3, date=dt))
        db.query.return_value.join.return_value.filter.return_value.all.return_value = rows
        calc = SectorMedianCalculator(db)
        result = calc.compute_rolling_medians("Tech", "pe_ratio", window_months=6)
        assert len(result["rolling_history"]) >= 2
        assert result["current_median"] is not None
        assert result["trend"] in ("up", "down", "stable")

    def test_trend_stable_for_flat_data(self):
        db = MagicMock(spec=Session)
        today = date.today()
        rows = []
        for i in range(12):
            dt = today - timedelta(days=30 * i)
            rows.append(named_row(ticker="A", value=10.0, date=dt))
            rows.append(named_row(ticker="B", value=10.0, date=dt))
        db.query.return_value.join.return_value.filter.return_value.all.return_value = rows
        calc = SectorMedianCalculator(db)
        result = calc.compute_rolling_medians("Flat", "pe_ratio")
        assert result["trend"] == "stable"


class TestComputeAllSectors:
    def test_returns_dict_keyed_by_sector(self):
        db = MagicMock(spec=Session)
        sectors = [("Tech",), ("Fin",)]
        db.query.return_value.distinct.return_value.filter.return_value.all.return_value = sectors

        tech_result = {
            "sector": "Tech", "metric": "pe_ratio", "current_median": 15.0,
            "rolling_history": [{"month": "2026-01", "median": 15.0, "rolling_median": 15.0}],
            "trend": "stable",
        }
        fin_result = {
            "sector": "Fin", "metric": "pe_ratio", "current_median": 8.0,
            "rolling_history": [{"month": "2026-01", "median": 8.0, "rolling_median": 8.0}],
            "trend": "stable",
        }

        with patch.object(SectorMedianCalculator, "compute_rolling_medians") as mock_crm:
            mock_crm.side_effect = [tech_result, fin_result]
            calc = SectorMedianCalculator(db)
            result = calc.compute_all_sectors("pe_ratio")

        assert result == {"Tech": tech_result, "Fin": fin_result}


class TestGetSectorOutliers:
    def test_no_outliers_when_within_threshold(self):
        db = MagicMock(spec=Session)
        rows = [
            named_row(ticker="A", value=10.0),
            named_row(ticker="B", value=10.5),
        ]
        subq = MagicMock()
        subq.c.ticker = "ticker"
        subq.c.value = "value"
        db.query.return_value.subquery.return_value = subq
        db.query.return_value.filter.return_value.all.return_value = rows
        calc = SectorMedianCalculator(db)
        result = calc.get_sector_outliers("Tech", "pe_ratio", std_threshold=5.0)
        assert len(result) == 0

    def test_known_outlier_detected(self):
        db = MagicMock(spec=Session)
        rows_data = [
            named_row(ticker="A", value=10.0),
            named_row(ticker="B", value=10.5),
            named_row(ticker="C", value=9.8),
            named_row(ticker="D", value=10.2),
            named_row(ticker="E", value=50.0),
        ]
        subq = MagicMock()
        subq.c.ticker = "ticker"
        subq.c.value = "value"
        db.query.return_value.subquery.return_value = subq
        db.query.return_value.filter.return_value.all.return_value = rows_data
        calc = SectorMedianCalculator(db)
        result = calc.get_sector_outliers("Tech", "pe_ratio", std_threshold=2.0)
        assert len(result) == 1
        assert result[0]["ticker"] == "E"
        assert result[0]["direction"] == "above"

    def test_empty_sector_returns_empty(self):
        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.all.return_value = []
        calc = SectorMedianCalculator(db)
        assert calc.get_sector_outliers("Ghost", "pe_ratio") == []


# ── OutlierDetector tests ────────────────────────────────────────────────────


class TestDetectOutliers:
    def test_zscore_detects_outliers(self):
        rng = np.random.default_rng(42)
        data = np.concatenate([rng.normal(0, 1, 100), [10, -10, 12]])
        df = pd.DataFrame({"value": data})
        detector = OutlierDetector()
        result = detector.detect_outliers(df, "value", method="zscore", threshold=2.0)
        assert result["is_outlier"].sum() >= 3

    def test_zscore_returns_expected_columns(self):
        df = pd.DataFrame({"value": [1, 2, 3, 4, 100]})
        detector = OutlierDetector()
        result = detector.detect_outliers(df, "value", method="zscore")
        assert "outlier_score" in result.columns
        assert "is_outlier" in result.columns

    def test_iqr_detects_outliers(self):
        df = pd.DataFrame({"value": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100]})
        detector = OutlierDetector()
        result = detector.detect_outliers(df, "value", method="iqr")
        assert bool(result["is_outlier"].iloc[-1]) is True

    def test_iqr_high_values(self):
        df = pd.DataFrame({"value": [10, 12, 11, 13, 14, 15, 100, 200]})
        detector = OutlierDetector()
        result = detector.detect_outliers(df, "value", method="iqr")
        assert bool(result["is_outlier"].iloc[-2]) is True
        assert bool(result["is_outlier"].iloc[-1]) is True

    def test_zscore_vs_iqr_different_sensitivities(self):
        values = list(range(1, 21)) + [30]
        df = pd.DataFrame({"value": values})
        detector = OutlierDetector()
        z_result = detector.detect_outliers(df, "value", method="zscore", threshold=2.0)
        iqr_result = detector.detect_outliers(df, "value", method="iqr")
        assert z_result["is_outlier"].sum() > 0
        assert iqr_result["is_outlier"].sum() >= 0
        assert not z_result["outlier_score"].equals(iqr_result["outlier_score"])

    def test_constant_values_no_outliers(self):
        df = pd.DataFrame({"value": [5, 5, 5, 5, 5]})
        detector = OutlierDetector()
        z_result = detector.detect_outliers(df, "value", method="zscore")
        assert z_result["is_outlier"].sum() == 0
        iqr_result = detector.detect_outliers(df, "value", method="iqr")
        assert iqr_result["is_outlier"].sum() == 0

    def test_unknown_method_raises(self):
        df = pd.DataFrame({"value": [1, 2, 3]})
        detector = OutlierDetector()
        with pytest.raises(ValueError, match="Unknown method"):
            detector.detect_outliers(df, "value", method="unknown")


class TestDetectTemporalOutliers:
    def test_insufficient_data_returns_empty(self):
        detector = OutlierDetector()
        detector.db = MagicMock()
        detector.db.query.return_value.join.return_value.filter.return_value.order_by.return_value.all.return_value = []
        result = detector.detect_temporal_outliers("TICK", "pe_ratio")
        assert result == []

    def test_known_spike_detected(self):
        today = date.today()
        rng = np.random.default_rng(42)
        rows = [(10.0 + rng.normal(0, 2.0), today - timedelta(days=i)) for i in range(200, 0, -1)]
        rows[160] = (50.0, today - timedelta(days=40))
        mock_rows = [named_row(value=v, date=d) for v, d in rows]

        detector = OutlierDetector()
        detector.db = MagicMock()
        detector.db.query.return_value.join.return_value.filter.return_value.order_by.return_value.all.return_value = mock_rows
        result = detector.detect_temporal_outliers("SPIKE", "pe_ratio", window_days=30)
        assert len(result) >= 1
        assert any(r["value"] > 40 for r in result)

    def test_flat_data_no_outliers(self):
        today = date.today()
        rows = [(10.0, today - timedelta(days=i)) for i in range(100, 0, -1)]
        mock_rows = [named_row(value=v, date=d) for v, d in rows]

        detector = OutlierDetector()
        detector.db = MagicMock()
        detector.db.query.return_value.join.return_value.filter.return_value.order_by.return_value.all.return_value = mock_rows
        result = detector.detect_temporal_outliers("FLAT", "pe_ratio", window_days=30)
        assert result == []

    def test_few_data_points_returns_empty(self):
        today = date.today()
        rows = [named_row(value=10.0, date=today - timedelta(days=i * 30)) for i in range(3)]
        detector = OutlierDetector()
        detector.db = MagicMock()
        detector.db.query.return_value.join.return_value.filter.return_value.order_by.return_value.all.return_value = rows
        result = detector.detect_temporal_outliers("SHORT", "pe_ratio")
        assert result == []


# ── edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_sector_median_constant_values_no_outliers(self):
        db = MagicMock(spec=Session)
        rows_data = [
            named_row(ticker="A", value=10.0),
            named_row(ticker="B", value=10.0),
            named_row(ticker="C", value=10.0),
            named_row(ticker="D", value=10.0),
            named_row(ticker="E", value=10.0),
        ]
        subq = MagicMock()
        subq.c.ticker = "ticker"
        subq.c.value = "value"
        db.query.return_value.subquery.return_value = subq
        db.query.return_value.filter.return_value.all.return_value = rows_data
        calc = SectorMedianCalculator(db)
        result = calc.get_sector_outliers("Const", "pe_ratio", std_threshold=2.0)
        assert result == []

    def test_empty_dataframe_outliers(self):
        df = pd.DataFrame({"value": []})
        detector = OutlierDetector()
        result = detector.detect_outliers(df, "value", method="zscore")
        assert len(result) == 0
        assert "is_outlier" in result.columns

    def test_single_row_outliers(self):
        df = pd.DataFrame({"value": [42]})
        detector = OutlierDetector()
        result = detector.detect_outliers(df, "value", method="zscore")
        assert bool(result["is_outlier"].iloc[0]) is False

    def test_metric_not_in_db_returns_empty(self):
        db = MagicMock(spec=Session)
        db.query.return_value.join.return_value.filter.return_value.all.return_value = []
        calc = SectorMedianCalculator(db)
        result = calc.compute_rolling_medians("Empty", "pe_ratio")
        assert result["current_median"] is None

    def test_all_sectors_aggregates_correctly(self):
        db = MagicMock(spec=Session)
        sectors = [("A",), ("B",)]
        db.query.return_value.distinct.return_value.filter.return_value.all.return_value = sectors

        expected = {
            "A": {"sector": "A", "current_median": 10.0, "rolling_history": [], "trend": "stable"},
            "B": {"sector": "B", "current_median": 20.0, "rolling_history": [], "trend": "stable"},
        }

        with patch.object(SectorMedianCalculator, "compute_rolling_medians") as mock_crm:
            mock_crm.side_effect = [expected["A"], expected["B"]]
            calc = SectorMedianCalculator(db)
            result = calc.compute_all_sectors("pe_ratio")

        assert result == expected
        assert mock_crm.call_count == 2
        mock_crm.assert_any_call("A", "pe_ratio")
        mock_crm.assert_any_call("B", "pe_ratio")
