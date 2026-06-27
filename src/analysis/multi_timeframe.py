from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TIMEFRAMES = {
    "daily": 1,
    "weekly": 5,
    "monthly": 21,
}


class MultiTimeframeAnalyzer:
    def compute_all(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        result = {}
        for name, period in TIMEFRAMES.items():
            resampled = self._resample(df, period)
            if resampled is not None and len(resampled) >= 30:
                result[name] = self._compute_indicators(resampled)
        return result

    def _resample(self, df: pd.DataFrame, period_days: int) -> pd.DataFrame | None:
        if df.empty or period_days < 1:
            return df
        if period_days == 1:
            return df.sort_values("date").reset_index(drop=True)

        d = df.sort_values("date").copy()
        d["_bucket"] = np.arange(len(d)) // period_days
        agg = d.groupby("_bucket").agg(
            date=("date", "last"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        return agg.reset_index(drop=True)

    def _compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        d = df.copy()
        d["sma_20"] = d["close"].rolling(window=min(20, len(d))).mean()
        d["sma_50"] = d["close"].rolling(window=min(50, len(d))).mean()

        delta = d["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(span=14, adjust=False).mean()
        avg_loss = loss.ewm(span=14, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        d["rsi"] = 100 - (100 / (1 + rs))

        ema_12 = d["close"].ewm(span=12, adjust=False).mean()
        ema_26 = d["close"].ewm(span=26, adjust=False).mean()
        d["macd_line"] = ema_12 - ema_26
        d["macd_signal"] = d["macd_line"].ewm(span=9, adjust=False).mean()
        d["macd_hist"] = d["macd_line"] - d["macd_signal"]

        return d

    def concordance(self, tf_data: dict[str, pd.DataFrame]) -> dict[str, Any]:
        signals = {}
        for tf, df in tf_data.items():
            if df.empty or len(df) < 2:
                continue
            signals[tf] = self._tf_signal(df)

        if not signals:
            return {"agreement": 0.0, "direction": 0, "details": {}}

        directions = []
        for tf, sig in signals.items():
            directions.append(sig["direction"])

        avg_dir = np.mean(directions)
        abs_dirs = [abs(d) for d in directions]
        agreement = float(np.mean(abs_dirs)) if abs_dirs else 0.0

        return {
            "agreement": round(agreement, 3),
            "direction": round(float(avg_dir), 3),
            "details": signals,
        }

    def _tf_signal(self, df: pd.DataFrame) -> dict[str, Any]:
        if df.empty or len(df) < 2:
            return {"direction": 0, "confidence": 0.0}
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        score = 0.0
        max_score = 0.0

        if not pd.isna(latest.get("rsi")):
            max_score += 1.0
            if latest["rsi"] < 30:
                score += 1.0
            elif latest["rsi"] > 70:
                score -= 1.0

        if not pd.isna(latest.get("macd_hist")) and not pd.isna(prev.get("macd_hist")):
            max_score += 1.0
            if latest["macd_hist"] > 0 and prev["macd_hist"] <= 0:
                score += 1.0
            elif latest["macd_hist"] < 0 and prev["macd_hist"] >= 0:
                score -= 1.0

        for col in ["sma_20", "sma_50"]:
            if not pd.isna(latest.get(col)):
                max_score += 0.5
                if latest["close"] > latest[col]:
                    score += 0.5
                else:
                    score -= 0.5

        normalized = score / max_score if max_score > 0 else 0.0
        return {"direction": round(float(normalized), 3), "confidence": round(abs(normalized), 3)}
