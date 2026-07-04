"""Configuration: load .env, resolve paths, expose a typed Config object.

All filesystem locations are relative to the project root (cwd) so the
skill stays portable between Windows and Linux. `.bcs-cache/` is
created on first import if missing.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .errors import ConfigError

CACHE_DIR = Path(os.environ.get("BCS_CACHE_DIR", ".bcs-cache"))
TOKENS_FILE = CACHE_DIR / "tokens.json"
DB_FILE = CACHE_DIR / "bcs.db"
CONFIG_FILE = CACHE_DIR / "config.json"
ENV_FILE = Path(os.environ.get("BCS_ENV_FILE", ".env"))


def _load_env_file(path: Path) -> Mapping[str, str]:
    """Minimal .env loader: KEY=VALUE, no expansion, no exports."""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _ensure_cache() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # On POSIX tighten permissions; on Windows the ACL is best-effort.
    if sys.platform != "win32":
        try:
            os.chmod(CACHE_DIR, 0o700)
        except OSError:
            pass


@dataclass(frozen=True)
class Config:
    refresh_token: str
    account: str | None
    read_only: bool
    sandbox: bool
    log_level: str
    base_url: str
    token_url: str

    def mask_token(self) -> str:
        t = self.refresh_token
        return f"***{t[-4:]}" if len(t) >= 4 else "***"


def load_config() -> Config:
    _ensure_cache()
    env = dict(os.environ)
    env.update(_load_env_file(ENV_FILE))

    refresh = env.get("BCS_REFRESH_TOKEN", "").strip()
    if not refresh:
        raise ConfigError(
            "BCS_REFRESH_TOKEN is not set. "
            "Create a .env file (see .env.example) or set the env var."
        )

    sandbox = env.get("BCS_SANDBOX", "0") == "1"
    base = env.get("BCS_BASE_URL", "https://be.broker.ru")
    token = env.get(
        "BCS_TOKEN_URL",
        "https://be.broker.ru/trade-api-keycloak/realms/tradeapi/protocol/openid-connect/token",
    )

    return Config(
        refresh_token=refresh,
        account=env.get("BCS_ACCOUNT") or None,
        read_only=env.get("BCS_READ_ONLY", "0") == "1",
        sandbox=sandbox,
        log_level=env.get("BCS_LOG_LEVEL", "INFO"),
        base_url=base,
        token_url=token,
    )
