import logging

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


def format_portfolio_for_stress(plan: dict) -> list[dict]:
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
    def __init__(self, positions: list[dict]):
        self.positions = positions
        self.total = sum(p.get("amount", 0) for p in positions)

    def run_crash_scenarios(self) -> list[dict]:
        results = []
        for name, shocks in CRASH_SCENARIOS.items():
            result = self._apply_shocks(name, shocks)
            results.append(result)
        return results

    def run_sector_shocks(self) -> list[dict]:
        results = []
        for name, shocks in SECTOR_SHOCKS.items():
            result = self._apply_shocks(name, shocks)
            results.append(result)
        return results

    def run_custom_shock(self, ticker: str, shock_pct: float) -> dict | None:
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

    def _apply_shocks(self, scenario_name: str, shocks: dict[str, float]) -> dict:
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

    def worst_historical_period(self, price_series: list[float], window: int = 21) -> dict:
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

    def format_results(self, results: list[dict]) -> str:
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
        return text
