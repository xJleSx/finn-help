import asyncio
import logging
from datetime import date
from typing import Optional

from src.db.connection import get_session
from src.db.models import Signal as SignalModel, GeoRiskScore, Portfolio, Instrument, Price
from src.notifications import (
    SignalNotification,
    GeoRiskNotification,
    DailySummaryNotification,
)

logger = logging.getLogger(__name__)

ACTION_EMOJI = {
    "BUY": "🟢",
    "CAUTIOUS_BUY": "🟡",
    "HOLD": "⚪",
    "SELL": "🔴",
    "NEUTRAL": "⚪",
}


def format_signal_text(n: SignalNotification) -> str:
    emoji = ACTION_EMOJI.get(n.action, "⚪")
    text = f"{emoji} *{n.ticker}* — {n.action} (уверенность: {n.confidence:.0%})\n"
    if n.prev_action and n.prev_action != n.action:
        text += f"🔄 Было: {n.prev_action} → Стало: {n.action}\n"
    for r in n.reasons[:4]:
        text += f"  • {r}\n"
    text += f"\n💡 Доля: до {n.max_portfolio_pct}% портфеля"
    return text


def format_daily_summary_text(n: DailySummaryNotification) -> str:
    text = (
        f"📊 *Ежедневная сводка — {n.date}*\n\n"
        f"Сигналов обработано: {n.total_signals}\n"
        f"🟢 К покупке: {n.buy_signals}\n"
        f"🔴 К продаже: {n.sell_signals}\n"
        f"🌍 GeoRisk: {n.geo_risk}/10\n"
    )
    if n.top_picks:
        text += f"\n🏆 Лучшие: {', '.join(n.top_picks)}\n"
    if n.portfolio_value:
        text += f"\n💵 Портфель: {n.portfolio_value:,.0f} ₽"
    return text


class NotificationService:
    def get_signal_changes(self) -> list[SignalNotification]:
        db = get_session()
        try:
            daily = date.today()
            recent = (
                db.query(SignalModel)
                .filter(SignalModel.date >= daily)
                .order_by(SignalModel.confidence.desc())
                .all()
            )

            yesterday = date.today()
            prev = (
                db.query(SignalModel)
                .filter(SignalModel.date < yesterday)
                .order_by(SignalModel.date.desc())
                .first()
            )

            changes = []
            for s in recent:
                prev_action = None
                if prev:
                    prev_same = (
                        db.query(SignalModel)
                        .filter(
                            SignalModel.instrument_id == s.instrument_id,
                            SignalModel.date < yesterday,
                        )
                        .order_by(SignalModel.date.desc())
                        .first()
                    )
                    if prev_same:
                        prev_action = prev_same.action

                inst = db.query(Instrument).filter_by(id=s.instrument_id).first()
                if not inst:
                    continue

                fused = s.fused_json or {}
                n = SignalNotification(
                    ticker=inst.ticker,
                    action=s.action,
                    prev_action=prev_action,
                    confidence=s.confidence,
                    weighted_score=fused.get("weighted_score", 0),
                    reasons=fused.get("reasons", []),
                    max_portfolio_pct=fused.get("max_portfolio_pct", 10),
                )
                changes.append(n)
            return changes
        finally:
            db.close()

    def get_geo_change(self) -> Optional[GeoRiskNotification]:
        db = get_session()
        try:
            today_score = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
            if not today_score:
                return None

            prev = (
                db.query(GeoRiskScore)
                .filter(GeoRiskScore.date < today_score.date)
                .order_by(GeoRiskScore.date.desc())
                .first()
            )
            prev_score = prev.score if prev else None

            return GeoRiskNotification(
                score=today_score.score,
                level=today_score.get("level", "LOW") if hasattr(today_score, "get") else "LOW",
                signals=[],
                prev_score=prev_score,
            )
        finally:
            db.close()

    def get_daily_summary(self) -> DailySummaryNotification:
        db = get_session()
        try:
            daily = date.today()
            signals = (
                db.query(SignalModel)
                .filter(SignalModel.date >= daily)
                .all()
            )
            buy = sum(1 for s in signals if s.action in ("BUY", "CAUTIOUS_BUY"))
            sell = sum(1 for s in signals if s.action == "SELL")

            geo = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
            geo_risk = geo.score if geo else 0.0

            top = (
                db.query(SignalModel)
                .filter(SignalModel.date >= daily, SignalModel.action.in_(["BUY", "CAUTIOUS_BUY"]))
                .order_by(SignalModel.confidence.desc())
                .limit(3)
                .all()
            )
            top_tickers = []
            for s in top:
                inst = db.query(Instrument).filter_by(id=s.instrument_id).first()
                if inst:
                    top_tickers.append(inst.ticker)

            total_value = 0.0
            positions = db.query(Portfolio).all()
            for p in positions:
                price = (
                    db.query(Price)
                    .filter_by(instrument_id=p.instrument_id)
                    .order_by(Price.date.desc())
                    .first()
                )
                if price and price.close:
                    total_value += price.close * p.quantity

            return DailySummaryNotification(
                date=daily.isoformat(),
                total_signals=len(signals),
                buy_signals=buy,
                sell_signals=sell,
                geo_risk=geo_risk,
                portfolio_value=total_value if total_value > 0 else None,
                top_picks=top_tickers,
            )
        finally:
            db.close()
