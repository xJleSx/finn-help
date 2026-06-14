import asyncio
import logging
from datetime import date, timedelta

import pandas as pd
from sqlalchemy.orm import Session

from src.collectors.cbr import CBRCollector
from src.collectors.moex import MOEXCollector
from src.collectors.news import NewsCollector
from src.db.connection import get_session
from src.db.models import Dividend, GeoRiskScore, Indicator, Instrument, News, Price
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
        signals = await _generate_signals(db, updated_ids=updated_ids)
        await _notify_signals(signals)
        logger.info("Daily update cycle completed")
    except Exception as e:
        logger.error(f"Daily update cycle failed: {e}")
    finally:
        db.close()


async def _collect_prices(db: Session) -> set[int]:
    updated_ids: set[int] = set()
    async with MOEXCollector() as moex:
        instruments = db.query(Instrument).all()
        for inst in instruments:
            last = db.query(Price.date).filter_by(instrument_id=inst.id).order_by(Price.date.desc()).first()
            from_date = last[0].isoformat() if last else (date.today() - timedelta(days=365)).isoformat()
            board = {"stock": "stock", "bond": "bond", "etf": "etf"}.get(inst.instrument_type, "shares")
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
                updated_ids.add(inst.id)
    return updated_ids


async def _collect_dividends(db: Session):
    async with MOEXCollector() as moex:
        instruments = db.query(Instrument).filter(Instrument.instrument_type.in_(["stock", "etf"])).all()
        for inst in instruments:
            last = db.query(Dividend.date).filter_by(instrument_id=inst.id).order_by(Dividend.date.desc()).first()
            if last:
                continue
            try:
                dividends = await moex.get_dividends(inst.ticker)
                for row in dividends:
                    d = row.get("recordDate") or row.get("recorddate")
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
    for inst in instruments:
        prices = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date).all()
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
    collector = NewsCollector()
    news_list = collector.fetch_all(max_per_feed=5)
    for item in news_list:
        exists = db.query(News).filter_by(url=item["url"]).first()
        if not exists:
            n = News(
                url=item["url"],
                title=item["title"],
                summary=item["summary"],
                source_type=item["source_type"],
                source_name=item["source_name"],
                published_at=item["published_at"],
                sentiment_score=item.get("sentiment_score"),
            )
            db.add(n)
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
            currency_vol = prev_stress * 0.7 + min(usd_rate.get("change_pct", 0) * 5, 2.0) * 0.3
        else:
            currency_vol = min(abs(usd_rate.get("change_pct", 0)) * 5, 2.0)

    risk = geo_risk.score(news_list, currency_volatility=currency_vol)

    today = date.today()
    existing = db.query(GeoRiskScore).filter_by(date=today).first()
    if existing:
        existing.score = risk["score"]
        existing.components_json = risk.get("components")
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

    return analysis_service.analyze_all(db, updated_ids=updated_ids)


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


async def _notify_signals(signals: list[dict]):
    from src.interfaces.telegram import broadcast_daily_summary, broadcast_signal

    for s in signals:
        n = _to_signal_notification(s)
        try:
            await broadcast_signal(n)
        except Exception as e:
            logger.warning(f"Broadcast failed for {s['ticker']}: {e}")

    try:
        await broadcast_daily_summary()
    except Exception as e:
        logger.warning(f"Daily summary broadcast failed: {e}")


def _to_signal_notification(fused: dict):
    from src.notifications import SignalNotification

    return SignalNotification(
        ticker=fused["ticker"],
        action=fused["action"],
        prev_action=None,
        confidence=fused["confidence"],
        weighted_score=fused["weighted_score"],
        reasons=fused.get("reasons", []),
        max_portfolio_pct=fused["max_portfolio_pct"],
    )


def run_daily_sync():
    asyncio.run(daily_update())
