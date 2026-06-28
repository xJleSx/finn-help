from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from sqlalchemy import select

from src.analysis.stress import CRASH_SCENARIOS, SECTOR_SHOCKS
from src.db.models import Instrument, Portfolio, Price

logger = logging.getLogger(__name__)


@dataclass
class ScenarioResult:
    name: str
    total_before: float = 0.0
    total_after: float = 0.0
    loss: float = 0.0
    loss_pct: float = 0.0
    var_95: float = 0.0
    cvar_95: float = 0.0
    var_99: float = 0.0
    details: list[dict[str, Any]] = field(default_factory=list)
    sector_breakdown: dict[str, float] = field(default_factory=dict)
    scenario_type: str = "shock"


class ScenarioEngine:
    CRASH_SCENARIOS = CRASH_SCENARIOS
    SECTOR_SHOCKS = SECTOR_SHOCKS

    MACRO_SCENARIOS: dict[str, dict[str, float]] = {
        "Нефть по $40": {"Нефть и газ": -0.30, "overall": -0.10},
        "Ключевая ставка 25%": {"Банки": -0.20, "overall": -0.08},
        "Рубль -20%": {"Потреб": -0.15, "IT": -0.12, "overall": -0.08},
        "Стагфляция": {"overall": -0.20},
        "Рост рынка +15%": {"overall": 0.15},
    }

    def __init__(self) -> None:
        self.positions: list[dict[str, Any]] = []
        self._returns: dict[str, np.ndarray] = {}
        self._cov_matrix: np.ndarray | None = None
        self._tickers: list[str] = []
        self._weights: np.ndarray | None = None
        self._total: float = 0.0

    def from_portfolio(self, db: Any, user_id: int = 0) -> ScenarioEngine:
        rows = (
            db.execute(
                select(
                    Instrument.ticker, Instrument.sector,
                    Portfolio.quantity, Portfolio.avg_price,
                )
                .join(Portfolio, Portfolio.instrument_id == Instrument.id)
                .where(Portfolio.user_id == user_id)
                .where(Portfolio.quantity > 0)
            )
            .mappings()
            .all()
        )
        self.positions = []
        for r in rows:
            qty = float(r["quantity"])
            price = float(r["avg_price"] or 0.0)
            amount = qty * price
            self.positions.append({
                "ticker": r["ticker"],
                "sector": r["sector"] or "Прочее",
                "quantity": qty,
                "avg_price": price,
                "amount": amount,
            })
        self._total = sum(p["amount"] for p in self.positions)
        return self

    def from_positions(self, positions: list[dict[str, Any]]) -> ScenarioEngine:
        self.positions = []
        for p in positions:
            amount = p.get("amount", 0) or (p.get("quantity", 0) * p.get("avg_price", 0))
            self.positions.append({
                "ticker": p.get("ticker", ""),
                "sector": p.get("sector", "Прочее"),
                "quantity": float(p.get("quantity", 0)),
                "avg_price": float(p.get("avg_price", 0)),
                "amount": float(amount),
            })
        self._total = sum(p["amount"] for p in self.positions)
        return self

    def load_prices(self, db: Any, days_back: int = 365) -> ScenarioEngine:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=days_back)
        self._tickers = [p["ticker"] for p in self.positions if p["ticker"]]
        self._returns = {}

        for ticker in self._tickers:
            rows = (
                db.execute(
                    select(Price.date, Price.close)
                    .join(Instrument, Instrument.id == Price.instrument_id)
                    .where(Instrument.ticker == ticker)
                    .where(Price.date >= cutoff)
                    .where(Price.close.isnot(None))
                    .order_by(Price.date)
                )
                .all()
            )
            closes = np.array([float(r.close) for r in rows if r.close and r.close > 0], dtype=float)
            if len(closes) < 20:
                self._returns[ticker] = np.array([])
                continue
            log_ret = np.diff(np.log(closes))
            self._returns[ticker] = log_ret

        tickers_with_data = [t for t in self._tickers if len(self._returns.get(t, [])) >= 20]
        if not tickers_with_data:
            return self

        min_len = min(len(self._returns[t]) for t in tickers_with_data)
        aligned = np.column_stack([self._returns[t][-min_len:] for t in tickers_with_data])
        self._cov_matrix = np.cov(aligned, rowvar=False)

        amounts = np.array([p["amount"] for p in self.positions if p["ticker"] in tickers_with_data], dtype=float)
        total = amounts.sum()
        self._weights = amounts / total if total > 0 else np.ones(len(amounts)) / len(amounts)
        self._tickers = tickers_with_data
        return self

    def _get_sector_amounts(self) -> dict[str, float]:
        sector_map: dict[str, float] = defaultdict(float)
        for p in self.positions:
            sector_map[p["sector"]] += p["amount"]
        return dict(sector_map)

    def run_monte_carlo(self, n_simulations: int = 10000, periods: int = 252) -> ScenarioResult:
        if self._cov_matrix is None or self._weights is None:
            return ScenarioResult(
                name="Monte Carlo", total_before=self._total,
                loss_pct=0.0, scenario_type="monte_carlo",
            )
        n_assets = len(self._weights)
        mean_ret = np.zeros(n_assets)
        rng = np.random.default_rng(42)
        sim_returns = rng.multivariate_normal(mean_ret, self._cov_matrix, size=(periods, n_simulations))
        port_returns = sim_returns @ self._weights
        cumulative = np.exp(np.cumsum(port_returns, axis=0)) - 1
        final_returns = cumulative[-1, :]
        final_returns.sort()

        var_95 = float(np.percentile(final_returns, 5))
        cvar_95 = float(final_returns[final_returns <= var_95].mean()) if (final_returns <= var_95).any() else 0.0
        var_99 = float(np.percentile(final_returns, 1))
        mean_ret_val = float(np.mean(final_returns))

        total_after = self._total * (1 + mean_ret_val)
        return ScenarioResult(
            name="Monte Carlo (252 дней)",
            total_before=self._total,
            total_after=round(total_after, 2),
            loss=round(total_after - self._total, 2),
            loss_pct=mean_ret_val,
            var_95=round(var_95, 4),
            cvar_95=round(cvar_95, 4),
            var_99=round(var_99, 4),
            sector_breakdown=self._get_sector_amounts(),
            scenario_type="monte_carlo",
        )

    def run_historical_bootstrap(self, n_simulations: int = 10000, periods: int = 252) -> ScenarioResult:
        if not self._tickers:
            return ScenarioResult(
                name="Historical Bootstrap", total_before=self._total,
                loss_pct=0.0, scenario_type="bootstrap",
            )
        weights_list = []
        for p in self.positions:
            if p["ticker"] in self._tickers:
                weights_list.append(p["amount"])
        weights_arr = np.array(weights_list, dtype=float)
        weights_arr = weights_arr / weights_arr.sum()

        tickers_with_data = [t for t in self._tickers if len(self._returns.get(t, [])) >= 20]
        if not tickers_with_data:
            return ScenarioResult(
                name="Historical Bootstrap", total_before=self._total,
                loss_pct=0.0, scenario_type="bootstrap",
            )
        min_len = min(len(self._returns[t]) for t in tickers_with_data)
        aligned = np.column_stack([self._returns[t][-min_len:] for t in tickers_with_data])

        rng = np.random.default_rng(42)
        n_assets = len(tickers_with_data)
        sim_results = np.zeros(n_simulations)
        for i in range(n_simulations):
            idx = rng.integers(0, min_len, size=periods)
            sampled = aligned[idx]
            cum_ret = np.exp(np.sum(sampled, axis=0)) - 1
            sim_results[i] = float(cum_ret @ weights_arr[:n_assets])

        sim_results.sort()
        var_95 = float(np.percentile(sim_results, 5))
        cvar_95 = float(sim_results[sim_results <= var_95].mean()) if (sim_results <= var_95).any() else 0.0
        var_99 = float(np.percentile(sim_results, 1))
        mean_ret_val = float(np.mean(sim_results))

        total_after = self._total * (1 + mean_ret_val)
        return ScenarioResult(
            name="Historical Bootstrap (252 дней)",
            total_before=self._total,
            total_after=round(total_after, 2),
            loss=round(total_after - self._total, 2),
            loss_pct=mean_ret_val,
            var_95=round(var_95, 4),
            cvar_95=round(cvar_95, 4),
            var_99=round(var_99, 4),
            sector_breakdown=self._get_sector_amounts(),
            scenario_type="bootstrap",
        )

    def run_scenario(self, scenario_name: str, shocks: dict[str, float]) -> ScenarioResult:
        overall = shocks.get("overall", 0.0)
        details: list[dict[str, Any]] = []
        total_after = 0.0

        for p in self.positions:
            sector = p["sector"]
            shock = shocks.get(sector, overall)
            shocked_val = p["amount"] * (1 + shock)
            total_after += shocked_val
            details.append({
                "ticker": p["ticker"],
                "sector": sector,
                "before": round(p["amount"], 2),
                "after": round(shocked_val, 2),
                "change_pct": shock,
            })

        details.sort(key=lambda x: x["change_pct"])
        loss = total_after - self._total

        sector_after: dict[str, float] = defaultdict(float)
        for d in details:
            sector_after[d["sector"]] += d["after"]

        return ScenarioResult(
            name=scenario_name,
            total_before=round(self._total, 2),
            total_after=round(total_after, 2),
            loss=round(loss, 2),
            loss_pct=loss / self._total if self._total > 0 else 0.0,
            details=details,
            sector_breakdown=dict(sector_after),
            scenario_type="shock",
        )

    def run_crash_scenarios(self) -> list[ScenarioResult]:
        return [self.run_scenario(name, s) for name, s in self.CRASH_SCENARIOS.items()]

    def run_macro_scenarios(self) -> list[ScenarioResult]:
        return [self.run_scenario(name, s) for name, s in self.MACRO_SCENARIOS.items()]

    def run_sector_shocks(self) -> list[ScenarioResult]:
        return [self.run_scenario(name, s) for name, s in self.SECTOR_SHOCKS.items()]

    def run_custom_shock(self, ticker: str, shock_pct: float) -> ScenarioResult | None:
        for p in self.positions:
            if p["ticker"] == ticker:
                shocked = p["amount"] * (1 + shock_pct)
                loss = shocked - p["amount"]
                loss_pct = loss / self._total if self._total > 0 else 0
                total_after = self._total + loss
                return ScenarioResult(
                    name=f"{ticker}: {shock_pct:+.0%}",
                    total_before=round(self._total, 2),
                    total_after=round(total_after, 2),
                    loss=round(loss, 2),
                    loss_pct=loss_pct,
                    details=[{
                        "ticker": ticker,
                        "sector": p["sector"],
                        "before": p["amount"],
                        "after": round(shocked, 2),
                        "change_pct": shock_pct,
                    }],
                    sector_breakdown=self._get_sector_amounts(),
                    scenario_type="custom",
                )
        return None

    def run_custom_sector_shock(self, sector: str, shock_pct: float) -> ScenarioResult:
        return self.run_scenario(f"{sector}: {shock_pct:+.0%}", {sector: shock_pct})

    def run_all(self) -> dict[str, Any]:
        results: dict[str, Any] = {
            "total": self._total,
            "positions": self.positions,
            "scenarios": [],
            "monte_carlo": None,
            "bootstrap": None,
        }
        for scenario in self.run_crash_scenarios():
            results["scenarios"].append({
                "name": scenario.name,
                "loss_pct": scenario.loss_pct,
                "loss": scenario.loss,
                "total_after": scenario.total_after,
                "var_95": scenario.var_95,
            })
        for scenario in self.run_macro_scenarios():
            results["scenarios"].append({
                "name": scenario.name,
                "loss_pct": scenario.loss_pct,
                "loss": scenario.loss,
                "total_after": scenario.total_after,
            })
        mc = self.run_monte_carlo()
        results["monte_carlo"] = {
            "var_95": mc.var_95,
            "cvar_95": mc.cvar_95,
            "var_99": mc.var_99,
            "mean_return": mc.loss_pct,
        }
        bs = self.run_historical_bootstrap()
        results["bootstrap"] = {
            "var_95": bs.var_95,
            "cvar_95": bs.cvar_95,
            "var_99": bs.var_99,
            "mean_return": bs.loss_pct,
        }
        results["sector_breakdown"] = self._get_sector_amounts()
        return results

    def max_drawdown(self, db: Any, ticker: str, window: int = 252) -> dict[str, Any]:
        rows = (
            db.execute(
                select(Price.close)
                .join(Instrument, Instrument.id == Price.instrument_id)
                .where(Instrument.ticker == ticker)
                .where(Price.close.isnot(None))
                .order_by(Price.date.desc())
                .limit(window + 1)
            )
            .scalars()
            .all()
        )
        closes = np.array([float(c) for c in rows if c and c > 0], dtype=float)
        if len(closes) < 20:
            return {"ticker": ticker, "max_drawdown": 0.0}

        peak = closes[0]
        max_dd = 0.0
        for val in closes:
            if val > peak:
                peak = val
            dd = (val - peak) / peak
            if dd < max_dd:
                max_dd = dd
        return {"ticker": ticker, "max_drawdown": round(float(max_dd), 4)}
