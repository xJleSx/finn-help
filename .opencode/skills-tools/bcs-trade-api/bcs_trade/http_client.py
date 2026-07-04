"""HTTP client with auth header, retries, and error mapping.

The client is intentionally thin: it does not own the access token
lifecycle. `auth.ensure_access_token()` is called by handlers, the
result is passed in via the `auth_header` argument. Retries cover
transient network errors and 5xx; 401 is surfaced so the caller can
refresh and retry once.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Mapping
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from .errors import ApiError, AuthError

log = logging.getLogger("bcs_trade.http")

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
) -> tuple[int, Mapping[str, str], bytes]:
    req = urlrequest.Request(url, data=body, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, dict(resp.headers), resp.read()
    except HTTPError as e:
        return e.code, dict(e.headers or {}), e.read() or b""
    except URLError as e:
        raise ApiError(f"network error: {e.reason}") from e


def request_json(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    json_body: Any = None,
    form_body: Mapping[str, str] | None = None,
    auth_header: str | None = None,
) -> Any:
    """Issue an HTTP request and return a parsed JSON body.

    Retries 5xx and connection errors with exponential backoff. 401 is
    NOT retried here — the caller decides whether to refresh and retry.

    `form_body` takes precedence over `json_body` and is sent as
    application/x-www-form-urlencoded (Keycloak-style token endpoint).
    """
    hdrs: dict[str, str] = {"Accept": "application/json"}
    if auth_header:
        hdrs["Authorization"] = auth_header
    if form_body is not None:
        from urllib.parse import urlencode

        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        body = urlencode(form_body).encode("utf-8")
    elif json_body is not None:
        hdrs["Content-Type"] = "application/json"
        body = json.dumps(json_body).encode("utf-8")
    else:
        body = None

    last_err: ApiError | None = None
    for attempt in range(MAX_RETRIES):
        status, _resp_headers, raw = _request(method, url, headers=hdrs, body=body)
        if status == 401:
            raise AuthError(f"401 Unauthorized for {method} {url}")
        if status >= 500:
            last_err = ApiError(f"{status} from {method} {url}")
            log.warning("retryable %s on %s %s (attempt %d)", status, method, url, attempt + 1)
            time.sleep(BACKOFF * (2**attempt))
            continue
        if status >= 400:
            text = raw.decode("utf-8", "replace")
            raise ApiError(f"{status} {method} {url}: {text[:300]}")
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise ApiError(f"non-JSON response from {url}: {e}") from e
    raise last_err or ApiError("exhausted retries")
