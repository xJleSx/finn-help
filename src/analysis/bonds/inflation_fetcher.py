from __future__ import annotations

from typing import Any, Optional


def get_inflation_forecast(
    official_rate: Optional[float] = None,
    cpi_year_ago: Optional[float] = None,
    cpi_monthly: Optional[float] = None,
    source: str = "cbr",
) -> dict[str, Any]:
    if official_rate is not None and cpi_year_ago is not None:
        rolling = cpi_year_ago
        implied = cpi_monthly * 12 if cpi_monthly else None
        forecast = None
        forecast = implied if implied and implied > rolling else rolling

        if forecast is None and official_rate > 10:
            forecast = 0.07 + (official_rate - 10) * 0.03
        elif forecast is None:
            forecast = 0.06
    else:
        forecast = 0.065

    real_rate = None
    if official_rate is not None and forecast is not None:
        real_rate = official_rate - forecast

    return {
        "inflationForecast": round(forecast, 2),
        "officialCPI": round(cpi_year_ago, 1) if cpi_year_ago else None,
        "impliedCPI": round(implied, 1) if implied else None,
        "source": source,
        "keyRate": official_rate,
        "realKeyRate": round(real_rate, 2) if real_rate is not None else None,
        "method": "official_cpi" if cpi_year_ago else "rate_based_estimate",
    }
