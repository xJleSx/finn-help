import asyncio
import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import func
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from src.analysis.service import analysis_service
from src.config import settings
from src.db.connection import close_session, get_session
from src.db.models import GeoRiskScore, Indicator, Instrument, News, Price, Signal, User
from src.interfaces.api.auth import (
    create_token,
    get_current_user,
    get_db,
    hash_password,
    require_user,
    verify_password,
)
from src.llm.router import llm

logger = logging.getLogger(__name__)

app = FastAPI(title="FinAdvisor API", version="0.1.0")


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


origins = [o.strip() for o in settings.cors_origins.split(",")]
if "*" in origins and origins != ["*"]:
    origins = [o for o in origins if o != "*"]
allow_creds = False if "*" in origins else settings.cors_credentials
if "*" in origins and settings.cors_credentials:
    logger.warning("CORS: allow_origins=* and allow_credentials=True is not allowed by spec, disabling credentials")
    allow_creds = False
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_creds,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


def get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()
        close_session()


@app.get("/api/health")
def health():
    return {"status": "ok"}


class RegisterBody(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    risk_profile: str = "balanced"


@app.post("/api/auth/register")
def register(body: RegisterBody, db: Session = Depends(get_db)):
    existing = db.query(User).filter((User.username == body.username) | ((body.email and User.email == body.email))).first()
    if existing:
        raise HTTPException(400, "Username or email already taken")
    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        risk_profile=body.risk_profile or "balanced",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_token(user.id, user.username)
    return {"access_token": token, "token_type": "bearer", "user_id": user.id, "username": user.username}


class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    token = create_token(user.id, user.username)
    return {"access_token": token, "token_type": "bearer", "user_id": user.id, "username": user.username}


@app.get("/api/auth/me")
def get_me(user: User = Depends(require_user)):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "risk_profile": user.risk_profile,
        "is_active": user.is_active,
    }


@app.get("/api/instruments")
def list_instruments(type_filter: Optional[str] = Query(None, alias="type"), db: Session = Depends(get_db)):
    q = db.query(Instrument)
    if type_filter:
        q = q.filter_by(instrument_type=type_filter)
    instruments = q.order_by(Instrument.ticker).all()

    result = []
    for inst in instruments:
        last_price = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date.desc()).first()
        result.append(
            {
                "id": inst.id,
                "ticker": inst.ticker,
                "full_name": inst.full_name,
                "sector": inst.sector,
                "type": inst.instrument_type,
                "last_price": last_price.close if last_price else None,
                "last_date": last_price.date.isoformat() if last_price else None,
            }
        )
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
    prices = db.query(Price).filter(Price.instrument_id == inst.id, Price.date >= cutoff).order_by(Price.date).all()

    return [
        {
            "date": p.date.isoformat(),
            "open": p.open,
            "high": p.high,
            "low": p.low,
            "close": p.close,
            "volume": p.volume,
        }
        for p in prices
    ]


@app.get("/api/instruments/{ticker}/indicators")
def get_indicators(ticker: str, days: int = Query(90), db: Session = Depends(get_db)):
    inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
    if not inst:
        raise HTTPException(404, "Instrument not found")

    cutoff = date.today() - timedelta(days=days)
    inds = (
        db.query(Indicator)
        .filter(Indicator.instrument_id == inst.id, Indicator.date >= cutoff)
        .order_by(Indicator.date)
        .all()
    )

    return [
        {
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
        }
        for i in inds
    ]


def _resolve_signal(ticker: str, db: Session) -> tuple[Instrument, dict]:
    inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
    if not inst:
        raise HTTPException(404, "Instrument not found")

    cached = (
        db.query(Signal)
        .filter(
            Signal.instrument_id == inst.id,
            func.date(Signal.date) == date.today(),
        )
        .order_by(Signal.date.desc())
        .first()
    )
    if cached and cached.fused_json:
        return inst, cached.fused_json

    try:
        fused = analysis_service.analyze_single(db, inst, ticker)
    except ValueError as e:
        raise HTTPException(400, str(e))

    analysis_service.fusion.save_signal(db, inst.id, fused)
    return inst, fused


@app.get("/api/instruments/{ticker}/signal")
def get_signal(ticker: str, db: Session = Depends(get_db)):
    _, fused = _resolve_signal(ticker, db)
    return fused


@app.get("/api/instruments/{ticker}/advice")
async def get_advice(ticker: str, db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    _, fused = _resolve_signal(ticker, db)
    advice = await llm.advise(fused)
    return {"signal": fused, "advice": advice, "user_id": user.id if user else None}


@app.get("/api/news")
def get_news(limit: int = Query(20, le=100), db: Session = Depends(get_db)):
    news = db.query(News).order_by(News.published_at.desc()).limit(limit).all()
    return [
        {
            "id": n.id,
            "title": n.title,
            "summary": n.summary[:300] if n.summary else "",
            "source": n.source_name,
            "url": n.url,
            "published_at": n.published_at.isoformat() if n.published_at else None,
        }
        for n in news
    ]


@app.get("/api/geo-risk")
def get_geo_risk(days: int = Query(30), db: Session = Depends(get_db)):
    cutoff = date.today() - timedelta(days=days)
    scores = db.query(GeoRiskScore).filter(GeoRiskScore.date >= cutoff).order_by(GeoRiskScore.date).all()
    return [
        {
            "date": s.date.isoformat(),
            "score": s.score,
            "components": s.components_json,
        }
        for s in scores
    ]


@app.get("/api/portfolio")
def get_portfolio(db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    from src.db.models import Portfolio

    q = db.query(Portfolio)
    if user:
        q = q.filter(Portfolio.user_id == user.id)
    positions = q.all()
    result = []
    for p in positions:
        inst = db.query(Instrument).filter_by(id=p.instrument_id).first()
        last_price = db.query(Price).filter_by(instrument_id=p.instrument_id).order_by(Price.date.desc()).first()
        result.append(
            {
                "id": p.id,
                "ticker": inst.ticker if inst else "?",
                "quantity": float(p.quantity),
                "avg_price": float(p.avg_price) if p.avg_price else 0,
                "current_price": float(last_price.close) if last_price and last_price.close else 0,
                "value": float(last_price.close * p.quantity) if last_price and last_price.close and p.quantity else 0,
                "profit_pct": round(((last_price.close / p.avg_price) - 1) * 100, 2)
                if last_price and last_price.close and p.avg_price
                else 0,
            }
        )
    return result


@app.post("/api/portfolio/add")
def add_portfolio_position(
    ticker: str = Query(...),
    quantity: float = Query(...),
    avg_price: Optional[float] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    from src.db.models import Portfolio

    inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
    if not inst:
        raise HTTPException(404, "Instrument not found")
    existing = db.query(Portfolio).filter(Portfolio.user_id == user.id, Portfolio.instrument_id == inst.id).first()
    if existing:
        existing.quantity += quantity
        if avg_price:
            existing.avg_price = avg_price
    else:
        pos = Portfolio(user_id=user.id, instrument_id=inst.id, quantity=quantity, avg_price=avg_price)
        db.add(pos)
    db.commit()
    return {"status": "ok"}


@app.post("/api/portfolio/allocate")
def allocate_portfolio(capital: float = 50000.0, db: Session = Depends(get_db), user: User = Depends(require_user)):
    from src.portfolio.allocator import allocator

    try:
        result = allocator.allocate(capital, db=db)
        return result
    except Exception as e:
        logger.exception("Allocation failed for capital=%s", capital)
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
                close_session()
            await asyncio.sleep(60)

    return EventSourceResponse(generate())
