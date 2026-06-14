import logging
from datetime import date

import numpy as np

from src.db.connection import get_session
from src.db.models import Dividend, Instrument, Price

logger = logging.getLogger(__name__)


KNOWN_DIVIDEND_STOCKS = {
    "SBER": "dividend",
    "GAZP": "dividend",
    "LKOH": "dividend",
    "VTBR": "dividend",
    "MOEX": "growth",
    "NLMK": "dividend",
    "MGNT": "dividend",
    "MTSS": "dividend",
    "SNGS": "dividend",
    "SNGSP": "dividend",
    "TATN": "dividend",
    "RTKM": "dividend",
    "PHOR": "dividend",
    "AFKS": "growth",
}

SECTOR_NAMES = {
    "SBER": "Банки",
    "GAZP": "Нефть и газ",
    "LKOH": "Нефть и газ",
    "VTBR": "Банки",
    "MOEX": "Финансы",
}

SAFE_ETFS = [
    "FXRL",
    "SBMX",
    "TMOS",
    "AKIM",
    "RUSB",
    "TRUR",
]

SAFE_BONDS = [
    "SU26238RMFS5",
    "SU26243RMFS2",
    "SU26248RMFS1",
]


SECTOR_LIMITS = {
    "Нефть и газ": 0.35,
    "Банки": 0.25,
    "Финансы": 0.20,
    "Металлы": 0.20,
    "Телеком": 0.15,
    "IT": 0.15,
    "Потреб": 0.20,
}


class PortfolioAllocator:
    TARGET_WEIGHTS = {
        "etf": {"weight": 0.40, "label": "БПИФ (ETF)", "max": 3},
        "dividend": {"weight": 0.30, "label": "Дивидендные акции", "max": 4},
        "bond": {"weight": 0.20, "label": "Облигации / ОФЗ", "max": 3},
        "growth": {"weight": 0.10, "label": "Акции роста", "max": 2},
    }

    def allocate(self, capital: float, db=None) -> dict:
        should_close = db is None
        if db is None:
            db = get_session()
        try:
            existing = self._get_current_portfolio(db)
            instruments_data = self._load_instruments(db)

            plan = {}
            total_allocated = 0.0
            sector_allocation: dict[str, float] = {}
            if should_close:
                db.close()

            for category, cfg in self.TARGET_WEIGHTS.items():
                budget = capital * cfg["weight"]
                candidates = self._score_candidates(instruments_data, category, budget, existing, db)

                max_positions = cfg["max"]
                if capital < 1000 and budget < 500:
                    max_positions = 1
                elif capital < 3000 and budget < 1000:
                    max_positions = min(max_positions, 2)

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
                    if capital >= 10000 and current_sector_weight > limit:
                        continue

                    sector_allocation[sector] = sector_allocation.get(sector, 0.0) + amount

                    risk = _item_risk(item, db, capital)
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
            if leftover > max(500, capital * 0.1):
                for cat_name in ["etf", "dividend"]:
                    if cat_name in plan and plan[cat_name]["items"]:
                        plan[cat_name]["items"][0]["amount"] = round(plan[cat_name]["items"][0]["amount"] + leftover, 2)
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
        finally:
            if should_close:
                db.close()

    def _get_current_portfolio(self, db) -> list[dict]:
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

    def _load_instruments(self, db) -> list[dict]:
        instruments = db.query(Instrument).all()
        result = []
        for inst in instruments:
            price = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date.desc()).first()
            last_price = price.close if price else None
            sector = SECTOR_NAMES.get(inst.ticker, inst.sector or "")

            div_yield = 0.0
            divs = db.query(Dividend).filter_by(instrument_id=inst.id).order_by(Dividend.date.desc()).limit(4).all()
            if divs and last_price and last_price > 0:
                div_yield = sum(d.amount for d in divs) / last_price * 100

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

    def _score_candidates(
        self,
        instruments: list[dict],
        category: str,
        budget: float,
        existing: list[dict],
        db,
    ) -> list[dict]:
        existing_tickers = set(e["ticker"] for e in existing)
        existing_tickers_list = list(existing_tickers)

        if category == "etf":
            candidates = [i for i in instruments if i["type"] == "etf" and i["last_price"]]
        elif category == "dividend":
            candidates = [i for i in instruments if i["type"] == "stock" and i["is_dividend"] and i["last_price"]]
        elif category == "bond":
            candidates = [i for i in instruments if i["type"] == "bond" and i["last_price"]]
        elif category == "growth":
            candidates = [i for i in instruments if i["type"] == "stock" and i["is_growth"] and i["last_price"]]
        else:
            return []

        from src.analysis.correlation import correlation as corr_analyzer

        for c in candidates:
            score = 0.0
            reason_parts = []

            if c["ticker"] in existing_tickers:
                score += 1.0
                reason_parts.append("уже в портфеле")

            penalty = corr_analyzer.diversification_penalty(c["ticker"], existing_tickers_list, db)
            if penalty > 0:
                score -= penalty
                reason_parts.append("высокая корреляция с портфелем")

            if c["div_yield"] > 5:
                score += 2.0
                reason_parts.append(f"див. доходность {c['div_yield']:.1f}%")
            elif c["div_yield"] > 3:
                score += 1.0
                reason_parts.append(f"див. доходность {c['div_yield']:.1f}%")

            upcoming = self._upcoming_dividend_score(c, db)
            if upcoming["bonus"]:
                score += upcoming["bonus"]
                reason_parts.append(upcoming["reason"])

            if category == "etf":
                volume_score = self._volume_score(c, db)
                score += volume_score
                if c["ticker"] in SAFE_ETFS:
                    score += 2.0
                    reason_parts.append("надёжный БПИФ")

            if category == "bond":
                if c["ticker"] in SAFE_BONDS:
                    score += 2.0
                    reason_parts.append("ОФЗ — госгарантия")
                else:
                    score += 1.0
                    reason_parts.append("корпоративная облигация")

            c["score"] = max(score, 0.1)
            c["reason"] = "; ".join(reason_parts) if reason_parts else "диверсификация"
            c["yield"] = c["div_yield"]

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates

    def _upcoming_dividend_score(self, inst: dict, db) -> dict:
        try:
            div = db.query(Dividend).filter_by(instrument_id=inst["id"]).order_by(Dividend.date.desc()).first()
            if not div:
                return {"bonus": 0.0, "reason": ""}
            days_since = (date.today() - div.date).days
            if 300 < days_since < 400:
                est_yield = div.amount / inst["last_price"] * 100 if inst.get("last_price") else 0
                return {"bonus": 2.0, "reason": f"ожидаются дивиденды ~{div.amount:.0f} ₽/акц ({est_yield:.1f}%)"}
            if days_since <= 90:
                return {"bonus": 0.5, "reason": "недавние дивиденды"}
            return {"bonus": 0.0, "reason": ""}
        except Exception:
            return {"bonus": 0.0, "reason": ""}

    def _volume_score(self, inst: dict, db) -> float:
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

    def _calc_projected_yield(self, plan: dict, total: float) -> float:
        monthly = 0.0
        for cat, data in plan.items():
            for item in data.get("items", []):
                ann = item.get("expected_yield", 0) * item["amount"] / 100
                monthly += ann / 12
        return monthly

    def recommend(self, capital: float = 0, db=None) -> list[dict]:
        should_close = db is None
        if db is None:
            db = get_session()
        try:
            instruments = self._load_instruments(db)
            existing = self._get_current_portfolio(db)
            all_picks = []
            for cat, cfg in self.TARGET_WEIGHTS.items():
                candidates = self._score_candidates(instruments, cat, capital or 100_000, existing, db)
                for c in candidates:
                    c["category"] = cfg["label"]
                    c["score"] = round(c.get("score", 0), 2)
                    all_picks.append(c)
            all_picks.sort(key=lambda x: x["score"], reverse=True)
            return all_picks[:15]
        finally:
            if should_close:
                db.close()


allocator = PortfolioAllocator()


def _item_risk(item: dict, db, capital: float = 100_000) -> dict:
    prices = db.query(Price).filter_by(instrument_id=item["id"]).order_by(Price.date.desc()).limit(60).all()
    if len(prices) < 10:
        return {"var_95": 0.0, "stop_loss_pct": 0.0, "position_limit_pct": 5.0}

    close_vals = [p.close for p in prices if p.close]
    if len(close_vals) < 10:
        return {"var_95": 0.0, "stop_loss_pct": 0.0, "position_limit_pct": 5.0}

    from src.risk.manager import compute_position_size, compute_stop_loss, compute_var

    var = compute_var(close_vals)
    last_price = close_vals[0]

    atr_val = None
    atr_rows = db.query(Price).filter_by(instrument_id=item["id"]).order_by(Price.date.desc()).limit(14).all()
    if len(atr_rows) >= 14:
        highs = np.array([r.high for r in atr_rows if r.high])
        lows = np.array([r.low for r in atr_rows if r.low])
        closes = np.array([r.close for r in atr_rows if r.close])
        if len(highs) >= 14 and len(lows) >= 14 and len(closes) >= 14:
            tr = np.maximum(
                highs[:-1] - lows[:-1],
                np.maximum(
                    abs(highs[:-1] - closes[1:]),
                    abs(lows[:-1] - closes[1:]),
                ),
            )
            atr_val = float(np.mean(tr))

    stop = compute_stop_loss(last_price, atr_val)
    sizing = compute_position_size(
        capital=capital,
        price=last_price,
        risk_per_trade_pct=2.0,
        stop_loss_pct=stop["stop_loss_pct"] if stop else None,
    )

    return {
        "var_95": var.get("var_95", 0.0),
        "var_99": var.get("var_99", 0.0),
        "stop_loss": stop["stop_loss"] if stop else None,
        "stop_loss_pct": stop["stop_loss_pct"] if stop else 0.0,
        "suggested_shares": sizing.get("shares", 0),
        "risk_per_trade_pct": 2.0,
    }
