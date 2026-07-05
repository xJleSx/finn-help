from __future__ import annotations

import logging
from typing import Optional

from src.config import settings
from src.trading.brokers.base import BaseBrokerClient

logger = logging.getLogger(__name__)

_broker_registry: dict[str, type[BaseBrokerClient]] = {}
_default_broker: str = "tbank"


def register_broker(name: str, client_class: type[BaseBrokerClient]) -> None:
    _broker_registry[name.lower()] = client_class
    logger.info("Broker registered: %s (%s)", name, client_class.__name__)


def get_broker(name: str) -> Optional[type[BaseBrokerClient]]:
    return _broker_registry.get(name.lower())


def list_brokers() -> list[str]:
    return list(_broker_registry.keys())


def set_default_broker(name: str) -> None:
    global _default_broker
    _default_broker = name.lower()
    logger.info("Default broker set to: %s", _default_broker)


def get_default_broker() -> str:
    return _default_broker


def create_broker_client(
    name: Optional[str] = None,
    token: Optional[str] = None,
    use_sandbox: Optional[bool] = None,
) -> BaseBrokerClient:
    broker_name = name or _default_broker
    client_class = _broker_registry.get(broker_name)
    if not client_class:
        raise ValueError(f"Unknown broker: {broker_name}. Available: {list_brokers()}")
    effective_token = token or settings.tinkoff_token
    effective_sandbox = use_sandbox if use_sandbox is not None else settings.tinkoff_sandbox
    return client_class(token=effective_token, use_sandbox=effective_sandbox)
