import logging
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator, Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.connection import get_async_session
from src.db.models import User

logger = logging.getLogger(__name__)

if not settings.jwt_secret:
    logger.warning("JWT_SECRET is not configured. Using auto-generated secret — all existing tokens will be invalidated on restart.")
SECRET_KEY = settings.jwt_secret or "insecure-fallback-not-for-production"
REFRESH_SECRET_KEY = settings.jwt_secret + "_refresh" if settings.jwt_secret else "insecure-refresh-fallback"
ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# In-memory blacklist for refresh tokens (use Redis in production)
_refresh_blacklist: set[str] = set()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_token(user_id: int, username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode(
        {"sub": str(user_id), "username": username, "exp": expire, "type": "access"},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def create_refresh_token(user_id: int, username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=30)
    return jwt.encode(
        {"sub": str(user_id), "username": username, "exp": expire, "type": "refresh"},
        REFRESH_SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decode_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def decode_refresh_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")


def blacklist_refresh_token(token: str) -> None:
    _refresh_blacklist.add(token)


def is_refresh_token_blacklisted(token: str) -> bool:
    return token in _refresh_blacklist


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_async_session():
        yield session


async def get_read_db() -> AsyncGenerator[AsyncSession, None]:
    from src.db.connection import get_read_replica_session

    async for session in get_read_replica_session():
        yield session


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    if not token:
        return None
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub", 0))
        if not user_id:
            return None
        result = await db.execute(select(User).where(User.id == user_id, User.is_active))
        user = result.scalar_one_or_none()
        return user
    except (JWTError, ValueError, TypeError):
        return None


async def require_user(
    user: Optional[User] = Depends(get_current_user),
) -> User:
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user
