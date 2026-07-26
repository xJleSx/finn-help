import logging

from fastapi import Request
from slowapi import Limiter

logger = logging.getLogger(__name__)


def _rate_limit_key(request: Request) -> str:
    user_id = None
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and len(auth) > 7:
        try:
            from src.interfaces.api.auth import decode_token
            payload = decode_token(auth[7:])
            user_id = payload.get("sub")
        except Exception:
            logger.exception("Failed to decode auth token for rate limit key")
    if user_id:
        return f"user:{user_id}"
    client = request.client
    if client is not None:
        return client.host
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return "127.0.0.1"


limiter = Limiter(key_func=_rate_limit_key)
