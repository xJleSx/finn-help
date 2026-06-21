import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.collectors.cbr import CBRCollector
from src.collectors.moex import MOEXCollector
from src.collectors.news import NewsCollector
from src.db.connection import get_session
from src.db.models import DailyReport, Dividend, GeoRiskScore, Indicator, Instrument, MetricSnapshot, News, Price
from src.db.models import Portfolio as PortModel
from src.db.models import Signal as SignalModel
from src.geo.risk_scorer import GeoRiskScorer
from src.geo.sentiment_divergence import SentimentDivergenceDetector
from src.signal.engine import SignalFusionEngine

logger = logging.getLogger(__name__)

fusion = SignalFusionEngine()
divergence = SentimentDivergenceDetector()
geo_risk = GeoRiskScorer()


async def daily_update():
    logger.info("Starting daily update cycle...")
    db = get_session()

    try:
        updated_ids = await _collect_prices(db)
        await _collect_dividends(db)
        _compute_indicators(db, instrument_ids=updated_ids)
        news_list = await _collect_news(db)
        await _compute_geo_risk(db, news_list)
        await _collect_macro(db)

        await _collect_social_sentiment()

        db.query(SignalModel).filter(func.date(SignalModel.date) == date.today()).delete()
        db.commit()
        await _generate_signals(db, updated_ids=None)
        logger.info("Daily update cycle completed")
    except Exception as e:
        logger.error(f"Daily update cycle failed: {e}")
    finally:
        db.close()


async def _collect_prices(db: Session) -> set[int]:
    updated_ids: set[int] = set()
    async with MOEXCollector() as moex:
        instruments = db.query(Instrument).all()
        if not instruments:
            return updated_ids

        from sqlalchemy import func as sqlfunc
        last_dates = dict(
            db.query(Price.instrument_id, sqlfunc.max(Price.date)).group_by(Price.instrument_id).all()
        )

        for inst in instruments:
            last_dt = last_dates.get(inst.id)
            from_date = last_dt.isoformat() if last_dt else (date.today() - timedelta(days=365)).isoformat()
            board = {"stock": "stock", "bond": "bond", "etf": "etf"}.get(str(inst.instrument_type), "shares")
            history = await moex.get_history(inst.ticker, from_date=from_date, board=board)
            new_count = 0
            for row in history:
                d = row.get("TRADEDATE") or row.get("tradedate")
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                if not d:
                    continue
                exists = db.query(Price).filter_by(instrument_id=inst.id, date=d).first()
                if not exists:
                    p = Price(
                        instrument_id=inst.id,
                        date=d,
                        open=row.get("OPEN") or row.get("open"),
                        high=row.get("HIGH") or row.get("high"),
                        low=row.get("LOW") or row.get("low"),
                        close=row.get("CLOSE") or row.get("close"),
                        volume=row.get("VOLUME") or row.get("volume"),
                    )
                    db.add(p)
                    new_count += 1
            db.commit()
            if new_count > 0:
                updated_ids.add(int(inst.id))
    return updated_ids


async def _collect_dividends(db: Session):
    async with MOEXCollector() as moex:
        instruments = db.query(Instrument).filter(Instrument.instrument_type.in_(["stock", "etf"])).all()
        if not instruments:
            return

        from sqlalchemy import func as sqlfunc
        last_dates = dict(
            db.query(Dividend.instrument_id, sqlfunc.max(Dividend.date)).group_by(Dividend.instrument_id).all()
        )

        for inst in instruments:
            last_dt = last_dates.get(inst.id)
            if last_dt and (date.today() - last_dt).days < 365:
                continue
            try:
                dividends = await moex.get_dividends(inst.ticker)
                for row in dividends:
                    d = row.get("registryclosedate") or row.get("recordDate") or row.get("recorddate")
                    amt = row.get("value") or row.get("dividendGross")
                    if not d or not amt:
                        continue
                    if isinstance(d, str):
                        d = date.fromisoformat(d)
                    exists = db.query(Dividend).filter_by(instrument_id=inst.id, date=d, amount=float(amt)).first()
                    if not exists:
                        div = Dividend(
                            instrument_id=inst.id,
                            date=d,
                            amount=float(amt),
                            currency="RUB",
                        )
                        db.add(div)
                db.commit()
            except Exception as e:
                logger.warning(f"Dividends failed for {inst.ticker}: {e}")


def _compute_indicators(db: Session, instrument_ids: set[int] | None = None):
    from src.analysis.technical import TechnicalAnalyzer

    analyzer = TechnicalAnalyzer()
    q = db.query(Instrument)
    if instrument_ids is not None:
        q = q.filter(Instrument.id.in_(instrument_ids))
    instruments = q.all()
    if not instruments:
        return

    ids = [inst.id for inst in instruments]
    all_prices = (
        db.query(Price)
        .filter(Price.instrument_id.in_(ids))
        .order_by(Price.instrument_id, Price.date)
        .all()
    )
    prices_by_inst: dict[int, list[Price]] = {}
    for p in all_prices:
        prices_by_inst.setdefault(p.instrument_id, []).append(p)

    for inst in instruments:
        prices = prices_by_inst.get(inst.id, [])
        if len(prices) < 50:
            continue
        df = pd.DataFrame(
            [
                {
                    "date": p.date,
                    "open": p.open,
                    "high": p.high,
                    "low": p.low,
                    "close": p.close,
                    "volume": p.volume,
                }
                for p in prices
            ]
        )
        df = analyzer.compute_all(df)
        for _, row in df.iterrows():
            exists = db.query(Indicator).filter_by(instrument_id=inst.id, date=row["date"]).first()
            if exists:
                continue
            ind = Indicator(
                instrument_id=inst.id,
                date=row["date"],
                rsi=row.get("rsi"),
                macd_line=row.get("macd_line"),
                macd_signal=row.get("macd_signal"),
                macd_hist=row.get("macd_hist"),
                sma_20=row.get("sma_20"),
                sma_50=row.get("sma_50"),
                sma_200=row.get("sma_200"),
                bb_upper=row.get("bb_upper"),
                bb_lower=row.get("bb_lower"),
                bb_mid=row.get("bb_mid"),
                volume_sma_20=row.get("volume_sma_20"),
                atr=row.get("atr"),
            )
            db.add(ind)
        db.commit()


async def _collect_news(db: Session) -> list[dict]:
    from src.db.models import NewsInstrument

    collector = NewsCollector()
    news_list = await collector.fetch_all(max_per_feed=5)

    ticker_map: dict[str, int] = {}
    for inst in db.query(Instrument).all():
        ticker_map[inst.ticker.upper()] = inst.id

    saved_news: list[News] = []
    for item in news_list:
        exists = db.query(News).filter_by(url=item["url"]).first()
        if exists:
            saved_news.append(exists)
            continue
        detail = item.get("sentiment_detail", {})
        n = News(
            url=item["url"],
            title=item["title"],
            summary=item["summary"],
            source_type=item["source_type"],
            source_name=item["source_name"],
            published_at=item["published_at"],
            sentiment_score=item.get("sentiment_score"),
            sentiment_weighted=item.get("sentiment_weighted"),
            sentiment_bert_score=detail.get("bert_score"),
            source_weight=detail.get("source_weight"),
        )
        db.add(n)
        db.flush()
        saved_news.append(n)

    for n in saved_news:
        search_text = f"{n.title or ''} {n.summary or ''}".upper()
        for ticker, inst_id in ticker_map.items():
            if len(ticker) >= 2 and ticker in search_text:
                exists = (
                    db.query(NewsInstrument)
                    .filter_by(news_id=n.id, instrument_id=inst_id)
                    .first()
                )
                if not exists:
                    db.add(NewsInstrument(news_id=n.id, instrument_id=inst_id))

    db.commit()
    return news_list


async def _compute_geo_risk(db: Session, news_list: list[dict]):
    sent = divergence.detect(news_list=news_list)
    cbr = CBRCollector()
    try:
        rates = await cbr.get_rates()
    except Exception:
        logger.warning("Failed to fetch CBR rates", exc_info=True)
        rates = []
    usd_rate = next((r for r in rates if r["code"] == "USD"), None)
    currency_vol = 0.0
    if usd_rate:
        prev = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
        if prev and prev.components_json:
            prev_stress = prev.components_json.get("currency_stress", 0)
            currency_vol = prev_stress * 0.7 + min(abs(usd_rate.get("change_pct", 0)) * 5, 2.0) * 0.3
        else:
            currency_vol = min(abs(usd_rate.get("change_pct", 0)) * 5, 2.0)

    risk = geo_risk.score(news_list, currency_volatility=currency_vol)

    today = date.today()
    existing = db.query(GeoRiskScore).filter_by(date=today).first()
    if existing:
        existing.score = risk["score"]
        existing.components_json = dict(risk.get("components") or {})
        existing.sources_json = {"sentiment_divergence": sent, "news_count": len(news_list)}
    else:
        score = GeoRiskScore(
            date=today,
            score=risk["score"],
            components_json=risk.get("components"),
            sources_json={"sentiment_divergence": sent, "news_count": len(news_list)},
        )
        db.add(score)
    db.commit()


async def _generate_signals(db: Session, updated_ids: set[int] | None = None) -> list[dict]:
    from src.analysis.service import analysis_service

    return analysis_service.analyze_all_sync(db, updated_ids=updated_ids)


async def _collect_macro(db: Session):
    from src.collectors.macro import MacroCollector
    from src.db.models import MacroIndicator

    collector = MacroCollector()
    items = await collector.fetch_all()
    today = date.today()
    for item in items:
        exists = db.query(MacroIndicator).filter_by(date=today, indicator_type=item["indicator_type"]).first()
        if not exists:
            db.add(MacroIndicator(**item))
    db.commit()


async def _collect_social_sentiment():
    from src.social.registry import registry
    from src.social.sentiment.analyzer import analyzer

    try:
        registry.build_from_config()
        sources = registry.get_active()
        if not sources:
            logger.info("No active social sources, skipping social collection")
            return

        from src.db.connection import get_session
        from src.db.models import SocialPost

        for src in sources:
            try:
                posts = await src.fetch_posts()
                db = get_session()
                try:
                    new_count = 0
                    for post in posts:
                        exists = db.query(SocialPost).filter_by(
                            source=post.source, external_id=post.external_id
                        ).first()
                        if exists:
                            continue
                        sp = SocialPost(
                            source=post.source,
                            external_id=post.external_id,
                            author_nick=post.author_nick,
                            author_id=post.author_id,
                            text=post.text,
                            published_at=post.published_at,
                            url=post.url,
                            tickers_mentioned=post.tickers,
                            raw_json=post.raw,
                        )
                        db.add(sp)
                        new_count += 1
                    db.commit()
                    logger.info("Social %s: %d new posts", src.source_name, new_count)
                finally:
                    db.close()
            except Exception as e:
                logger.error("Social collection failed for %s: %s", src.source_name, e)

        count = await analyzer.process_new_posts()
        logger.info("Social sentiment: %d signals created", count)
    except Exception as e:
        logger.error("Social sentiment cycle failed: %s", e)


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

        # Предыдущий срез этого периода для каждого инструмента
        prev: dict[int, MetricSnapshot] = {}
        for inst in instruments:
            p = (
                db.query(MetricSnapshot)
                .filter(MetricSnapshot.instrument_id == inst.id, MetricSnapshot.period == period)
                .order_by(MetricSnapshot.taken_at.desc())
                .first()
            )
            if p:
                prev[inst.id] = p

        now_utc = datetime.now(timezone.utc)

        # Рыночный контекст — один раз для всех
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
                all_tickers = [inst.ticker for inst in instruments if inst.ticker]
                all_social = aggregator.get_all_ticker_sentiments(all_tickers)  # type: ignore[arg-type]
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
                db.query(Indicator)
                .filter(Indicator.instrument_id == inst.id)
                .order_by(Indicator.date.desc())
                .first()
            )
            if not last_indicator:
                continue

            last_price = (
                db.query(Price)
                .filter(Price.instrument_id == inst.id)
                .order_by(Price.date.desc())
                .first()
            )
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

            # Дельта
            prev_snap = prev.get(inst.id)
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
        portfolio_rows: list[dict] = []

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
                portfolio_rows.append({
                    "ticker": ticker.upper(),
                    "action": action,
                    "confidence": s.fused_json.get("confidence", 0),
                    "score_delta": prev_snap.delta_score if prev_snap else None,
                })

        market_avg = round(sum(scores) / len(scores), 4) if scores else None
        if market_avg is not None:
            trend = "up" if market_avg > 0.02 else ("down" if market_avg < -0.02 else "flat")
        else:
            trend = "flat"

        # Формируем текст отчёта
        text_lines = [f"📅 *Отчёт за {today.isoformat()}*"]
        text_lines.append("")
        if market_avg is not None:
            emoji = "🟢" if trend == "up" else ("🔴" if trend == "down" else "🟡")
            text_lines.append(f"{emoji} Рынок: {trend} (средний score {market_avg:+.3f})")
        text_lines.append(f"• BUY: {total_buy}  SELL: {total_sell}  HOLD: {total_hold}")

        if portfolio_rows:
            text_lines.append("")
            text_lines.append("📂 *Позиции портфеля:*")
            for pr in portfolio_rows:
                delta_str = f" ({pr['score_delta']:+.3f})" if pr["score_delta"] is not None else ""
                text_lines.append(f"  {pr['ticker']} — {pr['action']} (уверенность {pr['confidence']:.0%}){delta_str}")

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


def run_daily_sync():
    asyncio.run(daily_update())
