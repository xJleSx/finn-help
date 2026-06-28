import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date
from typing import Any, AsyncIterator, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import func as sqlfunc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import Instrument, Price, Signal, User
from src.interfaces.api.auth import (
    create_token,
    get_db,
    hash_password,
    require_user,
    verify_password,
)
from src.interfaces.api.routes.analysis import router as analysis_router
from src.interfaces.api.routes_instruments import router as instruments_router
from src.interfaces.api.routes_market import router as market_router
from src.interfaces.api.routes_portfolio import router as portfolio_router
from src.interfaces.api.schemas import AuthTokenResponse, HealthResponse, UserResponse
from src.scheduler.service import run_forever
from src.scheduler.service import stop as stop_scheduler

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from src.db.connection import init_db

    try:
        init_db()
    except Exception as e:
        logger.warning("DB migration failed (may be OK if tables exist): %s", e)
    logger.info("Trade mode: DRY_RUN (set ENABLE_TRADING=true to enable AUTO)")
    scheduler_task = asyncio.create_task(run_forever())
    yield
    stop_scheduler()
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="FinAdvisor API", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
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
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(analysis_router)
app.include_router(instruments_router)
app.include_router(portfolio_router)
app.include_router(market_router)


@app.get("/api/health", response_model=HealthResponse)
async def health(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    healthy = True
    checks: dict[str, str] = {}
    components: dict[str, Any] = {}

    try:
        result = await db.execute(select(sqlfunc.count(Instrument.id)))
        val = result.scalar()
        components["instruments"] = int(val) if val is not None else 0
    except Exception:
        components["instruments"] = None

    try:
        from src.scheduler.service import _running

        components["scheduler_running"] = _running
    except Exception:
        components["scheduler_running"] = None

    try:
        last_signal = await db.execute(select(Signal.date).order_by(Signal.date.desc()).limit(1))
        row: Any = last_signal.scalar_one_or_none()
        if row is not None:
            components["last_signal_at"] = row.isoformat() if hasattr(row, "isoformat") else str(row)
        else:
            components["last_signal_at"] = None
    except Exception:
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
        components["models"] = None

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
async def register(request: Request, body: RegisterBody, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    result = await db.execute(
        select(User).where((User.username == body.username) | ((body.email is not None) & (User.email == body.email)))  # type: ignore[operator]
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
    token = create_token(int(user.id), str(user.username))
    return {"access_token": token, "token_type": "bearer", "user_id": int(user.id), "username": str(user.username)}


class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login", response_model=AuthTokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, body: LoginBody, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, str(user.hashed_password)):
        raise HTTPException(401, "Invalid credentials")
    token = create_token(int(user.id), str(user.username))
    return {"access_token": token, "token_type": "bearer", "user_id": int(user.id), "username": str(user.username)}


@app.get("/api/auth/me", response_model=UserResponse)
async def get_me(user: User = Depends(require_user)) -> dict[str, Any]:
    return {
        "id": int(user.id),
        "username": str(user.username),
        "email": str(user.email) if user.email is not None else None,
        "role": str(user.role),
        "risk_profile": str(user.risk_profile),
        "is_active": bool(user.is_active),
    }
