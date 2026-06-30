from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from src.analysis.fundamental import FundamentalAnalyzer
from src.collectors.news import NewsCollector
from src.constants import NEWS_STALE_HOURS
from src.db.models import Dividend, Indicator, Instrument, News, NewsInstrument, Price
from src.signal.engine import compute_risk_metrics

logger = logging.getLogger(__name__)


class TickerContextBuilder:
    def __init__(self, fundamental: FundamentalAnalyzer | None = None) -> None:
        self._fundamental = fundamental or FundamentalAnalyzer()

    def build(self, db: Any, ticker: str) -> str:
        from src.analysis.loader import data_loader
        from src.analysis.ml_coordinator import ml_coordinator

        inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
        if not inst:
            return ""

        lines = []
        itype = str(inst.instrument_type or "stock")

        lines.append(f"Название: {inst.full_name or '—'}")
        lines.append(f"Сектор: {inst.sector or '—'}")
        lines.append(f"Тип: {itype}")
        lines.append(f"Лот: {inst.lot_size or 1} шт")
        lines.append("")

        prices_q = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date).all()
        if len(prices_q) >= 20:
            closes = [p.close for p in prices_q if p.close]
            if closes:
                last = closes[-1]
                lines.append(f"Текущая цена: {last:.2f} ₽")

                def _add_stats(c: list[float], label: str) -> None:
                    if len(c) < 2:
                        return
                    mn, mx = min(c), max(c)
                    avg = sum(c) / len(c)
                    chg = (c[-1] - c[0]) / c[0] * 100
                    lines.append(f"Цена {label}: мин {mn:.2f}, макс {mx:.2f}, ср {avg:.2f}, изм {chg:+.2f}%")

                _add_stats(closes, "за всё время")
                for period, days in [("1 год", 252), ("6 мес", 126), ("3 мес", 63), ("1 мес", 21), ("1 нед", 7)]:
                    if len(closes) >= days:
                        _add_stats(closes[-days:], f"за {period}")

                ind = db.query(Indicator).filter_by(instrument_id=inst.id).order_by(Indicator.date.desc()).first()
                if ind:
                    lines.append("")
                    if ind.rsi is not None:
                        rsi_label = "перегрет" if ind.rsi > 70 else ("перепродан" if ind.rsi < 30 else "нейтрален")
                        lines.append(f"RSI: {ind.rsi:.1f} ({rsi_label})")
                    if ind.sma_20 is not None:
                        lines.append(f"SMA20: {ind.sma_20:.2f} (цена {'выше' if last > ind.sma_20 else 'ниже'})")
                    if ind.sma_50 is not None:
                        lines.append(f"SMA50: {ind.sma_50:.2f} (цена {'выше' if last > ind.sma_50 else 'ниже'})")
                    if ind.sma_200 is not None:
                        lines.append(f"SMA200: {ind.sma_200:.2f} (цена {'выше' if last > ind.sma_200 else 'ниже'})")
                    if ind.bb_upper is not None and ind.bb_lower is not None:
                        bb_pos = (
                            "у верхней"
                            if last >= ind.bb_upper
                            else ("у нижней" if last <= ind.bb_lower else "в середине")
                        )
                        lines.append(f"Боллинджер: {bb_pos} ({ind.bb_lower:.1f}–{ind.bb_upper:.1f})")
                    if ind.macd_hist is not None:
                        lines.append(f"MACD: {ind.macd_hist:.2f} ({'бычья' if ind.macd_hist > 0 else 'медвежья'})")
                    if ind.atr is not None:
                        lines.append(f"ATR: {ind.atr:.2f}")
                    if ind.volume_sma_20 is not None and prices_q and prices_q[-1].volume:
                        vol_ratio = prices_q[-1].volume / ind.volume_sma_20 if ind.volume_sma_20 > 0 else 1
                        vol_label = "выше" if vol_ratio > 1.2 else ("ниже" if vol_ratio < 0.8 else "около")
                        lines.append(f"Объём: {vol_label} среднего ({vol_ratio:.1f}x)")
            else:
                last = None
        else:
            last = None

        fin = data_loader.load_latest_report_sync(db, inst.id)
        if fin:
            facts = self._fundamental.analyze_report(fin)
            if facts:
                lines.append("")
                lines.append("Финансовая отчётность:")
                for f in facts:
                    lines.append(f"  {f}")

        if itype == "bond":
            bo = data_loader.load_bond_offering_sync(db, inst.id)
            if bo:
                lines.append("")
                lines.append("Параметры выпуска:")
                for k, v in bo.items():
                    if v is not None:
                        lines.append(f"  {k}: {v}")

        divs = db.query(Dividend).filter_by(instrument_id=inst.id).order_by(Dividend.date.desc()).limit(5).all()
        if divs and last and last > 0:
            lines.append("")
            lines.append("Дивиденды (последние):")
            for d in divs:
                yield_pct = d.amount / last * 100
                lines.append(f"  {d.date}: {d.amount:.4f} ₽/акцию (дох-ть {yield_pct:.2f}%)")

        latest_news = (
            db.query(News)
            .join(NewsInstrument, News.id == NewsInstrument.news_id)
            .filter(NewsInstrument.instrument_id == inst.id)
            .order_by(News.created_at.desc())
            .limit(1)
            .first()
        )
        if latest_news:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            created = latest_news.created_at.replace(tzinfo=None) if latest_news.created_at else now
            age_hours = (now - created).total_seconds() / 3600
        else:
            age_hours = float("inf")

        if age_hours > NEWS_STALE_HOURS:
            NewsCollector.collect_for_ticker_sync(db, ticker)

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        recent_news = (
            db.query(News)
            .join(NewsInstrument, News.id == NewsInstrument.news_id)
            .filter(NewsInstrument.instrument_id == inst.id, News.created_at >= cutoff)
            .order_by(News.created_at.desc())
            .limit(10)
            .all()
        )
        if recent_news:
            scores = [n.sentiment_weighted or n.sentiment_score or 0 for n in recent_news]
            avg_sent = sum(scores) / len(scores)
            pos = sum(1 for s in scores if s > 0)
            neg = sum(1 for s in scores if s < 0)
            lines.append("")
            lines.append(f"Новости (30д): {len(recent_news)} шт, сентимент {avg_sent:+.2f} (+{pos}/–{neg})")
            for n in recent_news[:5]:
                s = n.sentiment_weighted or n.sentiment_score or 0
                icon = "🟢" if s > 0 else ("🔴" if s < 0 else "⚪")
                lines.append(f"  {icon} {n.title[:150]}")

        try:
            from src.analysis.service import analysis_service

            fused = analysis_service._analyze_single_sync(db, inst, ticker.upper(), with_ml=True)
            if fused:
                lines.append("")
                lines.append(f"Сигнал: {fused['action']} (уверенность {fused['confidence']:.0%})")
                ml = fused.get("components", {}).get("ml", {})
                if ml and ml.get("change_pct") is not None:
                    lines.append(f"ML прогноз: {ml['change_pct']:+.2f}% (цель {ml.get('target_price', 0):.0f} ₽)")
                rr = fused.get("reasons", [])
                if rr:
                    lines.append("Обоснование:")
                    for r in rr[:5]:
                        lines.append(f"  • {r}")
        except Exception:
            pass

        return "\n".join(lines)


ticker_context_builder = TickerContextBuilder()
