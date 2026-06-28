from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from sqlalchemy import select

from src.analysis.scenario.engine import ScenarioEngine
from src.db.models import Instrument, News, NewsInstrument, Portfolio, Prediction, Price

logger = logging.getLogger(__name__)


class RiskExplorer:
    def __init__(self) -> None:
        pass

    def _get_positions(self, db: Any, user_id: int) -> list[dict[str, Any]]:
        rows = (
            db.execute(
                select(
                    Instrument.ticker,
                    Instrument.sector,
                    Portfolio.quantity,
                    Portfolio.avg_price,
                )
                .join(Portfolio, Portfolio.instrument_id == Instrument.id)
                .where(Portfolio.user_id == user_id)
                .where(Portfolio.quantity > 0)
            )
            .mappings()
            .all()
        )
        positions = []
        for r in rows:
            qty = float(r["quantity"])
            price = float(r["avg_price"] or 0.0)
            amount = qty * price
            positions.append({
                "ticker": r["ticker"],
                "sector": r["sector"] or "Прочее",
                "amount": amount,
            })
        return positions

    def _portfolio_value_series(
        self, db: Any, positions: list[dict[str, Any]], days: int
    ) -> np.ndarray | None:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
        tickers = [p["ticker"] for p in positions if p["ticker"]]
        weights = np.array([p["amount"] for p in positions if p["ticker"]], dtype=float)
        total = weights.sum()
        if total == 0:
            return None
        weights = weights / total

        series: dict[str, np.ndarray] = {}
        for ticker in tickers:
            rows = (
                db.execute(
                    select(Price.close)
                    .join(Instrument, Instrument.id == Price.instrument_id)
                    .where(Instrument.ticker == ticker)
                    .where(Price.date >= cutoff)
                    .where(Price.close.isnot(None))
                    .order_by(Price.date)
                )
                .scalars()
                .all()
            )
            closes = np.array([float(c) for c in rows if c and c > 0], dtype=float)
            if len(closes) >= 20:
                series[ticker] = closes

        if not series:
            return None

        min_len = min(len(v) for v in series.values())
        available = [t for t in tickers if t in series]
        w = np.array([weights[i] for i, t in enumerate(tickers) if t in series], dtype=float)
        w = w / w.sum()
        aligned = np.column_stack([series[t][-min_len:] / series[t][-min_len] for t in available])
        return aligned @ w

    def _recent_anomaly_count(self, db: Any, days: int = 7) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = db.execute(
            select(News.id)
            .where(News.published_at >= cutoff)
            .where(News.impact_score >= 0.7)
        )
        return len(result.all())

    def portfolio_risk_summary(self, db: Any, user_id: int = 0) -> dict[str, Any]:
        positions = self._get_positions(db, user_id)
        if not positions:
            return {
                "sector_concentration": {"hhi": 0.0, "top_sectors": []},
                "position_concentration": {"top_ticker_pct": 0.0},
                "VaR_95": 0.0,
                "CVaR_95": 0.0,
                "correlation_matrix": [],
                "max_drawdown_90d": 0.0,
                "max_drawdown_1y": 0.0,
                "anomaly_count": 0,
            }

        total = sum(p["amount"] for p in positions)

        sector_map: dict[str, float] = defaultdict(float)
        for p in positions:
            sector_map[p["sector"]] += p["amount"]

        hhi = sum((amt / total) ** 2 for amt in sector_map.values())
        top_sectors = sorted(sector_map.items(), key=lambda x: x[1], reverse=True)[:5]
        top_sectors = [{"sector": s, "weight": round(amt / total, 4)} for s, amt in top_sectors]

        top_tickers = sorted(positions, key=lambda x: x["amount"], reverse=True)
        top_ticker_pct = round(top_tickers[0]["amount"] / total, 4) if top_tickers else 0.0

        engine = ScenarioEngine()
        engine.from_positions(positions)
        engine.load_prices(db, 365)

        var_95 = 0.0
        cvar_95 = 0.0
        if engine._cov_matrix is not None and engine._weights is not None:
            mc = engine.run_monte_carlo(n_simulations=10000, periods=252)
            var_95 = mc.var_95
            cvar_95 = mc.cvar_95

        corr_pairs: list[dict[str, Any]] = []
        if engine._cov_matrix is not None and len(engine._tickers) > 1:
            cov = engine._cov_matrix
            d = np.sqrt(np.diag(cov))
            if (d > 0).all():
                corr = cov / np.outer(d, d)
                tickers = engine._tickers
                pairs = []
                for i in range(len(tickers)):
                    for j in range(i + 1, len(tickers)):
                        pairs.append((tickers[i], tickers[j], float(corr[i, j])))
                pairs.sort(key=lambda x: abs(x[2]), reverse=True)
                corr_pairs = [
                    {"ticker_a": a, "ticker_b": b, "correlation": round(c, 4)}
                    for a, b, c in pairs[:10]
                ]

        port_val_90d = self._portfolio_value_series(db, positions, 90)
        port_val_1y = self._portfolio_value_series(db, positions, 365)

        def compute_max_dd(series: np.ndarray | None) -> float:
            if series is None or len(series) < 20:
                return 0.0
            peak = series[0]
            max_dd = 0.0
            for val in series:
                if val > peak:
                    peak = val
                dd = (val - peak) / peak
                if dd < max_dd:
                    max_dd = dd
            return float(max_dd)

        max_drawdown_90d = compute_max_dd(port_val_90d)
        max_drawdown_1y = compute_max_dd(port_val_1y)
        anomaly_count = self._recent_anomaly_count(db)

        return {
            "sector_concentration": {
                "hhi": round(hhi, 4),
                "top_sectors": top_sectors,
            },
            "position_concentration": {
                "top_ticker_pct": top_ticker_pct,
            },
            "VaR_95": var_95,
            "CVaR_95": cvar_95,
            "correlation_matrix": corr_pairs,
            "max_drawdown_90d": round(max_drawdown_90d, 4),
            "max_drawdown_1y": round(max_drawdown_1y, 4),
            "anomaly_count": anomaly_count,
        }

    def ticker_deep_dive(self, db: Any, ticker: str) -> dict[str, Any]:
        rows = (
            db.execute(
                select(Price.close)
                .join(Instrument, Instrument.id == Price.instrument_id)
                .where(Instrument.ticker == ticker)
                .where(Price.close.isnot(None))
                .order_by(Price.date)
            )
            .scalars()
            .all()
        )
        closes = np.array([float(c) for c in rows if c and c > 0], dtype=float)

        price_stats: dict[str, Any] = {"volatility": 0.0, "avg_return": 0.0, "sharpe": None}
        if len(closes) >= 20:
            log_ret = np.diff(np.log(closes))
            vol = float(np.std(log_ret, ddof=1))
            avg_ret = float(np.mean(log_ret))
            sharpe = round(avg_ret / vol * np.sqrt(252), 4) if vol > 0 else None
            price_stats = {
                "volatility": round(vol, 4),
                "avg_return": round(avg_ret, 4),
                "sharpe": sharpe,
            }

        instr = db.execute(
            select(Instrument.id).where(Instrument.ticker == ticker)
        ).scalar_one_or_none()

        corr_to_portfolio: dict[str, Any] | None = None
        if instr is not None:
            in_portfolio = db.execute(
                select(Portfolio.id)
                .where(Portfolio.instrument_id == instr)
                .where(Portfolio.quantity > 0)
            ).first()
            if in_portfolio is not None:
                positions = self._get_positions(db, 0)
                portfolio_engine = ScenarioEngine()
                portfolio_engine.from_positions(positions)
                portfolio_engine.load_prices(db, 365)

                if ticker in portfolio_engine._returns and len(portfolio_engine._returns[ticker]) >= 20:
                    ticker_ret = portfolio_engine._returns[ticker]
                    if portfolio_engine._weights is not None and len(portfolio_engine._tickers) > 1:
                        port_ret = np.sum(
                            [
                                portfolio_engine._returns[t] * w
                                for t, w in zip(portfolio_engine._tickers, portfolio_engine._weights)
                                if len(portfolio_engine._returns.get(t, [])) >= 20
                            ],
                            axis=0,
                        )
                        if len(ticker_ret) > 0 and len(port_ret) > 0:
                            min_len = min(len(ticker_ret), len(port_ret))
                            c = float(np.corrcoef(ticker_ret[-min_len:], port_ret[-min_len:])[0, 1])
                            corr_to_portfolio = {"correlation": round(c, 4)}

        recent_anomalies: list[dict[str, Any]] = []
        if instr is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            anomaly_rows = (
                db.execute(
                    select(News.id, News.title, News.impact_score, News.published_at)
                    .join(NewsInstrument, NewsInstrument.news_id == News.id)
                    .where(NewsInstrument.instrument_id == instr)
                    .where(News.published_at >= cutoff)
                    .where(News.impact_score >= 0.7)
                    .order_by(News.impact_score.desc())
                    .limit(10)
                )
                .mappings()
                .all()
            )
            recent_anomalies = [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "impact_score": r["impact_score"],
                    "published_at": r["published_at"].isoformat() if r["published_at"] else None,
                }
                for r in anomaly_rows
            ]

        recent_impact_predictions: list[dict[str, Any]] = []
        if instr is not None:
            pred_cutoff = datetime.now(timezone.utc).date() - timedelta(days=30)
            pred_rows = (
                db.execute(
                    select(Prediction.model_name, Prediction.date, Prediction.target_price, Prediction.confidence)
                    .where(Prediction.instrument_id == instr)
                    .where(Prediction.date >= pred_cutoff)
                    .order_by(Prediction.date.desc())
                    .limit(5)
                )
                .mappings()
                .all()
            )
            recent_impact_predictions = [
                {
                    "model": r["model_name"],
                    "date": r["date"].isoformat() if r["date"] else None,
                    "target_price": r["target_price"],
                    "confidence": r["confidence"],
                }
                for r in pred_rows
            ]

        engine = ScenarioEngine()
        dd = engine.max_drawdown(db, ticker)
        max_drawdown = dd.get("max_drawdown", 0.0)

        return {
            "price_stats": price_stats,
            "correlation_to_portfolio": corr_to_portfolio,
            "recent_anomalies": recent_anomalies,
            "recent_impact_predictions": recent_impact_predictions,
            "max_drawdown": max_drawdown,
        }

    def sector_heatmap(self, db: Any, user_id: int = 0) -> list[dict[str, Any]]:
        positions = self._get_positions(db, user_id)
        if not positions:
            return []

        sector_tickers: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for p in positions:
            sector_tickers[p["sector"]].append(p)

        total = sum(p["amount"] for p in positions)

        engine = ScenarioEngine()
        engine.from_positions(positions)
        engine.load_prices(db, 365)

        result: list[dict[str, Any]] = []
        for sector, tickers_in_sector in sector_tickers.items():
            sector_amount = sum(p["amount"] for p in tickers_in_sector)
            weight = sector_amount / total

            var_contrib = 0.0
            sector_positions = [p for p in positions if p["sector"] == sector]
            sec_engine = ScenarioEngine()
            sec_engine.from_positions(sector_positions)
            sec_engine.load_prices(db, 365)
            if sec_engine._cov_matrix is not None and sec_engine._weights is not None:
                mc = sec_engine.run_monte_carlo(n_simulations=5000, periods=252)
                var_contrib = mc.var_95

            corr_to_market: float | None = None
            if (
                engine._returns
                and len(engine._tickers) > 1
                and engine._weights is not None
            ):
                port_ret = sum(
                    engine._returns[t] * w
                    for t, w in zip(engine._tickers, engine._weights)
                    if len(engine._returns.get(t, [])) >= 20
                )
                sector_tickers_in_data = [
                    t for t, _ in tickers_in_sector if t in engine._returns and len(engine._returns[t]) >= 20
                ]
                if sector_tickers_in_data and len(port_ret) > 0:
                    sector_ret = np.mean(
                        [engine._returns[t] for t in sector_tickers_in_data],
                        axis=0,
                    )
                    min_len = min(len(sector_ret), len(port_ret))
                    c = float(np.corrcoef(sector_ret[-min_len:], port_ret[-min_len:])[0, 1])
                    corr_to_market = round(c, 4)

            result.append({
                "sector": sector,
                "weight": round(weight, 4),
                "VaR_contribution": round(var_contrib, 4),
                "correlation_to_market": corr_to_market,
            })

        result.sort(key=lambda x: x["weight"], reverse=True)
        return result

    def correlation_table(
        self, db: Any, tickers: list[str]
    ) -> list[dict[str, Any]]:
        if len(tickers) < 2:
            return []

        returns: dict[str, np.ndarray] = {}
        for ticker in tickers:
            rows = (
                db.execute(
                    select(Price.close)
                    .join(Instrument, Instrument.id == Price.instrument_id)
                    .where(Instrument.ticker == ticker)
                    .where(Price.close.isnot(None))
                    .order_by(Price.date)
                )
                .scalars()
                .all()
            )
            closes = np.array([float(c) for c in rows if c and c > 0], dtype=float)
            if len(closes) >= 20:
                returns[ticker] = np.diff(np.log(closes))

        tickers_with_data = list(returns.keys())
        if len(tickers_with_data) < 2:
            return []

        min_len = min(len(returns[t]) for t in tickers_with_data)
        aligned = np.column_stack([returns[t][-min_len:] for t in tickers_with_data])
        corr = np.corrcoef(aligned, rowvar=False)

        result = []
        for i in range(len(tickers_with_data)):
            for j in range(i + 1, len(tickers_with_data)):
                result.append({
                    "ticker_a": tickers_with_data[i],
                    "ticker_b": tickers_with_data[j],
                    "correlation": round(float(corr[i, j]), 4),
                })

        result.sort(key=lambda x: abs(x["correlation"]), reverse=True)
        return result

    def format_summary(self, data: dict[str, Any]) -> str:
        lines: list[str] = []

        sc = data.get("sector_concentration", {})
        hhi = sc.get("hhi", 0.0)
        lines.append(f"HHI: {hhi}")
        lines.append("Top sectors:")
        for s in sc.get("top_sectors", []):
            lines.append(f"  {s['sector']}: {s['weight']:.1%}")

        pc = data.get("position_concentration", {})
        lines.append(f"Top position: {pc.get('top_ticker_pct', 0.0):.1%}")

        lines.append(f"VaR(95%): {data.get('VaR_95', 0.0):.4f}")
        lines.append(f"CVaR(95%): {data.get('CVaR_95', 0.0):.4f}")

        lines.append(f"Max drawdown 90d: {data.get('max_drawdown_90d', 0.0):.4f}")
        lines.append(f"Max drawdown 1y: {data.get('max_drawdown_1y', 0.0):.4f}")
        lines.append(f"Anomalies: {data.get('anomaly_count', 0)}")

        corr = data.get("correlation_matrix", [])
        if corr:
            lines.append("Top correlations:")
            for c in corr[:5]:
                lines.append(f"  {c['ticker_a']}-{c['ticker_b']}: {c['correlation']:.3f}")

        return "\n".join(lines)
