import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class ProphetPredictor:
    def __init__(self):
        self._model: Optional = None

    def predict(self, df: pd.DataFrame, days_ahead: int = 10) -> dict:
        if df.empty or len(df) < 30:
            return {"target_price": None, "confidence": 0.0, "signal_score": 0.0}

        from prophet import Prophet

        trend_df = df[["date", "close"]].copy()
        trend_df.columns = ["ds", "y"]
        trend_df["ds"] = pd.to_datetime(trend_df["ds"])
        trend_df["y"] = trend_df["y"].clip(lower=0.01)

        model = Prophet(
            yearly_seasonality=len(trend_df) >= 200,
            weekly_seasonality=False,
            daily_seasonality=False,
            interval_width=0.80,
            changepoint_prior_scale=0.01,
        )
        model.fit(trend_df)

        future = model.make_future_dataframe(periods=days_ahead)
        forecast = model.predict(future)

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

        prediction_window = (predictions["ds"].max() - predictions["ds"].min()).days

        n_observations = len(trend_df)
        data_quality = min(1.0, n_observations / 250)
        confidence *= data_quality

        return {
            "target_price": round(target_price, 2),
            "current_price": round(current_price, 2),
            "price_change_pct": round(price_change_pct, 2),
            "confidence": round(confidence, 2),
            "signal_score": round(signal_score, 3),
            "lower_bound": round(lower_bound, 2),
            "upper_bound": round(upper_bound, 2),
            "prediction_days": days_ahead,
        }
