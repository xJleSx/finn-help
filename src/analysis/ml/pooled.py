from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from src.analysis.ml._base import enrich_macro, prepare_features
from src.analysis.ml.walk_forward import build_labels, compute_threshold
from src.analysis.technical import TechnicalAnalyzer
from src.config import settings

logger = logging.getLogger(__name__)


def _standardize(x: np.ndarray, mean: float, std: float) -> np.ndarray:
    return np.where(std > 0, (x - mean) / std, 0)


class PooledMLClassifier:
    """Single model trained on pooled data from multiple tickers.

    Adds a ``ticker_id`` ordinal feature so the model can learn
    ticker-specific behaviour while sharing data across tickers.
    """

    _ABS_FEATURES = {"close", "sma_20", "sma_50", "macd_hist"}

    def __init__(self, base_model_factory: type, ticker: str = ""):
        self._base_factory = base_model_factory
        self._model: Any = None
        self._ticker: str = ticker
        self._ticker_map: dict[str, int] = {}
        self._feature_cols: list[str] = []

    def _get_ticker_id(self, ticker: str) -> int:
        return self._ticker_map.get(ticker, 0)

    def train_pooled(self, ticker_data: dict[str, pd.DataFrame]) -> bool:
        """Train a single model on all tickers' price data.

        Each ticker is processed independently through the technical indicator
        pipeline before concatenation to avoid cross-ticker boundary artifacts.
        """
        if not ticker_data:
            return False

        self._ticker_map = {t: i for i, t in enumerate(sorted(ticker_data))}
        tech = TechnicalAnalyzer()
        feature_parts: list[pd.DataFrame] = []
        label_parts: list[tuple[np.ndarray, np.ndarray]] = []

        for ticker, df in ticker_data.items():
            d = tech.compute_all(df.copy())
            d = enrich_macro(d)
            d["ticker_id"] = self._ticker_map[ticker]

            f = prepare_features(d)
            if f.empty:
                continue
            f = self._drop_abs(f)
            feature_parts.append(f)

            threshold = compute_threshold(d["close"], fallback=settings.ml_threshold)
            y_raw, mask = build_labels(d["close"], lookahead=settings.ml_lookahead, threshold=threshold)
            n = min(len(f), len(y_raw))
            label_parts.append((y_raw[:n], mask[:n]))

        if not feature_parts:
            return False

        all_y: list[np.ndarray] = []
        all_x: list[np.ndarray] = []
        for i, (y_raw, mask) in enumerate(label_parts):
            fp = feature_parts[i]
            n = len(fp)
            y_aligned = y_raw[:n]
            m = mask[:n]
            if m.sum() < 5:
                continue
            all_x.append(fp[m].values)
            all_y.append(y_aligned[m].astype(int))

        if not all_x:
            return False

        x_all = np.concatenate(all_x, axis=0)
        y_all = np.concatenate(all_y, axis=0)
        self._feature_cols = [c for c in feature_parts[0].columns if c != "ticker_id"]

        if len(x_all) < settings.ml_min_train_rows:
            return False

        model = self._base_factory(ticker="pooled")._create_model()
        model.fit(x_all, y_all)
        self._model = model
        logger.info(
            "Pooled %s trained on %d samples (%d tickers)",
            self._base_factory.__name__,
            len(x_all),
            len(ticker_data),
        )
        return True

    def _drop_abs(self, fp: pd.DataFrame) -> pd.DataFrame:
        return fp.drop(columns=[c for c in self._ABS_FEATURES if c in fp.columns], errors="ignore")

    def predict(self, df: pd.DataFrame) -> dict[str, Any]:
        """Predict for a single ticker using the pooled model."""
        if self._model is None or df.empty or "date" not in df.columns:
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0}

        d = df.copy()
        d["ticker_id"] = self._get_ticker_id(self._ticker)

        tech = TechnicalAnalyzer()
        d = tech.compute_all(d)
        d = enrich_macro(d)

        features = prepare_features(d)
        features = self._drop_abs(features)
        if features.empty or "ticker_id" not in features.columns:
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0}

        x = features.values

        try:
            probs = self._model.predict_proba(x)
            prob = 0.5 if probs.shape[1] < 2 else float(probs[-1, 1])
        except Exception:
            logger.debug("Pooled predict_proba failed", exc_info=True)
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0}

        confidence = abs(prob - 0.5) * 2
        signal_score = (prob - 0.5) * 2

        action_thresh = settings.ml_action_threshold
        if prob > 0.55 + action_thresh * 0.1:
            action = "BUY"
        elif prob < 0.45 - action_thresh * 0.1:
            action = "SELL"
        else:
            action = "HOLD"

        return {
            "action": action,
            "confidence": round(min(confidence, 1.0), 2),
            "signal_score": round(signal_score, 3),
            "probability": round(prob, 3),
        }
