from __future__ import annotations

import contextlib
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

import numpy as np
import pandas as pd

from src.analysis.ml.walk_forward import (
    baseline_accuracy,
    build_labels,
    compute_classification_metrics,
    compute_threshold,
    temporal_split,
)
from src.config import settings
from src.model_registry import load_model as load_from_registry
from src.model_registry import save_model

logger = logging.getLogger(__name__)

EVENT_FEATURE_COLS = ["event_count_30d", "event_severity_30d", "sanctions_30d", "days_since_major_event"]
MACRO_FEATURE_COLS = ["brent", "key_rate", "usd_rate", "imoex", "cpi", "ofz_10y"]
BASE_FEATURE_COLS = [
    "close",
    "rsi",
    "macd_hist",
    "sma_20",
    "sma_50",
    "price_sma20",
    "price_sma50",
    "sma20_sma50",
    "rsi_norm",
    "macd_signal_binary",
    "atr_pct",
    "volume_ratio",
    "bb_width",
    "hist_vol_20",
]


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    needed = ["rsi", "macd_hist", "sma_20", "sma_50", "close"]
    if not all(c in df.columns for c in needed):
        return pd.DataFrame()

    result = df[needed].copy()
    result["price_sma20"] = result["close"] / result["sma_20"].replace(0, np.nan)
    result["price_sma50"] = result["close"] / result["sma_50"].replace(0, np.nan)
    result["sma20_sma50"] = result["sma_20"] / result["sma_50"].replace(0, np.nan)
    result["rsi_norm"] = result["rsi"] / 100
    result["macd_signal_binary"] = (result["macd_hist"] > 0).astype(int)

    atr = df.get("atr")
    if atr is not None:
        denom = result["close"].values
        result["atr_pct"] = np.divide(atr.values, denom, out=np.full_like(atr.values, np.nan), where=denom > 0)
    else:
        result["atr_pct"] = 0.0

    vol = df.get("volume")
    vol_sma = df.get("volume_sma_20")
    if vol is not None and vol_sma is not None:
        vol_sma_safe = vol_sma.values.copy()
        vol_sma_safe[vol_sma_safe == 0] = np.nan
        result["volume_ratio"] = vol.values / vol_sma_safe
    else:
        result["volume_ratio"] = 1.0

    bb_up = df.get("bb_upper")
    bb_low = df.get("bb_lower")
    bb_mid = df.get("bb_mid")
    if bb_up is not None and bb_low is not None and bb_mid is not None:
        bb_mid_safe = bb_mid.values.copy()
        bb_mid_safe[bb_mid_safe == 0] = np.nan
        result["bb_width"] = (bb_up.values - bb_low.values) / bb_mid_safe
    else:
        result["bb_width"] = 0.0

    close_arr = df["close"].values
    returns = pd.Series(close_arr).pct_change(fill_method=None)
    hist_vol = returns.rolling(20).std()
    result["hist_vol_20"] = hist_vol.values

    for c in EVENT_FEATURE_COLS:
        result[c] = df[c].values if c in df.columns else 0
    for c in MACRO_FEATURE_COLS:
        result[c] = df[c].values if c in df.columns else 0
        chg = f"{c}_chg"
        result[chg] = df[chg].values if chg in df.columns else 0
    if "ticker_id" in df.columns:
        result["ticker_id"] = df["ticker_id"].values
    return result.dropna()


def enrich_macro(df: pd.DataFrame) -> pd.DataFrame:
    """Add macro indicators as columns (key_rate, brent, usd_rate, imoex, cpi, ofz_10y, m2).

    Queries MacroIndicator from DB for the date range of df and merges
    as forward-filled columns plus daily changes.
    """
    if df.empty or "date" not in df.columns:
        return df

    from datetime import date as dt_date

    from src.db.connection import get_session
    from src.db.models.misc import MacroIndicator

    dates = pd.to_datetime(df["date"])
    d_min = dates.min().date()
    d_max = dates.max().date()

    db = get_session()
    try:
        rows = (
            db.query(MacroIndicator)
            .filter(MacroIndicator.date.between(d_min, d_max))
            .order_by(MacroIndicator.date)
            .all()
        )
        if not rows:
            return df

        macro_dict: dict[dt_date, dict[str, float]] = {}
        for r in rows:
            macro_dict.setdefault(r.date, {})[r.indicator_type] = r.value

        macro_df = pd.DataFrame.from_dict(macro_dict, orient="index")
        macro_df.index.name = "date"
        macro_df = macro_df.reset_index()
        macro_df["date"] = pd.to_datetime(macro_df["date"])

        result = df.copy()
        result["date"] = pd.to_datetime(result["date"])
        result = result.merge(macro_df, on="date", how="left")

        macro_cols = [c for c in macro_df.columns if c != "date"]
        for col in macro_cols:
            result[col] = result[col].ffill().fillna(0)
            chg = f"{col}_chg"
            result[chg] = result[col].pct_change(fill_method=None).fillna(0)

        return result
    finally:
        db.close()


def log_shap(model: Any, x_train: np.ndarray, x_val: np.ndarray, model_name: str, feature_names: list[str]) -> None:
    try:
        import shap

        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(x_val)
        mean_abs = np.mean(np.abs(shap_values), axis=0)
        if len(mean_abs) > 0:
            top_k = min(5, len(mean_abs))
            top_idx = np.argsort(mean_abs)[-top_k:][::-1]
            parts = [f"{feature_names[i]}:{mean_abs[i]:.4f}" for i in top_idx]
            logger.info("%s — SHAP top features: %s", model_name, " ".join(parts))
    except Exception as e:
        logger.debug("SHAP unavailable: %s", e)


def log_feature_importance(model: Any, feature_names: list[str]) -> list[dict[str, Any]]:
    try:
        scores = model.feature_importances_
        indices = np.argsort(scores)[-10:][::-1]
        return [{"feature": feature_names[i], "importance": round(float(scores[i]), 4)} for i in indices]
    except Exception:
        logger.exception("Unhandled exception")
        return []


class PersistMixin:
    _model: Any = None
    _ticker: str = ""

    @property
    @abstractmethod
    def _model_prefix(self) -> str: ...

    @property
    def model_name(self) -> str:
        return f"{self._model_prefix}_{self._ticker}" if self._ticker else self._model_prefix

    def save(self, metrics: Optional[dict[str, Any]] = None, params: Optional[dict[str, Any]] = None) -> str:
        if self._model is None:
            raise ValueError("No trained model to save")
        return save_model(self._model, self.model_name, metrics=metrics, params=params)

    def load(self, version: Optional[str] = None) -> Any:
        self._model = self._post_load(load_from_registry(self.model_name, version=version))
        return self._model

    def _post_load(self, model: Any) -> Any:
        return model


class BaseMLClassifier(PersistMixin, ABC):
    def __init__(self, ticker: str = ""):
        self._model: Any = None
        self._calibrator: Any = None
        self._bootstrap_models: list[Any] = []
        self._ticker = ticker
        self._train_data_hash: int | None = None

    @property
    def _common_model_params(self) -> dict[str, Any]:
        return {
            "n_estimators": settings.ml_n_estimators,
            "max_depth": settings.ml_max_depth,
            "learning_rate": settings.ml_learning_rate,
        }

    @abstractmethod
    def _create_model(self) -> Any: ...

    def train(self, df: pd.DataFrame, anomaly_mask: np.ndarray | None = None) -> bool:
        if "date" in df.columns:
            df = enrich_macro(df)
        features = prepare_features(df)
        if features.empty or len(features) < settings.ml_min_train_rows:
            return False
        data_hash = hash(features.values.tobytes())
        if self._train_data_hash is not None and data_hash == self._train_data_hash:
            logger.debug("%s — data unchanged, skipping retrain", self.model_name)
            return True
        self._train_data_hash = data_hash
        result = self._train_on_the_fly(df, features, anomaly_mask=anomaly_mask)
        if result is None:
            return False
        model, val_metrics = result
        self._model = model
        save_metrics: dict[str, Any] = {"rows": len(features), "ticker": self._ticker}
        save_params: dict[str, Any] = {}
        if val_metrics:
            save_metrics["val_accuracy"] = val_metrics.get("accuracy", 0)
            save_metrics["val_precision"] = val_metrics.get("precision", 0)
            save_metrics["val_recall"] = val_metrics.get("recall", 0)
            save_metrics["val_f1"] = val_metrics.get("f1", 0)
        try:
            fi = log_feature_importance(model, self._feature_names())
            if fi:
                save_metrics["feature_importance"] = fi[:5]
        except Exception as e:
            logger.debug("Feature importance extraction failed: %s", e)
        if settings.ml_hpo_enabled and val_metrics:
            try:
                x_train, y_train, x_val, y_val = self._get_train_val_sets(df, features)
                if x_train is not None:
                    best_params = self.hpo(x_train, y_train, x_val, y_val, n_trials=settings.ml_hpo_trials)
                    if best_params:
                        save_params["hpo"] = best_params
                        model = self._create_model()
                        if hasattr(model, "set_params"):
                            model.set_params(**best_params)
                        model.fit(x_train, y_train)
                        self._model = model
            except Exception:
                logger.exception("Unhandled exception")
                logger.debug("HPO in train() failed, using default params", exc_info=True)
        self.save(metrics=save_metrics, params=save_params if save_params else None)
        return True

    def _model_age_seconds(self) -> float | None:
        try:
            from src.model_registry import _load_registry
            registry = _load_registry()
            name = self.model_name
            if name not in registry:
                return None
            version = registry[name].get("latest")
            if not version:
                return None
            meta = next((v for v in registry[name]["versions"] if v["version"] == version), None)
            if not meta or "created_at" not in meta:
                return None
            from datetime import datetime, timezone
            created = datetime.fromisoformat(meta["created_at"])
            return (datetime.now(timezone.utc) - created).total_seconds()
        except Exception:
            return None

    def predict(self, df: pd.DataFrame, anomaly_mask: np.ndarray | None = None) -> dict[str, Any]:
        if df.empty or len(df) < settings.ml_min_predict_rows:
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0}

        if "date" in df.columns:
            df = enrich_macro(df)
        features = prepare_features(df)
        if features.empty or len(features) < settings.ml_min_train_rows:
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0}

        model = self._model
        if model is None:
            with contextlib.suppress(ValueError, FileNotFoundError):
                model = self.load()

        if model is not None:
            age = self._model_age_seconds()
            if age is not None and age > 3600:
                logger.info("%s model age %.0fs > 3600s, rejecting stale model", self.model_name, age)
                model = None
                self._model = None

        if model is None:
            result = self._train_on_the_fly(df, features, anomaly_mask=anomaly_mask)
            if result is not None:
                model, _ = result
                if model is not None:
                    self._model = model
                    self.save(metrics={"rows": len(features), "ticker": self._ticker})

        if model is None:
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0}

        proba = float(self._predict_latest(features))

        threshold_high = settings.ml_action_threshold
        threshold_low = 1.0 - threshold_high
        if proba > threshold_high:
            action = "BUY"
            confidence = (proba - threshold_high) / threshold_low
            signal_score = proba * 2 - 1
        elif proba < threshold_low:
            action = "SELL"
            confidence = (threshold_low - proba) / threshold_low
            signal_score = proba * 2 - 1
        else:
            action = "HOLD"
            confidence = 1.0 - abs(proba - 0.5) * 10
            signal_score = 0.0

        pred_lower, pred_upper = self._bootstrap_interval(features, proba)
        bootstrap_uncertainty = round(pred_upper - pred_lower, 3) if pred_upper > pred_lower else 0.0

        return {
            "action": action,
            "confidence": round(min(confidence, 1.0), 2),
            "signal_score": round(signal_score, 3),
            "probability": round(proba, 3),
            "prediction_interval_lower": round(pred_lower, 3),
            "prediction_interval_upper": round(pred_upper, 3),
            "bootstrap_uncertainty": bootstrap_uncertainty,
        }

    def hpo(self, x_train: np.ndarray, y_train: np.ndarray, x_val: np.ndarray, y_val: np.ndarray, n_trials: int = 20) -> dict[str, Any]:
        try:
            import optuna
        except ImportError:
            logger.warning("optuna not installed, skipping HPO")
            return {}

        best_params: dict[str, Any] = {}

        def _objective(trial: optuna.Trial) -> float:
            params = {
                "n_estimators": trial.suggest_int("n_estimators", 20, 200, step=10),
                "max_depth": trial.suggest_int("max_depth", 2, 10),
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
                "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
                "subsample": trial.suggest_float("subsample", 0.6, 1.0),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            }
            model = self._create_model()
            if hasattr(model, "set_params"):
                model.set_params(**params)
            try:
                model.fit(x_train, y_train)
            except Exception:
                logger.exception("Unhandled exception")
                return 0.0
            preds = model.predict(x_val)
            acc = float(np.mean(preds == y_val))
            nonlocal best_params
            best_params = params
            return acc

        try:
            study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=42))
            study.optimize(_objective, n_trials=n_trials)
            if study.best_params:
                logger.info(
                    "%s — HPO best acc=%.3f params=%s",
                    self.model_name,
                    study.best_value,
                    study.best_params,
                )
                best_params = {**study.best_params}
        except Exception as e:
            logger.warning("%s HPO failed: %s", self.model_name, e)
            return {}

        return best_params

    def get_shap(self, x: np.ndarray) -> dict[str, float]:
        if self._model is None:
            return {}
        try:
            import shap

            explainer = shap.TreeExplainer(self._model)
            shap_values = explainer.shap_values(x)
            if isinstance(shap_values, list):
                shap_values = shap_values[1] if len(shap_values) > 1 else shap_values[0]
            mean_abs = np.mean(np.abs(shap_values), axis=0)
            feature_names = self._feature_names()
            return {feature_names[i]: round(float(mean_abs[i]), 4) for i in range(min(len(mean_abs), len(feature_names)))}
        except Exception:
            logger.exception("Unhandled exception")
            return {}

    def score(self, df: pd.DataFrame) -> float:
        features = prepare_features(df)
        if features.empty or len(features) < settings.ml_min_train_rows:
            return 0.0
        lookahead = settings.ml_lookahead
        threshold = settings.ml_threshold
        future_returns = df["close"].shift(-lookahead) / df["close"] - 1
        aligned = features.iloc[:-lookahead].copy()
        labels = np.asarray(future_returns.iloc[: len(aligned)].values).astype(float)
        y = np.where(labels > threshold, 1, np.where(labels < -threshold, 0, np.nan))
        mask = ~np.isnan(y)
        if mask.sum() < settings.ml_min_train_rows or self._model is None:
            return 0.0
        x_test = aligned[mask]
        try:
            preds = self._model.predict(x_test)
        except Exception:
            logger.exception("Unhandled exception")
            base = aligned[mask][BASE_FEATURE_COLS]
            preds = self._model.predict(base)
        y_test = y[mask].astype(int)
        return float(np.mean(preds == y_test))

    def fit(self, x_train: Any, y_train: Any) -> None:
        self._model = self._create_model()
        self._model.fit(x_train, y_train)

    def _get_train_val_sets(self, df: pd.DataFrame, features: pd.DataFrame) -> tuple[Any, Any, Any, Any]:
        lookahead = settings.ml_lookahead
        threshold = settings.ml_threshold
        y, mask = build_labels(df["close"], lookahead=lookahead, threshold=threshold)
        n = min(len(features), len(y))
        aligned = features.iloc[:n].copy()
        y = y[:n]
        mask = mask[:n]
        x_all = aligned[mask].values
        y_all = y[mask].astype(int)
        if len(x_all) < 40:
            return None, None, None, None
        splits = temporal_split(len(x_all))
        train_slice = splits["train"]
        val_slice = splits["val"]
        if val_slice.start >= val_slice.stop or val_slice.start >= len(x_all):
            return None, None, None, None
        return x_all[train_slice], y_all[train_slice], x_all[val_slice], y_all[val_slice]

    def _bootstrap_interval(self, features: pd.DataFrame, proba: float) -> tuple[float, float]:
        if not self._bootstrap_models or len(self._bootstrap_models) < 3:
            return proba, 0.0
        preds = []
        for bm in self._bootstrap_models:
            try:
                p = float(bm.predict_proba(features.iloc[-1:])[0, 1])
                preds.append(p)
            except Exception:
                logger.exception("Unhandled exception")
                continue
        if len(preds) < 3:
            return proba, 0.0
        lower = float(np.percentile(preds, 5))
        upper = float(np.percentile(preds, 95))
        return max(0.0, lower), min(1.0, upper)

    def _predict_latest(self, features: pd.DataFrame) -> float:
        latest = features.iloc[-1:]
        pred_model = self._calibrator if self._calibrator is not None else self._model
        try:
            return float(pred_model.predict_proba(latest)[0, 1])
        except Exception:
            logger.exception("Unhandled exception")
            base = features[BASE_FEATURE_COLS].iloc[-1:]
            return float(pred_model.predict_proba(base)[0, 1])

    def _train_on_the_fly(
        self,
        df: pd.DataFrame,
        features: pd.DataFrame,
        anomaly_mask: np.ndarray | None = None,
    ) -> tuple[Any, dict[str, Any] | None] | None:
        try:
            lookahead = settings.ml_lookahead
            threshold = compute_threshold(df["close"], lookahead=lookahead, fallback=settings.ml_threshold)
            y, mask = build_labels(df["close"], lookahead=lookahead, threshold=threshold)
            n = min(len(features), len(y))
            aligned = features.iloc[:n].copy()
            y = y[:n]
            mask = mask[:n]
            if anomaly_mask is not None:
                am = anomaly_mask[:n]
                mask = mask & (~am)
            x_all = aligned[mask].values
            y_all = y[mask].astype(int)

            if len(x_all) < settings.ml_min_train_rows:
                return None

            splits = temporal_split(len(x_all))
            train_slice = splits["train"]
            val_slice = splits["val"]

            x_train = x_all[train_slice]
            y_train = y_all[train_slice]

            val_metrics = None
            if len(x_train) < settings.ml_min_train_rows:
                x_train = x_all
                y_train = y_all
            else:
                x_val = x_all[val_slice]
                y_val = y_all[val_slice]

            model = self._create_model()
            model.fit(x_train, y_train)

            self._calibrator = None
            if val_slice.start < val_slice.stop and len(x_val) > 0:
                try:
                    from sklearn.calibration import CalibratedClassifierCV

                    calibrator = CalibratedClassifierCV(model, cv="prefit", method="sigmoid")
                    calibrator.fit(x_val, y_val)
                    self._calibrator = calibrator
                except Exception as e:
                    logger.debug("Calibration failed: %s", e)

            self._bootstrap_models = []
            n_bootstrap = settings.ml_bootstrap_samples
            if n_bootstrap > 0 and len(x_train) >= 40:
                rng = np.random.default_rng(42)
                for i in range(n_bootstrap):
                    idx = rng.integers(0, len(x_train), size=len(x_train))
                    bx, by = x_train[idx], y_train[idx]
                    try:
                        bm = self._create_model()
                        bm.fit(bx, by)
                        self._bootstrap_models.append(bm)
                    except Exception:
                        logger.exception("Unhandled exception")
                        continue

            if val_slice.start < val_slice.stop and len(x_val) > 0:
                preds = model.predict(x_val)
                val_metrics = compute_classification_metrics(y_val, preds)
                baseline_acc = baseline_accuracy(df["close"], y, mask, val_slice, y_val)
                logger.info(
                    "%s — val acc=%.3f prec=%.3f rec=%.3f f1=%.3f baseline=%.3f (%d samples)",
                    self.model_name,
                    val_metrics["accuracy"],
                    val_metrics["precision"],
                    val_metrics["recall"],
                    val_metrics["f1"],
                    baseline_acc,
                    len(y_val),
                )
                if baseline_acc > 0:
                    logger.info(
                        "%s — vs baseline: model=%.3f baseline=%.3f delta=%.3f",
                        self.model_name,
                        val_metrics["accuracy"],
                        baseline_acc,
                        val_metrics["accuracy"] - baseline_acc,
                    )
                log_shap(model, x_train, x_val, self.model_name, self._feature_names())

            return model, val_metrics
        except Exception as e:
            logger.warning("%s training failed: %s", self.model_name, e)
            return None

    def _feature_names(self) -> list[str]:
        macro_names = [name for c in MACRO_FEATURE_COLS for name in (c, f"{c}_chg")]
        return BASE_FEATURE_COLS + EVENT_FEATURE_COLS + macro_names


class BaseRegressor(PersistMixin, ABC):
    def __init__(self, ticker: str = ""):
        self._model: Any = None
        self._ticker = ticker

    @abstractmethod
    def train(self, *args: Any, **kwargs: Any) -> Any: ...

    @abstractmethod
    def predict(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...
