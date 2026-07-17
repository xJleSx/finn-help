import logging
from datetime import date, timedelta
from typing import Any, Optional

import pandas as pd

from src.interfaces.response_formatter import fmt_rub

logger = logging.getLogger(__name__)

MCAP_THRESHOLD_LOW = 1e9
MCAP_THRESHOLD_HIGH = 100e9

# Median sector benchmarks for MOEX (fallback when DB data unavailable).
# Format: {sector: {metric: median_value, ...}}
# Multiples used for anomaly detection:
#   P/E >  sector_pe_median * PE_HIGH_MULTIPLE       -> high
#   ROE <  sector_roe_median * ROE_LOW_MULTIPLE       -> low
#   D/E >  sector_de_median * DE_HIGH_MULTIPLE        -> leveraged
SECTOR_BENCHMARKS: dict[str, dict[str, float]] = {
    "Финансы":          {"pe_median": 6.0,  "pb_median": 0.8,  "roe_median": 15.0, "de_median": 5.0},
    "Нефть":            {"pe_median": 5.0,  "pb_median": 1.0,  "roe_median": 18.0, "de_median": 1.5},
    "Металлы":          {"pe_median": 7.0,  "pb_median": 1.5,  "roe_median": 20.0, "de_median": 1.0},
    "IT":               {"pe_median": 25.0, "pb_median": 4.0,  "roe_median": 10.0, "de_median": 0.8},
    "Потребительский":  {"pe_median": 10.0, "pb_median": 2.0,  "roe_median": 15.0, "de_median": 1.5},
    "Телеком":          {"pe_median": 8.0,  "pb_median": 1.2,  "roe_median": 12.0, "de_median": 2.5},
    "Энергетика":       {"pe_median": 6.0,  "pb_median": 1.0,  "roe_median": 10.0, "de_median": 3.0},
    "Химия":            {"pe_median": 9.0,  "pb_median": 1.8,  "roe_median": 18.0, "de_median": 1.2},
    "Транспорт":        {"pe_median": 8.0,  "pb_median": 1.5,  "roe_median": 12.0, "de_median": 2.0},
    "Прочее":           {"pe_median": 10.0, "pb_median": 1.5,  "roe_median": 12.0, "de_median": 1.5},
}

# Deviation multipliers: how far from sector median before flagging
PE_HIGH_MULTIPLE = 3.0   # P/E > median * 3 -> anomaly
ROE_LOW_MULTIPLE = 0.3   # ROE < median * 0.3 -> anomaly
DE_HIGH_MULTIPLE = 2.0   # D/E > median * 2 -> anomaly

# Russian national credit rating scale (AKPA / Expert RA) mapped to risk score.
# Each entry: (prefix, min_length) -> risk_score contribution.
# "ruAAA" -> 0, "ruBB+" -> 0.15, "ruCCC" -> 0.30, etc.
NATIONAL_CREDIT_RATING_MAP: list[tuple[float, list[str]]] = [
    (0.00, ["ruaaa", "ruaa+"]),
    (0.05, ["ruaa", "ruaa-", "rua+"]),
    (0.10, ["rua", "rua-"]),
    (0.15, ["rubbb+", "rubbb", "rubbb-"]),
    (0.20, ["rubB+", "rubB", "rubB-"]),
    (0.25, ["rub+", "rub"]),
    (0.30, ["ruccc", "rucc", "ruc", "rud"]),
]

# International scale mapped to risk score contribution
INTERNATIONAL_RATING_MAP: list[tuple[float, list[str]]] = [
    (0.00, ["aaa", "aa+"]),
    (0.05, ["aa", "aa-", "a+"]),
    (0.10, ["a", "a-"]),
    (0.15, ["bbb+", "bbb", "bbb-"]),
    (0.20, ["bb+", "bb", "bb-"]),
    (0.25, ["b+", "b"]),
    (0.30, ["ccc", "cc", "c", "d"]),
]


def _rating_risk(rating: str | None) -> float:
    """Return risk contribution (0-0.3) from a credit rating string.

    Handles both international (S&P/Moody's) and Russian national
    (AKPA / Expert RA) formats.
    """
    if not rating:
        return 0.1
    r = rating.strip().lower().replace(" ", "")
    for risk, prefixes in NATIONAL_CREDIT_RATING_MAP + INTERNATIONAL_RATING_MAP:
        if any(r.startswith(p) for p in prefixes):
            return risk
    # Unknown format -> mild penalty
    return 0.1


def _multiplicative_risk(risks: list[float]) -> float:
    """Combine independent risk contributions multiplicatively.

    1 - prod(1 - r_i)  — each new flag increases total but never exceeds 1.0.
    Preserves differentiation even with many flags.
    """
    total = 1.0
    for r in risks:
        total *= max(0.0, 1.0 - r)
    return 1.0 - total


class FundamentalAnalyzer:
    def analyze(
        self,
        prices: pd.DataFrame,
        dividends: pd.DataFrame,
        metrics: Optional[dict[str, Any]] = None,
        sector: str = "Прочее",
    ) -> dict[str, Any]:
        anomalies = []
        signals = []
        risk_parts: list[float] = []

        if prices.empty:
            return {"risk": 0.5, "anomalies": [], "signals": ["недостаточно ценовых данных"]}

        df = prices.sort_values("date").copy()
        df["close"] = pd.to_numeric(df["close"], errors="coerce")

        recent = df[df["date"] >= (date.today() - timedelta(days=365 * 3))]
        if len(recent) < 20:
            return {"risk": 0.5, "anomalies": [], "signals": ["недостаточно данных за 3 года"]}

        bench = SECTOR_BENCHMARKS.get(sector, SECTOR_BENCHMARKS["Прочее"])

        # ── Price-based risks (sector-agnostic) ──
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
                        risk_parts.append(0.20)

        if len(annual) >= 3:
            growth_rates = []
            for i in range(1, len(annual)):
                if annual.iloc[i - 1]["close"] > 0:
                    growth_rates.append((annual.iloc[i]["close"] - annual.iloc[i - 1]["close"]) / annual.iloc[i - 1]["close"] * 100)
            if len(growth_rates) >= 2 and all(growth_rates[i] < growth_rates[i - 1] for i in range(1, len(growth_rates))):
                anomalies.append("темп роста замедляется 3+ года подряд")
                risk_parts.append(0.25)

        recent_3m = df[df["date"] >= (date.today() - timedelta(days=90))]
        if len(recent_3m) > 5:
            vol = recent_3m["close"].pct_change().std() * (252**0.5)
            if vol > 0.5:
                anomalies.append(f"высокая волатильность: {vol:.1%} годовых")
                risk_parts.append(0.15)
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
                    risk_parts.append(0.25)

        # ── Dividend check ──
        if not dividends.empty:
            div_df = dividends.copy()
            div_df["date"] = pd.to_datetime(div_df["date"])
            recent_divs = div_df[div_df["date"] >= pd.Timestamp(date.today() - timedelta(days=365 * 2))]
            if recent_divs.empty:
                anomalies.append("нет дивидендных выплат за последние 2 года")
                risk_parts.append(0.10)
            else:
                avg_div = recent_divs["amount"].mean()
                last_price = recent["close"].iloc[-1] if not recent.empty else 0
                if last_price > 0 and avg_div > 0:
                    div_yield = (avg_div / last_price) * 100
                    signals.append(f"дивидендная доходность: {div_yield:.2f}%")

        # ── Fundamental metrics, sector-normalised ──
        if metrics:
            mcap = metrics.get("market_cap")
            pe = metrics.get("pe_ratio")
            pb = metrics.get("pb_ratio")
            roe = metrics.get("roe")
            eps = metrics.get("eps")
            debt_eq = metrics.get("debt_equity")

            if mcap is not None:
                signals.append(f"капитализация: {fmt_rub(mcap)}")
                if mcap < MCAP_THRESHOLD_LOW:
                    anomalies.append(f"малая капитализация ({fmt_rub(mcap)})")
                    risk_parts.append(0.15)
                elif mcap < MCAP_THRESHOLD_HIGH:
                    signals.append("средняя капитализация")
                else:
                    signals.append("крупная капитализация (blue chip)")

            if pe is not None:
                pe_threshold = bench["pe_median"] * PE_HIGH_MULTIPLE
                pe_str = f"P/E: {pe:.1f}"
                if bench["pe_median"] > 0:
                    pe_diff = (pe / bench["pe_median"] - 1) * 100
                    pe_str += f" (сектор: {bench['pe_median']:.0f}, отклонение: {pe_diff:+.0f}%)"
                signals.append(pe_str)
                if pe < 0:
                    anomalies.append(f"отрицательная прибыль (P/E={pe:.1f})")
                    risk_parts.append(0.25)
                elif pe > pe_threshold:
                    anomalies.append(f"P/E={pe:.1f} выше секторального порога ({pe_threshold:.0f})")
                    risk_parts.append(0.12)

            if pb is not None:
                pb_str = f"P/B: {pb:.1f}"
                if bench["pb_median"] > 0:
                    pb_diff = (pb / bench["pb_median"] - 1) * 100
                    pb_str += f" (сектор: {bench['pb_median']:.1f}, отклонение: {pb_diff:+.0f}%)"
                signals.append(pb_str)
                if pb > bench["pb_median"] * 3:
                    anomalies.append(f"высокий P/B ({pb:.1f}) vs сектор ({bench['pb_median']:.1f})")
                    risk_parts.append(0.10)

            if roe is not None:
                roe_threshold = max(1.0, bench["roe_median"] * ROE_LOW_MULTIPLE)
                signals.append(f"ROE: {roe:.1f}% (сектор: {bench['roe_median']:.0f}%)")
                if roe < roe_threshold:
                    anomalies.append(f"ROE={roe:.1f}% ниже секторального порога ({roe_threshold:.1f}%)")
                    risk_parts.append(0.15)

            if debt_eq is not None:
                de_threshold = max(0.5, bench["de_median"] * DE_HIGH_MULTIPLE)
                signals.append(f"D/E: {debt_eq:.1f} (сектор: {bench['de_median']:.1f})")
                if debt_eq > de_threshold:
                    anomalies.append(f"D/E={debt_eq:.1f} выше секторального порога ({de_threshold:.1f})")
                    risk_parts.append(0.12)

            if eps is not None:
                signals.append(f"EPS: {eps:.2f} ₽")

        risk_score = _multiplicative_risk(risk_parts)

        return {
            "risk": round(risk_score, 2),
            "anomalies": anomalies,
            "signals": signals,
        }

    def analyze_bond(self, bond_offering: dict[str, Any] | None, key_rate: float | None = None) -> dict[str, Any]:
        if not bond_offering:
            return {"risk": 0.5, "anomalies": [], "signals": ["Нет данных об облигации"]}

        anomalies: list[str] = []
        signals: list[str] = []
        risk_parts: list[float] = []

        ytm = bond_offering.get("yield_to_maturity")
        credit_rating = bond_offering.get("credit_rating")
        duration = bond_offering.get("duration_years")

        if ytm is not None:
            if key_rate is not None and key_rate > 0:
                spread = ytm - key_rate
                if spread > 5:
                    anomalies.append(f"Аномально высокий спред к ключевой ставке: {spread:.1f}%")
                    risk_parts.append(0.25)
                elif spread > 3:
                    signals.append(f"Спред к ключевой ставке: {spread:+.1f}%")
                    risk_parts.append(0.10)
                elif spread < -2:
                    anomalies.append(f"Отрицательный спред к ключевой ставке: {spread:.1f}%")
                    risk_parts.append(0.05)
                else:
                    signals.append(f"Спред к ключевой ставке в норме: {spread:+.1f}%")

                # YTM risk measured via spread, not absolute value
                if spread > 10:
                    anomalies.append(f"Экстремальный спред {spread:.1f}% — возможен дефолт")
                    risk_parts.append(0.30)
            else:
                # No key_rate: fallback to absolute YTM (less precise)
                if ytm > 25:
                    anomalies.append(f"Чрезмерная доходность {ytm:.1f}% — возможен дефолт")
                    risk_parts.append(0.30)
                elif ytm > 15:
                    signals.append(f"Высокая доходность: {ytm:.1f}%")
                    risk_parts.append(0.10)

        if duration is not None:
            if duration > 10:
                anomalies.append(f"Экстремальная дюрация: {duration:.1f} лет")
                risk_parts.append(0.20)
            elif duration > 5:
                signals.append(f"Длинная дюрация: {duration:.1f} лет — чувствительность к ставкам")
                risk_parts.append(0.10)

        rating_risk = _rating_risk(credit_rating)
        if rating_risk >= 0.15:
            anomalies.append(f"Низкий кредитный рейтинг: {credit_rating}")
        if rating_risk > 0:
            risk_parts.append(rating_risk)

        risk_score = _multiplicative_risk(risk_parts)

        return {
            "risk": round(risk_score, 2),
            "anomalies": anomalies,
            "signals": signals,
        }

    def analyze_report(self, report: dict[str, Any]) -> list[str]:
        from src.interfaces.response_formatter import format_financial_facts

        return format_financial_facts(report)
