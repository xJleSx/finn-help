import asyncio
import logging
import os
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from src.db.connection import get_session
from src.db.models import Instrument, Price, Indicator, Signal, News, GeoRiskScore, Dividend as DivModel
from src.analysis.technical import TechnicalAnalyzer
from src.analysis.fundamental import FundamentalAnalyzer
from src.signal.engine import SignalFusionEngine
from src.llm.router import llm
from src.analysis.ml.prophet_model import ProphetPredictor
from src.analysis.ml.xgboost_model import XGBoostClassifier

logger = logging.getLogger(__name__)

app = FastAPI(title="FinAdvisor API", version="0.1.0")

origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

analyzer = TechnicalAnalyzer()
fundamental = FundamentalAnalyzer()
fusion = SignalFusionEngine()
prophet = ProphetPredictor()
xgb_classifier = XGBoostClassifier()


def get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/instruments")
def list_instruments(type_filter: Optional[str] = Query(None, alias="type"), db: Session = Depends(get_db)):
    q = db.query(Instrument)
    if type_filter:
        q = q.filter_by(instrument_type=type_filter)
    instruments = q.order_by(Instrument.ticker).all()

    result = []
    for inst in instruments:
        last_price = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date.desc()).first()
        result.append({
            "id": inst.id,
            "ticker": inst.ticker,
            "full_name": inst.full_name,
            "sector": inst.sector,
            "type": inst.instrument_type,
            "last_price": last_price.close if last_price else None,
            "last_date": last_price.date.isoformat() if last_price else None,
        })
    return result


@app.get("/api/instruments/{ticker}")
def get_instrument(ticker: str, db: Session = Depends(get_db)):
    inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
    if not inst:
        raise HTTPException(404, "Instrument not found")
    return {
        "id": inst.id,
        "ticker": inst.ticker,
        "full_name": inst.full_name,
        "isin": inst.isin,
        "sector": inst.sector,
        "type": inst.instrument_type,
        "lot_size": inst.lot_size,
        "currency": inst.currency,
    }


@app.get("/api/instruments/{ticker}/prices")
def get_prices(ticker: str, days: int = Query(365, le=365 * 5), db: Session = Depends(get_db)):
    inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
    if not inst:
        raise HTTPException(404, "Instrument not found")

    cutoff = date.today() - timedelta(days=days)
    prices = db.query(Price).filter(
        Price.instrument_id == inst.id, Price.date >= cutoff
    ).order_by(Price.date).all()

    return [{
        "date": p.date.isoformat(),
        "open": p.open,
        "high": p.high,
        "low": p.low,
        "close": p.close,
        "volume": p.volume,
    } for p in prices]


@app.get("/api/instruments/{ticker}/indicators")
def get_indicators(ticker: str, days: int = Query(90), db: Session = Depends(get_db)):
    inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
    if not inst:
        raise HTTPException(404, "Instrument not found")

    cutoff = date.today() - timedelta(days=days)
    inds = db.query(Indicator).filter(
        Indicator.instrument_id == inst.id, Indicator.date >= cutoff
    ).order_by(Indicator.date).all()

    return [{
        "date": i.date.isoformat(),
        "rsi": i.rsi,
        "macd_line": i.macd_line,
        "macd_signal": i.macd_signal,
        "macd_hist": i.macd_hist,
        "sma_20": i.sma_20,
        "sma_50": i.sma_50,
        "sma_200": i.sma_200,
        "bb_upper": i.bb_upper,
        "bb_lower": i.bb_lower,
        "bb_mid": i.bb_mid,
        "volume_sma_20": i.volume_sma_20,
        "atr": i.atr,
    } for i in inds]


@app.get("/api/instruments/{ticker}/signal")
def get_signal(ticker: str, db: Session = Depends(get_db)):
    inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
    if not inst:
        raise HTTPException(404, "Instrument not found")

    cached = db.query(Signal).filter(
        Signal.instrument_id == inst.id,
        func.date(Signal.date) == date.today(),
    ).order_by(Signal.date.desc()).first()
    if cached and cached.fused_json:
        return cached.fused_json

    prices = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date).all()
    if len(prices) < 50:
        raise HTTPException(400, "Not enough data")

    df = pd.DataFrame([{
        "date": p.date, "open": p.open, "high": p.high,
        "low": p.low, "close": p.close, "volume": p.volume,
    } for p in prices])

    ind_rows = db.query(Indicator).filter_by(instrument_id=inst.id).order_by(Indicator.date).all()
    if len(ind_rows) < 2:
        raise HTTPException(400, "Not enough indicator data")

    ind_df = pd.DataFrame([{
        "date": r.date,
        "rsi": r.rsi, "macd_line": r.macd_line,
        "macd_signal": r.macd_signal, "macd_hist": r.macd_hist,
        "sma_20": r.sma_20, "sma_50": r.sma_50, "sma_200": r.sma_200,
        "bb_upper": r.bb_upper, "bb_lower": r.bb_lower, "bb_mid": r.bb_mid,
        "volume_sma_20": r.volume_sma_20, "atr": r.atr,
    } for r in ind_rows])

    tech_signal = analyzer.generate_signal(ind_df)

    divs = db.query(DivModel).filter_by(instrument_id=inst.id).all()
    div_df = pd.DataFrame([{"date": d.date, "amount": d.amount} for d in divs]) if divs else pd.DataFrame()
    fund = fundamental.analyze(df, div_df)

    geo = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
    geo_dict = {"score": geo.score} if geo else {"score": 0.0}

    ml_prediction = None
    if len(df) >= 60:
        try:
            pr = prophet.predict(df)
            xr = xgb_classifier.predict(ind_df)
            ml_prediction = pr
            ml_prediction["ml_confidence"] = max(pr.get("confidence", 0), xr.get("confidence", 0))
        except Exception:
            logger.warning("ML prediction failed for %s", ticker, exc_info=True)

    fused = fusion.fuse(
        ticker=ticker.upper(),
        technical=tech_signal,
        fundamental=fund,
        geo=geo_dict,
        ml_prediction=ml_prediction,
    )

    fusion.save_signal(db, inst.id, fused)

    return fused


@app.get("/api/instruments/{ticker}/advice")
async def get_advice(ticker: str, db: Session = Depends(get_db)):
    inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
    if not inst:
        raise HTTPException(404, "Instrument not found")

    cached = db.query(Signal).filter(
        Signal.instrument_id == inst.id,
        func.date(Signal.date) == date.today(),
    ).order_by(Signal.date.desc()).first()
    if cached and cached.fused_json:
        advice = await llm.advise(cached.fused_json)
        return {"signal": cached.fused_json, "advice": advice}

    prices = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date).all()
    if len(prices) < 50:
        raise HTTPException(400, "Not enough data")

    df = pd.DataFrame([{
        "date": p.date, "open": p.open, "high": p.high,
        "low": p.low, "close": p.close, "volume": p.volume,
    } for p in prices])

    ind_rows = db.query(Indicator).filter_by(instrument_id=inst.id).order_by(Indicator.date).all()
    if len(ind_rows) < 2:
        raise HTTPException(400, "Not enough indicator data")

    ind_df = pd.DataFrame([{
        "date": r.date,
        "rsi": r.rsi, "macd_line": r.macd_line,
        "macd_signal": r.macd_signal, "macd_hist": r.macd_hist,
        "sma_20": r.sma_20, "sma_50": r.sma_50, "sma_200": r.sma_200,
        "bb_upper": r.bb_upper, "bb_lower": r.bb_lower, "bb_mid": r.bb_mid,
        "volume_sma_20": r.volume_sma_20, "atr": r.atr,
    } for r in ind_rows])

    tech_signal = analyzer.generate_signal(ind_df)
    divs = db.query(DivModel).filter_by(instrument_id=inst.id).all()
    div_df = pd.DataFrame([{"date": d.date, "amount": d.amount} for d in divs]) if divs else pd.DataFrame()
    fund = fundamental.analyze(df, div_df)
    geo = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
    geo_dict = {"score": geo.score} if geo else {"score": 0.0}

    ml_prediction = None
    if len(df) >= 60:
        try:
            pr = prophet.predict(df)
            xr = xgb_classifier.predict(ind_df)
            ml_prediction = pr
            ml_prediction["ml_confidence"] = max(pr.get("confidence", 0), xr.get("confidence", 0))
        except Exception:
            logger.warning("ML prediction failed for %s", ticker, exc_info=True)

    fused = fusion.fuse(
        ticker=ticker.upper(),
        technical=tech_signal,
        fundamental=fund,
        geo=geo_dict,
        ml_prediction=ml_prediction,
    )

    fusion.save_signal(db, inst.id, fused)

    advice = await llm.advise(fused)
    return {"signal": fused, "advice": advice}


@app.get("/api/news")
def get_news(limit: int = Query(20, le=100), db: Session = Depends(get_db)):
    news = db.query(News).order_by(News.published_at.desc()).limit(limit).all()
    return [{
        "id": n.id,
        "title": n.title,
        "summary": n.summary[:300] if n.summary else "",
        "source": n.source_name,
        "url": n.url,
        "published_at": n.published_at.isoformat() if n.published_at else None,
    } for n in news]


@app.get("/api/geo-risk")
def get_geo_risk(days: int = Query(30), db: Session = Depends(get_db)):
    cutoff = date.today() - timedelta(days=days)
    scores = db.query(GeoRiskScore).filter(
        GeoRiskScore.date >= cutoff
    ).order_by(GeoRiskScore.date).all()
    return [{
        "date": s.date.isoformat(),
        "score": s.score,
        "components": s.components_json,
    } for s in scores]


@app.get("/api/portfolio")
def get_portfolio(db: Session = Depends(get_db)):
    from src.db.models import Portfolio, Transaction
    positions = db.query(Portfolio).all()
    result = []
    for p in positions:
        inst = db.query(Instrument).filter_by(id=p.instrument_id).first()
        last_price = db.query(Price).filter_by(instrument_id=p.instrument_id).order_by(Price.date.desc()).first()
        result.append({
            "ticker": inst.ticker if inst else "?",
            "quantity": float(p.quantity),
            "avg_price": float(p.avg_price) if p.avg_price else 0,
            "current_price": float(last_price.close) if last_price and last_price.close else 0,
            "value": float(last_price.close * p.quantity) if last_price and last_price.close and p.quantity else 0,
            "profit_pct": round(((last_price.close / p.avg_price) - 1) * 100, 2) if last_price and last_price.close and p.avg_price else 0,
        })
    return result


@app.post("/api/portfolio/allocate")
def allocate_portfolio(capital: float = 50000.0):
    from src.portfolio.allocator import allocator
    try:
        result = allocator.allocate(capital)
        return result
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Allocation failed")
        raise HTTPException(500, f"Allocation failed: {e}")


@app.get("/api/events")
async def event_stream():
    async def generate():
        while True:
            db = get_session()
            try:
                inst_count = db.query(Instrument).count()
                signal_count = db.query(Signal).count()
                latest_signal = db.query(Signal).order_by(Signal.date.desc()).first()
                yield {
                    "data": {
                        "instruments": inst_count,
                        "signals": signal_count,
                        "last_update": latest_signal.date.isoformat() if latest_signal else None,
                        "timestamp": date.today().isoformat(),
                    }
                }
            finally:
                db.close()
            await asyncio.sleep(60)

    return EventSourceResponse(generate())
