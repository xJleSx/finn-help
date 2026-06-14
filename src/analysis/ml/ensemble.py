import logging

import numpy as np
import pandas as pd

from src.analysis.ml.catboost_model import CatBoostClassifierModel
from src.analysis.ml.lightgbm_model import LightGBMClassifier
from src.analysis.ml.xgboost_model import XGBoostClassifier

logger = logging.getLogger(__name__)


class EnsemblePredictor:
    def __init__(self):
        self.xgb = XGBoostClassifier()
        self.lgb = LightGBMClassifier()
        self.cat = CatBoostClassifierModel()

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

        return {
            "action": action,
            "confidence": round(min(avg_confidence, 1.0), 2),
            "signal_score": round(signal_score, 3),
            "probability": round(avg_prob, 3),
            "model_votes": {"buy": buy_votes, "sell": sell_votes, "total": len(results)},
            "xgb_action": results[0]["action"] if results else "NEUTRAL",
            "lgb_action": results[1]["action"] if len(results) > 1 else "NEUTRAL",
            "cat_action": results[2]["action"] if len(results) > 2 else "NEUTRAL",
        }
