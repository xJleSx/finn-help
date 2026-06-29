from __future__ import annotations

import asyncio
import difflib
import json
import logging
import re
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from src.analysis.ml.news_impact import NewsImpactModel
from src.analysis.scenario.engine import ScenarioEngine
from src.db.models import (
    FundamentalMetric,
    Indicator,
    Instrument,
    MacroIndicator,
    News,
    NewsInstrument,
    Portfolio,
    Price,
)
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
    "instrument_info": [
        "instrument", "инструмент", "ticker", "тикер", "price", "цена",
        "pe", "p/e", "market cap", "капитализация", "sector", "сектор",
        "about", "о компании", "что такое", "кто такой", "описание",
        "info", "информация", "характеристик",
    ],
    "macro_query": [
        "macro", "макро", "cbr", "цб", "ключевая ставка", "inflation",
        "инфляция", "gdp", "ввп", "экономика", "economy", "ставка",
        "ставку", "процент",
    ],
    "compare": [
        "compare", "сравн", "vs", "против", "better", "лучш",
        "difference", "разниц", "which", "какой", "или",
    ],
}

_KNOWN_SECTORS: list[str] = [
    "финансы", "нефть", "it", "металлы", "электроэнергетика", "потреб",
    "химия", "транспорт", "телеком", "строительство", "машиностроение",
    "авиация", "ритейл", "здравоохран", "инфраструктур",
    "сельское хозяйство", "добыча", "обрабатывающ", "инновации",
]

_ABBREVIATIONS: dict[str, str] = {
    "сбер": "сбер банк",
    "газпром": "газпром",
    "сбп": "сбер банк",
    "втб": "втб банк",
    "лукойл": "лукойл",
    "роснефть": "роснефть",
    "яндекс": "яндекс",
    "новост": "новости",
}

_ENGLISH_TO_RUSSIAN: dict[str, str] = {
    "portfolio": "портфель",
    "value": "стоимость",
    "news": "новости",
    "risk": "риск",
    "buy": "купить",
    "sell": "продать",
    "top": "топ",
    "best": "лучший",
    "scenario": "сценарий",
    "crash": "обвал",
    "compare": "сравнить",
    "vs": "против",
    "macro": "макро",
    "rate": "ставка",
    "inflation": "инфляция",
    "gdp": "ввп",
    "economy": "экономика",
}

_TIMEFRAME_WORDS: dict[str, str] = {
    "день": "1d",
    "дня": "1d",
    "дней": "1d",
    "daily": "1d",
    "недел": "1w",
    "weekly": "1w",
    "месяц": "1m",
    "месяца": "1m",
    "месяцев": "1m",
    "month": "1m",
    "год": "1y",
    "года": "1y",
    "лет": "1y",
    "year": "1y",
    "annual": "1y",
    "quarter": "1q",
    "квартал": "1q",
}


class NLQueryEngine:
    _conversation_memory: dict[int, deque] = {}

    def __init__(self, llm_client: Any = None) -> None:
        self._llm_client = llm_client or default_llm

    def _expand_query(self, query: str) -> str:
        lowered = query.lower()
        for abbr, full in _ABBREVIATIONS.items():
            lowered = re.sub(r"\b" + re.escape(abbr) + r"\w*", full, lowered)
        for eng, rus in _ENGLISH_TO_RUSSIAN.items():
            lowered = re.sub(r"\b" + re.escape(eng) + r"\w*", rus, lowered)
        return lowered

    def _extract_entities(self, query: str, db: Any = None) -> dict[str, Any]:
        entities: dict[str, Any] = {
            "tickers": [],
            "sectors": [],
            "amounts": [],
            "timeframe": "",
        }
        ticker_candidates = re.findall(r"\b[A-Z]{4,5}\b", query.upper())
        if db is not None:
            try:
                known = set()
                rows = db.execute(select(Instrument.ticker)).all()
                for row in rows:
                    val = row[0]
                    if val:
                        known.add(val.upper())
                entities["tickers"] = [t for t in ticker_candidates if t in known]
            except Exception:
                entities["tickers"] = ticker_candidates
        else:
            entities["tickers"] = ticker_candidates

        q_lower = query.lower()
        for sector in _KNOWN_SECTORS:
            if sector in q_lower:
                entities["sectors"].append(sector)

        pct_amounts = re.findall(r"(\d+(?:[.,]\d+)?)\s*%", query)
        entities["amounts"].extend(float(a.replace(",", ".")) for a in pct_amounts)
        ruble_amounts = re.findall(r"(\d+(?:[.,]\d+)?)\s*(?:руб|₽|rub)", query.lower())
        entities["amounts"].extend(float(a.replace(",", ".")) for a in ruble_amounts)

        for word, tf in _TIMEFRAME_WORDS.items():
            if word in q_lower:
                entities["timeframe"] = tf
                break

        return entities

    def _get_context(self, user_id: int) -> str:
        history = self._conversation_memory.get(user_id, [])
        if not history:
            return ""
        lines = ["История диалога (последние запросы):"]
        for i, entry in enumerate(list(history)[-3:], 1):
            lines.append(f"  {i}. Запрос: {entry['query']}")
            lines.append(f"     Ответ: {entry['response'][:200]}")
        return "\n".join(lines)

    def _classify_fuzzy(self, text_lower: str) -> str | None:
        words = text_lower.split()
        best_intent: str | None = None
        best_score = 0
        for intent, keywords in _INTENT_MAP.items():
            score = 0
            for kw in keywords:
                if len(kw) < 4:
                    continue
                matches = difflib.get_close_matches(kw, words, n=1, cutoff=0.75)
                if matches:
                    score += 1
            if score > best_score:
                best_score = score
                best_intent = intent
        return best_intent if best_score > 0 else None

    def classify_query(self, text: str) -> str:
        expanded = self._expand_query(text)
        expanded_lower = expanded.lower()
        scores: dict[str, int] = {}
        for intent, keywords in _INTENT_MAP.items():
            score = sum(1 for kw in keywords if kw in expanded_lower)
            if score > 0:
                scores[intent] = score
        if scores:
            return max(scores, key=scores.get)
        best = self._classify_fuzzy(expanded_lower)
        if best:
            return best
        return "unknown"

    def execute(self, query: str, db: Any, user_id: int = 0) -> dict[str, Any]:
        intent = self.classify_query(query)
        handler = getattr(self, f"_handle_{intent}", None)
        if handler is None:
            return self._handle_unknown(query, db, user_id)
        return handler(query, db, user_id)

    def answer(self, query: str, db: Any, user_id: int = 0, llm_client: Any = None) -> str:
        data = self.execute(query, db, user_id)
        client = llm_client or self._llm_client
        result: str | None = None
        if client:
            try:
                prompt = self._build_prompt(query, data, user_id)
                if hasattr(client, "answer_question"):
                    coro = client.answer_question(prompt, user_id=str(user_id))
                    try:
                        loop = asyncio.get_running_loop()
                        if loop.is_running():
                            result = asyncio.run_coroutine_threadsafe(coro, loop).result()
                        else:
                            result = asyncio.run(coro)
                    except RuntimeError:
                        result = asyncio.run(coro)
                elif callable(client):
                    result = client(prompt)
            except Exception as e:
                logger.warning("LLM response failed: %s", e)
        if result is None:
            result = self.format_response(data.get("intent", "unknown"), data)
        self._store_memory(user_id, query, data)
        return result

    def format_response(self, intent: str, data: dict[str, Any]) -> str:
        formatter = getattr(self, f"_format_{intent}", None)
        if formatter is None:
            return data.get("error", "I couldn't process that query.")
        return formatter(data)

    def _build_prompt(self, query: str, data: dict[str, Any], user_id: int = 0) -> str:
        context = self._get_context(user_id)
        lines = [
            "You are a financial assistant FinAdvisor. Answer in Russian based on the structured data below.",
            "",
            f"User query: {query}",
            f"Intent: {data.get('intent', 'unknown')}",
            "",
        ]
        if context:
            lines.append(context)
            lines.append("")
        lines.append("Structured data:")
        lines.append(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        lines.append("")
        lines.append("Provide a concise, helpful answer in Russian. Use emojis for visual structure.")
        return "\n".join(lines)

    def _store_memory(self, user_id: int, query: str, data: dict[str, Any]) -> None:
        if user_id not in self._conversation_memory:
            self._conversation_memory[user_id] = deque(maxlen=3)
        response = self.format_response(data.get("intent", "unknown"), data)
        self._conversation_memory[user_id].append({
            "query": query,
            "response": response,
            "intent": data.get("intent", "unknown"),
        })

    def _handle_unknown(self, query: str, db: Any, user_id: int) -> dict[str, Any]:
        entities = self._extract_entities(query, db)
        tickers = entities.get("tickers", [])
        if tickers:
            result = self._handle_instrument_info(query, db, user_id)
            result["intent"] = "unknown"
            result["fallback_tickers"] = tickers
            return result
        return {"intent": "unknown", "error": f"Unrecognized query: {query}"}

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

    def _handle_instrument_info(self, query: str, db: Any, user_id: int) -> dict[str, Any]:
        entities = self._extract_entities(query, db)
        tickers = list(entities.get("tickers", []))

        if not tickers:
            q_lower = query.lower()
            rows = db.execute(select(Instrument)).all()
            for row in rows:
                if row.full_name and q_lower in row.full_name.lower():
                    tickers = [row.ticker]
                    break

        instruments = []
        for ticker in tickers[:5]:
            row = (
                db.execute(
                    select(Instrument, Price)
                    .outerjoin(Price, Price.instrument_id == Instrument.id)
                    .where(Instrument.ticker == ticker)
                    .order_by(Price.date.desc())
                    .limit(1)
                )
                .first()
            )
            if not row:
                continue
            inst, price = row if row else (None, None)
            if not inst:
                continue
            fm = (
                db.execute(
                    select(FundamentalMetric)
                    .where(FundamentalMetric.instrument_id == inst.id)
                    .order_by(FundamentalMetric.date.desc())
                    .limit(1)
                )
                .scalar_one_or_none()
            )
            instruments.append({
                "ticker": inst.ticker,
                "name": inst.full_name,
                "sector": inst.sector,
                "price": float(price.close) if price and price.close else None,
                "pe_ratio": float(fm.pe_ratio) if fm and fm.pe_ratio else None,
                "market_cap": float(fm.market_cap) if fm and fm.market_cap else None,
                "eps": float(fm.eps) if fm and fm.eps else None,
            })
        return {
            "intent": "instrument_info",
            "instruments": instruments,
            "count": len(instruments),
        }

    def _handle_macro_query(self, query: str, db: Any, user_id: int) -> dict[str, Any]:
        indicators: dict[str, dict[str, Any]] = {}
        for indicator_type in ["cbr_rate", "inflation", "gdp"]:
            row = (
                db.execute(
                    select(MacroIndicator)
                    .where(MacroIndicator.indicator_type == indicator_type)
                    .order_by(MacroIndicator.date.desc())
                    .limit(1)
                )
                .scalar_one_or_none()
            )
            if row:
                indicators[indicator_type] = {
                    "value": row.value,
                    "date": row.date.isoformat() if row.date else "",
                }
        return {
            "intent": "macro_query",
            "indicators": indicators,
        }

    def _handle_compare(self, query: str, db: Any, user_id: int) -> dict[str, Any]:
        entities = self._extract_entities(query, db)
        tickers = entities.get("tickers", [])
        if len(tickers) < 2:
            return {
                "intent": "compare",
                "error": "Need at least two tickers to compare.",
                "tickers": tickers,
            }
        instruments = []
        for ticker in tickers[:2]:
            row = (
                db.execute(
                    select(Instrument, Price)
                    .outerjoin(Price, Price.instrument_id == Instrument.id)
                    .where(Instrument.ticker == ticker)
                    .order_by(Price.date.desc())
                    .limit(1)
                )
                .first()
            )
            if not row:
                continue
            inst, price = row if row else (None, None)
            if not inst:
                continue
            ind = (
                db.execute(
                    select(Indicator)
                    .where(Indicator.instrument_id == inst.id)
                    .order_by(Indicator.date.desc())
                    .limit(1)
                )
                .scalar_one_or_none()
            )
            instruments.append({
                "ticker": inst.ticker,
                "name": inst.full_name,
                "sector": inst.sector,
                "price": float(price.close) if price and price.close else None,
                "rsi": float(ind.rsi) if ind and ind.rsi else None,
                "atr": float(ind.atr) if ind and ind.atr else None,
            })
        return {
            "intent": "compare",
            "instruments": instruments,
            "count": len(instruments),
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

    def _format_instrument_info(self, data: dict[str, Any]) -> str:
        if not data["instruments"]:
            return "ℹ️ No instrument found."
        lines = [f"ℹ️ Instrument Info ({data['count']} found):"]
        for inst in data["instruments"]:
            lines.append(f"   • {inst['ticker']} — {inst.get('name', '?')}")
            if inst.get("sector"):
                lines.append(f"     Sector: {inst['sector']}")
            if inst.get("price") is not None:
                lines.append(f"     Price: {inst['price']:.2f} ₽")
            if inst.get("pe_ratio") is not None:
                lines.append(f"     P/E: {inst['pe_ratio']:.2f}")
            if inst.get("market_cap") is not None:
                lines.append(f"     Market Cap: {inst['market_cap']:,.0f} ₽")
        return "\n".join(lines)

    def _format_macro_query(self, data: dict[str, Any]) -> str:
        ind = data.get("indicators", {})
        if not ind:
            return "📊 No macro data available."
        lines = ["📊 Macro Indicators:"]
        labels = {"cbr_rate": "CBR Rate", "inflation": "Inflation", "gdp": "GDP"}
        for key, info in ind.items():
            label = labels.get(key, key)
            lines.append(f"   • {label}: {info['value']} ({info['date']})")
        return "\n".join(lines)

    def _format_compare(self, data: dict[str, Any]) -> str:
        if "error" in data:
            return f"⚠️ {data['error']}"
        lines = [f"📊 Comparison ({data['count']} instruments):"]
        for inst in data.get("instruments", []):
            lines.append(f"   • {inst['ticker']} ({inst.get('name', '?')})")
            if inst.get("sector"):
                lines.append(f"     Sector: {inst['sector']}")
            if inst.get("price") is not None:
                lines.append(f"     Price: {inst['price']:.2f} ₽")
            if inst.get("rsi") is not None:
                lines.append(f"     RSI: {inst['rsi']:.1f}")
            if inst.get("atr") is not None:
                lines.append(f"     ATR: {inst['atr']:.2f}")
        return "\n".join(lines)

    def _format_unknown(self, data: dict[str, Any]) -> str:
        tickers = data.get("fallback_tickers", [])
        if tickers:
            msg = data.get("error", "")
            if msg:
                return msg
            return (
                f"ℹ️ I found tickers {', '.join(tickers)} but couldn't determine what you want. "
                "Try: 'info about SBER', 'news about SBER', 'compare SBER and VTBR'"
            )
        return data.get(
            "error",
            "I couldn't process that query. Try asking about portfolio, news, risks, macro, or instruments.",
        )


nlq: NLQueryEngine = NLQueryEngine()
