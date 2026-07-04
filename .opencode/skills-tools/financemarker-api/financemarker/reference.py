"""Reference data: exchanges and the operation-metric catalogue."""
from __future__ import annotations

from typing import Any

from .config import Config
from .endpoints import EXCHANGES, OPERATION_METRICS
from .http_client import get


def list_exchanges(cfg: Config) -> list[dict[str, Any]]:
    return get(cfg, EXCHANGES) or []


def list_operation_metrics(cfg: Config) -> list[dict[str, Any]]:
    return get(cfg, OPERATION_METRICS) or []
