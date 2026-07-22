from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import hmac

import structlog
from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.core.totp import (
    generate_recovery_codes,
    generate_secret,
    get_totp_uri,
    hash_recovery_code,
    verify_recovery_code,
    verify_totp,
)
from src.db.models import User
from src.interfaces.api.auth import create_refresh_token, create_token, hash_password, verify_password

logger = structlog.get_logger(__name__)

_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_MAX_LOGIN_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 300


def _check_login_rate_limit(key: str) -> None:
    now = datetime.now(timezone.utc).timestamp()
    attempts = _LOGIN_ATTEMPTS.setdefault(key, [])
    attempts[:] = [t for t in attempts if now - t < _LOGIN_WINDOW_SECONDS]
    if len(attempts) >= _MAX_LOGIN_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
    attempts.append(now)


def _validate_password(password: str) -> None:
    if len(password) < settings.password_min_length:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {settings.password_min_length} characters long",
        )


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def register(self, username: str, password: str, email: str | None = None, risk_profile: str = "balanced") -> dict[str, Any]:
        _validate_password(password)
        filters = [User.username == username]
        if email is not None:
            filters.append(User.email == email)
        result = await self.db.execute(select(User).where(or_(*filters)))
        if result.scalar_one_or_none():
            raise HTTPException(400, "Username or email already taken")
        user = User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
            risk_profile=risk_profile or "balanced",
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        token = create_token(int(user.id), str(user.username))
        refresh_token = create_refresh_token(int(user.id), str(user.username))
        return {
            "access_token": token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user_id": int(user.id),
            "username": str(user.username),
        }

    async def login(self, username: str, password: str, totp_code: Optional[str] = None) -> dict[str, Any]:
        _check_login_rate_limit(username)
        result = await self.db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user or not verify_password(password, str(user.hashed_password)):
            raise HTTPException(401, "Invalid credentials")

        if user.totp_enabled:
            if not totp_code:
                raise HTTPException(428, "TOTP code required")
            secret = user.totp_secret or ""
            if verify_totp(secret, totp_code):
                pass
            elif user.recovery_codes and verify_recovery_code(totp_code, user.recovery_codes):
                hashed = hash_recovery_code(totp_code)
                matched = [c for c in user.recovery_codes if hmac.compare_digest(c, hashed)]
                if matched:
                    user.recovery_codes = [c if c != matched[0] else f"USED:{c}" for c in user.recovery_codes]
                    await self.db.commit()
            else:
                raise HTTPException(401, "Invalid TOTP code")

        token = create_token(int(user.id), str(user.username))
        refresh_token = create_refresh_token(int(user.id), str(user.username))
        return {
            "access_token": token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user_id": int(user.id),
            "username": str(user.username),
        }

    async def get_me(self, user: User) -> dict[str, Any]:
        return {
            "id": int(user.id),
            "username": str(user.username),
            "email": str(user.email) if user.email is not None else None,
            "role": str(user.role),
            "risk_profile": str(user.risk_profile),
            "totp_enabled": bool(user.totp_enabled),
            "is_active": bool(user.is_active),
        }

    async def setup_totp(self, user: User) -> dict[str, Any]:
        secret = generate_secret()
        user.totp_secret = secret
        await self.db.commit()
        uri = get_totp_uri(secret, str(user.username))
        return {"secret": secret, "uri": uri}

    async def confirm_totp(self, user: User, code: str) -> dict[str, Any]:
        secret = user.totp_secret or ""
        if not verify_totp(secret, code):
            raise HTTPException(400, "Invalid TOTP code")
        user.totp_enabled = True
        codes = generate_recovery_codes(8)
        user.recovery_codes = [hash_recovery_code(c) for c in codes]
        await self.db.commit()
        return {"enabled": True, "recovery_codes": codes}

    async def disable_totp(self, user: User) -> dict[str, Any]:
        user.totp_secret = None
        user.totp_enabled = False
        user.recovery_codes = None
        await self.db.commit()
        return {"enabled": False}
