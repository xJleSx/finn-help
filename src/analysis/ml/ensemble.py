import logging

import numpy as np
import pandas as pd

from src.analysis.ml.walk_forward import adjust_confidence_by_oos, walk_forward_validate

logger = logging.getLogger(__name__)


class EnsemblePredictor:
    def __init__(self):
        self._xgb = None
        self._lgb = None
        self._cat = None

    @property
    def xgb(self):
        if self._xgb is None:
            from src.analysis.ml.xgboost_model import XGBoostClassifier

            self._xgb = XGBoostClassifier()
        return self._xgb

    @property
    def lgb(self):
        if self._lgb is None:
            from src.analysis.ml.lightgbm_model import LightGBMClassifier

            self._lgb = LightGBMClassifier()
        return self._lgb

    @property
    def cat(self):
        if self._cat is None:
            from src.analysis.ml.catboost_model import CatBoostClassifierModel

            self._cat = CatBoostClassifierModel()
        return self._cat

    def predict(self, df: pd.DataFrame) -> dict:
        results = []
        for name, model in [("xgb", self.xgb), ("lgb", self.lgb), ("cat", self.cat)]:
            try:
                pred = model.predict(df)
                if pred.get("action") != "NEUTRAL":
                    results.append(pred)
            except Exception as e:
                logger.warning(f"Ensemble {name} failed: {e}")

        if not results:
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0}

        probs = [r.get("probability", 0.5) for r in results]
        avg_prob = float(np.mean(probs))
        confidences = [r.get("confidence", 0) for r in results]
        avg_confidence = float(np.mean(confidences))

        buy_votes = sum(1 for r in results if r["action"] == "BUY")
        sell_votes = sum(1 for r in results if r["action"] == "SELL")

        if buy_votes > sell_votes and buy_votes > len(results) // 2:
            action = "BUY"
        elif sell_votes > buy_votes and sell_votes > len(results) // 2:
            action = "SELL"
        else:
            action = "HOLD"

        signal_score = (avg_prob - 0.5) * 2

        oos = self._walk_forward_validate(df)
        final_confidence = adjust_confidence_by_oos(avg_confidence, oos)

        return {
            "action": action,
            "confidence": round(min(final_confidence, 1.0), 2),
            "signal_score": round(signal_score, 3),
            "probability": round(avg_prob, 3),
            "model_votes": {"buy": buy_votes, "sell": sell_votes, "total": len(results)},
            "xgb_action": results[0]["action"] if results else "NEUTRAL",
            "lgb_action": results[1]["action"] if len(results) > 1 else "NEUTRAL",
            "cat_action": results[2]["action"] if len(results) > 2 else "NEUTRAL",
            "walk_forward": oos,
        }

    def _walk_forward_validate(self, df: pd.DataFrame) -> dict:
        if df.empty or len(df) < 60:
            return {"oos_accuracy": 0.5, "folds_completed": 0}

        lookahead = 5
        threshold = 0.03

        needed = ["rsi", "macd_hist", "sma_20", "sma_50", "close"]
        if not all(c in df.columns for c in needed):
            return {"oos_accuracy": 0.5, "folds_completed": 0}

        features = df[needed].copy()
        features["price_sma20"] = features["close"] / features["sma_20"].replace(0, np.nan)
        features["price_sma50"] = features["close"] / features["sma_50"].replace(0, np.nan)
        features["sma20_sma50"] = features["sma_20"] / features["sma_50"].replace(0, np.nan)
        features["rsi_norm"] = features["rsi"] / 100
        features["macd_signal_binary"] = (features["macd_hist"] > 0).astype(int)
        features = features.dropna()

        if len(features) < 30:
            return {"oos_accuracy": 0.5, "folds_completed": 0}

        future_returns = df["close"].shift(-lookahead) / df["close"] - 1
        aligned = features.iloc[:-lookahead].copy()
        labels = future_returns.iloc[: len(aligned)].values

        y = np.where(labels > threshold, 1, np.where(labels < -threshold, 0, np.nan))
        mask = ~np.isnan(y)
        if mask.sum() < 30:
            return {"oos_accuracy": 0.5, "folds_completed": 0}

        x = aligned[mask].values
        y_clean = y[mask].astype(int)

        def _make_model():
            from xgboost import XGBClassifier

            return XGBClassifier(n_estimators=50, max_depth=3, learning_rate=0.1, eval_metric="logloss", verbosity=0)

        return walk_forward_validate(x, y_clean, _make_model, n_splits=3)
