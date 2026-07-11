from __future__ import annotations

import warnings
from typing import Any, Optional

import numpy as np
import pandas as pd
import structlog

from src.analysis.ml._base import BaseRegressor

logger = structlog.get_logger(__name__)


class HoltWintersModel:
    def __init__(self, fitted: Any, trend_df: pd.DataFrame) -> None:
        self._fitted = fitted
        self._trend_df = trend_df

    def make_future_dataframe(self, periods: int) -> pd.DataFrame:
        last = self._trend_df["ds"].max()
        dates = pd.date_range(last + pd.Timedelta(days=1), periods=periods)
        return pd.DataFrame({"ds": dates})

    def predict(self, future_df: pd.DataFrame) -> pd.DataFrame:
        all_dates = pd.concat([self._trend_df["ds"], future_df["ds"]], ignore_index=True)
        forecast = self._fitted.forecast(len(all_dates))
        pred = forecast.values
        return pd.DataFrame(
            {
                "ds": all_dates,
                "trend": pred,
                "yhat": pred,
                "yhat_lower": pred * 0.9,
                "yhat_upper": pred * 1.1,
            }
        )


class StatsModelsTrendPredictor(BaseRegressor):
    def __init__(self, ticker: str = ""):
        super().__init__(ticker)
        self._model: Optional[Any] = None
        self._fitted_values: np.ndarray = np.array([])
        self._residual_std: float = 0.0

    @property
    def _model_prefix(self) -> str:
        return "trend"

    def train(self, df: pd.DataFrame) -> bool:
        if df.empty or len(df) < 30:
            return False
        self._model = self._fit(df)
        if self._model is not None:
            self.save(metrics={"rows": len(df), "ticker": self._ticker})
            return True
        return False

    def predict(self, df: pd.DataFrame, days_ahead: int = 10) -> dict[str, Any]:
        if df.empty or len(df) < 30:
            return {"target_price": None, "confidence": 0.0, "signal_score": 0.0}

        if self._model is None:
            try:
                self.load()
            except (ValueError, FileNotFoundError, ModuleNotFoundError, ImportError, NotImplementedError):
                logger.warning(
                    "Trend model for %s not found, auto-training (run train() first for performance)",
                    self._ticker or "default",
                )

        if self._model is not None:
            try:
                return self._predict_with_model(df, days_ahead)
            except Exception:
                logger.exception("Unhandled exception")
                logger.warning("Loaded trend model failed, retraining", exc_info=True)

        logger.info("Training trend model for %s on the fly (%d rows)", self._ticker or "default", len(df))
        self._model = self._fit(df)
        if self._model is None:
            return {"target_price": None, "confidence": 0.0, "signal_score": 0.0}
        self.save(metrics={"rows": len(df), "ticker": self._ticker})
        return self._predict_with_model(df, days_ahead)

    def _fit(self, df: pd.DataFrame) -> Any:
        trend_df = df[["date", "close"]].copy()
        trend_df.columns = ["ds", "y"]
        trend_df["ds"] = pd.to_datetime(trend_df["ds"])
        trend_df["y"] = trend_df["y"].clip(lower=0.01)

        try:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing
        except ImportError:
            logger.warning("statsmodels not installed, using linear trend fallback")
            return self._linear_fallback(trend_df)

        n = len(trend_df)
        seasonal_periods: Optional[int] = None
        if n >= 730:
            seasonal_periods = 365
        elif n >= 100:
            seasonal_periods = 7

        try:
            if seasonal_periods is not None:
                model = ExponentialSmoothing(
                    trend_df["y"],
                    trend="add",
                    seasonal="add",
                    seasonal_periods=seasonal_periods,
                    initialization_method="estimated",
                )
            else:
                model = ExponentialSmoothing(
                    trend_df["y"],
                    trend="add",
                    seasonal=None,
                    initialization_method="estimated",
                )
            fitted = model.fit()
            self._fitted_values = fitted.fittedvalues.values
            residuals = trend_df["y"].values[: len(self._fitted_values)] - self._fitted_values
            self._residual_std = float(np.std(residuals)) if len(residuals) > 0 else 0.0
            return HoltWintersModel(fitted, trend_df)
        except Exception as e:
            logger.warning("ExponentialSmoothing failed for %s: %s, falling back to linear", self._ticker or "", e)
            return self._linear_fallback(trend_df)

    def _linear_fallback(self, trend_df: pd.DataFrame) -> Any:
        x = np.arange(len(trend_df))
        y = np.log(trend_df["y"].values)
        coeffs = np.polyfit(x, y, 1)
        fitted_log = coeffs[0] * x + coeffs[1]
        self._fitted_values = np.exp(fitted_log)
        residuals = trend_df["y"].values - self._fitted_values
        self._residual_std = float(np.std(residuals)) if len(residuals) > 0 else 0.0

        class LinearTrendModel:
            def __init__(self, coeffs: np.ndarray, trend_df: pd.DataFrame) -> None:
                self._coeffs = coeffs
                self._trend_df = trend_df

            def make_future_dataframe(self, periods: int) -> pd.DataFrame:
                last = self._trend_df["ds"].max()
                dates = pd.date_range(last + pd.Timedelta(days=1), periods=periods)
                return pd.DataFrame({"ds": dates}).astype({"ds": "datetime64[ns]"})

            def predict(self, future_df: pd.DataFrame) -> pd.DataFrame:
                all_dates = pd.concat([self._trend_df["ds"], future_df["ds"]], ignore_index=True)
                x = np.arange(len(all_dates))
                log_pred = self._coeffs[0] * x + self._coeffs[1]
                pred = np.exp(log_pred)
                return pd.DataFrame(
                    {
                        "ds": all_dates,
                        "trend": pred,
                        "yhat": pred,
                        "yhat_lower": pred * 0.9,
                        "yhat_upper": pred * 1.1,
                    }
                )

        return LinearTrendModel(coeffs, trend_df)

    def _trend_slope(self, forecast: pd.DataFrame, n_days: int = 21) -> float:
        trend: np.ndarray = np.asarray(forecast["trend"].values).astype(float)
        if len(trend) < n_days:
            return 0.0
        recent = trend[-n_days:]
        x = np.arange(n_days)
        slope = np.polyfit(x, recent, 1)[0]
        mean_price = float(np.mean(recent))
        if mean_price <= 0:
            return 0.0
        normalized = np.tanh(slope / mean_price * 100)
        return round(float(normalized), 3)

    def _detect_changepoints(self) -> dict[str, Any]:
        if self._model is None:
            return {"changed": False, "magnitude": 0.0}
        try:
            if hasattr(self._model, "params") and "delta" in self._model.params:
                deltas = self._model.params["delta"]
                delta_series = pd.Series(deltas.flatten() if hasattr(deltas, "flatten") else deltas)
                if len(delta_series) > 0:
                    total_magnitude = float(delta_series.abs().sum())
                    return {"changed": total_magnitude > 0.02, "magnitude": round(total_magnitude, 4)}
        except Exception:
            logger.exception("Unhandled exception")
            pass
        return {"changed": False, "magnitude": 0.0}

    def _trend_strength(self, forecast: pd.DataFrame, trend_df: pd.DataFrame) -> float:
        try:
            hist = forecast.iloc[: len(trend_df)]
            if len(hist) < 10:
                return 0.0
            predicted: np.ndarray = np.asarray(hist["yhat"].values).astype(float)
            actual: np.ndarray = np.asarray(trend_df["y"].values[: len(hist)]).astype(float)
            residuals = actual - predicted
            ss_res = float(np.sum(residuals**2))
            ss_tot = float(np.sum((actual - np.mean(actual)) ** 2))
            if ss_tot <= 0:
                return 0.0
            r2 = max(0.0, min(1.0, 1.0 - ss_res / ss_tot))
            return round(r2, 3)
        except Exception:
            logger.exception("Unhandled exception")
            return 0.0

    def _forecast_uncertainty(self, forecast: pd.DataFrame, current_price: float) -> float:
        try:
            n = min(10, len(forecast))
            if n == 0:
                return 0.5
            future = forecast.tail(n)
            if current_price <= 0:
                return 0.5
            widths = (future["yhat_upper"] - future["yhat_lower"]) / current_price
            avg_width = float(widths.mean())
            return round(min(avg_width, 1.0), 3)
        except Exception:
            logger.exception("Unhandled exception")
            return 0.5

    def _predict_with_model(self, df: pd.DataFrame, days_ahead: int = 10) -> dict[str, Any]:
        trend_df = df[["date", "close"]].copy()
        trend_df.columns = ["ds", "y"]
        trend_df["ds"] = pd.to_datetime(trend_df["ds"])
        trend_df["y"] = trend_df["y"].clip(lower=0.01)

        future = self._model.make_future_dataframe(periods=days_ahead)
        forecast = self._model.predict(future)

        if self._residual_std > 0 and "yhat" in forecast.columns and "yhat_lower" not in forecast.columns:
            forecast["yhat_lower"] = forecast["yhat"] - 1.96 * self._residual_std
            forecast["yhat_upper"] = forecast["yhat"] + 1.96 * self._residual_std

        last_date = trend_df["ds"].max()
        future_forecast = forecast[forecast["ds"] > last_date]

        if future_forecast.empty:
            return {"target_price": None, "confidence": 0.0, "signal_score": 0.0}

        predictions = future_forecast.head(days_ahead)
        target_price = float(predictions["yhat"].iloc[-1])
        lower_bound = float(predictions["yhat_lower"].iloc[-1] if "yhat_lower" in predictions.columns else target_price * 0.95)
        upper_bound = float(predictions["yhat_upper"].iloc[-1] if "yhat_upper" in predictions.columns else target_price * 1.05)

        current_price = float(trend_df["y"].iloc[-1])
        if current_price <= 0:
            return {"target_price": None, "confidence": 0.0, "signal_score": 0.0}

        target_price = max(current_price * 0.3, target_price)

        price_change_pct = ((target_price / current_price) - 1) * 100
        uncertainty = abs(upper_bound - lower_bound) / max(current_price, 0.01)

        confidence = max(0.0, min(1.0, 1.0 - uncertainty / 0.3))

        signal_score = np.tanh(price_change_pct / 15.0)

        n_observations = len(trend_df)
        data_quality = min(1.0, n_observations / 500)
        confidence *= data_quality

        trend_slope = self._trend_slope(forecast)
        cp = self._detect_changepoints()
        trend_strength = self._trend_strength(forecast, trend_df)
        forecast_uncertainty = self._forecast_uncertainty(forecast, current_price)

        return {
            "target_price": round(target_price, 2),
            "current_price": round(current_price, 2),
            "price_change_pct": round(price_change_pct, 2),
            "confidence": round(confidence, 2),
            "signal_score": round(signal_score, 3),
            "lower_bound": round(lower_bound, 2),
            "upper_bound": round(upper_bound, 2),
            "prediction_days": days_ahead,
            "trend_slope": trend_slope,
            "trend_changed": cp["changed"],
            "changepoint_magnitude": cp["magnitude"],
            "trend_strength": trend_strength,
            "forecast_uncertainty": forecast_uncertainty,
        }


warnings.warn(
    "ProphetPredictor is deprecated, use StatsModelsTrendPredictor",
    DeprecationWarning,
    stacklevel=2,
)
ProphetPredictor = StatsModelsTrendPredictor
