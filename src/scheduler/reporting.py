import logging
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func

from src.db.connection import get_session
from src.db.models import (
    DailyReport,
    GeoRiskScore,
    Indicator,
    Instrument,
    MetricSnapshot,
    Price,
)
from src.db.models import Portfolio as PortModel
from src.db.models import Signal as SignalModel

logger = logging.getLogger(__name__)


async def take_snapshot(period: str) -> None:
    """Снять срез метрик для всех инструментов.
    period: 'daily' | 'weekly' | 'monthly'
    """
    db = get_session()
    try:
        instruments = db.query(Instrument).all()
        if not instruments:
            logger.warning("No instruments for snapshot")
            return

        prev: dict[int, MetricSnapshot] = {}
        for inst in instruments:
            p = (
                db.query(MetricSnapshot)
                .filter(MetricSnapshot.instrument_id == inst.id, MetricSnapshot.period == period)
                .order_by(MetricSnapshot.taken_at.desc())
                .first()
            )
            if p:
                prev[int(inst.id)] = p

        now_utc = datetime.now(timezone.utc)

        market_score_avg: float | None = None
        social_score_avg: float | None = None
        geo_score: float | None = None

        if period == "daily":
            signals_today = db.query(SignalModel).filter(func.date(SignalModel.date) == date.today()).all()
            if signals_today:
                scores = [s.fused_json.get("weighted_score", 0) if s.fused_json else 0 for s in signals_today]
                market_score_avg = round(sum(scores) / len(scores), 4) if scores else None

            try:
                from src.social.sentiment.aggregator import aggregator

                all_tickers = [str(inst.ticker) for inst in instruments if inst.ticker]
                all_social = aggregator.get_all_ticker_sentiments(all_tickers)
                social_with_data = [s for s in all_social.values() if s["count"] > 0]
                if social_with_data:
                    social_score_avg = round(sum(s["score"] for s in social_with_data) / len(social_with_data), 4)
            except Exception:
                pass

            geo_row = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
            if geo_row:
                geo_score = round(float(geo_row.score), 2)

        for inst in instruments:
            last_indicator = (
                db.query(Indicator).filter(Indicator.instrument_id == inst.id).order_by(Indicator.date.desc()).first()
            )
            if not last_indicator:
                continue

            last_price = db.query(Price).filter(Price.instrument_id == inst.id).order_by(Price.date.desc()).first()
            last_signal = (
                db.query(SignalModel)
                .filter(SignalModel.instrument_id == inst.id)
                .order_by(SignalModel.date.desc())
                .first()
            )

            rsi_val = float(last_indicator.rsi) if last_indicator.rsi is not None else None
            macd_line = float(last_indicator.macd_line) if last_indicator.macd_line is not None else None
            macd_signal = float(last_indicator.macd_signal) if last_indicator.macd_signal is not None else None
            macd_hist = float(last_indicator.macd_hist) if last_indicator.macd_hist is not None else None
            sma_20 = float(last_indicator.sma_20) if last_indicator.sma_20 is not None else None
            sma_50 = float(last_indicator.sma_50) if last_indicator.sma_50 is not None else None
            sma_200 = float(last_indicator.sma_200) if last_indicator.sma_200 is not None else None
            price_close = float(last_price.close) if last_price and last_price.close else None

            signal_action: str | None = None
            signal_score: float | None = None
            signal_confidence: float | None = None
            if last_signal and last_signal.fused_json:
                fj = last_signal.fused_json
                signal_action = fj.get("action")
                signal_score = fj.get("weighted_score")
                signal_confidence = fj.get("confidence")

            prev_snap = prev.get(int(inst.id))
            delta_price_pct: float | None = None
            delta_score: float | None = None
            delta_rsi: float | None = None
            delta_action_changed: bool | None = None
            if prev_snap:
                if price_close is not None and prev_snap.price and prev_snap.price > 0:
                    delta_price_pct = round((price_close - prev_snap.price) / prev_snap.price * 100, 2)
                if signal_score is not None and prev_snap.signal_score is not None:
                    delta_score = round(signal_score - prev_snap.signal_score, 4)
                if rsi_val is not None and prev_snap.rsi is not None:
                    delta_rsi = round(rsi_val - prev_snap.rsi, 2)
                if signal_action and prev_snap.signal_action:
                    delta_action_changed = signal_action != prev_snap.signal_action

            snap = MetricSnapshot(
                instrument_id=inst.id,
                taken_at=now_utc,
                period=period,
                price=price_close,
                rsi=rsi_val,
                macd_line=macd_line,
                macd_signal=macd_signal,
                macd_hist=macd_hist,
                sma_20=sma_20,
                sma_50=sma_50,
                sma_200=sma_200,
                signal_action=signal_action,
                signal_score=signal_score,
                signal_confidence=signal_confidence,
                delta_price_pct=delta_price_pct,
                delta_score=delta_score,
                delta_rsi=delta_rsi,
                delta_action_changed=delta_action_changed,
                market_score_avg=market_score_avg,
                social_score_avg=social_score_avg,
                geo_score=geo_score,
            )
            db.add(snap)

        db.commit()
        logger.info("Snapshot %s saved for %d instruments", period, len(instruments))
    except Exception:
        logger.exception("Snapshot %s failed", period)
    finally:
        db.close()


async def generate_daily_report() -> DailyReport | None:
    """Сформировать ежедневный отчёт. Сохраняет в БД и возвращает объект."""
    db = get_session()
    try:
        today = date.today()
        existing = db.query(DailyReport).filter(DailyReport.date == today).first()
        if existing:
            logger.info("Daily report already exists for %s", today)
            return existing

        signals_today = db.query(SignalModel).filter(func.date(SignalModel.date) == today).all()

        total_buy = 0
        total_sell = 0
        total_hold = 0
        scores: list[float] = []
        portfolio_rows: list[dict[str, Any]] = []

        portfolio_tickers = set()
        for p in db.query(PortModel).all():
            inst = db.query(Instrument).filter(Instrument.id == p.instrument_id).first()
            if inst and inst.ticker:
                portfolio_tickers.add(inst.ticker.upper())

        for s in signals_today:
            if not s.fused_json:
                continue
            action = s.fused_json.get("action", "HOLD")
            if action == "BUY":
                total_buy += 1
            elif action == "SELL":
                total_sell += 1
            else:
                total_hold += 1

            score = s.fused_json.get("weighted_score")
            if score is not None and isinstance(score, (int, float)) and not (score != score):
                scores.append(float(score))

            ticker = s.fused_json.get("ticker", "")
            if ticker and ticker.upper() in portfolio_tickers:
                prev_snap = (
                    db.query(MetricSnapshot)
                    .filter(MetricSnapshot.instrument_id == s.instrument_id, MetricSnapshot.period == "daily")
                    .order_by(MetricSnapshot.taken_at.desc())
                    .first()
                )
                portfolio_rows.append(
                    {
                        "ticker": ticker.upper(),
                        "action": action,
                        "confidence": s.fused_json.get("confidence", 0),
                        "score_delta": prev_snap.delta_score if prev_snap else None,
                    }
                )

        market_avg = round(sum(scores) / len(scores), 4) if scores else None
        if market_avg is not None:
            trend = "up" if market_avg > 0.02 else ("down" if market_avg < -0.02 else "flat")
        else:
            trend = "flat"

        text_lines = [f"📅 *Отчёт за {today.isoformat()}*"]
        text_lines.append("")

        trend_labels = {"up": "был позитивным", "down": "был негативным", "flat": "оставался нейтральным"}
        if market_avg is not None:
            emoji = "🟢" if trend == "up" else ("🔴" if trend == "down" else "🟡")
            text_lines.append(f"{emoji} *Рынок*: {trend_labels.get(trend, trend)}")

        text_lines.append("")
        action_emojis = {"BUY": "✅", "SELL": "🔴", "CAUTIOUS_BUY": "🟡", "HOLD": "⚪", "NEUTRAL": "⚪"}
        text_lines.append("*Сигналы за день:*")
        text_lines.append(f"  {action_emojis.get('BUY', '')} К покупке: {total_buy}")
        text_lines.append(f"  {action_emojis.get('SELL', '')} К продаже: {total_sell}")
        text_lines.append(f"  {action_emojis.get('HOLD', '')} Нейтрально / держать: {total_hold}")

        if portfolio_rows:
            text_lines.append("")
            text_lines.append("📂 *Ваш портфель:*")
            for pr in portfolio_rows:
                emoji = action_emojis.get(pr["action"], "⚪")
                action_labels = {
                    "BUY": "можно покупать",
                    "CAUTIOUS_BUY": "можно рассмотреть",
                    "HOLD": "держать",
                    "SELL": "продавать",
                    "NEUTRAL": "нейтрально",
                }
                label = action_labels.get(pr["action"], pr["action"])
                text_lines.append(f"  {emoji} *{pr['ticker']}* — {label} (уверенность {pr['confidence']:.0%})")

        report = DailyReport(
            date=today,
            created_at=datetime.now(timezone.utc),
            total_buy=total_buy,
            total_sell=total_sell,
            total_hold=total_hold,
            market_score_avg=market_avg,
            market_score_trend=trend,
            portfolio_signals=portfolio_rows,
            report_text="\n".join(text_lines),
        )
        db.add(report)
        db.commit()
        logger.info("Daily report saved for %s", today)
        return report
    except Exception:
        logger.exception("Failed to generate daily report")
        return None
    finally:
        db.close()


async def generate_weekly_report_text() -> str:
    """Сформировать текст еженедельной сводки (без сохранения, только текст)."""
    db = get_session()
    try:
        instruments = db.query(Instrument).all()
        lines = ["📆 *Недельная сводка*", ""]
        changed: list[str] = []

        for inst in instruments:
            recent = (
                db.query(MetricSnapshot)
                .filter(MetricSnapshot.instrument_id == inst.id, MetricSnapshot.period == "weekly")
                .order_by(MetricSnapshot.taken_at.desc())
                .limit(2)
                .all()
            )
            if len(recent) < 2:
                continue
            curr, prev_snap = recent[0], recent[1]
            ticker = str(inst.ticker or "")

            parts = []
            if curr.delta_price_pct is not None:
                emoji = "🟢" if curr.delta_price_pct > 0 else "🔴"
                parts.append(f"{emoji} цена {curr.delta_price_pct:+.1f}%")
            if curr.delta_rsi is not None:
                parts.append(f"RSI {prev_snap.rsi:.0f}→{curr.rsi:.0f}")
            if curr.delta_action_changed:
                parts.append(f"сигнал {prev_snap.signal_action}→{curr.signal_action}")
            if curr.delta_score is not None:
                parts.append(f"score {curr.delta_score:+.3f}")

            if parts:
                changed.append(f"• *{ticker}*: {' | '.join(parts)}")

        if changed:
            lines.extend(changed)
        else:
            lines.append("Изменений за неделю нет.")

        lines.append("")
        lines.append("💡 Для детального анализа используйте /analyze TICKER")
        return "\n".join(lines)
    except Exception:
        logger.exception("Failed to generate weekly report")
        return "Не удалось сформировать недельную сводку."
    finally:
        db.close()
