import asyncio
import logging
from datetime import date, datetime

import pandas as pd
from sqlalchemy.orm import Session

from src.db.connection import get_session
from src.db.models import Instrument, Price, Indicator, Dividend, Prediction, News, GeoRiskScore
from src.collectors.moex import MOEXCollector
from src.collectors.news import NewsCollector
from src.collectors.cbr import CBRCollector
from src.analysis.technical import TechnicalAnalyzer
from src.analysis.fundamental import FundamentalAnalyzer
from src.analysis.ml.prophet_model import ProphetPredictor
from src.analysis.ml.xgboost_model import XGBoostClassifier
from src.geo.sentiment_divergence import SentimentDivergenceDetector
from src.geo.risk_scorer import GeoRiskScorer
from src.signal.engine import SignalFusionEngine
from src.llm.router import llm

logger = logging.getLogger(__name__)

analyzer = TechnicalAnalyzer()
fundamental = FundamentalAnalyzer()
fusion = SignalFusionEngine()
prophet = ProphetPredictor()
xgb_classifier = XGBoostClassifier()
divergence = SentimentDivergenceDetector()
geo_risk = GeoRiskScorer()


async def daily_update():
    logger.info("Starting daily update cycle...")
    db = get_session()

    try:
        await _collect_prices(db)
        _compute_indicators(db)
        news_list = await _collect_news(db)
        await _compute_geo_risk(db, news_list)
        signals = await _generate_signals(db)
        await _notify_signals(signals)
        logger.info("Daily update cycle completed")
    except Exception as e:
        logger.error(f"Daily update cycle failed: {e}")
    finally:
        db.close()


async def _collect_prices(db: Session):
    async with MOEXCollector() as moex:
        instruments = db.query(Instrument).all()
        for inst in instruments:
            last = db.query(Price.date).filter_by(instrument_id=inst.id).order_by(Price.date.desc()).first()
            from_date = last[0].isoformat() if last else (date.today() - __import__("datetime").timedelta(days=365)).isoformat()
            history = await moex.get_history(inst.ticker, from_date=from_date)
            for row in history:
                d = row.get("TRADEDATE") or row.get("tradedate")
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                if not d:
                    continue
                exists = db.query(Price).filter_by(instrument_id=inst.id, date=d).first()
                if not exists:
                    p = Price(
                        instrument_id=inst.id, date=d,
                        open=row.get("OPEN") or row.get("open"),
                        high=row.get("HIGH") or row.get("high"),
                        low=row.get("LOW") or row.get("low"),
                        close=row.get("CLOSE") or row.get("close"),
                        volume=row.get("VOLUME") or row.get("volume"),
                    )
                    db.add(p)
            db.commit()


def _compute_indicators(db: Session):
    instruments = db.query(Instrument).all()
    for inst in instruments:
        prices = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date).all()
        if len(prices) < 50:
            continue
        df = pd.DataFrame([{
            "date": p.date, "open": p.open, "high": p.high,
            "low": p.low, "close": p.close, "volume": p.volume,
        } for p in prices])
        df = analyzer.compute_all(df)
        for _, row in df.iterrows():
            exists = db.query(Indicator).filter_by(
                instrument_id=inst.id, date=row["date"]
            ).first()
            if exists:
                continue
            ind = Indicator(
                instrument_id=inst.id, date=row["date"],
                rsi=row.get("rsi"), macd_line=row.get("macd_line"),
                macd_signal=row.get("macd_signal"), macd_hist=row.get("macd_hist"),
                sma_20=row.get("sma_20"), sma_50=row.get("sma_50"),
                sma_200=row.get("sma_200"),
                bb_upper=row.get("bb_upper"), bb_lower=row.get("bb_lower"),
                bb_mid=row.get("bb_mid"), volume_sma_20=row.get("volume_sma_20"),
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
        rates = []
    usd_rate = next((r for r in rates if r["code"] == "USD"), None)
    currency_vol = 0.0
    if usd_rate:
        from src.collectors.cbr import CBRCollector as C
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


async def _generate_signals(db: Session) -> list[dict]:
    instruments = db.query(Instrument).all()
    signals = []
    changes = []

    for inst in instruments:
        prices = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date).all()
        if len(prices) < 50:
            continue

        df = pd.DataFrame([{
            "date": p.date, "open": p.open, "high": p.high,
            "low": p.low, "close": p.close, "volume": p.volume,
        } for p in prices])

        df_ind = analyzer.compute_all(df)
        tech_signal = analyzer.generate_signal(df_ind)

        divs = db.query(Dividend).filter_by(instrument_id=inst.id).all()
        div_df = pd.DataFrame([{"date": d.date, "amount": d.amount} for d in divs])
        fund = fundamental.analyze(df, div_df)

        ml_prediction = None
        if len(df) >= 60:
            try:
                prophet_result = prophet.predict(df)
                xgb_result = xgb_classifier.predict(df_ind)
                ml_prediction = prophet_result
                ml_prediction["ml_confidence"] = max(
                    prophet_result.get("confidence", 0),
                    xgb_result.get("confidence", 0),
                )
                ml_prediction["xgb_action"] = xgb_result.get("action", "NEUTRAL")
            except Exception as e:
                logger.warning(f"ML failed for {inst.ticker}: {e}")

        geo = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
        geo_dict = {"score": geo.score} if geo else {"score": 0.0}

        fused = fusion.fuse(
            ticker=inst.ticker,
            technical=tech_signal,
            fundamental=fund,
            geo=geo_dict,
            ml_prediction=ml_prediction,
        )
        fusion.save_signal(db, inst.id, fused)
        signals.append(fused)

    return signals


async def _notify_signals(signals: list[dict]):
    from src.interfaces.telegram import broadcast_signal, broadcast_daily_summary

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
