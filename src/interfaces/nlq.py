from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from src.analysis.ml.news_impact import NewsImpactModel
from src.analysis.scenario.engine import ScenarioEngine
from src.db.models import Instrument, News, NewsInstrument, Portfolio
from src.db.models import Signal as SignalModel
from src.llm.router import llm as default_llm

logger = logging.getLogger(__name__)

_INTENT_MAP: dict[str, list[str]] = {
    "portfolio_value": [
        "portfolio", "портфель", "value", "стоимость", "worth", "how much",
        "balance", "баланс", "holdings", "позиции", "positions",
    ],
    "scenario_analysis": [
        "scenario", "сценарий", "what if", "что если", "crash", "обвал",
        "stress", "стресс", "macro", "макро", "shock", "шок",
    ],
    "news_impact": [
        "news", "новости", "новость", "impact", "влияние", "effect",
        "sentiment", "сентимент", "affect", "повлия", "последн",
    ],
    "top_picks": [
        "top", "топ", "best", "лучш", "pick", "выбор", "recommend",
        "рекомендац", "signal", "сигнал", "buy", "купить",
    ],
    "risk_metrics": [
        "risk", "риск", "var", "cvar", "value at risk", "drawdown",
        "просадк", "volatility", "волатильност", "опасн",
    ],
    "rebalance": [
        "rebalance", "ребаланс", "rebalancing", "drift", "отклонен",
        "target", "целев", "overweight", "перевес",
    ],
}


class NLQueryEngine:
    def __init__(self, llm_client: Any = None) -> None:
        self._llm_client = llm_client or default_llm

    def classify_query(self, text: str) -> str:
        text_lower = text.lower()
        scores: dict[str, int] = {}
        for intent, keywords in _INTENT_MAP.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[intent] = score
        if not scores:
            return "unknown"
        return max(scores, key=scores.get)

    def execute(self, query: str, db: Any, user_id: int = 0) -> dict[str, Any]:
        intent = self.classify_query(query)
        handler = getattr(self, f"_handle_{intent}", None)
        if handler is None:
            return {"intent": "unknown", "error": f"Unrecognized query: {query}"}
        return handler(query, db, user_id)

    def answer(self, query: str, db: Any, user_id: int = 0, llm_client: Any = None) -> str:
        data = self.execute(query, db, user_id)
        client = llm_client or self._llm_client
        if client:
            try:
                prompt = self._build_prompt(query, data)
                if hasattr(client, "answer_question"):
                    coro = client.answer_question(prompt, user_id=str(user_id))
                    try:
                        loop = asyncio.get_running_loop()
                        if loop.is_running():
                            return asyncio.run_coroutine_threadsafe(coro, loop).result()
                    except RuntimeError:
                        pass
                    return asyncio.run(coro)
                if callable(client):
                    return client(prompt)
            except Exception as e:
                logger.warning("LLM response failed: %s", e)
        return self.format_response(data.get("intent", "unknown"), data)

    def format_response(self, intent: str, data: dict[str, Any]) -> str:
        formatter = getattr(self, f"_format_{intent}", None)
        if formatter is None:
            return data.get("error", "I couldn't process that query.")
        return formatter(data)

    def _build_prompt(self, query: str, data: dict[str, Any]) -> str:
        lines = [
            "You are a financial assistant FinAdvisor. Answer in Russian based on the structured data below.",
            "",
            f"User query: {query}",
            f"Intent: {data.get('intent', 'unknown')}",
            "",
            "Structured data:",
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            "",
            "Provide a concise, helpful answer in Russian. Use emojis for visual structure.",
        ]
        return "\n".join(lines)

    def _handle_portfolio_value(self, query: str, db: Any, user_id: int) -> dict[str, Any]:
        rows = (
            db.execute(
                select(
                    Instrument.ticker, Instrument.full_name,
                    Portfolio.quantity, Portfolio.avg_price,
                )
                .join(Portfolio, Portfolio.instrument_id == Instrument.id)
                .where(Portfolio.user_id == user_id)
                .where(Portfolio.quantity > 0)
            )
            .mappings()
            .all()
        )
        positions = []
        total = 0.0
        for r in rows:
            qty = float(r["quantity"])
            price = float(r["avg_price"] or 0.0)
            amount = qty * price
            total += amount
            positions.append({
                "ticker": r["ticker"],
                "name": r["full_name"],
                "quantity": qty,
                "avg_price": price,
                "amount": round(amount, 2),
            })
        return {
            "intent": "portfolio_value",
            "total": round(total, 2),
            "positions": positions,
            "count": len(positions),
        }

    def _handle_scenario_analysis(self, query: str, db: Any, user_id: int) -> dict[str, Any]:
        engine = ScenarioEngine().from_portfolio(db, user_id).load_prices(db)
        results = engine.run_all()
        return {
            "intent": "scenario_analysis",
            "total": results.get("total", 0),
            "scenarios": results.get("scenarios", []),
            "monte_carlo": results.get("monte_carlo"),
            "bootstrap": results.get("bootstrap"),
            "sector_breakdown": results.get("sector_breakdown", {}),
        }

    def _handle_news_impact(self, query: str, db: Any, user_id: int) -> dict[str, Any]:
        tickers = re.findall(r"\b[A-Z]{4,5}\b", query.upper())
        if not tickers:
            rows = (
                db.execute(
                    select(Instrument.ticker)
                    .join(Portfolio, Portfolio.instrument_id == Instrument.id)
                    .where(Portfolio.user_id == user_id)
                )
                .all()
            )
            tickers = [r[0] for r in rows[:3]]
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        news_list: list[dict[str, Any]] = []
        for ticker in tickers[:5]:
            rows = (
                db.execute(
                    select(News)
                    .join(NewsInstrument, NewsInstrument.news_id == News.id)
                    .join(Instrument, Instrument.id == NewsInstrument.instrument_id)
                    .where(Instrument.ticker == ticker)
                    .where(News.published_at >= cutoff)
                    .order_by(News.published_at.desc())
                    .limit(10)
                )
                .scalars()
                .all()
            )
            for article in rows:
                model = NewsImpactModel(ticker)
                impact = model.predict(db, article, horizon_days=1)
                news_list.append({
                    "ticker": ticker,
                    "title": article.title,
                    "sentiment": article.sentiment_score,
                    "published": article.published_at.isoformat() if article.published_at else "",
                    "predicted_return": impact.get("predicted_return", 0.0),
                    "confidence": impact.get("confidence", 0.0),
                })
        return {
            "intent": "news_impact",
            "news": news_list,
            "count": len(news_list),
        }

    def _handle_top_picks(self, query: str, db: Any, user_id: int) -> dict[str, Any]:
        rows = (
            db.execute(
                select(SignalModel, Instrument.ticker)
                .join(Instrument, Instrument.id == SignalModel.instrument_id)
                .order_by(SignalModel.confidence.desc())
                .limit(10)
            )
            .all()
        )
        signals = []
        for signal, ticker in rows:
            signals.append({
                "ticker": ticker,
                "action": signal.action,
                "confidence": signal.confidence,
                "date": signal.date.isoformat() if signal.date else "",
            })
        return {
            "intent": "top_picks",
            "signals": signals,
            "count": len(signals),
        }

    def _handle_risk_metrics(self, query: str, db: Any, user_id: int) -> dict[str, Any]:
        engine = ScenarioEngine().from_portfolio(db, user_id).load_prices(db)
        mc = engine.run_monte_carlo()
        bs = engine.run_historical_bootstrap()
        return {
            "intent": "risk_metrics",
            "total": mc.total_before,
            "monte_carlo": {
                "var_95": mc.var_95,
                "cvar_95": mc.cvar_95,
                "var_99": mc.var_99,
            },
            "bootstrap": {
                "var_95": bs.var_95,
                "cvar_95": bs.cvar_95,
                "var_99": bs.var_99,
            },
        }

    def _handle_rebalance(self, query: str, db: Any, user_id: int) -> dict[str, Any]:
        instruments = db.execute(select(Instrument)).scalars().all()
        positions = (
            db.execute(select(Portfolio).where(Portfolio.user_id == user_id))
            .scalars()
            .all()
        )
        inst_map = {inst.id: inst for inst in instruments}
        total_value = 0.0
        pos_data: list[dict[str, Any]] = []
        for p in positions:
            inst = inst_map.get(p.instrument_id)
            if not inst:
                continue
            val = float(p.quantity * (p.avg_price or 0))
            total_value += val
            pos_data.append({
                "ticker": inst.ticker,
                "value": round(val, 2),
                "pct": 0.0,
            })
        for p in pos_data:
            p["pct"] = round(p["value"] / total_value * 100, 2) if total_value > 0 else 0.0
        return {
            "intent": "rebalance",
            "total_value": round(total_value, 2),
            "positions": pos_data,
            "count": len(pos_data),
        }

    def _format_portfolio_value(self, data: dict[str, Any]) -> str:
        lines = [f"💰 Portfolio Value: {data['total']:,.2f} RUB"]
        lines.append(f"   Holdings: {data['count']} positions")
        for p in data["positions"]:
            lines.append(f"   • {p['ticker']} — {p['quantity']} × {p['avg_price']:.2f} = {p['amount']:,.2f}")
        return "\n".join(lines)

    def _format_scenario_analysis(self, data: dict[str, Any]) -> str:
        lines = [f"📊 Scenario Analysis (portfolio: {data['total']:,.2f} RUB)"]
        for s in data.get("scenarios", []):
            loss_pct = s.get("loss_pct", 0) * 100
            loss_val = s.get("loss", 0)
            lines.append(f"   • {s.get('name', '?')}: {loss_pct:+.1f}% ({loss_val:+,.2f})")
        mc = data.get("monte_carlo")
        if mc:
            v95 = mc.get("var_95", 0) * 100
            cv95 = mc.get("cvar_95", 0) * 100
            lines.append(f"   \u2022 Monte Carlo: VaR95={v95:.1f}% CVaR95={cv95:.1f}%")
        bs = data.get("bootstrap")
        if bs:
            lines.append(f"   • Bootstrap: VaR95={bs.get('var_95', 0)*100:.1f}% CVaR95={bs.get('cvar_95', 0)*100:.1f}%")
        return "\n".join(lines)

    def _format_news_impact(self, data: dict[str, Any]) -> str:
        if not data["news"]:
            return "📰 No recent news found."
        lines = [f"📰 Recent News Impact ({data['count']} articles):"]
        for n in data["news"]:
            sent = n.get("sentiment", "")
            pred = n.get("predicted_return", 0)
            conf = n.get("confidence", 0)
            lines.append(f"   • [{n['ticker']}] {n.get('title', '?')} — sentiment: {sent}")
            if pred:
                lines.append(f"     Impact: {pred:+.4f} (conf: {conf:.2f})")
        return "\n".join(lines)

    def _format_top_picks(self, data: dict[str, Any]) -> str:
        if not data["signals"]:
            return "📈 No signals available."
        lines = [f"📈 Top Picks ({data['count']} signals):"]
        for s in data["signals"]:
            conf = s.get("confidence", 0) or 0
            lines.append(f"   • {s['ticker']} — {s['action']} ({conf * 100:.0f}%)")
        return "\n".join(lines)

    def _format_risk_metrics(self, data: dict[str, Any]) -> str:
        lines = [f"⚠️ Risk Metrics (portfolio: {data['total']:,.2f} RUB)"]
        mc = data.get("monte_carlo", {})
        lines.append("   Monte Carlo:")
        lines.append(f"     VaR95:  {mc.get('var_95', 0) * 100:.2f}%")
        lines.append(f"     CVaR95: {mc.get('cvar_95', 0) * 100:.2f}%")
        lines.append(f"     VaR99:  {mc.get('var_99', 0) * 100:.2f}%")
        bs = data.get("bootstrap", {})
        lines.append("   Historical Bootstrap:")
        lines.append(f"     VaR95:  {bs.get('var_95', 0) * 100:.2f}%")
        lines.append(f"     CVaR95: {bs.get('cvar_95', 0) * 100:.2f}%")
        lines.append(f"     VaR99:  {bs.get('var_99', 0) * 100:.2f}%")
        return "\n".join(lines)

    def _format_rebalance(self, data: dict[str, Any]) -> str:
        if not data["positions"]:
            return "⚖️ No positions to rebalance."
        lines = [f"⚖️ Rebalancing Analysis (total: {data['total_value']:,.2f} RUB)"]
        for p in data["positions"]:
            lines.append(f"   • {p['ticker']}: {p['pct']:.1f}% ({p['value']:,.2f} RUB)")
        return "\n".join(lines)


nlq: NLQueryEngine = NLQueryEngine()
