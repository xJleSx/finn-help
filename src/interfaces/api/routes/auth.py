from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from structlog import get_logger

from src.config import settings
from src.db.models import User
from src.interfaces.api.auth import (
    blacklist_refresh_token,
    create_token,
    create_oauth_token,
    decode_refresh_token,
    is_refresh_token_blacklisted,
    oauth_login,
    require_user,
)
from src.interfaces.api.dependencies import get_auth_service
from src.interfaces.api.rate_limiter import limiter
from src.interfaces.api.schemas import AuthTokenResponse, UserResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = get_logger(__name__)


class RefreshBody(BaseModel):
    refresh_token: str


class RegisterBody(BaseModel):
    username: str = Field(min_length=3, pattern=r"^[a-zA-Z0-9_]+$")
    password: str
    email: Optional[str] = None
    risk_profile: str = "balanced"

    @field_validator("password")
    @classmethod
    def password_validator(cls, v: str) -> str:
        if len(v) < settings.password_min_length:
            raise ValueError(f"Password must be at least {settings.password_min_length} characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class LoginBody(BaseModel):
    username: str
    password: str
    totp_code: Optional[str] = None


class TotpCodeBody(BaseModel):
    code: str


class OAuthBody(BaseModel):
    code: str


@router.post("/refresh")
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


@router.post("/logout")
@limiter.limit("10/minute")
async def logout(
    request: Request,
    body: RefreshBody,
) -> dict[str, str]:
    blacklist_refresh_token(body.refresh_token)
    return {"status": "ok"}


@router.post("/register", response_model=AuthTokenResponse)
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


@router.post("/login", response_model=AuthTokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginBody,
    svc=Depends(get_auth_service),
) -> dict[str, Any]:
    return await svc.login(
        username=body.username,
        password=body.password,
        totp_code=body.totp_code,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(
    user: User = Depends(require_user),
    svc=Depends(get_auth_service),
) -> dict[str, Any]:
    return await svc.get_me(user)


@router.post("/totp/setup")
@limiter.limit("5/minute")
async def setup_totp(
    request: Request,
    user: User = Depends(require_user),
    svc=Depends(get_auth_service),
) -> dict[str, Any]:
    return await svc.setup_totp(user)


@router.post("/totp/confirm")
@limiter.limit("5/minute")
async def confirm_totp(
    request: Request,
    body: TotpCodeBody,
    user: User = Depends(require_user),
    svc=Depends(get_auth_service),
) -> dict[str, Any]:
    return await svc.confirm_totp(user, body.code)


@router.post("/totp/disable")
@limiter.limit("3/minute")
async def disable_totp(
    request: Request,
    user: User = Depends(require_user),
    svc=Depends(get_auth_service),
) -> dict[str, Any]:
    return await svc.disable_totp(user)


@router.post("/oauth/{provider}")
@limiter.limit("10/minute")
async def oauth(
    request: Request,
    provider: str,
    body: OAuthBody,
) -> dict[str, Any]:
    return oauth_login(provider, body.code)
