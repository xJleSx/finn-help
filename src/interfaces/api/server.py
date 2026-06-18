import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import User
from src.interfaces.api.auth import (
    create_token,
    get_current_user,
    get_db,
    hash_password,
    require_user,
    verify_password,
)
from src.interfaces.api.routes_instruments import router as instruments_router
from src.interfaces.api.routes_portfolio import router as portfolio_router
from src.interfaces.api.routes_market import router as market_router
from src.execution.engine import set_mode, TradeMode
from src.scheduler.service import run_forever, stop as stop_scheduler

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.tinkoff_token and settings.tinkoff_sandbox:
        await set_mode(TradeMode.AUTO)
        logger.info("Trade mode set to AUTO (sandbox)")
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
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
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

app.include_router(instruments_router)
app.include_router(portfolio_router)
app.include_router(market_router)


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
        select(User).where((User.username == body.username) | ((body.email is not None) & (User.email == body.email)))
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
