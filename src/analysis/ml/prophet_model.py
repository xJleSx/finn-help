import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

from src.model_registry import load_model as load_from_registry
from src.model_registry import save_model

logger = logging.getLogger(__name__)


class ProphetPredictor:
    def __init__(self, ticker: str = ""):
        self._model: Optional[Any] = None
        self._ticker = ticker

    @property
    def model_name(self) -> str:
        return f"prophet_{self._ticker}" if self._ticker else "prophet"

    def save(self, metrics: Optional[dict[str, Any]] = None) -> str:
        if self._model is None:
            raise ValueError("No trained model to save")
        return save_model(self._model, self.model_name, metrics=metrics)

    def load(self, version: Optional[str] = None) -> Any:
        self._model = load_from_registry(self.model_name, version=version)
        return self._model

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
            except (ValueError, FileNotFoundError, ModuleNotFoundError, ImportError):
                logger.warning(
                    "Prophet model for %s not found, auto-training (run train() first for performance)",
                    self._ticker or "default",
                )

        if self._model is not None:
            try:
                return self._predict_with_model(df, days_ahead)
            except Exception:
                logger.warning("Loaded Prophet model failed, retraining", exc_info=True)

        logger.info("Training Prophet model for %s on the fly (%d rows)", self._ticker or "default", len(df))
        self._model = self._fit(df)
        if self._model is None:
            return {"target_price": None, "confidence": 0.0, "signal_score": 0.0}
        self.save(metrics={"rows": len(df), "ticker": self._ticker})
        return self._predict_with_model(df, days_ahead)

    def _fit(self, df: pd.DataFrame) -> Any:
        try:
            from prophet import Prophet  
        except ImportError:
            logger.warning("prophet not installed, using linear trend fallback")
            import numpy as np

            trend_df = df[["date", "close"]].copy()
            trend_df.columns = ["ds", "y"]
            trend_df["ds"] = pd.to_datetime(trend_df["ds"])
            trend_df["y"] = trend_df["y"].clip(lower=0.01)

            class LinearFallback:
                def __init__(self, trend_df: pd.DataFrame) -> None:
                    self.trend_df = trend_df
                    self.changepoints: list[Any] = []
                    self.params: dict[str, Any] = {"delta": np.array([])}
                    x = np.arange(len(trend_df))
                    y = np.log(trend_df["y"].values)
                    self._coeffs = np.polyfit(x, y, 1)

                def make_future_dataframe(self, periods: int) -> pd.DataFrame:
                    import pandas as pd

                    last = self.trend_df["ds"].max()
                    return pd.DataFrame({"ds": pd.date_range(last + pd.Timedelta(days=1), periods=periods)})

                def predict(self, future_df: pd.DataFrame) -> pd.DataFrame:
                    import pandas as pd

                    all_dates = pd.concat([self.trend_df["ds"], future_df["ds"]], ignore_index=True)
                    x = np.arange(len(all_dates))
                    log_pred = self._coeffs[0] * x + self._coeffs[1]
                    pred = np.exp(log_pred)
                    result = pd.DataFrame(
                        {
                            "ds": all_dates,
                            "trend": pred,
                            "yhat": pred,
                            "yhat_lower": pred * 0.9,
                            "yhat_upper": pred * 1.1,
                        }
                    )
                    return result

            return LinearFallback(trend_df)

        trend_df = df[["date", "close"]].copy()
        trend_df.columns = ["ds", "y"]
        trend_df["ds"] = pd.to_datetime(trend_df["ds"])
        trend_df["y"] = trend_df["y"].clip(lower=0.01)

        n = len(trend_df)
        model = Prophet(
            yearly_seasonality=n >= 730,
            weekly_seasonality=n >= 100,
            daily_seasonality=False,
            interval_width=0.80,
            changepoint_prior_scale=0.20,
        )
        model.fit(trend_df)
        return model

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
            changepoints = self._model.changepoints
            if changepoints is None or len(changepoints) == 0:
                return {"changed": False, "magnitude": 0.0}
            deltas = self._model.params["delta"]
            delta_series = pd.Series(deltas.flatten() if hasattr(deltas, "flatten") else deltas)
            if len(delta_series) == 0:
                return {"changed": False, "magnitude": 0.0}

            today = pd.Timestamp.today()
            recent_mask = (today - changepoints).dt.days.between(0, 20)
            recent_indices = recent_mask[recent_mask].index
            if len(recent_indices) == 0:
                return {"changed": False, "magnitude": 0.0}

            recent_deltas = delta_series.iloc[recent_indices]
            total_magnitude = float(recent_deltas.abs().sum())
            return {"changed": total_magnitude > 0.02, "magnitude": round(total_magnitude, 4)}
        except Exception:
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
            return 0.5

    def _predict_with_model(self, df: pd.DataFrame, days_ahead: int = 10) -> dict[str, Any]:
        trend_df = df[["date", "close"]].copy()
        trend_df.columns = ["ds", "y"]
        trend_df["ds"] = pd.to_datetime(trend_df["ds"])
        trend_df["y"] = trend_df["y"].clip(lower=0.01)

        future = self._model.make_future_dataframe(periods=days_ahead)  # type: ignore[union-attr]
        forecast = self._model.predict(future)  # type: ignore[union-attr]

        last_date = trend_df["ds"].max()
        future_forecast = forecast[forecast["ds"] > last_date]

        if future_forecast.empty:
            return {"target_price": None, "confidence": 0.0, "signal_score": 0.0}

        predictions = future_forecast.head(days_ahead)
        target_price = float(predictions["yhat"].iloc[-1])
        lower_bound = float(predictions["yhat_lower"].iloc[-1])
        upper_bound = float(predictions["yhat_upper"].iloc[-1])

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
