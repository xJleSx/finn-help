import logging

import lightgbm as lgb
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class LightGBMClassifier:
    def predict(self, df: pd.DataFrame) -> dict:
        if df.empty or len(df) < 60:
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0}

        features = self._prepare_features(df)
        if features.empty or len(features) < 30:
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0}

        model = self._train_on_the_fly(df, features)
        if model is None:
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0}

        latest = features.iloc[-1:].values
        proba = model.predict_proba(latest)[0, 1]

        if proba > 0.55:
            action = "BUY"
            confidence = (proba - 0.55) / 0.45
            signal_score = proba * 2 - 1
        elif proba < 0.45:
            action = "SELL"
            confidence = (0.45 - proba) / 0.45
            signal_score = proba * 2 - 1
        else:
            action = "HOLD"
            confidence = 1.0 - abs(proba - 0.5) * 10
            signal_score = 0.0

        return {
            "action": action,
            "confidence": round(min(confidence, 1.0), 2),
            "signal_score": round(signal_score, 3),
            "probability": round(proba, 3),
        }

    def _prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        needed = ["rsi", "macd_hist", "sma_20", "sma_50", "close"]
        if not all(c in df.columns for c in needed):
            return pd.DataFrame()

        result = df[needed].copy()
        result["price_sma20"] = result["close"] / result["sma_20"].replace(0, np.nan)
        result["price_sma50"] = result["close"] / result["sma_50"].replace(0, np.nan)
        result["sma20_sma50"] = result["sma_20"] / result["sma_50"].replace(0, np.nan)
        result["rsi_norm"] = result["rsi"] / 100
        result["macd_signal_binary"] = (result["macd_hist"] > 0).astype(int)
        result = result.dropna()
        return result

    def _train_on_the_fly(self, df: pd.DataFrame, features: pd.DataFrame):
        try:
            lookahead = 5
            threshold = 0.03
            future_returns = df["close"].shift(-lookahead) / df["close"] - 1
            aligned = features.iloc[:-lookahead].copy()
            labels = future_returns.iloc[: len(aligned)].values
            y = np.where(labels > threshold, 1, np.where(labels < -threshold, 0, np.nan))
            mask = ~np.isnan(y)
            if mask.sum() < 30:
                return None

            x_train = aligned[mask].values
            y_train = y[mask].astype(int)

            model = lgb.LGBMClassifier(
                n_estimators=50,
                max_depth=3,
                learning_rate=0.1,
                verbosity=-1,
                deterministic=True,
            )
            model.fit(x_train, y_train)
            return model
        except Exception as e:
            logger.warning(f"LightGBM training failed: {e}")
            return None
