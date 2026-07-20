from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import FundamentalMetric, Instrument

_METRIC_COLUMNS: dict[str, Any] = {
    "pe_ratio": FundamentalMetric.pe_ratio,
    "pb_ratio": FundamentalMetric.pb_ratio,
    "roe": FundamentalMetric.roe,
    "eps": FundamentalMetric.eps,
    "debt_equity": FundamentalMetric.debt_equity,
    "market_cap": FundamentalMetric.market_cap,
    "book_value": FundamentalMetric.book_value,
    "revenue": FundamentalMetric.revenue,
    "net_income": FundamentalMetric.net_income,
}


class SectorMedianCalculator:
    def __init__(self, db: Session) -> None:
        self.db = db

    def compute_rolling_medians(self, sector: str, metric: str = "pe_ratio", window_months: int = 12) -> dict[str, Any]:
        column = _METRIC_COLUMNS.get(metric)
        if column is None:
            raise ValueError(f"Unknown metric '{metric}'. Available: {list(_METRIC_COLUMNS)}")

        rows = (
            self.db.query(Instrument.ticker, column.label("value"), FundamentalMetric.date)
            .join(FundamentalMetric, FundamentalMetric.instrument_id == Instrument.id)
            .filter(Instrument.sector == sector, column.isnot(None))
            .all()
        )
        if not rows:
            return {
                "sector": sector,
                "metric": metric,
                "current_median": None,
                "rolling_history": [],
                "trend": "stable",
            }

        df = pd.DataFrame(
            [{"ticker": r.ticker, "value": r.value, "date": r.date} for r in rows]
        )
        df["month"] = pd.to_datetime(df["date"]).dt.to_period("M").dt.to_timestamp()

        monthly = df.groupby("month")["value"].median().reset_index().sort_values("month")

        if len(monthly) < 2:
            current = monthly["value"].iloc[-1] if not monthly.empty else None
            return {
                "sector": sector,
                "metric": metric,
                "current_median": float(current) if current is not None else None,
                "rolling_history": [],
                "trend": "stable",
            }

        monthly["rolling"] = monthly["value"].rolling(window=window_months, min_periods=1).median()

        history = [
            {"month": str(row["month"].date()), "median": float(row["value"]), "rolling_median": float(row["rolling"])}
            for _, row in monthly.iterrows()
        ]

        current_median = float(monthly["rolling"].iloc[-1])
        trend = self._determine_trend(monthly["rolling"].dropna().values)
        return {
            "sector": sector,
            "metric": metric,
            "current_median": current_median,
            "rolling_history": history,
            "trend": trend,
        }

    def compute_all_sectors(self, metric: str = "pe_ratio") -> dict[str, dict[str, Any]]:
        sectors = [row[0] for row in self.db.query(Instrument.sector).distinct().filter(Instrument.sector.isnot(None)).all()]
        return {s: self.compute_rolling_medians(s, metric) for s in sectors}

    def get_sector_outliers(self, sector: str, metric: str = "pe_ratio", std_threshold: float = 2.0) -> list[dict[str, Any]]:
        column = _METRIC_COLUMNS.get(metric)
        if column is None:
            raise ValueError(f"Unknown metric '{metric}'")

        subq = (
            self.db.query(
                Instrument.ticker,
                column.label("value"),
                func.row_number()
                .over(partition_by=FundamentalMetric.instrument_id, order_by=FundamentalMetric.date.desc())
                .label("rn"),
            )
            .join(FundamentalMetric, FundamentalMetric.instrument_id == Instrument.id)
            .filter(Instrument.sector == sector, column.isnot(None))
            .subquery()
        )
        rows = self.db.query(subq.c.ticker, subq.c.value).filter(subq.c.rn == 1).all()

        if not rows:
            return []

        values = np.array([r.value for r in rows])
        median = float(np.median(values))
        std = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0

        if std == 0:
            return []

        outliers: list[dict[str, Any]] = []
        for r in rows:
            deviation = (r.value - median) / std
            if abs(deviation) > std_threshold:
                outliers.append({
                    "ticker": r.ticker,
                    "value": float(r.value),
                    "sector_median": median,
                    "deviation": round(float(deviation), 3),
                    "direction": "above" if deviation > 0 else "below",
                })
        return outliers

    @staticmethod
    def _determine_trend(values: np.ndarray) -> str:
        if len(values) < 3:
            return "stable"
        if np.std(values) == 0:
            return "stable"
        x = np.arange(len(values))
        slope, _, _, p_value, _ = stats.linregress(x, values)
        if np.isnan(p_value) or p_value > 0.05:
            return "stable"
        if slope > 0:
            return "up"
        return "down"


class OutlierDetector:
    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    def detect_outliers(self, df: pd.DataFrame, value_col: str, method: str = "zscore", threshold: float = 2.0) -> pd.DataFrame:
        result = df.copy()
        values = result[value_col].dropna()

        if len(values) == 0:
            result["outlier_score"] = 0.0
            result["is_outlier"] = False
            return result

        if method == "zscore":
            z = np.abs(stats.zscore(values, nan_policy="omit"))
            scores = pd.Series(index=values.index, data=z, dtype=float)
            result["outlier_score"] = scores.reindex(result.index, fill_value=0.0)
            result["is_outlier"] = result["outlier_score"] > threshold

        elif method == "iqr":
            q1 = values.quantile(0.25)
            q3 = values.quantile(0.75)
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr

            def score_fn(v: float) -> float:
                if iqr == 0:
                    return 0.0
                if v < lower:
                    return (lower - v) / iqr
                if v > upper:
                    return (v - upper) / iqr
                return 0.0

            result["outlier_score"] = result[value_col].apply(score_fn)
            result["is_outlier"] = (result[value_col] < lower) | (result[value_col] > upper)
        else:
            raise ValueError(f"Unknown method '{method}'. Use 'zscore' or 'iqr'.")

        return result

    def detect_temporal_outliers(self, ticker: str, metric: str = "pe_ratio", window_days: int = 365) -> list[dict[str, Any]]:
        column = _METRIC_COLUMNS.get(metric)
        if column is None:
            raise ValueError(f"Unknown metric '{metric}'")

        rows = (
            self.db.query(column.label("value"), FundamentalMetric.date)
            .join(Instrument, FundamentalMetric.instrument_id == Instrument.id)
            .filter(Instrument.ticker == ticker, column.isnot(None))
            .order_by(FundamentalMetric.date)
            .all()
        )
        if len(rows) < 5:
            return []

        df = pd.DataFrame([{"value": r.value, "date": r.date} for r in rows]).sort_values("date")
        df = df.set_index("date").sort_index()

        roll = df["value"].rolling(window=window_days, min_periods=3)
        df["rolling_median"] = roll.median()
        df["abs_dev"] = (df["value"] - df["rolling_median"]).abs()
        df["mad"] = df["abs_dev"].rolling(window=window_days, min_periods=3).median()

        epsilon = 1e-8
        outliers: list[dict[str, Any]] = []
        for dt_idx, row in df.iterrows():
            mad = row["mad"]
            if pd.isna(mad) or mad < epsilon:
                continue
            expected = row["rolling_median"]
            deviation = (row["value"] - expected) / max(mad, epsilon)
            if abs(deviation) > 3.0:
                outliers.append({
                    "date": str(dt_idx),
                    "value": float(row["value"]),
                    "expected": float(expected),
                    "deviation": round(float(deviation), 3),
                })
        return outliers
