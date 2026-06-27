import logging
from typing import Any, TypedDict

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class _VolatilityThresholds(TypedDict):
    label: str
    threshold_atr: float
    threshold_hv: float


VOLATILITY_REGIMES: dict[str, _VolatilityThresholds] = {
    "LOW": {"label": "Низкая", "threshold_atr": 0.012, "threshold_hv": 0.15},
    "NORMAL": {"label": "Нормальная", "threshold_atr": 0.025, "threshold_hv": 0.30},
    "HIGH": {"label": "Высокая", "threshold_atr": float("inf"), "threshold_hv": float("inf")},
}


class VolatilityRegimeDetector:
    def detect(self, df: pd.DataFrame, ind_df: pd.DataFrame) -> dict[str, Any]:
        if df.empty:
            return {"regime": "NORMAL", "atr_ratio": 0.0, "hv": 0.0, "adjustment": 1.0}

        close = np.asarray(df["close"], dtype=float)
        returns = np.diff(close) / close[:-1]
        hv = float(np.std(returns) * np.sqrt(252)) if len(returns) > 1 else 0.0

        atr_ratio = 0.0
        if not ind_df.empty and "atr" in ind_df.columns:
            last_atr = ind_df["atr"].iloc[-1]
            last_close = close[-1]
            if pd.notna(last_atr) and last_close > 0:
                atr_ratio = last_atr / last_close

        regime = self._classify(atr_ratio, hv)

        adjustment = self._weight_adjustment(regime)

        return {
            "regime": regime,
            "atr_ratio": round(atr_ratio, 4),
            "hv": round(hv, 4),
            "adjustment": adjustment,
        }

    def _classify(self, atr_ratio: float, hv: float) -> str:
        low_atr: float = VOLATILITY_REGIMES["LOW"]["threshold_atr"]
        low_hv: float = VOLATILITY_REGIMES["LOW"]["threshold_hv"]
        norm_atr: float = VOLATILITY_REGIMES["NORMAL"]["threshold_atr"]
        norm_hv: float = VOLATILITY_REGIMES["NORMAL"]["threshold_hv"]
        if atr_ratio < low_atr and hv < low_hv:
            return "LOW"
        if atr_ratio < norm_atr or hv < norm_hv:
            return "NORMAL"
        return "HIGH"

    def _weight_adjustment(self, regime: str) -> dict[str, float]:
        if regime == "HIGH":
            return {
                "technical_mult": 0.7,
                "fundamental_mult": 1.3,
                "geo_mult": 1.5,
                "ml_mult": 0.6,
            }
        elif regime == "LOW":
            return {
                "technical_mult": 1.2,
                "fundamental_mult": 0.8,
                "geo_mult": 0.6,
                "ml_mult": 1.2,
            }
        return {
            "technical_mult": 1.0,
            "fundamental_mult": 1.0,
            "geo_mult": 1.0,
            "ml_mult": 1.0,
        }
