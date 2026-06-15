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
        self._meta = None

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

    def _get_weights(self, oos_list: list[dict]) -> list[float]:
        weights = []
        for oos in oos_list:
            acc = oos.get("oos_accuracy", 0.5)
            folds = oos.get("folds_completed", 0)
            w = max((acc - 0.5) * 4 * min(folds / 3, 1), 0.1) if folds > 0 else 1.0
            weights.append(w)
        total = sum(weights)
        return [w / total for w in weights] if total > 0 else [1.0 / len(weights)] * len(weights)

    def predict(self, df: pd.DataFrame) -> dict:
        models = [("xgb", self.xgb), ("lgb", self.lgb), ("cat", self.cat)]
        results = []
        oos_list = []

        for name, model in models:
            try:
                pred = model.predict(df)
                oos = self._walk_forward_validate(df, model)
                oos_list.append(oos)
                if pred.get("action") != "NEUTRAL":
                    pred["oos"] = oos
                    results.append(pred)
            except Exception as e:
                logger.warning(f"Ensemble {name} failed: {e}")
                oos_list.append({"oos_accuracy": 0.5, "folds_completed": 0})

        if not results:
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0, "uncertainty": 1.0}

        weights = self._get_weights(oos_list)
        weighted_probs = []
        weighted_confs = []
        actions = []

        for i, r in enumerate(results):
            w = weights[i] if i < len(weights) else 1.0 / len(results)
            weighted_probs.append(r.get("probability", 0.5) * w)
            weighted_confs.append(r.get("confidence", 0) * w)
            actions.append(r["action"])

        avg_prob = float(np.sum(weighted_probs) / np.sum(weights[:len(results)]))
        avg_confidence = float(np.sum(weighted_confs) / np.sum(weights[:len(results)]))

        buy_votes = sum(1 for a in actions if a == "BUY")
        sell_votes = sum(1 for a in actions if a == "SELL")

        if buy_votes > sell_votes and buy_votes > len(results) // 2:
            action = "BUY"
        elif sell_votes > buy_votes and sell_votes > len(results) // 2:
            action = "SELL"
        else:
            action = "HOLD"

        probs_array = np.array([r.get("probability", 0.5) for r in results])
        uncertainty = float(np.std(probs_array)) * 2
        uncertainty = min(max(uncertainty, 0.0), 1.0)

        meta_probs = self._stacking_predict(df, results)
        if meta_probs is not None:
            avg_prob = meta_probs
            signal_score = (meta_probs - 0.5) * 2
        else:
            signal_score = (avg_prob - 0.5) * 2

        oos_agg = {
            "oos_accuracy": float(np.mean([o.get("oos_accuracy", 0.5) for o in oos_list])),
            "folds_completed": min(o.get("folds_completed", 0) for o in oos_list),
        }
        final_confidence = adjust_confidence_by_oos(avg_confidence, oos_agg)

        return {
            "action": action,
            "confidence": round(min(final_confidence, 1.0), 2),
            "signal_score": round(signal_score, 3),
            "probability": round(avg_prob, 3),
            "uncertainty": round(uncertainty, 3),
            "model_votes": {"buy": buy_votes, "sell": sell_votes, "total": len(results)},
            "xgb_action": results[0]["action"] if len(results) > 0 else "NEUTRAL",
            "lgb_action": results[1]["action"] if len(results) > 1 else "NEUTRAL",
            "cat_action": results[2]["action"] if len(results) > 2 else "NEUTRAL",
            "walk_forward": oos_agg,
            "weights": [round(w, 3) for w in weights[:len(results)]],
        }

    def _stacking_predict(self, df: pd.DataFrame, base_preds: list[dict]) -> float | None:
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.model_selection import train_test_split

            needed = ["rsi", "macd_hist", "sma_20", "sma_50", "close"]
            if not all(c in df.columns for c in needed):
                return None
            lookahead = 5
            threshold = 0.03

            features = df[needed].copy()
            features["price_sma20"] = features["close"] / features["sma_20"].replace(0, np.nan)
            features["price_sma50"] = features["close"] / features["sma_50"].replace(0, np.nan)
            features["sma20_sma50"] = features["sma_20"] / features["sma_50"].replace(0, np.nan)
            features["rsi_norm"] = features["rsi"] / 100
            features["macd_signal_binary"] = (features["macd_hist"] > 0).astype(int)
            features = features.dropna()

            if len(features) < 50:
                return None

            future_returns = df["close"].shift(-lookahead) / df["close"] - 1
            aligned = features.iloc[:-lookahead]
            labels = future_returns.iloc[: len(aligned)].values
            y = np.where(labels > threshold, 1, np.where(labels < -threshold, 0, np.nan))
            mask = ~np.isnan(y)
            if mask.sum() < 40:
                return None

            x_meta = aligned[mask].values
            y_meta = y[mask].astype(int)

            x_train, _, y_train, _ = train_test_split(x_meta, y_meta, test_size=0.2, random_state=42)
            meta_model = LogisticRegression(max_iter=500, random_state=42, C=0.5)
            meta_model.fit(x_train, y_train)
            latest = features.iloc[-1:].values
            prob = float(meta_model.predict_proba(latest)[0, 1])
            return prob
        except Exception as e:
            logger.warning(f"Stacking meta-learner failed: {e}")
            return None

    def _walk_forward_validate(self, df: pd.DataFrame, model) -> dict:
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
            try:
                import copy
                from xgboost import XGBClassifier

                return XGBClassifier(
                    n_estimators=50, max_depth=3, learning_rate=0.1, eval_metric="logloss", verbosity=0, random_state=42
                )
            except Exception:
                from sklearn.linear_model import LogisticRegression

                return LogisticRegression(max_iter=200, random_state=42)

        return walk_forward_validate(x, y_clean, _make_model, n_splits=3)
