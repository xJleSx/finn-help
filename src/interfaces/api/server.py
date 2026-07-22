import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import structlog
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from prometheus_client import Counter, Histogram, generate_latest
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src.config import settings
from src.core.executor import get_executor, shutdown_executor
from src.core.logging import setup_logging
from src.core.observability import AsyncTraceMiddleware, setup_metrics, setup_tracing
from src.core.sentry import setup_sentry
from src.interfaces.api.rate_limiter import limiter
from src.interfaces.api.rbac.models import (
    ROLE_PERMISSIONS,
    Permission,
    Role,
    get_current_user_role,
    require_permission,
)
from src.interfaces.api.routes.alert_preferences import router as alert_prefs_router
from src.interfaces.api.routes.analysis import router as analysis_router
from src.interfaces.api.routes.auth import router as auth_router
from src.interfaces.api.routes.backtest import router as backtest_router
from src.interfaces.api.routes.bonds import router as bonds_router
from src.interfaces.api.routes.health import router as health_router
from src.interfaces.api.routes.paper_trading import router as paper_trading_router
from src.interfaces.api.routes.portfolio_bonds import router as portfolio_bonds_router
from src.interfaces.api.routes.trading_v2 import router as trading_v2_router
from src.interfaces.api.routes_instruments import router as instruments_router
from src.interfaces.api.routes_market import router as market_router
from src.interfaces.api.routes_portfolio import router as portfolio_router
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
    setup_tracing("finn-help")
    setup_metrics("finn-help")
    from src.db.connection import close_db, init_db

    try:
        init_db()
    except Exception as e:
        log = structlog.get_logger("finn-help")
        log.warning("db_migration_failed", error=str(e))
    setup_sentry()
    logger.info("startup.trade_mode", mode="DRY_RUN" if not settings.enable_trading else "AUTO")
    use_celery = not settings.celery_task_always_eager and settings.celery_broker_url.startswith("redis")
    if use_celery:
        logger.info("startup.celery_mode", broker=settings.celery_broker_url)
        scheduler_task = None
    else:
        scheduler_task = asyncio.create_task(run_forever())
    yield
    if scheduler_task is not None:
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
    except Exception as e:
        logger.warning("Failed to close Redis: %s", e)
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
    except Exception as e:
        logger.warning("Failed to set Sentry context in error handler: %s", e)
    logger.exception("unhandled_exception", method=request.method, path=request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


origins = [o.strip() for o in (settings.cors_origins or "").split(",") if o.strip()]
allow_creds = settings.cors_credentials and "*" not in origins
if allow_creds and "*" in origins:
    logger.warning("CORS: cannot use credentials with wildcard origins, disabling credentials")
    allow_creds = False
app.add_middleware(AsyncTraceMiddleware)
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
    if not PRODUCTION:
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

RBAC_PROTECTED_PATHS: dict[str, Permission] = {
    "/api/trading": Permission.TRADE_EXECUTE,
    "/api/portfolio": Permission.VIEW_PORTFOLIO,
    "/api/instruments": Permission.VIEW_INSTRUMENTS,
    "/api/analysis": Permission.VIEW_ANALYSIS,
    "/api/alerts": Permission.MANAGE_ALERTS,
}


@app.middleware("http")
async def rbac_middleware(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS":
        return await call_next(request)
    for prefix, perm in RBAC_PROTECTED_PATHS.items():
        if path.startswith(prefix):
            try:
                role = get_current_user_role(request)
                if perm not in ROLE_PERMISSIONS.get(role, set()):
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={"detail": f"Missing required permission: {perm.value}"},
                    )
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
            break
    return await call_next(request)


app.include_router(auth_router)
app.include_router(health_router)
app.include_router(alert_prefs_router)
app.include_router(analysis_router)
app.include_router(backtest_router)
app.include_router(bonds_router)
app.include_router(portfolio_bonds_router)
app.include_router(paper_trading_router)
app.include_router(trading_v2_router)
app.include_router(instruments_router)
app.include_router(portfolio_router)
app.include_router(market_router)
from src.interfaces.api.sse import sse_router
app.include_router(sse_router)


@app.get("/metrics")
async def metrics(request: Request) -> Response:
    token = settings.metrics_token
    if not token:
        logger.warning("METRICS_TOKEN not set — /metrics only accessible from localhost")
        host = getattr(request.client, "host", "unknown")
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise HTTPException(status_code=403, detail="Forbidden")
        return PlainTextResponse(generate_latest().decode("utf-8"), media_type="text/plain")

    auth = request.headers.get("Authorization", "")
    expected = f"Bearer {token}"
    if not secrets.compare_digest(auth, expected):
        raise HTTPException(status_code=403, detail="Forbidden")
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type="text/plain")
