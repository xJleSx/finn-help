"""Authentication: refresh-token → access-token, persisted locally.

`tokens.json` lives in `.bcs-cache/` and is chmod 600 on POSIX. The
access token is short-lived (24h); the refresh token lives in `.env`
and is never written to disk.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from .config import TOKENS_FILE, Config
from .errors import AuthError
from .http_client import request_json

log = logging.getLogger("bcs_trade.auth")

# Cached in-process to avoid re-reading the file on every request.
_cached_access: dict[str, Any] = {}


def _save_tokens(payload: dict[str, Any]) -> None:
    TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOKENS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, TOKENS_FILE)
    if os.name != "nt":
        try:
            os.chmod(TOKENS_FILE, 0o600)
        except OSError:
            pass


def _load_tokens() -> dict[str, Any] | None:
    if not TOKENS_FILE.exists():
        return None
    try:
        return json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise AuthError(f"corrupt tokens.json: {e}") from e


def _is_fresh(token: dict[str, Any], skew_seconds: int = 60) -> bool:
    expires_at = token.get("expires_at", 0)
    return expires_at > time.time() + skew_seconds


def get_access_token(cfg: Config) -> str:
    """Return a valid access token, refreshing if necessary."""
    cached = _cached_access.get("token")
    if cached and _is_fresh(cached):
        return cached["access_token"]

    stored = _load_tokens()
    if stored and _is_fresh(stored):
        _cached_access["token"] = stored
        return stored["access_token"]

    # Refresh. Try several client_id variants because BCS docs are vague
    # about which is the public SPA client.
    last_err: AuthError | None = None
    for client_id in ("trade-api", "trade-api-write", "trade-api-read"):
        body = {
            "grant_type": "refresh_token",
            "refresh_token": cfg.refresh_token,
            "client_id": client_id,
        }
        try:
            resp = request_json("POST", cfg.token_url, form_body=body)
            break
        except AuthError as e:
            last_err = e
            log.info("token endpoint rejected client_id=%s, trying next", client_id)
    else:
        if last_err is not None:
            raise last_err
        raise AuthError("token endpoint did not respond")
    if not resp or "access_token" not in resp:
        raise AuthError("token endpoint did not return access_token")
    access = resp["access_token"]
    refresh = resp.get("refresh_token", cfg.refresh_token)
    expires_in = int(resp.get("expires_in", 24 * 3600))
    payload = {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": int(time.time()) + expires_in,
    }
    _save_tokens(payload)
    _cached_access["token"] = payload
    return access


def auth_header(cfg: Config) -> str:
    return f"Bearer {get_access_token(cfg)}"


def status(cfg: Config) -> dict[str, Any]:
    """Return a redacted summary of the current auth state."""
    return {
        "refresh_token": cfg.mask_token(),
        "has_access_token": bool(_cached_access.get("token") or _load_tokens()),
        "cache_dir": str(Path(".bcs-cache").resolve()),
        "sandbox": cfg.sandbox,
        "read_only": cfg.read_only,
    }


# ---------- CLI dispatch ----------


def run(subcommand: str, cfg: Config) -> dict[str, Any]:
    if subcommand == "status":
        return status(cfg)
    if subcommand == "login":
        # Force refresh
        _cached_access.pop("token", None)
        get_access_token(cfg)
        return status(cfg)
    raise AuthError(f"unknown auth subcommand: {subcommand}")
