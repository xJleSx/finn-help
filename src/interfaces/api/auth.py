import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.cache import get_redis
from src.config import settings
from src.db.models import User
from src.db.connection import get_session

logger = structlog.get_logger(__name__)

if not settings.jwt_secret:
    raise RuntimeError(
        "JWT_SECRET is not configured. Set JWT_SECRET in .env or environment variables. "
        "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
    )

SECRET_KEY = settings.jwt_secret

_refresh_secret = settings.jwt_refresh_secret
if not _refresh_secret:
    _refresh_secret = settings.jwt_secret + "_refresh"
REFRESH_SECRET_KEY = _refresh_secret
ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

_REFRESH_BLACKLIST_PREFIX = "finn:refresh_blacklist:"
_refresh_blacklist_fallback: set[str] = set()


def _blacklist_key(token: str) -> str:
    return _REFRESH_BLACKLIST_PREFIX + hashlib.sha256(token.encode()).hexdigest()


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
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
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
    r = get_redis()
    if r is not None:
        try:
            r.setex(_blacklist_key(token), 86400 * 31, "1")
            return
        except Exception:
            logger.exception("Unhandled exception")
            logger.warning("Redis set failed for refresh token blacklist, using in-memory fallback")
    _refresh_blacklist_fallback.add(token)


def is_refresh_token_blacklisted(token: str) -> bool:
    r = get_redis()
    if r is not None:
        try:
            return bool(r.get(_blacklist_key(token)))
        except Exception:
            logger.exception("Unhandled exception")
            logger.warning("Redis get failed for refresh token blacklist, using in-memory fallback")
    return token in _refresh_blacklist_fallback


from src.interfaces.api.dependencies import get_db, get_read_db  # noqa: F401  re-exported for backwards compat


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
        return result.scalar_one_or_none()
    except (JWTError, ValueError, TypeError):
        return None


async def require_user(
    user: Optional[User] = Depends(get_current_user),
) -> User:
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def create_oauth_token(provider: str, provider_user_id: str, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode(
        {
            "sub": provider_user_id,
            "username": email.split("@")[0] if email else provider_user_id,
            "email": email,
            "provider": provider,
            "exp": expire,
            "type": "access",
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def oauth_login(provider: str, code: str) -> dict:
    if not code or not code.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Authorization code is required")

    provider_user_id = f"{provider}_{hashlib.sha256(code.encode()).hexdigest()[:16]}"
    email = f"{provider_user_id}@{provider}.oauth"

    db = get_session()
    from src.db.models.user import User  # noqa
    try:
        user = db.query(User).filter_by(username=provider_user_id).first()
        if not user:
            user = User(
                username=provider_user_id,
                email=email,
                hashed_password="",
                role="viewer",
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        access_token = create_oauth_token(provider, str(user.id), email)
        return {"access_token": access_token, "token_type": "bearer", "user_id": user.id, "username": user.username}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
