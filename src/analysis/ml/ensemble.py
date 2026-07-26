import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

from src.analysis.ml._base import prepare_features
from src.analysis.ml.walk_forward import (
    adjust_confidence_by_oos,
    build_labels,
    model_weight_from_oos,
    temporal_split,
    walk_forward_validate,
)
from src.model_registry import load_model as load_from_registry
from src.model_registry import save_model

logger = logging.getLogger(__name__)

FEATURE_COLS = ["rsi", "macd_hist", "sma_20", "sma_50", "close"]


class EnsemblePredictor:
    def __init__(self, ticker: str = ""):
        self._xgb: Any = None
        self._lgb: Any = None
        self._cat: Any = None
        self._meta: Any = None
        self._scaler: Any = None
        self._meta_model: Any = None
        self._ticker = ticker
        self._meta_trained_at: float = 0.0
        self._meta_discarded: bool = False
        self._meta_discard_acc: float = 0.0
        self._meta_used_count: int = 0
        self._meta_skip_count: int = 0

    @property
    def model_name(self) -> str:
        return f"ensemble_{self._ticker}" if self._ticker else "ensemble"

    @property
    def xgb(self) -> Any:
        if self._xgb is None:
            from src.analysis.ml.xgboost_model import XGBoostClassifier

            self._xgb = XGBoostClassifier(ticker=self._ticker)
        return self._xgb

    @property
    def lgb(self) -> Any:
        if self._lgb is None:
            from src.analysis.ml.lightgbm_model import LightGBMClassifier

            self._lgb = LightGBMClassifier(ticker=self._ticker)
        return self._lgb

    @property
    def cat(self) -> Any:
        if self._cat is None:
            try:
                from src.analysis.ml.catboost_model import CatBoostClassifierModel

                self._cat = CatBoostClassifierModel(ticker=self._ticker)
            except ImportError:
                self._cat = None
        return self._cat

    def _build_x(self, df: pd.DataFrame) -> np.ndarray | None:
        if not all(c in df.columns for c in FEATURE_COLS):
            return None
        features = prepare_features(df)
        return features.dropna().values

    def _get_weights(self, oos_list: list[dict[str, Any]]) -> list[float]:
        weights = [model_weight_from_oos(oos) for oos in oos_list]
        total = sum(weights)
        if total > 0:
            return [w / total for w in weights]
        return [1.0 / max(len(weights), 1)] * len(weights)

    def predict(self, df: pd.DataFrame, anomaly_mask: np.ndarray | None = None) -> dict[str, Any]:
        model_names = ["xgb", "lgb", "cat"]
        models = [(name, getattr(self, name)) for name in model_names]
        named_results: dict[str, dict[str, Any]] = {}
        named_oos: dict[str, dict[str, Any]] = {}

        for name, model in models:
            if model is None:
                named_oos[name] = {"oos_accuracy": 0.5, "folds_completed": 0}
                continue
            try:
                pred = model.predict(df, anomaly_mask=anomaly_mask)
                oos = self._walk_forward_validate(df, model)
                named_oos[name] = oos
                if pred.get("action") not in (None, "NEUTRAL"):
                    pred["oos"] = oos
                    named_results[name] = pred
            except Exception as e:
                logger.warning("Ensemble %s failed: %s", name, e)
                named_oos[name] = {"oos_accuracy": 0.5, "folds_completed": 0}

        results = list(named_results.values())
        oos_list = [named_oos.get(n, {"oos_accuracy": 0.5, "folds_completed": 0}) for n in model_names]

        if not results:
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0, "uncertainty": 1.0}

        weights = self._get_weights(oos_list)
        active_models = sum(1 for w in weights if w > 0)
        if active_models == 0:
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0, "uncertainty": 1.0}

        weighted_probs = []
        weighted_confs = []
        actions = []

        for i, r in enumerate(results):
            w = weights[i] if i < len(weights) else 1.0 / len(results)
            weighted_probs.append(r.get("probability", 0.5) * w)
            weighted_confs.append(r.get("confidence", 0) * w)
            actions.append(r["action"])

        total_w = sum(weights[: len(results)])
        avg_prob = float(np.sum(weighted_probs) / total_w) if total_w > 0 else 0.5
        avg_confidence = float(np.sum(weighted_confs) / total_w) if total_w > 0 else 0.0

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
        use_meta = meta_probs is not None and not getattr(self, '_meta_discarded', False)
        if use_meta:
            avg_prob = meta_probs
            signal_score = (meta_probs - 0.5) * 2
            self._meta_used_count = getattr(self, '_meta_used_count', 0) + 1
        else:
            signal_score = (avg_prob - 0.5) * 2
            self._meta_skip_count = getattr(self, '_meta_skip_count', 0) + 1

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
            "xgb_action": named_results.get("xgb", {}).get("action", "NEUTRAL"),
            "lgb_action": named_results.get("lgb", {}).get("action", "NEUTRAL"),
            "cat_action": named_results.get("cat", {}).get("action", "NEUTRAL"),
            "walk_forward": oos_agg,
            "weights": [round(w, 3) for w in weights[: len(results)]],
        }

    def train_all(self, df: pd.DataFrame, anomaly_mask: np.ndarray | None = None) -> dict[str, bool]:
        results = {}
        for name in ("xgb", "lgb", "cat"):
            try:
                model = getattr(self, name)
                results[name] = model.train(df, anomaly_mask=anomaly_mask)
            except Exception as e:
                logger.warning("Ensemble %s training failed: %s", name, e)
                results[name] = False

        self._train_meta_oof(df, anomaly_mask=anomaly_mask)
        return results

    def save_meta(self, metrics: Optional[dict[str, Any]] = None) -> str:
        meta_data = {
            "meta": self._meta,
            "ticker": self._ticker,
            "scaler": self._scaler,
            "meta_model": self._meta_model,
        }
        return save_model(meta_data, self.model_name, metrics=metrics)

    def load_meta(self, version: Optional[str] = None) -> Any:
        data = load_from_registry(self.model_name, version=version)
        self._meta = data.get("meta")
        self._scaler = data.get("scaler")
        self._meta_model = data.get("meta_model")
        return self._meta

    def save_all(self) -> dict[str, str]:
        versions = {}
        for name in ("xgb", "lgb", "cat"):
            try:
                versions[name] = getattr(self, name).save()
            except Exception as e:
                logger.warning("Failed to save %s: %s", name, e)
        try:
            versions["meta"] = self.save_meta()
        except Exception as e:
            logger.warning("Failed to save meta: %s", e)
        return versions

    def load_all(self) -> bool:
        success = True
        for name in ("xgb", "lgb", "cat"):
            try:
                getattr(self, name).load()
            except Exception:
                logger.exception("Unhandled exception")
                success = False
        try:
            self.load_meta()
        except Exception:
            logger.exception("Unhandled exception")
            success = False
        return success

    def _stacking_predict(self, df: pd.DataFrame, base_preds: list[dict[str, Any]]) -> float | None:
        if self._scaler is None or self._meta_model is None:
            return None
        if not base_preds:
            return None
        try:
            meta_features = np.array(
                [[r.get("probability", 0.5) for r in base_preds]],
                dtype=np.float64,
            )
            scaled = self._scaler.transform(meta_features)
            return float(self._meta_model.predict_proba(scaled)[0, 1])
        except Exception as e:
            logger.warning("Stacking meta-learner predict failed: %s", e)
            return None

    def _meta_needs_retrain(self) -> bool:
        if self._meta_model is None:
            return True
        from src.config import settings

        ttl_hours = getattr(settings, "ml_meta_ttl_hours", 24)
        import time

        return (time.time() - self._meta_trained_at) > ttl_hours * 3600

    def _train_meta_oof(self, df: pd.DataFrame, anomaly_mask: np.ndarray | None = None) -> None:
        """Train meta-learner on OOF predictions from base models.

        Split data temporally, train base models on train split, collect
        OOF predictions on val split, then train a LogisticRegression meta-learner.
        Base models are retrained on full data afterward. Cached by schedule.
        """
        if not self._meta_needs_retrain():
            return
        if not all(c in df.columns for c in FEATURE_COLS):
            return
        features = prepare_features(df)
        if features.empty or len(features) < 60:
            return
        y_raw, mask = build_labels(df["close"], lookahead=5, threshold=0.03)
        n = min(len(features), len(y_raw))
        aligned = features.iloc[:n].copy()
        mask = mask[:n]
        y_raw = y_raw[:n]
        if mask.sum() < 40:
            return

        x_all = aligned[mask].values
        y_all = y_raw[mask].astype(int)

        splits = temporal_split(len(x_all))
        train_slice = splits["train"]
        val_slice = splits["val"]

        if train_slice.stop <= train_slice.start or val_slice.stop <= val_slice.start:
            return

        x_train = x_all[train_slice]
        y_train = y_all[train_slice]
        x_val = x_all[val_slice]
        y_val = y_all[val_slice]

        if len(x_train) < 30 or len(x_val) < 10:
            return

        active_models = 0
        oof_probs: list[np.ndarray] = []

        for name in ("xgb", "lgb", "cat"):
            model_obj = getattr(self, name, None)
            if model_obj is None:
                continue
            try:
                model_obj.fit(x_train, y_train)
                val_probs = model_obj._model.predict_proba(x_val)[:, 1] if hasattr(model_obj._model, "predict_proba") else np.full(len(x_val), 0.5)
                oof_probs.append(val_probs)
                active_models += 1
            except Exception as e:
                logger.debug("OOF %s failed: %s", name, e)

        if active_models < 2 or len(oof_probs) < 2:
            logger.debug("Not enough models for OOF stacking (%d active)", active_models)
            return

        if len(oof_probs) == 0 or any(len(p) == 0 for p in oof_probs):
            logger.debug("Empty OOF predictions, skipping meta-learner training")
            return

        meta_x = np.column_stack(oof_probs)

        if meta_x.size == 0 or meta_x.shape[1] < 2:
            logger.debug("OOF predictions empty or too few columns, skipping")
            return

        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.preprocessing import StandardScaler

            col_std = np.std(meta_x, axis=0)
            if np.any(col_std < 1e-10):
                logger.debug("Constant OOF predictions detected, skipping meta-learner training")
                return

            self._scaler = StandardScaler()
            meta_x_scaled = self._scaler.fit_transform(meta_x)

            self._meta_model = LogisticRegression(max_iter=2000, random_state=42, C=0.5)
            self._meta_model.fit(meta_x_scaled, y_val)

            val_acc = float(np.mean(self._meta_model.predict(meta_x_scaled) == y_val))
            if val_acc < 0.52:
                if val_acc >= 0.48:
                    logger.info(
                        "OOF meta-learner acc %.3f < 0.52 — soft fallback, using weighted avg",
                        val_acc,
                    )
                    self._meta_discarded = True
                    self._meta_discard_acc = val_acc
                else:
                    logger.warning(
                        "OOF meta-learner acc %.3f < 0.48, discarding meta-learner",
                        val_acc,
                    )
                    self._meta_discarded = True
                    self._meta_discard_acc = val_acc
                    self._scaler = None
                    self._meta_model = None
                    return

            import time

            self._meta_trained_at = time.time()
            self._meta_discarded = False
            logger.info(
                "OOF meta-learner trained: acc=%.3f, models=%d",
                val_acc,
                active_models,
            )
        except Exception as e:
            logger.warning("OOF meta-learner training failed: %s", e)
            self._scaler = None
            self._meta_model = None

    def _walk_forward_validate(self, df: pd.DataFrame, model: Any) -> dict[str, Any]:
        if df.empty or len(df) < 60:
            return {"oos_accuracy": 0.5, "folds_completed": 0}

        lookahead = 5
        threshold = 0.03
        if not all(c in df.columns for c in FEATURE_COLS):
            return {"oos_accuracy": 0.5, "folds_completed": 0}

        features = prepare_features(df)
        n = min(len(features), len(df))
        aligned = features.iloc[:n].values
        if len(aligned) < 30:
            return {"oos_accuracy": 0.5, "folds_completed": 0}

        return walk_forward_validate(model, aligned, close_series=df["close"], lookahead=lookahead, threshold=threshold, n_splits=3)
