import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, AsyncIterator, Optional

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from prometheus_client import Counter, Histogram, generate_latest
from pydantic import BaseModel, Field, field_validator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func as sqlfunc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.core.executor import get_executor, shutdown_executor
from src.core.health import health_registry
from src.core.logging import setup_logging
from src.core.sentry import setup_sentry
from src.db.models import Instrument, Price, Signal, User
from src.interfaces.api.auth import (
    blacklist_refresh_token,
    create_token,
    decode_refresh_token,
    get_db,
    is_refresh_token_blacklisted,
    require_user,
)
from src.interfaces.api.dependencies import get_auth_service
from src.interfaces.api.rate_limiter import limiter
from src.interfaces.api.routes.alert_preferences import router as alert_prefs_router
from src.interfaces.api.routes.analysis import router as analysis_router
from src.interfaces.api.routes.backtest import router as backtest_router
from src.interfaces.api.routes.paper_trading import router as paper_trading_router
from src.interfaces.api.routes.trading_v2 import router as trading_v2_router
from src.interfaces.api.routes_instruments import router as instruments_router
from src.interfaces.api.routes_market import router as market_router
from src.interfaces.api.routes_portfolio import router as portfolio_router
from src.interfaces.api.schemas import AuthTokenResponse, HealthResponse, UserResponse
from src.scheduler.service import run_forever
from src.scheduler.service import stop as stop_scheduler

PRODUCTION = os.getenv("FINN_ENV", "").lower() == "production"

logger = structlog.get_logger(__name__)

HTTP_REQUESTS = Counter("http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"])
HTTP_LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency", ["method", "endpoint"])


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    from src.core.container import wire

    wire()
    from src.core.tracing import setup_tracing

    setup_tracing("finn-help")
    from src.db.connection import close_db, init_db

    try:
        init_db()
    except Exception as e:
        log = structlog.get_logger("finn-help")
        log.warning("db_migration_failed", error=str(e))
    setup_sentry()
    logger.info("startup.trade_mode", mode="DRY_RUN" if not settings.enable_trading else "AUTO")
    scheduler_task = asyncio.create_task(run_forever())
    yield
    logger.info("shutdown.stopping_scheduler")
    stop_scheduler()
    scheduler_task.cancel()
    try:
        await asyncio.wait_for(scheduler_task, timeout=10.0)
    except asyncio.CancelledError:
        pass
    except asyncio.TimeoutError:
        logger.warning("shutdown.scheduler_timeout")

    loop = asyncio.get_running_loop()
    try:
        from src.cache import close_redis

        await loop.run_in_executor(get_executor(), close_redis)
    except Exception:
        logger.exception("Unhandled exception")
        pass
    await loop.run_in_executor(get_executor(), close_db)
    shutdown_executor()
    logger.info("shutdown.complete")


app = FastAPI(title="FinAdvisor API", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    try:
        import sentry_sdk

        sentry_sdk.set_context("request", {"method": request.method, "path": request.url.path})
        if hasattr(request, "user") and request.user:
            sentry_sdk.set_user({"id": str(request.user.id), "username": request.user.username})
    except Exception:
        logger.exception("Unhandled exception")
        pass
    logger.exception("unhandled_exception", method=request.method, path=request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


origins = [o.strip() for o in settings.cors_origins.split(",")]
allow_creds = False
if "*" in origins:
    if len(origins) > 1:
        origins = [o for o in origins if o != "*"]
else:
    allow_creds = settings.cors_credentials
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_creds,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next: Any) -> Response:
    nonce = secrets.token_urlsafe(16)
    request.state.nonce = nonce

    if PRODUCTION:
        style_src = f"'self' 'nonce-{nonce}'"
        script_src = f"'self' 'nonce-{nonce}'"
    else:
        style_src = "'self' 'unsafe-inline'"
        script_src = "'self' 'unsafe-inline'"

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        f"default-src 'self'; "
        f"script-src {script_src}; "
        f"style-src {style_src}; "
        f"img-src 'self' data:; "
        f"font-src 'self'; "
        f"connect-src 'self'; "
        f"form-action 'self'; "
        f"base-uri 'self'; "
        f"frame-ancestors 'none'"
    )
    return response


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next: Any) -> Response:
    with HTTP_LATENCY.labels(method=request.method, endpoint=request.url.path).time():
        response = await call_next(request)
    HTTP_REQUESTS.labels(method=request.method, endpoint=request.url.path, status=response.status_code).inc()
    return response


app.include_router(alert_prefs_router)
app.include_router(analysis_router)
app.include_router(backtest_router)
app.include_router(paper_trading_router)
app.include_router(trading_v2_router)
app.include_router(instruments_router)
app.include_router(portfolio_router)
app.include_router(market_router)


@app.get("/metrics")
async def metrics(request: Request) -> Response:
    token = settings.metrics_token
    if not token:
        logger.warning("METRICS_TOKEN not set — /metrics only accessible from localhost")
        host = request.client.host if request.client else ""
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise HTTPException(status_code=403, detail="Forbidden")
        return PlainTextResponse(generate_latest().decode("utf-8"), media_type="text/plain")

    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {token}":
        raise HTTPException(status_code=403, detail="Forbidden")
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type="text/plain")


class RefreshBody(BaseModel):
    refresh_token: str


@app.post("/api/auth/refresh")
@limiter.limit("10/minute")
async def refresh_token(
    request: Request,
    body: RefreshBody,
) -> dict[str, Any]:
    if is_refresh_token_blacklisted(body.refresh_token):
        raise HTTPException(status_code=401, detail="Refresh token revoked")
    try:
        payload = decode_refresh_token(body.refresh_token)
        user_id = int(payload.get("sub", 0))
        username = str(payload.get("username", ""))
        if not user_id or not username:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        new_token = create_token(user_id, username)
        return {"access_token": new_token, "token_type": "bearer"}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unhandled exception")
        raise HTTPException(status_code=401, detail="Invalid refresh token")


@app.post("/api/auth/logout")
async def logout(
    request: Request,
    body: RefreshBody,
) -> dict[str, str]:
    blacklist_refresh_token(body.refresh_token)
    return {"status": "ok"}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health", response_model=HealthResponse)
async def health(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    healthy = True
    checks: dict[str, str] = {}
    components: dict[str, Any] = {}

    try:
        from src.core.resilience import get_all_circuit_states

        cb_states = get_all_circuit_states()
        if cb_states:
            components["circuit_breakers"] = cb_states
        for name, snap in cb_states.items():
            if snap.get("state") == "open":
                checks[f"circuit_breaker_{name}"] = f"OPEN ({snap.get('failure_count', 0)} failures)"
    except Exception:
        logger.exception("Unhandled exception")
        components["circuit_breakers"] = None

    try:
        result = await db.execute(select(sqlfunc.count(Instrument.id)))
        val = result.scalar()
        components["instruments"] = int(val) if val is not None else 0
    except Exception:
        logger.exception("Unhandled exception")
        components["instruments"] = None

    try:
        from src.scheduler.service import _running

        components["scheduler_running"] = _running
    except Exception:
        logger.exception("Unhandled exception")
        components["scheduler_running"] = None

    try:
        last_signal = await db.execute(select(Signal.date).order_by(Signal.date.desc()).limit(1))
        row: Any = last_signal.scalar_one_or_none()
        if row is not None:
            components["last_signal_at"] = row.isoformat() if hasattr(row, "isoformat") else str(row)
        else:
            components["last_signal_at"] = None
    except Exception:
        logger.exception("Unhandled exception")
        components["last_signal_at"] = None

    try:
        last_price = await db.execute(select(Price.date).order_by(Price.date.desc()).limit(1))
        price_row: Any = last_price.scalar_one_or_none()
        if price_row is not None:
            dt_str = price_row.isoformat() if hasattr(price_row, "isoformat") else str(price_row)
            components["last_price_date"] = dt_str
            try:
                days: int = (date.today() - price_row).days
                components["price_staleness_days"] = days
                if days > 2:
                    checks["staleness"] = f"Последняя цена от {dt_str}, {days}д назад"
            except TypeError:
                pass
    except Exception:
        logger.exception("Unhandled exception")
        components["last_price_date"] = None

    try:
        from src.model_registry import _load_registry

        registry = _load_registry()
        if registry:
            models_summary = {}
            for name, entry in registry.items():
                latest = entry.get("latest")
                if latest:
                    models_summary[name] = str(latest)
            components["models"] = models_summary
    except Exception:
        logger.exception("Unhandled exception")
        components["models"] = None

    # Enrichment coverage
    try:
        total_inst = components.get("instruments") or 1
        from src.db.models import AltDataPoint, BondOffering, CompanyProfile, CorporateEvent, FinancialReport

        for table, label, model in [
            (CompanyProfile, "profile_coverage", CompanyProfile),
            (FinancialReport, "report_coverage", FinancialReport),
            (BondOffering, "bond_coverage", BondOffering),
            (CorporateEvent, "event_coverage", CorporateEvent),
            (AltDataPoint, "alt_data_count", AltDataPoint),
        ]:
            cnt = await db.execute(select(sqlfunc.count(model.id)))
            cval: Any = cnt.scalar()
            if label.endswith("_coverage") and cval is not None:
                pct = round(cval / total_inst * 100, 1) if total_inst > 0 else 0
                components[label] = f"{cval}/{total_inst} ({pct}%)"
            else:
                components[label] = int(cval) if cval is not None else 0
    except Exception as e:
        logger.warning("Health check component failed: %s", e)

    # Alert stats
    try:
        from src.db.models import AlertLog

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        alert_cnt = await db.execute(select(sqlfunc.count(AlertLog.id)).where(AlertLog.created_at >= cutoff))
        components["alerts_7d"] = int(alert_cnt.scalar() or 0)
    except Exception:
        logger.exception("Unhandled exception")
        components["alerts_7d"] = None

    # Run registered module health checks
    for name, check_fn in health_registry.items():
        if name not in components:
            try:
                components[name] = await check_fn()
            except Exception:
                logger.exception("Unhandled exception")
                components[name] = "error"

    status = "degraded" if checks and healthy else "unhealthy" if not healthy else "ok"
    return {
        "status": status,
        "checks": checks or None,
        "components": components,
    }


class RegisterBody(BaseModel):
    username: str = Field(min_length=3, pattern=r"^[a-zA-Z0-9_]+$")
    password: str
    email: Optional[str] = None
    risk_profile: str = "balanced"

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < settings.password_min_length:
            raise ValueError(f"Password must be at least {settings.password_min_length} characters")
        return v


@app.post("/api/auth/register", response_model=AuthTokenResponse)
@limiter.limit("5/minute")
async def register(
    request: Request,
    body: RegisterBody,
    svc=Depends(get_auth_service),
) -> dict[str, Any]:
    return await svc.register(
        username=body.username,
        password=body.password,
        email=body.email,
        risk_profile=body.risk_profile,
    )


class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login", response_model=AuthTokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginBody,
    svc=Depends(get_auth_service),
) -> dict[str, Any]:
    return await svc.login(username=body.username, password=body.password)


@app.get("/api/auth/me", response_model=UserResponse)
async def get_me(
    user: User = Depends(require_user),
    svc=Depends(get_auth_service),
) -> dict[str, Any]:
    return await svc.get_me(user)
