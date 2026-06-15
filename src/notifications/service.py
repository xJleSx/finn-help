import logging
from datetime import date, timedelta
from typing import Optional

from src.db.connection import get_session
from src.db.models import GeoRiskScore, Instrument, Notification, Portfolio, Price, Subscription
from src.db.models import Signal as SignalModel
from src.notifications import (
    DailySummaryNotification,
    DividendNotification,
    GeoRiskNotification,
    SignalNotification,
)

logger = logging.getLogger(__name__)

ACTION_EMOJI = {
    "BUY": "🟢",
    "CAUTIOUS_BUY": "🟡",
    "HOLD": "⚪",
    "SELL": "🔴",
    "NEUTRAL": "⚪",
}


def _geo_level(score: float) -> str:
    if score < 3:
        return "LOW"
    if score < 5:
        return "MODERATE"
    if score < 7:
        return "HIGH"
    return "CRITICAL"


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
    # --- Subscriptions ---

    VALID_NOTIFY_TYPES = frozenset({"signal", "daily", "geo", "dividend"})

    def subscribe(self, user_id: int, chat_id: int, notify_type: str = "daily") -> None:
        if notify_type not in self.VALID_NOTIFY_TYPES:
            raise ValueError(f"Invalid notify_type: {notify_type}")
        db = get_session()
        try:
            sub = db.query(Subscription).filter_by(user_id=user_id).first()
            if sub:
                setattr(sub, f"notify_{notify_type}", True)
            else:
                kwargs = {f"notify_{notify_type}": True}
                sub = Subscription(user_id=user_id, chat_id=chat_id, **kwargs)
                db.add(sub)
            db.commit()
        except Exception as e:
            logger.error("Failed to subscribe %d: %s", user_id, e)
            db.rollback()
        finally:
            db.close()

    def unsubscribe(self, user_id: int, notify_type: str | None = None) -> None:
        if notify_type is not None and notify_type not in self.VALID_NOTIFY_TYPES:
            raise ValueError(f"Invalid notify_type: {notify_type}")
        db = get_session()
        try:
            sub = db.query(Subscription).filter_by(user_id=user_id).first()
            if sub:
                if notify_type:
                    setattr(sub, f"notify_{notify_type}", False)
                else:
                    db.delete(sub)
                db.commit()
        except Exception as e:
            logger.error("Failed to unsubscribe %d: %s", user_id, e)
            db.rollback()
        finally:
            db.close()

    def get_subscribers(self, notify_type: str = "signal") -> list[tuple[int, int]]:
        db = get_session()
        try:
            col = getattr(Subscription, f"notify_{notify_type}", None)
            if col is None:
                return []
            results = db.query(Subscription.user_id, Subscription.chat_id).filter(col).all()
            return [(r.user_id, r.chat_id) for r in results]
        finally:
            db.close()

    # --- Notification persistence ---

    def save_notification(
        self, user_id: int, notif_type: str, message: str, title: str | None = None, data: dict | None = None
    ) -> None:
        db = get_session()
        try:
            n = Notification(
                user_id=user_id,
                type=notif_type,
                title=title,
                message=message,
                data_json=data,
            )
            db.add(n)
            db.commit()
        except Exception as e:
            logger.error("Failed to save notification: %s", e)
            db.rollback()
        finally:
            db.close()

    def was_signal_sent_today(self, ticker: str, notif_type: str = "signal") -> bool:
        db = get_session()
        try:
            today = date.today()
            count = (
                db.query(Notification)
                .filter(
                    Notification.type == notif_type,
                    Notification.created_at >= today,
                    Notification.title == ticker,
                )
                .count()
            )
            return count > 0
        finally:
            db.close()

    def get_unread_count(self, user_id: int) -> int:
        db = get_session()
        try:
            return db.query(Notification).filter_by(user_id=user_id, read=False).count()
        finally:
            db.close()

    def mark_read(self, user_id: int, notif_id: int | None = None) -> None:
        db = get_session()
        try:
            q = db.query(Notification).filter_by(user_id=user_id, read=False)
            if notif_id:
                q = q.filter(Notification.id == notif_id)
            q.update({"read": True})
            db.commit()
        except Exception as e:
            logger.error("Failed to mark notifications read: %s", e)
            db.rollback()
        finally:
            db.close()

    # --- Signal changes ---

    def get_signal_changes(self) -> list[SignalNotification]:
        db = get_session()
        try:
            daily = date.today()
            recent = (
                db.query(SignalModel).filter(SignalModel.date >= daily).order_by(SignalModel.confidence.desc()).all()
            )

            changes = []
            for s in recent:
                prev_same = (
                    db.query(SignalModel)
                    .filter(
                        SignalModel.instrument_id == s.instrument_id,
                        SignalModel.date < daily,
                    )
                    .order_by(SignalModel.date.desc())
                    .first()
                )
                prev_action = prev_same.action if prev_same else None

                inst = db.query(Instrument).filter_by(id=s.instrument_id).first()
                if not inst:
                    continue

                if self.was_signal_sent_today(inst.ticker):
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

    # --- Geo risk ---

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
                level=_geo_level(today_score.score),
                signals=[],
                prev_score=prev_score,
            )
        finally:
            db.close()

    # --- Dividends ---

    def get_upcoming_dividends(self, days_ahead: int = 14) -> list[DividendNotification]:
        from src.db.models import Dividend

        db = get_session()
        try:
            cutoff = date.today() + timedelta(days=days_ahead)
            upcoming = (
                db.query(Dividend)
                .filter(Dividend.date.between(date.today(), cutoff))
                .order_by(Dividend.date)
                .all()
            )
            result = []
            for d in upcoming:
                inst = db.query(Instrument).filter_by(id=d.instrument_id).first()
                if not inst:
                    continue
                price = (
                    db.query(Price)
                    .filter_by(instrument_id=d.instrument_id)
                    .order_by(Price.date.desc())
                    .first()
                )
                yield_pct = (d.amount / price.close * 100) if price and price.close else None
                result.append(
                    DividendNotification(
                        ticker=inst.ticker,
                        amount=d.amount,
                        ex_date=d.date.isoformat() if hasattr(d.date, "isoformat") else str(d.date),
                        yield_pct=round(yield_pct, 2) if yield_pct else None,
                    )
                )
            return result
        finally:
            db.close()

    # --- Daily summary ---

    def get_daily_summary(self) -> DailySummaryNotification:
        db = get_session()
        try:
            daily = date.today()
            signals = db.query(SignalModel).filter(SignalModel.date >= daily).all()
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
                price = db.query(Price).filter_by(instrument_id=p.instrument_id).order_by(Price.date.desc()).first()
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
