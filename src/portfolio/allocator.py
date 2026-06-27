import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import (
    ALLOCATOR_CAPITAL_TIERS,
    ALLOCATOR_LEFTOVER_MIN_ABS,
    ALLOCATOR_LEFTOVER_THRESHOLD,
    ALLOCATOR_RECOMMEND_MAX_PICKS,
    ALLOCATOR_RECOMMEND_TIER_PICKS,
    ALLOCATOR_SECTOR_LIMIT_MIN_CAPITAL,
    KNOWN_DIVIDEND_STOCKS,
    SAFE_BONDS,
    SAFE_ETFS,
    SECTOR_LIMITS,
    SECTOR_NAMES,
)
from src.db.connection import get_session, session_scope
from src.db.models import Dividend, Instrument, Price
from src.portfolio.risk import item_risk

logger = logging.getLogger(__name__)


class PortfolioAllocator:
    PROFILES = {
        "conservative": {
            "etf": {"weight": 0.50, "label": "БПИФ (ETF)", "max": 4},
            "dividend": {"weight": 0.20, "label": "Дивидендные акции", "max": 3},
            "bond": {"weight": 0.25, "label": "Облигации / ОФЗ", "max": 4},
            "growth": {"weight": 0.05, "label": "Акции роста", "max": 1},
        },
        "balanced": {
            "etf": {"weight": 0.40, "label": "БПИФ (ETF)", "max": 3},
            "dividend": {"weight": 0.30, "label": "Дивидендные акции", "max": 4},
            "bond": {"weight": 0.20, "label": "Облигации / ОФЗ", "max": 3},
            "growth": {"weight": 0.10, "label": "Акции роста", "max": 2},
        },
        "aggressive": {
            "etf": {"weight": 0.25, "label": "БПИФ (ETF)", "max": 3},
            "dividend": {"weight": 0.25, "label": "Дивидендные акции", "max": 3},
            "bond": {"weight": 0.10, "label": "Облигации / ОФЗ", "max": 2},
            "growth": {"weight": 0.40, "label": "Акции роста", "max": 4},
        },
    }

    def __init__(self) -> None:
        self.profile = "balanced"

    def set_profile(self, profile: str) -> None:
        if profile in self.PROFILES:
            self.profile = profile

    def _load_profile_from_db(self) -> None:
        try:
            from src.db.models import UserSetting

            with session_scope() as db:
                row = db.query(UserSetting).filter_by(key="risk_profile").first()
                if row and row.value in self.PROFILES:
                    self.profile = row.value
        except Exception as e:
            logger.warning("Failed to load risk profile from DB: %s", e)

    def _weights(self) -> dict[str, Any]:
        return self.PROFILES.get(self.profile, self.PROFILES["balanced"])

    def _allocate_from_data(
        self, capital: float, existing: list[dict[str, Any]],
        instruments_data: list[dict[str, Any]], db: Any,
    ) -> dict[str, Any]:
        plan = {}
        total_allocated = 0.0
        sector_allocation: dict[str, float] = {}

        for category, cfg in self._weights().items():
            budget = capital * cfg["weight"]
            candidates = self._score_candidates(instruments_data, category, budget, existing, db)

            max_positions = cfg["max"]
            for tier in ALLOCATOR_CAPITAL_TIERS:
                if capital < tier["max_capital"] and budget < tier["min_budget"]:
                    max_positions = tier["max_positions"]
                    break

            selected = candidates[:max_positions]
            if not selected:
                continue

            cat_total = sum(s["score"] for s in selected) or 1
            category_items = []
            for item in selected:
                share = item["score"] / cat_total
                amount = round(budget * share, 2)

                last_price = item.get("last_price")
                if last_price and last_price > 0 and amount < last_price:
                    continue

                sector = item.get("sector", "Прочее")
                limit = SECTOR_LIMITS.get(sector, 0.30)
                current_sector_weight = (sector_allocation.get(sector, 0.0) + amount) / capital
                if capital >= ALLOCATOR_SECTOR_LIMIT_MIN_CAPITAL and current_sector_weight > limit:
                    continue

                sector_allocation[sector] = sector_allocation.get(sector, 0.0) + amount

                risk = item_risk(item, db, capital)
                category_items.append(
                    {
                        "ticker": item["ticker"],
                        "name": item["name"],
                        "amount": amount,
                        "reason": item.get("reason", ""),
                        "expected_yield": item.get("yield", 0),
                        "sector": sector,
                        "last_price": item.get("last_price"),
                        "risk": risk,
                    }
                )
                total_allocated += amount

            plan[category] = {
                "label": cfg["label"],
                "budget": round(budget, 2),
                "items": category_items,
            }

        leftover = round(capital - total_allocated, 2)
        if leftover > max(ALLOCATOR_LEFTOVER_MIN_ABS, capital * ALLOCATOR_LEFTOVER_THRESHOLD):
            for cat_name in ["etf", "dividend"]:
                if cat_name in plan and plan[cat_name]["items"]:
                    items = plan[cat_name]["items"]
                    total_score = sum(it.get("amount", 0) for it in items) or 1
                    for it in items:
                        frac = it["amount"] / total_score
                        it["amount"] = round(it["amount"] + leftover * frac, 2)
                    total_allocated += leftover
                    break

        projected_monthly = self._calc_projected_yield(plan, capital)

        return {
            "capital": capital,
            "total_allocated": round(total_allocated, 2),
            "reserve": round(capital - total_allocated, 2),
            "plan": plan,
            "projected_monthly_yield": round(projected_monthly, 2),
            "projected_monthly_pct": round((projected_monthly / capital) * 100 if capital > 0 else 0, 2),
            "existing_portfolio": existing,
            "sector_allocation": sector_allocation,
        }

    def allocate(self, capital: float, db: Any = None) -> dict[str, Any]:
        should_close = db is None
        if db is None:
            db = get_session()
        try:
            existing = self._get_current_portfolio(db)
            instruments_data = self._load_instruments(db)
            return self._allocate_from_data(capital, existing, instruments_data, db)
        finally:
            if should_close:
                db.close()

    def _get_current_portfolio(self, db: Any) -> list[dict[str, Any]]:
        from src.db.models import Portfolio as PortModel

        positions = db.query(PortModel).all()
        result = []
        for p in positions:
            inst = db.query(Instrument).filter_by(id=p.instrument_id).first()
            price = db.query(Price).filter_by(instrument_id=p.instrument_id).order_by(Price.date.desc()).first()
            current_price = price.close if price else 0
            value = current_price * p.quantity if current_price else 0
            result.append(
                {
                    "ticker": inst.ticker if inst else "?",
                    "quantity": float(p.quantity),
                    "avg_price": float(p.avg_price) if p.avg_price else 0,
                    "current_value": round(float(value), 2),
                }
            )
        return result

    def _load_instruments(self, db: Any) -> list[dict[str, Any]]:
        instruments = db.query(Instrument).all()
        result = []
        for inst in instruments:
            price = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date.desc()).first()
            last_price = price.close if price else None
            sector = SECTOR_NAMES.get(inst.ticker, inst.sector or "")

            div_yield = 0.0
            one_year_ago = date.today() - timedelta(days=365)
            divs = (
                db.query(Dividend)
                .filter_by(instrument_id=inst.id)
                .filter(Dividend.date >= one_year_ago)
                .order_by(Dividend.date.desc())
                .all()
            )
            if divs and last_price and last_price > 0:
                div_yield = sum(d.amount for d in divs) / last_price * 100
                if div_yield > 25:
                    logger.warning(
                        "Suspicious div yield %.1f%% for %s (divs=%s, price=%s), capping at 25%%",
                        div_yield,
                        inst.ticker,
                        [d.amount for d in divs],
                        last_price,
                    )
                    div_yield = 25.0

            result.append(
                {
                    "id": inst.id,
                    "ticker": inst.ticker,
                    "name": inst.full_name or inst.ticker,
                    "type": inst.instrument_type,
                    "sector": sector,
                    "last_price": float(last_price) if last_price else None,
                    "div_yield": round(div_yield, 2),
                    "is_dividend": KNOWN_DIVIDEND_STOCKS.get(inst.ticker) == "dividend",
                    "is_growth": KNOWN_DIVIDEND_STOCKS.get(inst.ticker) == "growth",
                }
            )
        return result

    def _filter_candidates_by_category(self, instruments: list[dict[str, Any]], category: str) -> list[dict[str, Any]]:
        if category == "etf":
            return [i for i in instruments if i["type"] == "etf" and i["last_price"]]
        if category == "dividend":
            return [i for i in instruments if i["type"] == "stock" and i["is_dividend"] and i["last_price"]]
        if category == "bond":
            return [i for i in instruments if i["type"] == "bond" and i["last_price"]]
        if category == "growth":
            return [i for i in instruments if i["type"] == "stock" and i["is_growth"] and i["last_price"]]
        return []

    def _score_candidates_core(
        self,
        candidates: list[dict[str, Any]],
        category: str,
        budget: float,
        existing_tickers: set[str],
        existing_tickers_list: list[str],
        risk_fn: Any,
        penalty_fn: Any,
        dividend_fn: Any,
        volume_fn: Any,
        momentum_fn: Any,
    ) -> list[dict[str, Any]]:
        for c in candidates:
            score = 0.0
            reason_parts = []

            risk = risk_fn(c, budget)
            c["risk"] = risk

            var_95 = risk.get("var_95", 0) or 0
            if var_95 > 5.0:
                score -= 1.0
                reason_parts.append("высокий VaR (5%)")
            elif var_95 > 3.0:
                score -= 0.5
                reason_parts.append("повышенный VaR")

            max_pos_val = risk.get("suggested_shares", 999) * (c.get("last_price") or 1)
            max_pos_pct = max_pos_val / budget if budget > 0 else 1
            if max_pos_pct < 0.02:
                score -= 0.5
                reason_parts.append("низкий лимит позиции")
            if max_pos_pct > 0.5:
                score -= 1.0
                reason_parts.append("высокая концентрация")

            if c["ticker"] in existing_tickers:
                score += 0.5
                reason_parts.append("уже в портфеле")

            penalty = penalty_fn(c["ticker"], existing_tickers_list)
            if penalty > 0:
                score -= penalty
                reason_parts.append("высокая корреляция с портфелем")

            div_yield = min(c["div_yield"], 20.0)
            if div_yield > 5:
                score += 2.0
                reason_parts.append(f"див. доходность {c['div_yield']:.1f}%")
            elif div_yield > 3:
                score += 1.0
                reason_parts.append(f"див. доходность {c['div_yield']:.1f}%")

            momentum = momentum_fn(c)
            if momentum["bonus"]:
                score += momentum["bonus"]
                reason_parts.append(momentum["reason"])

            upcoming = dividend_fn(c)
            if upcoming["bonus"]:
                score += upcoming["bonus"]
                reason_parts.append(upcoming["reason"])

            if category == "etf":
                vs = volume_fn(c)
                score += vs
                if c["ticker"] in SAFE_ETFS:
                    score += 1.0
                    reason_parts.append("надёжный БПИФ")

            if category == "bond":
                if c["ticker"] in SAFE_BONDS:
                    score += 2.0
                    reason_parts.append("ОФЗ — госгарантия")
                else:
                    score += 1.0
                    reason_parts.append("корпоративная облигация")

            c["score"] = max(score, 0.0)
            c["reason"] = "; ".join(reason_parts) if reason_parts else "диверсификация"
            c["yield"] = c["div_yield"]

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates

    def _score_candidates(
        self,
        instruments: list[dict[str, Any]],
        category: str,
        budget: float,
        existing: list[dict[str, Any]],
        db: Any,
    ) -> list[dict[str, Any]]:
        existing_tickers = set(e["ticker"] for e in existing)
        existing_tickers_list = list(existing_tickers)
        candidates = self._filter_candidates_by_category(instruments, category)
        if not candidates:
            return []

        from src.analysis.correlation import correlation as corr_analyzer

        return self._score_candidates_core(
            candidates,
            category,
            budget,
            existing_tickers,
            existing_tickers_list,
            risk_fn=lambda c, b: item_risk(c, db, b),
            penalty_fn=lambda t, tl: corr_analyzer.diversification_penalty(t, tl, db),
            dividend_fn=lambda c: self._upcoming_dividend_score(c, db),
            volume_fn=lambda c: self._volume_score(c, db),
            momentum_fn=lambda c: self._momentum_score(c, db),
        )

    def _upcoming_dividend_score(self, inst: dict[str, Any], db: Any) -> dict[str, Any]:
        try:
            divs = db.query(Dividend).filter_by(instrument_id=inst["id"]).order_by(Dividend.date.desc()).limit(2).all()
            if not divs:
                return {"bonus": 0.0, "reason": ""}

            div = divs[0]
            days_since = (date.today() - div.date).days

            gap = 365
            if len(divs) >= 2:
                gap = (divs[0].date - divs[1].date).days

            upcoming_in = gap - days_since
            if 0 < upcoming_in <= 90:
                est_yield = div.amount / inst["last_price"] * 100 if inst.get("last_price") else 0
                if est_yield > 25:
                    logger.warning(
                        "Suspicious div yield %.1f%% for %s (amount=%.4f, price=%s)",
                        est_yield,
                        inst.get("ticker"),
                        div.amount,
                        inst.get("last_price"),
                    )
                return {"bonus": 2.0, "reason": f"ожидаются дивиденды ~{div.amount:.0f} ₽/акц ({est_yield:.1f}%)"}
            if days_since <= 90:
                return {"bonus": 0.5, "reason": "недавние дивиденды"}
            return {"bonus": 0.0, "reason": ""}
        except Exception as e:
            logger.warning("Dividend score failed for %s: %s", inst.get("ticker", "?"), e)
            return {"bonus": 0.0, "reason": ""}

    def _volume_score(self, inst: dict[str, Any], db: Any) -> float:
        try:
            prices = db.query(Price).filter_by(instrument_id=inst["id"]).order_by(Price.date.desc()).limit(20).all()
            if not prices:
                return 0.0
            avg_vol = sum(p.volume or 0 for p in prices) / len(prices)
            if avg_vol > 1_000_000:
                return 2.0
            elif avg_vol > 100_000:
                return 1.0
            return 0.5
        except Exception:
            logger.warning("Failed to get liquidity score", exc_info=True)
            return 0.0

    def _momentum_score(self, inst: dict[str, Any], db: Any) -> dict[str, Any]:
        try:
            prices = db.query(Price).filter_by(instrument_id=inst["id"]).order_by(Price.date.desc()).limit(21).all()
            if not prices or len(prices) < 5:
                return {"bonus": 0.0, "reason": ""}

            closes = [p.close for p in prices if p.close]
            if len(closes) < 5:
                return {"bonus": 0.0, "reason": ""}

            closes = closes[::-1]
            closes_arr = np.array(closes, dtype=float)
            if np.any(closes_arr <= 0):
                return {"bonus": 0.0, "reason": ""}

            x = np.arange(len(closes_arr))
            slope = np.polyfit(x, closes_arr, 1)[0]
            mean_price = float(np.mean(closes_arr))
            normalized_slope = slope / mean_price * 100

            if normalized_slope < -0.8:
                return {"bonus": -1.5, "reason": f"тренд вниз: {normalized_slope:.2f}%/день"}
            if normalized_slope < -0.4:
                return {"bonus": -0.8, "reason": f"тренд вниз: {normalized_slope:.2f}%/день"}
            if normalized_slope < -0.15:
                return {"bonus": -0.3, "reason": f"слабый нисходящий тренд: {normalized_slope:.2f}%/день"}
            if normalized_slope > 0.8:
                return {"bonus": 1.0, "reason": f"тренд вверх: {normalized_slope:.2f}%/день"}
            if normalized_slope > 0.4:
                return {"bonus": 0.5, "reason": f"тренд вверх: {normalized_slope:.2f}%/день"}
            if normalized_slope > 0.15:
                return {"bonus": 0.2, "reason": f"слабый восходящий тренд: {normalized_slope:.2f}%/день"}

            return {"bonus": 0.0, "reason": ""}
        except Exception as e:
            logger.warning("Momentum score failed for %s: %s", inst.get("ticker", "?"), e)
            return {"bonus": 0.0, "reason": ""}

    def _calc_projected_yield(self, plan: dict[str, Any], total: float) -> float:
        monthly = 0.0
        for cat, data in plan.items():
            for item in data.get("items", []):
                ann = item.get("expected_yield", 0) * item["amount"] / 100
                monthly += ann / 12
        return monthly

    def _downtrend_excluded(self, ticker: str, db: Any) -> bool:
        try:
            inst = db.query(Instrument).filter_by(ticker=ticker).first()
            if not inst:
                return False
            prices = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date.desc()).limit(22).all()
            if not prices or len(prices) < 5:
                return False
            closes = [p.close for p in prices if p.close]
            if len(closes) < 5:
                return False
            closes21 = closes[:21]
            change_21d = (closes21[0] / closes21[-1] - 1) * 100 if len(closes21) >= 5 else 0
            if change_21d < -8.0:
                return True
            closes7 = closes[:7]
            change_7d = (closes7[0] / closes7[-1] - 1) * 100 if len(closes7) >= 5 else 0
            if change_7d < -5.0:
                return True
            return False
        except Exception:
            return False

    def recommend(self, capital: float = 0, db: Any = None, exclude: set[str] | None = None) -> list[dict[str, Any]]:
        self._load_profile_from_db()
        should_close = db is None
        if db is None:
            db = get_session()
        try:
            instruments = self._load_instruments(db)
            existing = self._get_current_portfolio(db)
            all_picks = []
            for cat, cfg in self._weights().items():
                candidates = self._score_candidates(instruments, cat, capital or 100_000, existing, db)
                for c in candidates:
                    if exclude and c["ticker"] in exclude:
                        continue
                    if self._downtrend_excluded(c["ticker"], db):
                        continue
                    last_price = c.get("last_price")
                    if last_price and capital > 0 and last_price > capital * 0.8:
                        continue
                    c["category"] = cfg["label"]
                    c["score"] = round(c.get("score", 0), 2)
                    risk = item_risk(c, db, capital)
                    c["risk"] = risk
                    all_picks.append(c)
            all_picks.sort(key=lambda x: x["score"], reverse=True)
            max_picks = ALLOCATOR_RECOMMEND_MAX_PICKS
            for tier in ALLOCATOR_RECOMMEND_TIER_PICKS:
                if capital < tier["max_capital"]:
                    max_picks = tier["max_picks"]
                    break
            return all_picks[:max_picks]
        finally:
            if should_close:
                db.close()

    async def allocate_async(self, capital: float, db: AsyncSession | None = None) -> dict[str, Any]:
        if db is not None:
            logger.warning("allocate_async: AsyncSession ignored, using sync session via run_in_executor")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.allocate, capital, None)


allocator = PortfolioAllocator()
