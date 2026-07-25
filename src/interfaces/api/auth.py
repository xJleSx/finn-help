import hashlib
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
import httpx
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.cache import get_redis
from src.config import settings
from src.db.connection import get_session
from src.db.models import User
from src.interfaces.api.dependencies import get_db

logger = structlog.get_logger(__name__)


OAUTH_PROVIDERS: dict[str, dict[str, str]] = {
    "google": {
        "client_id": settings.oauth_google_client_id,
        "client_secret": settings.oauth_google_client_secret,
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v2/userinfo",
    },
    "github": {
        "client_id": settings.oauth_github_client_id,
        "client_secret": settings.oauth_github_client_secret,
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
    },
    "yandex": {
        "client_id": settings.oauth_yandex_client_id,
        "client_secret": settings.oauth_yandex_client_secret,
        "token_url": "https://oauth.yandex.ru/token",
        "userinfo_url": "https://login.yandex.ru/info",
    },
}


async def _verify_oauth_code(provider: str, code: str) -> dict:
    cfg = OAUTH_PROVIDERS.get(provider)
    if not cfg:
        raise AuthError(f"Unsupported OAuth provider: {provider}")

    if not cfg["client_id"] or not cfg["client_secret"]:
        logger.warning("OAuth provider %s not configured — skipping code verification", provider)
        return {}

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            cfg["token_url"],
            data={
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "code": code,
                "redirect_uri": settings.oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            logger.error("OAuth token exchange failed for %s: %s", provider, token_resp.text)
            raise AuthError(f"OAuth provider {provider} rejected the authorization code")

        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise AuthError(f"No access_token in {provider} response")

        user_resp = await client.get(
            cfg["userinfo_url"],
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            raise AuthError(f"Failed to fetch user info from {provider}")

        return user_resp.json()


class AuthError(Exception):
    """Custom exception for authentication errors, separate from HTTPException."""
    def __init__(self, detail: str = "Authentication failed", status_code: int = status.HTTP_401_UNAUTHORIZED):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)

if not settings.jwt_secret:
    raise RuntimeError(
        "JWT_SECRET is not configured. Set JWT_SECRET in .env or environment variables. "
        "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
    )

SECRET_KEY = settings.jwt_secret

_refresh_secret = settings.jwt_refresh_secret
if not _refresh_secret:
    logger.warning(
        "REFRESH_SECRET not set — falling back to JWT_SECRET + '_refresh'. "
        "Set REFRESH_SECRET in .env for production."
    )
    _refresh_secret = settings.jwt_secret + "_refresh"
REFRESH_SECRET_KEY = _refresh_secret
ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

_REFRESH_BLACKLIST_PREFIX = "finn:refresh_blacklist:"
_refresh_blacklist_fallback: dict[str, float] = {}
_REFRESH_BLACKLIST_MAX = 10_000
_REFRESH_BLACKLIST_TTL = 86400 * 31


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
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise AuthError("Invalid token type")
        return payload
    except JWTError:
        raise AuthError("Invalid token")


def decode_refresh_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise AuthError("Invalid token type")
        return payload
    except JWTError:
        raise AuthError("Invalid refresh token")


def _evict_old_blacklist_entries() -> None:
    now = time.time()
    cutoff = now - _REFRESH_BLACKLIST_TTL
    stale = [k for k, ts in _refresh_blacklist_fallback.items() if ts < cutoff]
    for k in stale:
        _refresh_blacklist_fallback.pop(k, None)


def blacklist_refresh_token(token: str) -> None:
    r = get_redis()
    if r is not None:
        try:
            r.setex(_blacklist_key(token), 86400 * 31, "1")
            return
        except Exception:
            logger.exception("Unhandled exception")
            logger.warning("Redis set failed for refresh token blacklist, using in-memory fallback")
    _evict_old_blacklist_entries()
    if len(_refresh_blacklist_fallback) >= _REFRESH_BLACKLIST_MAX:
        oldest = min(_refresh_blacklist_fallback, key=_refresh_blacklist_fallback.get)
        _refresh_blacklist_fallback.pop(oldest, None)
    _refresh_blacklist_fallback[token] = time.time()


def is_refresh_token_blacklisted(token: str) -> bool:
    r = get_redis()
    if r is not None:
        try:
            return bool(r.get(_blacklist_key(token)))
        except Exception:
            logger.exception("Unhandled exception")
            logger.warning("Redis get failed for refresh token blacklist, using in-memory fallback")
    ts = _refresh_blacklist_fallback.get(token)
    if ts is None:
        return False
    if time.time() - ts > _REFRESH_BLACKLIST_TTL:
        _refresh_blacklist_fallback.pop(token, None)
        return False
    return True



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
    except (JWTError, ValueError, TypeError, AuthError):
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


async def oauth_login(provider: str, code: str) -> dict:
    if not code or not code.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Authorization code is required")

    user_info = await _verify_oauth_code(provider, code)
    provider_user_id = user_info.get("id") or user_info.get("sub") or f"{provider}_{hashlib.sha256(code.encode()).hexdigest()[:16]}"
    email = user_info.get("email") or f"{provider_user_id}@{provider}.oauth"

    db = get_session()
    from src.db.models.user import User  # noqa: F811
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
