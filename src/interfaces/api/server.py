import asyncio
import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
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

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="FinAdvisor API", version="0.1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


origins = [o.strip() for o in settings.cors_origins.split(",")]
if "*" in origins:
    if len(origins) > 1:
        origins = [o for o in origins if o != "*"]
    else:
        allow_creds = False
else:
    allow_creds = settings.cors_credentials
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_creds,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


class RegisterBody(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    risk_profile: str = "balanced"


@app.post("/api/auth/register")
@limiter.limit("5/minute")
async def register(request: Request, body: RegisterBody, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(
            (User.username == body.username) |
            ((body.email is not None) & (User.email == body.email))
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(400, "Username or email already taken")
    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        risk_profile=body.risk_profile or "balanced",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    token = create_token(user.id, user.username)
    return {"access_token": token, "token_type": "bearer", "user_id": user.id, "username": user.username}


class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
@limiter.limit("10/minute")
async def login(request: Request, body: LoginBody, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    token = create_token(user.id, user.username)
    return {"access_token": token, "token_type": "bearer", "user_id": user.id, "username": user.username}


@app.get("/api/auth/me")
async def get_me(user: User = Depends(require_user)):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "risk_profile": user.risk_profile,
        "is_active": user.is_active,
    }


@app.get("/api/instruments")
async def list_instruments(
    type_filter: Optional[str] = Query(None, alias="type"),
    db: AsyncSession = Depends(get_db),
):
    q = select(Instrument)
    if type_filter:
        q = q.where(Instrument.instrument_type == type_filter)
    q = q.order_by(Instrument.ticker)
    result = await db.execute(q)
    instruments = result.scalars().all()

    output = []
    for inst in instruments:
        price_result = await db.execute(
            select(Price).where(Price.instrument_id == inst.id).order_by(Price.date.desc()).limit(1)
        )
        last_price = price_result.scalar_one_or_none()
        output.append({
            "id": inst.id,
            "ticker": inst.ticker,
            "full_name": inst.full_name,
            "sector": inst.sector,
            "type": inst.instrument_type,
            "last_price": last_price.close if last_price else None,
            "last_date": last_price.date.isoformat() if last_price else None,
        })
    return output


@app.get("/api/instruments/{ticker}")
async def get_instrument(ticker: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
    inst = result.scalar_one_or_none()
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
async def get_prices(
    ticker: str,
    days: int = Query(365, le=365 * 5),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(404, "Instrument not found")

    cutoff = date.today() - timedelta(days=days)
    price_result = await db.execute(
        select(Price)
        .where(Price.instrument_id == inst.id, Price.date >= cutoff)
        .order_by(Price.date)
    )
    prices = price_result.scalars().all()
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
async def get_indicators(
    ticker: str,
    days: int = Query(90),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(404, "Instrument not found")

    cutoff = date.today() - timedelta(days=days)
    ind_result = await db.execute(
        select(Indicator)
        .where(Indicator.instrument_id == inst.id, Indicator.date >= cutoff)
        .order_by(Indicator.date)
    )
    inds = ind_result.scalars().all()
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


async def _resolve_signal(ticker: str, db: AsyncSession) -> tuple[Instrument, dict]:
    result = await db.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(404, "Instrument not found")

    signal_result = await db.execute(
        select(Signal)
        .where(
            Signal.instrument_id == inst.id,
            func.date(Signal.date) == date.today(),
        )
        .order_by(Signal.date.desc())
        .limit(1)
    )
    cached = signal_result.scalar_one_or_none()
    if cached and cached.fused_json:
        return inst, cached.fused_json

    try:
        fused = await analysis_service.analyze_single(db, inst, ticker)
    except ValueError as e:
        raise HTTPException(400, str(e))

    await analysis_service.fusion.save_signal(db, inst.id, fused)
    return inst, fused


@app.get("/api/instruments/{ticker}/signal")
async def get_signal(ticker: str, db: AsyncSession = Depends(get_db)):
    _, fused = await _resolve_signal(ticker, db)
    return fused


@app.get("/api/instruments/{ticker}/advice")
async def get_advice(
    ticker: str,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    _, fused = await _resolve_signal(ticker, db)
    advice = await llm.advise(fused)
    return {"signal": fused, "advice": advice, "user_id": user.id if user else None}


@app.get("/api/news")
async def get_news(limit: int = Query(20, le=100), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(News).order_by(News.published_at.desc()).limit(limit))
    news_list = result.scalars().all()
    return [
        {
            "id": n.id,
            "title": n.title,
            "summary": n.summary[:300] if n.summary else "",
            "source": n.source_name,
            "url": n.url,
            "published_at": n.published_at.isoformat() if n.published_at else None,
        }
        for n in news_list
    ]


@app.get("/api/geo-risk")
async def get_geo_risk(days: int = Query(30), db: AsyncSession = Depends(get_db)):
    cutoff = date.today() - timedelta(days=days)
    result = await db.execute(
        select(GeoRiskScore).where(GeoRiskScore.date >= cutoff).order_by(GeoRiskScore.date)
    )
    scores = result.scalars().all()
    return [
        {
            "date": s.date.isoformat(),
            "score": s.score,
            "components": s.components_json,
        }
        for s in scores
    ]


@app.get("/api/macro")
async def get_macro(db: AsyncSession = Depends(get_db)):
    from src.collectors.macro import MacroCollector
    return await MacroCollector.latest_values_async(db)


@app.get("/api/sectors/performance")
async def get_sector_performance(days: int = Query(30, le=365), db: AsyncSession = Depends(get_db)):
    from src.analysis.sector import sector_analyzer
    return await sector_analyzer.compute_sector_performance_async(db, days=days)


@app.get("/api/sectors/correlation")
async def get_sector_correlation(days: int = Query(90, le=365), db: AsyncSession = Depends(get_db)):
    from src.analysis.sector import sector_analyzer
    return await sector_analyzer.compute_sector_correlation_async(db, days=days)


@app.get("/api/sectors/volatility")
async def get_sector_volatility(days: int = Query(30, le=365), db: AsyncSession = Depends(get_db)):
    from src.analysis.sector import sector_analyzer
    return await sector_analyzer.compute_sector_volatility_async(db, days=days)


@app.get("/api/portfolio")
async def get_portfolio(
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    from src.db.models import Portfolio
    q = select(Portfolio)
    if user:
        q = q.where(Portfolio.user_id == user.id)
    result = await db.execute(q)
    positions = result.scalars().all()

    output = []
    for p in positions:
        inst_result = await db.execute(select(Instrument).where(Instrument.id == p.instrument_id))
        inst = inst_result.scalar_one_or_none()
        price_result = await db.execute(
            select(Price).where(Price.instrument_id == p.instrument_id).order_by(Price.date.desc()).limit(1)
        )
        last_price = price_result.scalar_one_or_none()
        current_price = last_price.close if last_price else 0
        output.append({
            "id": p.id,
            "ticker": inst.ticker if inst else "?",
            "quantity": float(p.quantity),
            "avg_price": float(p.avg_price) if p.avg_price else 0,
            "current_price": float(current_price),
            "value": float(current_price * p.quantity) if current_price and p.quantity else 0,
            "profit_pct": round(((current_price / p.avg_price) - 1) * 100, 2)
            if current_price and p.avg_price
            else 0,
        })
    return output


class AddPositionBody(BaseModel):
    ticker: str
    quantity: float
    avg_price: Optional[float] = None


@app.post("/api/portfolio/add")
async def add_portfolio_position(
    body: AddPositionBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    from src.db.models import Portfolio
    result = await db.execute(select(Instrument).where(Instrument.ticker == body.ticker.upper()))
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(404, "Instrument not found")

    existing_result = await db.execute(
        select(Portfolio).where(Portfolio.user_id == user.id, Portfolio.instrument_id == inst.id)
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        existing.quantity += body.quantity
        if body.avg_price:
            existing.avg_price = body.avg_price
    else:
        pos = Portfolio(user_id=user.id, instrument_id=inst.id, quantity=body.quantity, avg_price=body.avg_price)
        db.add(pos)
    await db.commit()
    return {"status": "ok"}


@app.post("/api/portfolio/allocate")
async def allocate_portfolio(
    capital: float = 50000.0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    from src.portfolio.allocator import allocator
    try:
        result = await allocator.allocate_async(capital, db=db)
        return result
    except Exception as e:
        logger.exception("Allocation failed for capital=%s", capital)
        raise HTTPException(500, f"Allocation failed: {e}")


@app.get("/api/models")
async def list_models():
    from src.model_registry import list_models
    return list_models()


@app.get("/api/reports/portfolio")
async def report_portfolio_csv(
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    from src.db.models import Portfolio
    from src.reports import generate_portfolio_csv

    q = select(Portfolio)
    if user:
        q = q.where(Portfolio.user_id == user.id)
    result = await db.execute(q)
    positions_raw = result.scalars().all()

    positions = []
    for p in positions_raw:
        inst_result = await db.execute(select(Instrument).where(Instrument.id == p.instrument_id))
        inst = inst_result.scalar_one_or_none()
        price_result = await db.execute(
            select(Price).where(Price.instrument_id == p.instrument_id).order_by(Price.date.desc()).limit(1)
        )
        last_price = price_result.scalar_one_or_none()
        current_price = last_price.close if last_price else 0
        positions.append({
            "ticker": inst.ticker if inst else "?",
            "name": inst.full_name if inst else "",
            "quantity": float(p.quantity),
            "avg_price": float(p.avg_price) if p.avg_price else 0,
            "current_price": float(current_price),
            "value": float(current_price * p.quantity) if current_price and p.quantity else 0,
            "profit_pct": round(((current_price / p.avg_price) - 1) * 100, 2) if current_price and p.avg_price else 0,
        })
    csv_content = generate_portfolio_csv(positions)
    return PlainTextResponse(
        csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=portfolio.csv"},
    )


@app.get("/api/reports/signals")
async def report_signals_csv(db: AsyncSession = Depends(get_db)):
    from src.reports import generate_signals_csv

    result = await db.execute(select(Signal).order_by(Signal.date.desc()).limit(50))
    signals = result.scalars().all()
    signal_list = [s.fused_json or {} for s in signals if s.fused_json]
    csv_content = generate_signals_csv(signal_list)
    return PlainTextResponse(
        csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=signals.csv"},
    )


@app.get("/api/reports/sectors")
async def report_sectors_csv(db: AsyncSession = Depends(get_db)):
    from src.reports import generate_sector_report_csv
    from src.analysis.sector import sector_analyzer

    perf = await sector_analyzer.compute_sector_performance_async(db)
    vol = await sector_analyzer.compute_sector_volatility_async(db)
    csv_content = generate_sector_report_csv(perf, vol)
    return PlainTextResponse(
        csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sectors.csv"},
    )


@app.get("/api/alerts/price-targets")
async def get_price_target_alerts():
    from src.notifications.service import notification_service
    alerts = []
    for a in notification_service.check_price_targets():
        alerts.append({
            "ticker": a.ticker,
            "current_price": a.current_price,
            "target_price": a.target_price,
            "target_type": a.target_type,
            "triggered_pct": a.triggered_pct,
        })
    return alerts


@app.get("/api/alerts/divergence/{ticker}")
async def get_divergence_alerts(ticker: str, db: AsyncSession = Depends(get_db)):
    from src.notifications.service import notification_service

    result = await db.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(404, "Instrument not found")

    cutoff = date.today() - timedelta(days=90)
    price_result = await db.execute(
        select(Price).where(Price.instrument_id == inst.id, Price.date >= cutoff).order_by(Price.date)
    )
    prices = price_result.scalars().all()
    closes = [p.close for p in prices if p.close]

    ind_result = await db.execute(
        select(Indicator).where(Indicator.instrument_id == inst.id, Indicator.date >= cutoff).order_by(Indicator.date)
    )
    indicators = ind_result.scalars().all()
    rsi_vals = [i.rsi for i in indicators if i.rsi is not None]
    macd_vals = [i.macd_hist for i in indicators if i.macd_hist is not None]

    alerts = notification_service.check_divergence(ticker, closes, rsi_vals, macd_vals)
    return [
        {"ticker": a.ticker, "divergence_type": a.divergence_type, "indicator": a.indicator, "strength": a.strength}
        for a in alerts
    ]


@app.get("/api/alerts/rebalance")
async def get_rebalance_alerts(db: AsyncSession = Depends(get_db)):
    from src.notifications.service import notification_service
    alerts = notification_service.check_rebalance_async(db)
    return [
        {
            "ticker": a.ticker,
            "current_pct": a.current_pct,
            "target_pct": a.target_pct,
            "deviation_pct": a.deviation_pct,
            "reason": a.reason,
        }
        for a in alerts
    ]


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
            except Exception:
                logger.exception("SSE event error")
            finally:
                db.close()
                close_session()
            await asyncio.sleep(60)

    return EventSourceResponse(generate())
