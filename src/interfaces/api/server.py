import asyncio
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from src.db.connection import get_session
from src.db.models import Instrument, Price, Indicator, Signal, News, GeoRiskScore
from src.collectors.moex import MOEXCollector
from src.analysis.technical import TechnicalAnalyzer
from src.analysis.fundamental import FundamentalAnalyzer
from src.signal.engine import SignalFusionEngine
from src.llm.router import llm

app = FastAPI(title="FinAdvisor API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

analyzer = TechnicalAnalyzer()
fundamental = FundamentalAnalyzer()
fusion = SignalFusionEngine()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/instruments")
def list_instruments(type_filter: Optional[str] = Query(None, alias="type")):
    db = get_session()
    try:
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
    finally:
        db.close()


@app.get("/api/instruments/{ticker}")
def get_instrument(ticker: str):
    db = get_session()
    try:
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
    finally:
        db.close()


@app.get("/api/instruments/{ticker}/prices")
def get_prices(ticker: str, days: int = Query(365, le=365 * 5)):
    db = get_session()
    try:
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
    finally:
        db.close()


@app.get("/api/instruments/{ticker}/indicators")
def get_indicators(ticker: str, days: int = Query(90)):
    db = get_session()
    try:
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
    finally:
        db.close()


@app.get("/api/instruments/{ticker}/signal")
def get_signal(ticker: str):
    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
        if not inst:
            raise HTTPException(404, "Instrument not found")

        prices = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date).all()
        if len(prices) < 50:
            raise HTTPException(400, "Not enough data")

        df = pd.DataFrame([{
            "date": p.date, "open": p.open, "high": p.high,
            "low": p.low, "close": p.close, "volume": p.volume,
        } for p in prices])

        df_ind = analyzer.compute_all(df)
        tech_signal = analyzer.generate_signal(df_ind)

        divs = db.query(Instrument).filter_by(instrument_id=inst.id).all()
        div_df = pd.DataFrame()
        fund = fundamental.analyze(df, div_df)

        geo = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
        geo_dict = {"score": geo.score} if geo else {"score": 0.0}

        fused = fusion.fuse(
            ticker=ticker.upper(),
            technical=tech_signal,
            fundamental=fund,
            geo=geo_dict,
        )

        return fused
    finally:
        db.close()


@app.get("/api/instruments/{ticker}/advice")
async def get_advice(ticker: str):
    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
        if not inst:
            raise HTTPException(404, "Instrument not found")

        prices = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date).all()
        if len(prices) < 50:
            raise HTTPException(400, "Not enough data")

        df = pd.DataFrame([{
            "date": p.date, "open": p.open, "high": p.high,
            "low": p.low, "close": p.close, "volume": p.volume,
        } for p in prices])

        df_ind = analyzer.compute_all(df)
        tech_signal = analyzer.generate_signal(df_ind)
        divs = db.query(Instrument).filter_by(instrument_id=inst.id).all()
        div_df = pd.DataFrame()
        fund = fundamental.analyze(df, div_df)
        geo = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
        geo_dict = {"score": geo.score} if geo else {"score": 0.0}

        fused = fusion.fuse(
            ticker=ticker.upper(),
            technical=tech_signal,
            fundamental=fund,
            geo=geo_dict,
        )

        advice = await llm.advise(fused)
        return {"signal": fused, "advice": advice}
    finally:
        db.close()


@app.get("/api/news")
def get_news(limit: int = Query(20, le=100)):
    db = get_session()
    try:
        news = db.query(News).order_by(News.published_at.desc()).limit(limit).all()
        return [{
            "id": n.id,
            "title": n.title,
            "summary": n.summary[:300] if n.summary else "",
            "source": n.source_name,
            "url": n.url,
            "published_at": n.published_at.isoformat() if n.published_at else None,
        } for n in news]
    finally:
        db.close()


@app.get("/api/geo-risk")
def get_geo_risk(days: int = Query(30)):
    db = get_session()
    try:
        cutoff = date.today() - timedelta(days=days)
        scores = db.query(GeoRiskScore).filter(
            GeoRiskScore.date >= cutoff
        ).order_by(GeoRiskScore.date).all()
        return [{
            "date": s.date.isoformat(),
            "score": s.score,
            "components": s.components_json,
        } for s in scores]
    finally:
        db.close()


@app.get("/api/portfolio")
def get_portfolio():
    from src.db.models import Portfolio, Transaction
    db = get_session()
    try:
        positions = db.query(Portfolio).all()
        result = []
        for p in positions:
            inst = db.query(Instrument).filter_by(id=p.instrument_id).first()
            last_price = db.query(Price).filter_by(instrument_id=p.instrument_id).order_by(Price.date.desc()).first()
            result.append({
                "ticker": inst.ticker if inst else "?",
                "quantity": p.quantity,
                "avg_price": p.avg_price,
                "current_price": last_price.close if last_price else None,
                "value": (last_price.close * p.quantity) if last_price and p.quantity else 0,
                "profit_pct": ((last_price.close / p.avg_price) - 1) * 100 if last_price and p.avg_price else 0,
            })
        return result
    finally:
        db.close()


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
