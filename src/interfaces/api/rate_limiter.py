from fastapi import Request
from slowapi import Limiter


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = request.client
    if client is not None:
        return client.host
    return "127.0.0.1"


limiter = Limiter(key_func=_get_client_ip)
