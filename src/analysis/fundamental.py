import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

MCAP_THRESHOLD_LOW = 1e9  # 1 млрд RUB — минимальная капитализация для blue chip
MCAP_THRESHOLD_HIGH = 100e9  # 100 млрд RUB


class FundamentalAnalyzer:
    def analyze(
        self,
        prices: pd.DataFrame,
        dividends: pd.DataFrame,
        metrics: Optional[dict] = None,
    ) -> dict:
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
                    growth_rates.append(
                        (annual.iloc[i]["close"] - annual.iloc[i - 1]["close"]) / annual.iloc[i - 1]["close"] * 100
                    )
            if len(growth_rates) >= 2 and all(
                growth_rates[i] < growth_rates[i - 1] for i in range(1, len(growth_rates))
            ):
                anomalies.append("темп роста замедляется 3+ года подряд")
                risk_score += 0.3

        recent_3m = df[df["date"] >= (date.today() - timedelta(days=90))]
        if len(recent_3m) > 5:
            vol = recent_3m["close"].pct_change().std() * (252**0.5)
            if vol > 0.5:
                anomalies.append(f"высокая волатильность: {vol:.1%} годовых")
                risk_score += 0.15
            signals.append(f"волатильность: {vol:.1%} годовых")

        recent_1m = df[df["date"] >= (date.today() - timedelta(days=30))]
        if len(recent_1m) >= 5:
            first_close = recent_1m["close"].iloc[0]
            last_close = recent_1m["close"].iloc[-1]
            if first_close > 0:
                monthly_change = (last_close - first_close) / first_close
                signals.append(f"изменение за месяц: {monthly_change:+.1%}")
                if monthly_change < -0.15:
                    anomalies.append(f"резкое падение за месяц: {monthly_change:.1%}")
                    risk_score += 0.3

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

        if metrics:
            mcap = metrics.get("market_cap")
            pe = metrics.get("pe_ratio")
            pb = metrics.get("pb_ratio")
            roe = metrics.get("roe")
            eps = metrics.get("eps")
            debt_eq = metrics.get("debt_equity")

            if mcap is not None:
                signals.append(f"капитализация: {_fmt_big(mcap)} ₽")
                if mcap < MCAP_THRESHOLD_LOW:
                    anomalies.append(f"малая капитализация ({_fmt_big(mcap)} ₽)")
                    risk_score += 0.15
                elif mcap < MCAP_THRESHOLD_HIGH:
                    signals.append("средняя капитализация")
                else:
                    signals.append("крупная капитализация (blue chip)")

            if pe is not None:
                signals.append(f"P/E: {pe:.1f}")
                if pe < 0:
                    anomalies.append("отрицательная прибыль (P/E < 0)")
                    risk_score += 0.3
                elif pe > 30:
                    anomalies.append(f"высокий P/E ({pe:.1f})")
                    risk_score += 0.1

            if pb is not None:
                signals.append(f"P/B: {pb:.1f}")
                if pb > 5:
                    anomalies.append(f"высокий P/B ({pb:.1f})")
                    risk_score += 0.1

            if roe is not None:
                signals.append(f"ROE: {roe:.1f}%")
                if roe < 5:
                    anomalies.append(f"низкая рентабельность капитала ({roe:.1f}%)")
                    risk_score += 0.15

            if debt_eq is not None:
                signals.append(f"D/E: {debt_eq:.1f}")
                if debt_eq > 2:
                    anomalies.append(f"высокая долговая нагрузка ({debt_eq:.1f})")
                    risk_score += 0.15

            if eps is not None:
                signals.append(f"EPS: {eps:.2f} ₽")

            metrics_snapshot = {
                "market_cap": mcap,
                "pe_ratio": pe,
                "pb_ratio": pb,
                "roe": roe,
                "eps": eps,
                "debt_equity": debt_eq,
            }
        else:
            metrics_snapshot = None

        risk_score = min(risk_score, 1.0)

        return {
            "risk": round(risk_score, 2),
            "anomalies": anomalies,
            "signals": signals,
            "fundamental_metrics": metrics_snapshot,
        }

    def analyze_report(self, report: dict) -> list[str]:
        """Анализ финансовой отчётности (МСФО/РСБУ) — возвращает список фактов для LLM."""
        facts = []
        period = report.get("period_type", "")
        date_str = report.get("report_date", "")

        np_val = report.get("net_profit")
        if np_val is not None:
            facts.append(f"Чистая прибыль ({period} {date_str}): {_fmt_big(np_val)} ₽")

        rev = report.get("revenue")
        if rev is not None:
            facts.append(f"Выручка: {_fmt_big(rev)} ₽")

        nii = report.get("net_interest_income")
        if nii is not None:
            facts.append(f"Чистые процентные доходы: {_fmt_big(nii)} ₽")

        assets = report.get("total_assets")
        if assets is not None:
            facts.append(f"Активы: {_fmt_big(assets)} ₽")

        liabilities = report.get("total_liabilities")
        if liabilities is not None:
            facts.append(f"Обязательства: {_fmt_big(liabilities)} ₽")

        equity = report.get("total_equity")
        if equity is not None:
            facts.append(f"Собственный капитал: {_fmt_big(equity)} ₽")

        loan = report.get("loan_portfolio")
        if loan is not None:
            facts.append(f"Кредитный портфель: {_fmt_big(loan)} ₽")

        deposits = report.get("customer_deposits")
        if deposits is not None:
            facts.append(f"Средства клиентов: {_fmt_big(deposits)} ₽")

        roe = report.get("roe")
        if roe is not None:
            facts.append(f"ROE: {roe:.1f}%")

        roa = report.get("roa")
        if roa is not None:
            facts.append(f"ROA: {roa:.1f}%")

        npl = report.get("npl_ratio")
        if npl is not None:
            facts.append(f"NPL (просрочка): {npl:.1f}%")

        adequacy = report.get("capital_adequacy")
        if adequacy is not None:
            facts.append(f"Достаточность капитала: {adequacy:.1f}%")

        cir = report.get("cost_income_ratio")
        if cir is not None:
            facts.append(f"CIR (расходы/доходы): {cir:.1f}%")

        margin = report.get("net_margin")
        if margin is not None:
            facts.append(f"Чистая процентная маржа: {margin:.1f}%")

        return facts


def _fmt_big(val: float) -> str:
    if val >= 1e12:
        return f"{val / 1e12:.2f}трлн"
    if val >= 1e9:
        return f"{val / 1e9:.2f}млрд"
    if val >= 1e6:
        return f"{val / 1e6:.2f}млн"
    return f"{val:.0f}"
