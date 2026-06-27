import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

CRASH_SCENARIOS: dict[str, dict[str, float]] = {
    "2022 (санкционный шок)": {
        "overall": -0.40,
        "Нефть и газ": -0.45,
        "Банки": -0.55,
        "Финансы": -0.35,
        "Металлы": -0.30,
        "IT": -0.25,
        "Телеком": -0.20,
        "Потреб": -0.15,
    },
    "2020 (COVID-19)": {
        "overall": -0.30,
        "Нефть и газ": -0.35,
        "Банки": -0.30,
        "Финансы": -0.25,
        "Металлы": -0.20,
        "IT": -0.15,
        "Телеком": -0.10,
        "Потреб": -0.15,
    },
    "2014 (санкции + нефть)": {
        "overall": -0.25,
        "Нефть и газ": -0.40,
        "Банки": -0.30,
        "Финансы": -0.20,
        "Металлы": -0.25,
        "IT": -0.10,
        "Телеком": -0.10,
        "Потреб": -0.15,
    },
    "2008 (мировой кризис)": {
        "overall": -0.60,
        "Нефть и газ": -0.65,
        "Банки": -0.70,
        "Финансы": -0.55,
        "Металлы": -0.50,
        "IT": -0.40,
        "Телеком": -0.35,
        "Потреб": -0.30,
    },
}

SECTOR_SHOCKS: dict[str, dict[str, float]] = {
    "Нефть по $40": {"Нефть и газ": -0.30, "overall": -0.10},
    "Ключевая ставка 25%": {"Банки": -0.20, "overall": -0.08},
    "Рубль -20%": {"Потреб": -0.15, "IT": -0.12, "overall": -0.08},
    "Геополитическая эскалация": {"overall": -0.25},
}


def format_portfolio_for_stress(plan: dict[str, Any]) -> list[dict[str, Any]]:
    positions = []
    for cat, data in plan.items():
        for item in data.get("items", []):
            positions.append(
                {
                    "ticker": item["ticker"],
                    "amount": item.get("amount", 0),
                    "last_price": item.get("last_price", 0),
                    "sector": item.get("sector", "Прочее"),
                    "name": item.get("name", ""),
                }
            )
    return positions


class StressTester:
    def __init__(self, positions: list[dict[str, Any]]) -> None:
        self.positions = positions
        self.total = sum(p.get("amount", 0) for p in positions)

    def run_crash_scenarios(self) -> list[dict[str, Any]]:
        results = []
        for name, shocks in CRASH_SCENARIOS.items():
            result = self._apply_shocks(name, shocks)
            results.append(result)
        return results

    def run_sector_shocks(self) -> list[dict[str, Any]]:
        results = []
        for name, shocks in SECTOR_SHOCKS.items():
            result = self._apply_shocks(name, shocks)
            results.append(result)
        return results

    def run_custom_shock(self, ticker: str, shock_pct: float) -> dict[str, Any] | None:
        for p in self.positions:
            if p["ticker"] == ticker:
                shocked = p["amount"] * (1 + shock_pct)
                loss = shocked - p["amount"]
                loss_pct = loss / self.total if self.total > 0 else 0
                return {
                    "scenario": f"{ticker}: {shock_pct:+.0%}",
                    "total_before": self.total,
                    "total_after": self.total + loss,
                    "loss": loss,
                    "loss_pct": loss_pct,
                    "details": [
                        {
                            "ticker": p["ticker"],
                            "sector": p.get("sector", ""),
                            "before": p["amount"],
                            "after": shocked,
                            "change_pct": shock_pct,
                        }
                    ],
                }
        return None

    def _apply_shocks(self, scenario_name: str, shocks: dict[str, float]) -> dict[str, Any]:
        overall = shocks.get("overall", 0.0)
        details = []
        total_after = 0.0
        for p in self.positions:
            sector = p.get("sector", "Прочее")
            ticker_shock = shocks.get(sector, overall)
            shocked_val = p["amount"] * (1 + ticker_shock)
            total_after += shocked_val
            details.append(
                {
                    "ticker": p["ticker"],
                    "sector": sector,
                    "before": p["amount"],
                    "after": round(shocked_val, 2),
                    "change_pct": ticker_shock,
                }
            )

        details.sort(key=lambda x: x["change_pct"])
        loss = total_after - self.total

        return {
            "scenario": scenario_name,
            "total_before": self.total,
            "total_after": round(total_after, 2),
            "loss": round(loss, 2),
            "loss_pct": loss / self.total if self.total > 0 else 0,
            "max_position_loss": details[0]["change_pct"] if details else 0,
            "details": details,
        }

    def worst_historical_period(self, price_series: list[float], window: int = 21) -> dict[str, Any]:
        arr = np.array(price_series)
        if len(arr) < window + 1:
            return {"max_drawdown": 0.0, "worst_period": "N/A"}
        max_dd = 0.0
        worst_start = 0
        for i in range(len(arr) - window + 1):
            segment = arr[i : i + window]
            peak = segment[0]
            for val in segment:
                if val > peak:
                    peak = val
                dd = (val - peak) / peak
                if dd < max_dd:
                    max_dd = dd
                    worst_start = i
        return {
            "max_drawdown": round(max_dd, 4),
            "worst_period": f"{window}-дневное окно с {worst_start}",
        }

    def format_results(self, results: list[dict[str, Any]]) -> str:
        text = ""
        for r in results:
            emoji = "🔴" if r["loss_pct"] < -0.10 else "🟡" if r["loss_pct"] < -0.05 else "🟢"
            text += (
                f"{emoji} *{r['scenario']}*\n"
                f"   Было: {r['total_before']:,.0f} ₽\n"
                f"   Стало: {r['total_after']:,.0f} ₽\n"
                f"   {r['loss']:,.0f} ₽ ({r['loss_pct']:.1%})\n"
            )
            worst = r.get("max_position_loss", 0)
            if worst < -0.3:
                text += f"   ⚠️ Сильнее всего: {r['details'][0]['ticker']} ({worst:.0%})\n"
            text += "\n"
        text += format_var_section(self.positions)
        text += format_sector_concentration(self.positions)
        return text


def format_var_section(positions: list[dict[str, Any]]) -> str:
    amounts = [p.get("amount", 0) for p in positions if p.get("amount", 0) > 0]
    if len(amounts) < 5:
        return ""

    import numpy as np

    arr = np.array(amounts)
    total = arr.sum()
    weights = arr / total if total > 0 else arr

    # simulate portfolio returns
    rng = np.random.default_rng(42)
    sim_returns = rng.normal(0, 0.02, size=(10000, len(weights)))
    port_returns = sim_returns @ weights
    port_returns.sort()

    var_95 = float(np.percentile(port_returns, 5))
    cvar_95 = float(port_returns[port_returns <= np.percentile(port_returns, 5)].mean())
    var_99 = float(np.percentile(port_returns, 1))

    text = (
        f"\n*📊 VaR / CVaR (нормальное распределение)*\n"
        f"   VaR(95%): {var_95:.1%} ({total * abs(var_95):,.0f} ₽)\n"
        f"   CVaR(95%): {cvar_95:.1%} ({total * abs(cvar_95):,.0f} ₽)\n"
        f"   VaR(99%): {var_99:.1%} ({total * abs(var_99):,.0f} ₽)\n"
    )
    return text


def format_sector_concentration(positions: list[dict[str, Any]]) -> str:
    sector_map: dict[str, float] = {}
    total = 0
    for p in positions:
        sector = p.get("sector", "Прочее")
        amt = p.get("amount", 0)
        sector_map[sector] = sector_map.get(sector, 0) + amt
        total += amt

    if not sector_map or total == 0:
        return ""

    sorted_sectors = sorted(sector_map.items(), key=lambda x: x[1], reverse=True)
    text = "\n*🏭 Концентрация по секторам*\n"
    for sector, amt in sorted_sectors:
        pct = amt / total
        bar = "█" * int(pct * 20) + "░" * (20 - int(pct * 20))
        emoji = "🔴" if pct > 0.4 else "🟡" if pct > 0.25 else "🟢"
        text += f"{emoji} {sector}: {pct:.0%} {bar}\n"

    # HHI index
    hhi = sum((amt / total) ** 2 for amt in sector_map.values())
    text += f"\n   HHI: {hhi:.3f} {'🔴 >0.3' if hhi > 0.3 else '🟢 <0.3'}\n"
    return text
