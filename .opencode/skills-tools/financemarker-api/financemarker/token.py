"""Token / quota handling.

`token_info` is the one endpoint that does NOT need any extra params,
and its result is a small dict we want to surface to the user. We
also persist it to `token_status.json` so the agent can warn early
when `day_limit` drops.
"""
from __future__ import annotations

import json
import time
from typing import Any

from .cache import get_conn
from .config import TOKEN_STATUS_FILE, Config
from .endpoints import TOKEN_INFO
from .http_client import get


def get_token_info(cfg: Config) -> dict[str, Any]:
    payload = get(cfg, TOKEN_INFO)
    # Persist for the next call; non-critical so a write failure is fine.
    try:
        TOKEN_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_STATUS_FILE.write_text(
            json.dumps({"ts": int(time.time()), **payload}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
    return payload


def last_token_status() -> dict[str, Any] | None:
    if not TOKEN_STATUS_FILE.exists():
        return None
    try:
        return json.loads(TOKEN_STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
