import logging
from datetime import date, timedelta

import pandas as pd

logger = logging.getLogger(__name__)


class FundamentalAnalyzer:
    def analyze(self, prices: pd.DataFrame, dividends: pd.DataFrame) -> dict:
        anomalies = []
        signals = []
        risk_score = 0.0

        if prices.empty:
            return {"risk": 0.5, "anomalies": [], "signals": ["недостаточно ценовых данных"]}

        df = prices.sort_values("date").copy()
        df["close"] = pd.to_numeric(df["close"], errors="coerce")

        recent = df[df["date"] >= (date.today() - timedelta(days=365 * 3))]
        if len(recent) < 20:
            return {"risk": 0.5, "anomalies": [], "signals": ["недостаточно данных за 3 года"]}

        yearly = recent.copy()
        yearly["year"] = pd.to_datetime(yearly["date"]).dt.year
        annual = yearly.groupby("year").agg({"close": "last", "volume": "sum"}).reset_index()

        if len(annual) >= 2:
            for i in range(1, len(annual)):
                prev_close = annual.iloc[i - 1]["close"]
                curr_close = annual.iloc[i]["close"]
                if prev_close > 0:
                    growth = (curr_close - prev_close) / prev_close * 100
                    signals.append(f"годовой рост ({int(annual.iloc[i]['year'])}): {growth:+.1f}%")
                    if growth < -30:
                        anomalies.append(f"резкое падение цены в {int(annual.iloc[i]['year'])} году: {growth:.1f}%")
                        risk_score += 0.2

        if len(annual) >= 3:
            growth_rates = []
            for i in range(1, len(annual)):
                if annual.iloc[i - 1]["close"] > 0:
                    growth_rates.append((annual.iloc[i]["close"] - annual.iloc[i - 1]["close"]) / annual.iloc[i - 1]["close"] * 100)
            if len(growth_rates) >= 2 and all(g < growth_rates[0] for g in growth_rates[1:]):
                anomalies.append("темп роста замедляется 3+ года подряд")
                risk_score += 0.3

        recent_3m = df[df["date"] >= (date.today() - timedelta(days=90))]
        if len(recent_3m) > 5:
            vol = recent_3m["close"].pct_change().std() * (252 ** 0.5)
            if vol > 0.5:
                anomalies.append(f"высокая волатильность: {vol:.1%} годовых")
                risk_score += 0.15
            signals.append(f"волатильность: {vol:.1%} годовых")

        if not dividends.empty:
            div_df = dividends.copy()
            div_df["date"] = pd.to_datetime(div_df["date"])
            recent_divs = div_df[div_df["date"] >= pd.Timestamp(date.today() - timedelta(days=365 * 2))]
            if recent_divs.empty:
                anomalies.append("нет дивидендных выплат за последние 2 года")
                risk_score += 0.1
            else:
                avg_div = recent_divs["amount"].mean()
                last_price = recent["close"].iloc[-1] if not recent.empty else 0
                if last_price > 0 and avg_div > 0:
                    div_yield = (avg_div / last_price) * 100
                    signals.append(f"дивидендная доходность: {div_yield:.2f}%")

        risk_score = min(risk_score, 1.0)

        return {
            "risk": round(risk_score, 2),
            "anomalies": anomalies,
            "signals": signals,
        }
