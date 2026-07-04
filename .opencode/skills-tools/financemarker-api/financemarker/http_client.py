"""HTTP client with auth via api_token query param, retries, error mapping.

FinanceMarker is `?api_token=…&other=…&…` — the token is *always* part
of the query string per their swagger.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Mapping
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from .config import Config
from .errors import ApiError, AuthError, FmcError

log = logging.getLogger("financemarker.http")

DEFAULT_TIMEOUT = 15.0
MAX_RETRIES = 3
BACKOFF = 0.5


def _request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, bytes]:
    req = urlrequest.Request(url, data=body, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read()
    except HTTPError as e:
        return e.code, e.read() or b""
    except URLError as e:
        raise ApiError(f"network error: {e.reason}") from e


def _build_url(cfg: Config, path: str, params: Mapping[str, Any] | None) -> str:
    base = cfg.base_url.rstrip("/")
    full = f"{base}{path}"
    q: dict[str, Any] = {"api_token": cfg.api_token}
    if params:
        for k, v in params.items():
            if v is None:
                continue
            q[k] = v
    return f"{full}?{urlencode(q)}"


def get(
    cfg: Config,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
) -> Any:
    """GET with auth, retries on 5xx, JSON decode."""
    url = _build_url(cfg, path, params)
    last_err: ApiError | None = None
    for attempt in range(MAX_RETRIES):
        status, raw = _request("GET", url, headers={"Accept": "application/json"})
        if status == 400:
            text = raw.decode("utf-8", "replace")
            if "token_not_found" in text or "user_not_found" in text:
                raise AuthError(text.strip())
            raise ApiError(f"400 GET {url}: {text[:300]}")
        if status == 403:
            raise AuthError(f"403 GET {url}: {raw.decode('utf-8', 'replace')[:200]}")
        if status == 404:
            raise ApiError(f"404 GET {url}: endpoint or resource not found")
        if status >= 500:
            last_err = ApiError(f"{status} GET {url}")
            log.warning("retryable %s on GET %s (attempt %d)", status, url, attempt + 1)
            time.sleep(BACKOFF * (2**attempt))
            continue
        if status >= 400:
            text = raw.decode("utf-8", "replace")
            raise ApiError(f"{status} GET {url}: {text[:300]}")
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise ApiError(f"non-JSON response from {url}: {e}") from e
    raise last_err or ApiError("exhausted retries")


def get_raw(cfg: Config, path: str, *, params: Mapping[str, Any] | None = None) -> bytes:
    """Bypass JSON decoding — for debugging."""
    url = _build_url(cfg, path, params)
    status, raw = _request("GET", url)
    if status >= 400:
        raise FmcError(f"{status} GET {url}: {raw[:200]!r}")
    return raw
