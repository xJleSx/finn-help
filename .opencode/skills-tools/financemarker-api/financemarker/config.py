"""Configuration: load .env, resolve paths, expose a typed Config object.

Paths are project-relative (cwd) so the skill stays portable between
Windows and Linux. `.fmc-cache/` is created on first import if missing.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .errors import ConfigError

CACHE_DIR = Path(os.environ.get("FMC_CACHE_DIR", ".fmc-cache"))
DB_FILE = CACHE_DIR / "fmc.db"
CONFIG_FILE = CACHE_DIR / "config.json"
TOKEN_STATUS_FILE = CACHE_DIR / "token_status.json"
ENV_FILE = Path(os.environ.get("FMC_ENV_FILE", ".env"))


def _load_env_file(path: Path) -> Mapping[str, str]:
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
    if sys.platform != "win32":
        try:
            os.chmod(CACHE_DIR, 0o700)
        except OSError:
            pass


@dataclass(frozen=True)
class Config:
    api_token: str
    log_level: str
    base_url: str

    def mask_token(self) -> str:
        t = self.api_token
        return f"***{t[-4:]}" if len(t) >= 4 else "***"


def load_config() -> Config:
    _ensure_cache()
    env = dict(os.environ)
    env.update(_load_env_file(ENV_FILE))

    token = env.get("FM_API_TOKEN", "").strip()
    if not token:
        raise ConfigError(
            "FM_API_TOKEN is not set. "
            "Generate one at https://financemarker.ru/profile and add "
            "FM_API_TOKEN=… to .env."
        )

    return Config(
        api_token=token,
        log_level=env.get("FMC_LOG_LEVEL", "INFO"),
        base_url=env.get("FMC_BASE_URL", "https://financemarker.ru/api/fm/v2"),
    )
